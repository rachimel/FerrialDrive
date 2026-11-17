"""저장된 Unreal 자세를 상·하체 방향별 입력용 표로 출력한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automate.unreal.pose_math import add, sub, rotate, inverse, qmul, from_euler, to_euler


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def turned_world(bones,upper_bones,upper,lower):
    """Euler 변환 이전의 목표 월드 변환. 저장 결과 검사의 독립 기준이다."""
    root, waist = bones["Root"]["position_cm"], bones["waist"]["position_cm"]
    uq, lq = from_euler([0, upper, 0]), from_euler([0, lower, 0])
    turned_waist = add(root, rotate(lq, sub(waist, root)))
    world = {}
    for name,row in bones.items():
        rotation = uq if name in upper_bones else lq
        position = (add(turned_waist, rotate(uq, sub(row["position_cm"], waist))) if name in upper_bones
                    else add(root, rotate(lq, sub(row["position_cm"], root))))
        world[name] = (position, qmul(rotation, row["rotation_xyzw"]))
    return world


def turn_pose(plan, bones, upper_bones, upper, lower):
    """평가된 원본 자세·파지를 유지하며 Root·허리 로컬 키로 환산한다."""
    parents = {"Root":None,**{row["name"]: row["parent"] for row in plan["bones"]}}
    bind = {"Root":[0,0,0],**{row["name"]: row["position_cm"] for row in plan["bones"]}}
    world,controls = turned_world(bones,upper_bones,upper,lower),{}
    for name in parents:
        position,_ = world[name]
        parent = parents[name]
        pp, pq = world.get(parent, ([0, 0, 0], [0, 0, 0, 1]))
        local_position = rotate(inverse(pq), sub(position, pp))
        rest = sub(bind[name], bind.get(parent, [0, 0, 0]))
        controls[name] = {"translation_delta_cm": sub(local_position, rest),
                          "rotation_delta_deg": to_euler(qmul(inverse(pq), world[name][1]))}
    return controls


def upper_bone_names(plan, attachments):
    parents = {row["name"]: row["parent"] for row in plan["bones"]}
    upper = set()
    for name in parents:
        current = name
        while current in parents:
            if current == "waist":
                upper.add(name)
                break
            current = parents[current]
    while True:
        additional = {item["bone"] for item in attachments if item["driver"] in upper}
        if additional <= upper:
            break
        upper.update(additional)
    return upper


def prepare(request):
    workspace = Path(request["workspace"])
    if not (ROOT / workspace).resolve().is_relative_to(ROOT / "automate/workspace"):
        raise ValueError("automate의 새 작업 경로가 필요하다.")
    if (ROOT / workspace / "table.json").exists():
        raise FileExistsError(workspace)
    plan = read(request["rig_plan"])
    template = read(request["scene_template"])["scenes"][request.get("scene_index", 20)]
    factor = request.get("canvas_factor",1)
    template["size"] = [round(v*factor) for v in template["size"]]
    template["camera"]["width_cm"] *= factor
    groups = template["groups"]
    lower = groups["lower_body"]
    groups = {"body": [part for key, parts in groups.items() if key != "lower_body" for part in parts],
              "lower_body": lower}
    table = {"version": 1, "directions": 8, "fps": 12, "motions": {}, "root_controlled":True,
             "camera": {**template["camera"], "size": template["size"]}, "source_sha256": {}}
    animations, scenes, renders = [], [], []
    root = request["asset_root"]
    first_mesh_root = root.replace("/Game/MechLab/", "/Game/MechLab/RenderUnits_") + "_000"
    for index, (motion, source_path) in enumerate(request["motions"].items()):
        source = read(source_path)
        tracking_path = source["tracking"]["output"]
        tracking = read(tracking_path)
        if not {"Root",*(row["name"] for row in plan["bones"])} <= set(tracking["extra_bones"]):
            raise ValueError("모든 본을 기록한 저장 원본이 필요하다.")
        count = source["frame_count"] + (0 if source.get("loop") else 1)
        keys, rows = [], []
        attachments = [*source.get("attachments", []),
                       *({"bone":bone,"driver":driver} for bone,driver in request.get("attachment_drivers",{}).items())]
        upper_bones = upper_bone_names(plan, attachments)
        for lower_index in range(8):
            for upper_index in range(8):
                for frame in range(count):
                    native = tracking["samples"][frame * tracking["sample_hz"] // 12]["extra_bones"]
                    controls = turn_pose(plan, native, upper_bones, upper_index * 45, lower_index * 45)
                    key = len(rows) * 2
                    keys.extend([{"frame": key, "controls": controls}, {"frame": key+1, "controls": controls}])
                    rows.append({"source_frame": key, "lower": lower_index, "upper": upper_index, "motion_frame": frame})
        total = len(keys)
        keys.append({"frame": total, "controls": keys[-1]["controls"]})
        report = str(workspace / f"{motion}_native.json")
        animation = {"operation": "animation_clip", "source_mesh": source["source_mesh"],
                     "animation_asset": f"{root}/{motion}/A_Table", "frame_count": total, "fps": 12,
                     "pose_table": True, "bake_substeps": 1, "loop": False, "poses": keys,
                     "report_bones": ["Root", "waist", "head", "hand_r", "weapon_gun", "weapon_sword", "foot_l", "foot_r"],
                     "report": report}
        animations.append(animation)
        prefix = root.replace("/Game/MechLab/", "/Game/MechLab/RenderUnits_") + f"_{index:03d}"
        scene = deepcopy(template)
        scene.update(asset_root=prefix, animation=animation["animation_asset"], groups=groups,
                     frame_count=total, pose_table=True, report=str(workspace / f"{motion}_scene.json"))
        scene.pop("reuse_mesh_root", None)
        scene["reuse_meshes"] = {"lower_body": template["reuse_meshes"]["lower_body"]}
        if request.get("combined_mesh_root"):
            scene["reuse_meshes"]["body"] = request["combined_mesh_root"]+"/SK_body"
        elif index:
            scene["reuse_meshes"]["body"] = f"{first_mesh_root}/SK_body"
        scenes.append(scene)
        scenes.append({"shadow_reference_only": True, "map": prefix+"/MAP_Reference",
                       "asset_root": prefix+"_clear", "animation": animation["animation_asset"],
                       "frame_count": total, "report": str(workspace / f"{motion}_clear.json")})
        output = request["output"] + "/" + motion
        render = {"asset_id": "upper_lower_pose_table", "map": prefix+"/MAP_Render", "sequence": prefix+"/LS_Render",
                  "size": scene["size"], "pivot": request["pivot"], "frame_count": total, "pose_table": True,
                  "frame_step": 2, "clip": motion, "layers": {"body": {"anchor": "root", "name": "상체·장비"},
                  "lower_body": {"anchor": "root", "name": "하체"}}, "order": ["lower_body", "body"],
                  "output": output, "disable_tone_curve": True, "quit_when_finished": True,
                  "energy": {"map": prefix+"/MAP_Energy", "sequence": prefix+"/LS_Energy"},
                  "reference": {"map": prefix+"/MAP_Reference", "sequence": prefix+"/LS_Reference", "actor_layers": ["unsplit_reference"]},
                  "shadow": {"receiver_layer": "shadow_receiver", "part_id": "shadow", "reference":
                             {"map": prefix+"_clear/MAP_Clear", "sequence": prefix+"_clear/LS_Clear"}}}
        renders.append(render)
        table["motions"][motion] = {"frames": count, "source_frame_count": source["frame_count"],
                                    "loop": source.get("loop", False), "output": output, "rows": rows,
                                    "native": report, "source": source_path, "tracking": tracking_path}
        table["motions"][motion]["attachments"] = attachments
        for path in [source_path, tracking_path]:
            table["source_sha256"][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    table.update(workspace=str(workspace), output=request["output"], runtime=request["runtime"],
                 pivot=request["pivot"], rig_plan=request["rig_plan"])
    write(workspace / "animations.json", {"operation": "animation_clip", "clips": animations,
                                          "report": str(workspace / "animations_native.json")})
    write(workspace / "scenes.json", {"scenes": scenes, "report": str(workspace / "scenes_native.json")})
    write(workspace / "render.json", {"requests": renders, "output": request["output"]+"_batch", "quit_when_finished": True})
    write(workspace / "table.json", table)
    return {"motions": len(animations), "render_frames": sum(len(row["rows"]) for row in table["motions"].values())}


def run(request, args):
    workspace = Path(request["workspace"])
    def verify_animation():
        if (ROOT/workspace/"table.json").exists():
            from automate.unreal.pose_table_pack import verify_native
            result = verify_native(read(workspace/"table.json"))
            print(json.dumps({"requested_world_verified":result},ensure_ascii=False),flush=True)
    for route, filename in [("unreal-animation", "animations.json"), ("unreal-units", "scenes.json"), ("unreal-render", "render.json")]:
        if not (ROOT/workspace/filename).is_file():
            continue
        spec = read(workspace / filename)
        report = (ROOT / spec["output"] / "status.json") if "output" in spec else ROOT / spec["report"]
        if report.is_file() and (read(report).get("phase") == "complete" or read(report).get("scenes")):
            if route == "unreal-animation":
                verify_animation()
            print(f"완료 단계 재사용: {route}", flush=True)
            continue
        if route == "unreal-render" and request.get("pilot_frames"):
            pilot_path = workspace / "pilot.json"
            pilot = {**spec["requests"][0], "frame_count": request["pilot_frames"],
                     "output": request["output"]+"_pilot"}
            write(pilot_path, pilot)
            pilot_report = ROOT / pilot["output"] / "status.json"
            if not pilot_report.exists():
                pilot_command = [sys.executable, "-X", "utf8", str(ROOT/"automate/run.py"), route,
                    "--request", str(pilot_path), "--unreal", str(args.unreal), "--project", str(args.project), "--timeout", "600"]
                pilot_command += ["--engine-arg="+value for value in args.engine_arg]
                pilot_command += ["--engine-arg=-abslog="+str(ROOT/workspace/"pilot_engine.log")]
                with (ROOT/workspace/"pilot.log").open("w", encoding="utf-8") as log:
                    subprocess.run(pilot_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            expected = list(range(0, request["pilot_frames"], 2))
            if read(Path(pilot["output"])/"manifest.json")["source_frame_numbers"] != expected:
                raise ValueError("표의 렌더 프레임 간격이 요청과 다르다.")
            print("짝수 프레임 시험 렌더 확인 완료", flush=True)
        command = [sys.executable, "-X", "utf8", str(ROOT/"automate/run.py"), route, "--request", str(workspace/filename),
                   "--unreal", str(args.unreal), "--project", str(args.project), "--timeout", "7200"]
        if route != "unreal-render":
            command += ["--python-mode", "commandlet"]
        for value in args.engine_arg:
            command.append("--engine-arg="+value)
        command.append("--engine-arg=-abslog="+str(ROOT/workspace/(route+"_engine.log")))
        print(f"실행: {route}", flush=True)
        with (ROOT/workspace/(route+".log")).open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(f"완료: {route}", flush=True)
        if route == "unreal-animation":
            verify_animation()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "pack", "extend-canvas", "merge", "transform"))
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--unreal", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--engine-arg", action="append", default=[])
    args = parser.parse_args()
    request = read(args.request)
    if args.stage == "transform":
        from automate.unreal.pose_math import forward_pose
        controls = turn_pose(request["plan"],request["bones"],upper_bone_names(request["plan"],request["attachments"]),
                             request["upper_yaw_degrees"],request["lower_yaw_degrees"])
        print(json.dumps({"controls":controls,"world":forward_pose(request["plan"],controls)},ensure_ascii=False,indent=2))
    elif args.stage == "prepare":
        print(json.dumps(prepare(request), ensure_ascii=False))
    elif args.stage == "run":
        run(request, args)
    elif args.stage == "merge":
        from automate.unreal.pose_table_pack import merge_catalogs
        merge_catalogs(request)
    else:
        for path in request.get("python_paths", []):
            directory = (ROOT/path).resolve()
            if not directory.is_relative_to(ROOT/"automate/runtime") or not directory.is_dir():
                raise ValueError("기존 automate/runtime의 Python 의존성 경로가 필요하다.")
            sys.path.insert(0,str(directory))
        from automate.unreal.pose_table_pack import pack, extend_canvas
        table = read(Path(request["workspace"]) / "table.json")
        if args.stage == "pack":
            pack(table)
        else:
            extend_canvas(table, request)


if __name__ == "__main__":
    main()
