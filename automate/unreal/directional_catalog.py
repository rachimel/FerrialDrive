"""기존 모션과 카메라 JSON으로 방향별 장면·렌더·기존 메카 시트를 연결한다."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(profile, workspace):
    snapshot = workspace / "profile_snapshot.json"
    if snapshot.exists() and read(snapshot) != profile:
        raise ValueError("완료 결과와 다른 제작 입력이다. 새 작업 폴더를 사용한다.")
    if not workspace.is_relative_to(ROOT / "automate/workspace"):
        raise ValueError("제작 요청은 automate/workspace 안에 보존한다.")
    for field, base in (("render_output", "output"), ("packed_input", "output"), ("asset_output", "data")):
        path = (ROOT / profile[field]).resolve()
        if not path.is_relative_to(ROOT / base) or path == ROOT / base:
            raise ValueError(f"{field} 출력 범위가 유효하지 않다.")
    if set(profile["cameras"]) != {"s", "sw", "w", "nw", "n", "ne", "e", "se"}:
        raise ValueError("서로 다른 8방향 카메라가 필요하다.")
    if (not 1 <= len(profile["clips"]) <= 32
            or len({clip["name"] for clip in profile["clips"]}) != len(profile["clips"])):
        raise ValueError("동작은 이름이 중복되지 않는 1~32개가 필요하다.")
    for clip in profile["clips"]:
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", clip["name"])
                or type(clip["frames"]) is not int or not 1 <= clip["frames"] <= 12
                or type(clip["loop"]) is not bool or not clip["animation"].startswith("/Game/")):
            raise ValueError("동작 이름·프레임·반복·애니메이션 경로가 유효하지 않다.")
    write(snapshot, profile)
    template = profile["scene_template"]
    jobs, scene_batches, render_batches, combined_scenes = [], [], [], []
    for direction, camera in profile["cameras"].items():
        scenes = []
        for clip in profile["clips"]:
            name = clip["name"]
            prefix = profile["asset_root"] + f"_{name}_{direction}"
            report = (workspace / f"scene_{name}_{direction}.json").relative_to(ROOT).as_posix()
            scenes.append({**deepcopy(template), "camera": camera, "animation": clip["animation"],
                           "frame_count": clip["frames"], "asset_root": prefix, "report": report})
            jobs.append({"asset_id": profile["asset_id"], "map": prefix + "/MAP_Render",
                         "sequence": prefix + "/LS_Render", "size": template["size"],
                         "pivot": [0, 0], "frame_count": clip["frames"], "clip": f"{name}/{direction}",
                         "layers": {"body": {"anchor": "root"}}, "order": ["body"],
                         "output": f"{profile['render_output']}/{name}_{direction}",
                         "disable_tone_curve": True, "quit_when_finished": True,
                         "scene_report": report, "loop": clip["loop"]})
            if template.get("energy_materials"):
                jobs[-1]["energy"] = {"map": prefix + "/MAP_Energy", "sequence": prefix + "/LS_Energy"}
        if profile.get("scene_batch_size"):
            combined_scenes.extend(scenes)
        else:
            batch = workspace / f"prepare_{direction}.json"
            write(batch, {"scenes": scenes, "report": (workspace / f"prepared_{direction}.json").relative_to(ROOT).as_posix()})
            scene_batches.append(batch)
    if combined_scenes:
        batch_size = profile["scene_batch_size"]
        if type(batch_size) is not int or not 1 <= batch_size <= 32:
            raise ValueError("장면 묶음 크기는 1~32 정수여야 한다.")
        for start in range(0, len(combined_scenes), batch_size):
            name = f"{start // batch_size:02}"
            path = workspace / f"prepare_{name}.json"
            write(path, {"scenes": combined_scenes[start:start + batch_size],
                         "report": (workspace / f"prepared_{name}.json").relative_to(ROOT).as_posix()})
            scene_batches.append(path)
    for index in range(0, len(jobs), 32):
        path = workspace / f"render_{index // 32:02}.json"
        members = [{k: v for k, v in job.items() if k not in ("scene_report", "loop")} for job in jobs[index:index + 32]]
        write(path, {"output": f"{profile['render_output']}_batch_{index // 32:02}",
                     "requests": members, "quit_when_finished": True})
        render_batches.append(path)
    write(workspace / "catalog_jobs.json", jobs)
    return scene_batches, render_batches


def run_batches(scene_batches, render_batches, unreal, project, engine_args=()):
    for route, paths in (("unreal-units", scene_batches), ("unreal-render", render_batches)):
        for path in paths:
            data = read(path)
            report = ROOT / data["report"] if route == "unreal-units" else ROOT / data["output"] / "status.json"
            if report.exists():
                if report.with_suffix(".error.txt").exists() or (route == "unreal-render" and not read(report).get("success")):
                    raise RuntimeError(f"이전 실패 결과를 먼저 확인한다: {report}")
                print(f"완료 결과 재사용: {path.name}", flush=True)
                continue
            print(f"실행: {route} {path.name}", flush=True)
            subprocess.run([sys.executable, str(ROOT / "automate/run.py"), route,
                            "--unreal", str(unreal), "--project", str(project), "--request", str(path),
                            "--timeout", "3600", *["--engine-arg=" + value for value in engine_args]], cwd=ROOT, check=True)


def pack(profile, workspace):
    from Tools.asset_loader.unreal_import import import_render
    jobs = read(workspace / "catalog_jobs.json")
    directory = ROOT / profile["packed_input"]
    directory.mkdir(parents=True, exist_ok=True)
    clips, metadata = [], {}
    for job in jobs:
        manifest = read(ROOT / job["output"] / "manifest.json")
        scene = read(ROOT / job["scene_report"])
        clip = manifest["clips"][0]
        collections = {}
        for field in ("frames", "energy_frames"):
            if field not in clip:
                continue
            frames = []
            for index, frame in enumerate(clip[field]):
                packed_frame = {}
                for layer, relative in frame.items():
                    target = directory / job["clip"] / field / layer / f"{index:04}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / job["output"] / relative, target)
                    packed_frame[layer] = target.relative_to(directory).as_posix()
                frames.append(packed_frame)
            collections[field] = frames
        clips.append({**clip, **collections, "pivot": scene["pivot"]})
        frames = collections["frames"]
        metadata[job["clip"]] = {"frames": len(frames), "fps": clip["fps"], "loop": job["loop"]}
    manifest = {"version": 1, "type": "unreal_prerender", "asset_id": profile["asset_id"],
                "size": profile["scene_template"]["size"], "pivot": [0, 0],
                "layers": manifest["layers"], "clips": clips}
    write(directory / "manifest.json", manifest)
    # 긴 방향별 목록은 기존 시트 제한을 유지한 채 여러 메카 번들로 나눈다.
    per_sheet = profile.get("clips_per_sheet", 32)
    if type(per_sheet) is not int or not 1 <= per_sheet <= 128:
        raise ValueError("시트별 클립 수는 1~128 정수여야 한다.")
    results, assets = [], []
    for index in range(0, len(clips), per_sheet):
        name = f"part_{index // per_sheet:02}"
        member = {**manifest, "clips": clips[index:index + per_sheet]}
        source = directory / f"manifest_{name}.json"
        write(source, member)
        result = import_render(source, ROOT / profile["asset_output"] / name, trim_padding=True)
        results.append(result)
        assets.append({"id": name, "kind": "mech", "source": f"{name}/mech.json"})
    write(ROOT / profile["asset_output"] / "catalog.json", {"version": 1, "assets": assets})
    write(workspace / "packed.json", {"results": results, "clips": metadata})
    print(json.dumps({"bundles": len(results), "clips": len(clips)}, ensure_ascii=False), flush=True)


def export_shadows(profile, workspace, unreal, project, engine_args=()):
    """완료한 모션 장면에서 같은 포즈·광원의 그림자/무그림자 패스를 추가한다."""
    jobs = read(workspace / "catalog_jobs.json")
    destination = workspace / "with_shadow"
    destination.mkdir(exist_ok=True)
    scenes, outputs = [], []
    for job in jobs:
        scene = read(ROOT / job["scene_report"])
        name = job["clip"].replace("/", "_")
        prefix = profile["asset_root"] + "_Clear_" + name
        report = (destination / f"clear_{name}.json").relative_to(ROOT).as_posix()
        scenes.append({"shadow_reference_only": True, "map": scene["map"],
                       "animation": scene["animation"], "frame_count": job["frame_count"],
                       "asset_root": prefix, "report": report})
        outputs.append({**job, "output": profile["render_output"] + "_shadow/" + name,
                        "pivot": scene["pivot"],
                        "shadow": {"receiver_layer": "shadow_receiver", "part_id": "shadow",
                                   "reference": {"map": prefix + "/MAP_Clear", "sequence": prefix + "/LS_Clear"}}})
    scene_batches, render_batches = [], []
    for start in range(0, len(jobs), 32):
        index = start // 32
        path = destination / f"prepare_{index:02}.json"
        write(path, {"scenes": scenes[start:start + 32],
                     "report": (destination / f"prepared_{index:02}.json").relative_to(ROOT).as_posix()})
        scene_batches.append(path)
        path = destination / f"render_{index:02}.json"
        write(path, {"output": profile["render_output"] + f"_shadow_batch_{index:02}",
                     "requests": [{k: v for k, v in job.items() if k not in ("scene_report", "loop")}
                                  for job in outputs[start:start + 32]], "quit_when_finished": True})
        render_batches.append(path)
    shadow_profile = {**profile, "packed_input": profile["packed_input"] + "_shadow",
                      "asset_output": profile["asset_output"] + "_shadow", "clips_per_sheet": 16}
    write(destination / "profile.json", shadow_profile)
    write(destination / "catalog_jobs.json", outputs)
    run_batches(scene_batches, render_batches, unreal, project, engine_args)
    pack(shadow_profile, destination)


def export_vectors(profile, workspace, unreal, project, blender, engine_args=()):
    """기존 8방향 장면의 네이티브 벡터를 같은 모션 스프라이트 규약으로 인계한다."""
    jobs = read(workspace / "catalog_jobs.json")
    destination = workspace / "interpolation"
    destination.mkdir(exist_ok=True)
    decoder = destination / "decoder.json"
    write(decoder, {"channels": [0, 1], "signs": [-1, 1], "scale": 2})
    data_root = ROOT / "data/runtime/frame_interpolation" / profile["asset_id"]
    captures, conversions = [], []
    for job in jobs:
        scene = read(ROOT / job["scene_report"])
        name = job["clip"].replace("/", "_")
        output = profile.get("vector_render_output", profile["render_output"] + "_motion") + "/" + name
        captures.append({"map": scene["reference_map"], "animation": scene["animation"],
                         "asset_root": profile.get("vector_asset_root", "/Game/MechLab/Interpolation_" + profile["asset_id"]) + "_" + name,
                         "output": output, "size": profile["scene_template"]["size"],
                         "duration_seconds": job["frame_count"] / 12, "source_fps": 12, "reference_fps": 24})
        if scene.get("energy_map"):
            captures[-1]["energy_map"] = scene["energy_map"]
        conversions.append({"source": str(ROOT / output), "output": str(data_root / name), "decoder": str(decoder)})
        if job["clip"] in profile.get("vector_energy_overrides", {}):
            conversions[-1]["energy_source"] = str(ROOT / profile["vector_energy_overrides"][job["clip"]])
    for start in range(0, len(captures), 32):
        index = start // 32
        path = destination / f"capture_{index:02}.json"
        output = profile.get("vector_batch_output", profile["render_output"] + "_motion_batch") + f"_{index:02}"
        write(path, {"output": output, "captures": captures[start:start + 32]})
        status = ROOT / output / "status.json"
        if not status.exists():
            print(f"벡터 렌더: {index + 1}/{(len(captures) + 31) // 32}", flush=True)
            subprocess.run([sys.executable, str(ROOT / "automate/run.py"), "unreal-motion-vectors",
                            "--unreal", str(unreal), "--project", str(project), "--request", str(path),
                            "--timeout", "3600", *["--engine-arg=" + value for value in engine_args]], cwd=ROOT, check=True)
        elif not read(status).get("success"):
            raise RuntimeError(f"이전 벡터 출력 실패: {status}")
    conversion_path = destination / "convert.json"
    write(conversion_path, conversions)
    subprocess.run([str(blender), "--background", "--factory-startup", "--python-exit-code", "1",
                    "--python", str(ROOT / "automate/unreal/motion_vector_convert.py"),
                    "--", "--batch", str(conversion_path)], cwd=ROOT, check=True)
    rows = []
    for job, conversion in zip(jobs, conversions):
        path = Path(conversion["output"]) / "clip.json"
        data = read(path)
        left, top = data["provenance"]["crop_top_left"]
        scene = read(ROOT / job["scene_report"])
        rows.append({"name": job["clip"], "path": path.relative_to(data_root).as_posix(),
                     "pivot_top_left": [scene["pivot"][0] - left,
                                        profile["scene_template"]["size"][1] - scene["pivot"][1] - top],
                     "pixel_scale": 1, "loop": job["loop"]})
    sources = sorted((ROOT / (profile["asset_output"] + "_shadow")).glob("part_*/mech.json"))
    import os
    write(data_root / "catalog.json", {"schema_version": 1, "clips": rows,
        "source_assets": [{"path": os.path.relpath(path, data_root), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in sources]})


def reuse_vectors(profile, workspace, source_catalog, output_catalog):
    """같은 원본 모션의 기존 벡터를 재사용하고 표시 기준점만 월드 원점으로 맞춘다."""
    import os
    from ferrial_drive.rendering.pico_motion_sprite import validate_source_assets
    source_catalog, output_catalog = source_catalog.resolve(), output_catalog.resolve()
    source = read(source_catalog)
    validate_source_assets(source, source_catalog.parent)
    if output_catalog.exists() or not output_catalog.is_relative_to(ROOT / "data"):
        raise ValueError("data 아래 새 보간 카탈로그가 필요하다.")
    known = {row["name"]: row for row in source["clips"]}
    rows = []
    for job in read(workspace / "catalog_jobs.json"):
        row = known[job["clip"]]
        clip_path = (source_catalog.parent / row["path"]).resolve()
        native = read(clip_path)["provenance"]
        scene = read(ROOT / job["scene_report"])
        if native["animation"].split(".")[0] != scene["animation"].split(".")[0]:
            raise ValueError("재사용하려는 보간 동작과 현재 AnimSequence가 다르다.")
        left, top = native["crop_top_left"]
        ratio = row["pixel_scale"]
        rows.append({**row, "path": os.path.relpath(clip_path, output_catalog.parent),
                     "pivot_top_left": [scene["pivot"][0] / ratio - left,
                                        (profile["scene_template"]["size"][1] - scene["pivot"][1]) / ratio - top]})
    sources = [(source_catalog.parent / row["path"]).resolve() for row in source.get("source_assets", [])]
    sources += list((ROOT / (profile["asset_output"] + "_shadow")).glob("part_*/mech.json"))
    write(output_catalog, {"schema_version": 1, "clips": rows, "source_assets": [
        {"path": os.path.relpath(path, output_catalog.parent), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(set(sources))]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--unreal", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--engine-arg", action="append", default=[])
    parser.add_argument("--source-catalog", type=Path)
    parser.add_argument("--output-catalog", type=Path)
    parser.add_argument("--stage", choices=("plan", "render", "pack", "shadows", "vectors", "reuse-vectors", "all"), default="all")
    args = parser.parse_args()
    profile = read(args.profile)
    workspace = args.profile.resolve().parent
    if args.stage == "reuse-vectors":
        if not args.source_catalog or not args.output_catalog:
            parser.error("--source-catalog와 --output-catalog가 필요하다.")
        reuse_vectors(profile, workspace, args.source_catalog, args.output_catalog)
        return
    if args.stage == "vectors":
        if not args.unreal or not args.project or not args.blender:
            parser.error("벡터 출력에는 --unreal·--project·--blender가 필요하다.")
        export_vectors(profile, workspace, args.unreal, args.project, args.blender, args.engine_arg)
        return
    if args.stage == "shadows":
        if not args.unreal or not args.project:
            parser.error("그림자 출력에는 --unreal과 --project가 필요하다.")
        export_shadows(profile, workspace, args.unreal, args.project, args.engine_arg)
        return
    if args.stage == "pack":
        pack(profile, workspace)
        return
    scenes, renders = prepare(profile, workspace)
    if args.stage in ("render", "all"):
        if not args.unreal or not args.project:
            parser.error("렌더에는 --unreal과 --project가 필요하다.")
        run_batches(scenes, renders, args.unreal, args.project, args.engine_arg)
    if args.stage in ("pack", "all"):
        pack(profile, workspace)
        if args.stage == "all" and profile.get("render_shadows", False):
            export_shadows(profile, workspace, args.unreal, args.project, args.engine_arg)


if __name__ == "__main__":
    main()
