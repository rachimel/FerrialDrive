"""방향 조합별 분리 출력과 본 추적을 기존 아틀라스 규약으로 패킹한다."""

import hashlib
import json
import os
from math import acos, ceil, degrees, sqrt
from pathlib import Path
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from automate.unreal.pose_table import ROOT, read, write
from automate.unreal.pose_math import add, inverse, qmul, rotate, sub

try:
    from PIL import Image, ImageChops
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT/"automate/runtime/image/python"))
    from PIL import Image, ImageChops

from ferrial_drive.rendering.motion_atlas import UniqueFrames, pack_items, resize_color


def verify_native(table):
    from automate.unreal.pose_table import turned_world, upper_bone_names
    plan = read(table["rig_plan"])
    maximum_position,maximum_angle,checked = 0,0,0
    maximum_grip,grips_checked = 0,0
    for motion,spec in table["motions"].items():
        source,tracking,native = read(spec["source"]),read(spec["tracking"]),read(spec["native"])
        if native.get("phase") != "complete":
            raise ValueError("저장·재로딩을 완료한 자세 표가 아니다.")
        upper = upper_bone_names(plan,spec.get("attachments",source.get("attachments",[])))
        actual = {row["frame"]:row["bones"] for row in native["evaluated"]}
        for row in spec["rows"]:
            base = tracking["samples"][row["motion_frame"]*tracking["sample_hz"]//12]["extra_bones"]
            expected = turned_world(base,upper,row["upper"]*45,row["lower"]*45)
            if not table.get("root_controlled",False):
                # 기존 표는 pelvis에 월드 변환을 기록하고 Root 피봇은 보존했다.
                expected["Root"] = (base["Root"]["position_cm"],base["Root"]["rotation_xyzw"])
            for bone,pose in actual[row["source_frame"]].items():
                position,rotation = expected[bone]
                maximum_position = max(maximum_position,sqrt(sum((a-b)**2 for a,b in zip(position,pose["translation"]))))
                q = pose["rotation"]
                cosine = abs(sum(a*b for a,b in zip(rotation,q)))/sqrt(sum(a*a for a in rotation)*sum(a*a for a in q))
                maximum_angle = max(maximum_angle,degrees(2*acos(min(1,cosine))))
                checked += 1
            for attachment in spec.get("attachments",source.get("attachments",[])):
                bone,driver = attachment["bone"],attachment["driver"]
                pose = actual[row["source_frame"]]
                if bone not in pose or driver not in pose:
                    continue
                before = rotate(inverse(base[driver]["rotation_xyzw"]),sub(base[bone]["position_cm"],base[driver]["position_cm"]))
                after = rotate(inverse(pose[driver]["rotation"]),sub(pose[bone]["translation"],pose[driver]["translation"]))
                maximum_grip = max(maximum_grip,sqrt(sum((a-b)**2 for a,b in zip(before,after))))
                grips_checked += 1
    result = {"checked_bone_poses":checked,"max_position_error_cm":maximum_position,"max_angle_error_degrees":maximum_angle,
              "checked_grips":grips_checked,"max_hand_grip_error_cm":maximum_grip}
    result["motions"] = list(table["motions"])
    write(table.get("native_verification",str(Path(table["workspace"])/"native_verification.json")),result)
    if maximum_position>.01 or maximum_angle>.01 or maximum_grip>.05:
        raise ValueError("저장된 자세 표가 원본의 요청 변환과 다르다: "+str(result))
    return result


def rgba(path):
    with Image.open(path) as image:
        return image.convert("RGBA")


def compose_table(spec):
    directory = ROOT / spec["output"]
    manifest = read(directory / "manifest.json")
    clip = manifest["clips"][0]
    if len(clip["frames"]) != len(spec["rows"]):
        raise ValueError("자세 표와 실제 출력 프레임 수가 다르다.")
    output = directory / "assembled"
    output.mkdir(exist_ok=True)
    if (directory/"verification.json").is_file():
        checks = read(directory/"verification.json")
        if (len(checks) == len(spec["rows"]) and all(row["alpha_error"] == row["energy_alpha_error"] == 0
                and row["uncut"] for row in checks) and (output/f"energy_{len(checks)-1:04d}.png").is_file()):
            boxes = [r["bbox"] for r in checks]
            box = [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
            return output,box,checks
    boxes, checks = [], []
    for index, (frame, energy_frame) in enumerate(zip(clip["frames"], clip["energy_frames"])):
        body, energy = Image.new("RGBA", manifest["size"]), Image.new("RGBA", manifest["size"])
        mask_error = 0
        for part in clip["order"]:
            if part == "shadow":
                continue
            color, mask = rgba(directory/frame[part]), rgba(directory/energy_frame[part])
            mask_error = max(mask_error, ImageChops.difference(color.getchannel("A"), mask.getchannel("A")).getextrema()[1])
            body = Image.alpha_composite(body, color)
            energy = Image.alpha_composite(energy, mask)
        shadow = rgba(directory/frame["shadow"])
        reference = rgba(directory/manifest["reference_mask_frames"]["unsplit_reference"][index])
        difference = ImageChops.difference(body, reference)
        rgb = difference.convert("RGB")
        maximum = ImageChops.lighter(ImageChops.lighter(rgb.getchannel("R"), rgb.getchannel("G")), rgb.getchannel("B"))
        box = ImageChops.lighter(body.getchannel("A"), shadow.getchannel("A")).getbbox()
        checks.append({"frame": index, "alpha_error": difference.getchannel("A").getextrema()[1],
                       "energy_alpha_error": mask_error, "rgb_pixels_over_two": sum(maximum.histogram()[3:]),
                       "rgb_max_difference": maximum.getextrema()[1], "bbox": box,
                       "uncut": bool(box) and box[0]>0 and box[1]>0 and box[2]<body.width and box[3]<body.height})
        if box:
            boxes.append(box)
        for name, image in [("body",body), ("energy",energy), ("shadow",shadow)]:
            image.save(output/f"{name}_{index:04d}.png",compress_level=1)
    write(directory/"verification.json", checks)
    if not all(row["alpha_error"] == row["energy_alpha_error"] == 0 and row["uncut"] for row in checks):
        raise ValueError("자세 표의 실루엣·마스크·화면 잘림 검사가 실패했다.")
    box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return output, box, checks


def build_atlas(table, motion, spec, assembled, box, destination, divisor):
    if (ROOT/destination/"atlas.json").exists():
        return
    colors, energy, vectors = UniqueFrames(), UniqueFrames(), UniqueFrames()
    width, height = box[2]-box[0], box[3]-box[1]
    size = (ceil(width/divisor), ceil(height/divisor))
    zero = vectors.add(bytes([128,0,128,0])*(size[0]*size[1]), *size)
    cells = {}
    origin = spec.get("pivot",table["pivot"])
    canvas = spec.get("size",table["camera"]["size"])
    pivot = [origin[0]-box[0], canvas[1]-origin[1]-box[1]]
    for index, row in enumerate(spec["rows"]):
        indices = {}
        for name, pool in [("body", colors), ("energy", energy), ("shadow", colors)]:
            image = rgba(assembled/f"{name}_{index:04d}.png").crop(box)
            pixels,w,h = resize_color(image.tobytes(),width,height,divisor)
            indices[name] = pool.add(pixels,w,h)
        name = f"{motion}/u{row['upper']}l{row['lower']}"
        cells.setdefault(name, []).append([indices["body"],indices["body"],zero,zero,indices["energy"],indices["energy"]])
        cells.setdefault("shadow/"+name, []).append([indices["shadow"],indices["shadow"],zero,zero])
    clips = {name:{"pairs":pairs,"interval_seconds":1/12,"source_size":[width,height],"size":list(size),
                   "pivot":pivot,"pixel_scale":table.get("pixel_scale",1),"loop":spec["loop"]} for name,pairs in cells.items()}
    manifest = {"version":1,"divisor":divisor,"color_alpha_mode":"premultiplied","vector_encoding":"signed16_rgba_x64",
                "interpolation":"source_frames_only","clips":clips,"sources":{},"pages":{},"frames":{},"statistics":{}}
    for kind,pool in [("color",colors),("energy",energy),("vector",vectors)]:
        pages,positions = pack_items(pool.items,max_side=4096)
        manifest["frames"][kind] = positions
        manifest["pages"][kind] = []
        for index,page in enumerate(pages):
            payload = zlib.compress(page.pixels,3)
            name = f"{kind}_{index:03d}.rgba.zlib"
            path = ROOT/destination/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(payload)
            manifest["pages"][kind].append({"file":name,"codec":"rgba_zlib","width":page.width,"height":page.height,
                                               "sha256":hashlib.sha256(payload).hexdigest()})
        manifest["statistics"][kind] = {"unique_frames":len(pool.items),"gpu_bytes":sum(len(p.pixels) for p in pages)}
    write(destination/"atlas.json",manifest)


def extend_canvas(table,request):
    from copy import deepcopy
    workspace = Path(table["workspace"])
    render_requests = read(workspace/"render.json")["requests"]
    scene_requests = read(workspace/"scenes.json")["scenes"]
    scenes,renders,clipped = [],[],{}
    revised = deepcopy(table)
    extra = workspace/"canvas_r02"
    for motion,spec in table["motions"].items():
        directory = ROOT/spec["output"]
        manifest = read(directory/"manifest.json")
        clip = manifest["clips"][0]
        bad = []
        for index,frame in enumerate(clip["frames"]):
            body = rgba(directory/manifest["reference_mask_frames"]["unsplit_reference"][index]).getchannel("A")
            shadow = rgba(directory/frame["shadow"]).getchannel("A")
            box = ImageChops.lighter(body,shadow).getbbox()
            if not box or min(box[:2])<=0 or box[2]>=body.width or box[3]>=body.height:
                bad.append({"frame":index,"bbox":box})
        if not bad:
            continue
        clipped[motion] = bad
        render = deepcopy(next(r for r in render_requests if r["clip"] == motion))
        scene = deepcopy(next(s for s in scene_requests if not s.get("shadow_reference_only")
                              and s["animation"].endswith(f"/{motion}/A_Table")))
        previous = scene["asset_root"]
        prefix = previous+"_canvas_r02"
        scene["asset_root"] = prefix
        scene["size"] = [round(v*1.5) for v in scene["size"]]
        scene["camera"]["width_cm"] *= 1.5
        scene["report"] = str(extra/f"{motion}_scene.json")
        # 완료된 첫 상체 메시와 원래 하체 메시를 그대로 재사용한다.
        if "body" not in scene["reuse_meshes"]:
            scene["reuse_meshes"]["body"] = previous+"/SK_body"
        scenes.append(scene)
        scenes.append({"shadow_reference_only":True,"map":prefix+"/MAP_Reference","asset_root":prefix+"_clear",
                       "animation":scene["animation"],"frame_count":scene["frame_count"],"report":str(extra/f"{motion}_clear.json")})
        for key in ("map","sequence"):
            render[key] = render[key].replace(previous,prefix)
        for section in ("energy","reference"):
            for key in ("map","sequence"):
                render[section][key] = render[section][key].replace(previous,prefix)
        for key in ("map","sequence"):
            render["shadow"]["reference"][key] = render["shadow"]["reference"][key].replace(previous,prefix)
        render["pivot"] = [v+(new-old)/2 for v,new,old in zip(render["pivot"],scene["size"],render["size"])]
        render["size"] = scene["size"]
        render["output"] = table["output"]+"_canvas_r02/"+motion
        renders.append(render)
        revised["motions"][motion].update(output=render["output"],pivot=render["pivot"],size=render["size"])
    write(extra/"clipping.json",clipped)
    write(extra/"scenes.json",{"scenes":scenes,"report":str(extra/"scenes_native.json")})
    write(extra/"render.json",{"requests":renders,"output":table["output"]+"_canvas_r02_batch","quit_when_finished":True})
    write(extra/"request.json",{"workspace":str(extra),"output":table["output"]+"_canvas_r02"})
    write(extra/"table_revised.json",revised)
    print(json.dumps({"clipped_motions":{k:len(v) for k,v in clipped.items()},"workspace":str(extra)},ensure_ascii=False))


def attachment_tracks(table, request):
    definitions = read(request["attachment_definitions"])
    points = {**definitions["ground_anchors"], "muzzle":definitions["muzzle"],
              "blade_root":definitions["blade"]["root"], "blade_tip":definitions["blade"]["tip"]}
    from automate.unreal.pose_table import upper_bone_names
    plan = read(table["rig_plan"])
    result = {}
    for name,spec in table["motions"].items():
        source,tracking = read(spec["source"]),read(spec["tracking"])
        upper = upper_bone_names(plan,spec.get("attachments",source.get("attachments",[])))
        rows = []
        for sample in tracking["samples"]:
            bones = sample["extra_bones"]
            row = {"seconds":sample["time_seconds"],"root":bones["Root"]["position_cm"],
                   "waist":bones["waist"]["position_cm"],"points":{}}
            for label,point in points.items():
                bone = bones[point["bone"]]
                row["points"][label] = add(bone["position_cm"],rotate(bone["rotation_xyzw"],point["local_cm"]))
            rows.append(row)
        result[name] = {"duration_seconds":source["frame_count"]/12,"loop":source.get("loop",False),
                        "upper_points":[label for label,p in points.items() if p["bone"] in upper], "samples":rows}
    return result


def pack(table):
    started = perf_counter()
    native_path = Path(table.get("native_verification",str(Path(table["workspace"])/"native_verification.json")))
    native = read(native_path) if (ROOT/native_path).exists() else verify_native(table)
    if (native["max_position_error_cm"]>.01 or native["max_angle_error_degrees"]>.01
            or native.get("max_hand_grip_error_cm",0)>.05):
        raise ValueError("저장된 자세 표의 변환 정합이 기준을 넘었다.")
    request = read(Path(table["workspace"])/"request.json")
    table["pixel_scale"] = request.get("pixel_scale",1)
    runtime = Path(table["runtime"])
    catalog = {"version":1,"type":"upper_lower_pose_table","directions":8,"fps":12,"pixel_scale":table["pixel_scale"],
               "camera":table["camera"],"pivot":table["pivot"],"motions":{},"source_sha256":table["source_sha256"],
               "interpolation":"source_frames_only"}
    totals = {"frames":0,"rgb_frames_over_two":0,"rgb_pixels_over_two":0,"rgb_max_difference":0}
    def pack_motion(item):
        motion,spec = item
        assembled,box,checks = compose_table(spec)
        variants = {}
        for quality,divisor in [("high",1),("medium",2),("low",3)]:
            destination = runtime/quality/motion
            build_atlas(table,motion,spec,assembled,box,destination,divisor)
            variants[quality] = (Path(quality)/motion/"atlas.json").as_posix()
        print(f"패킹 완료: {motion}",flush=True)
        return motion,{"frames":spec["frames"],"source_frame_count":spec["source_frame_count"],
                       "loop":spec["loop"],"variants":variants},checks
    workers = request.get("pack_workers",1)
    if type(workers) is not int or not 1<=workers<=4:
        raise ValueError("패킹 작업자는 1~4개 정수여야 한다.")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for motion,spec,checks in executor.map(pack_motion,table["motions"].items()):
            catalog["motions"][motion] = spec
            totals["frames"] += len(checks)
            totals["rgb_frames_over_two"] += sum(r["rgb_pixels_over_two"]>0 for r in checks)
            totals["rgb_pixels_over_two"] += sum(r["rgb_pixels_over_two"] for r in checks)
            totals["rgb_max_difference"] = max(totals["rgb_max_difference"],max(r["rgb_max_difference"] for r in checks))
    catalog["attachments"] = attachment_tracks(table,request)
    write(runtime/"catalog.json",catalog)
    write(Path(table["workspace"])/"pack_verification.json",{**totals,"pack_seconds":perf_counter()-started,"workers":workers,"silhouettes_equal":True,"energy_alpha_equal":True,
                                                               "uncut":True,"runtime":str(runtime/"catalog.json")})
    print(json.dumps(totals),flush=True)


def merge_catalogs(request):
    from copy import deepcopy
    destination = ROOT/request["destination"]
    if destination.exists() or not destination.resolve().is_relative_to(ROOT/"data/runtime"):
        raise ValueError("data/runtime의 새 카탈로그 경로가 필요하다.")
    result = None
    for value in request["sources"]:
        path = ROOT/value
        source = read(path)
        if result is None:
            result = {**deepcopy(source),"motions":{},"attachments":{},"source_sha256":{},"source_catalogs":[]}
        density = lambda d:d["camera"]["size"][0]/d["camera"]["width_cm"]*d.get("pixel_scale",1)
        if (abs(density(source)-density(result))>1e-9 or source["camera"]["position"]!=result["camera"]["position"]
                or source["camera"]["target"]!=result["camera"]["target"] or set(source["motions"])&set(result["motions"])):
            raise ValueError("투영·방향·동작 이름이 호환되는 표가 필요하다.")
        for name,spec in source["motions"].items():
            spec = deepcopy(spec)
            spec["variants"] = {key:os.path.relpath((path.parent/value).resolve(),destination.parent)
                                for key,value in spec["variants"].items()}
            result["motions"][name] = spec
        result["attachments"].update(source["attachments"])
        result["source_sha256"].update(source["source_sha256"])
        result["source_catalogs"].append({"path":value,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    if result is None:
        raise ValueError("연결할 자세 표가 없다.")
    result["approval_source"] = request.get("approval_source")
    write(destination,result)
    print(json.dumps({"motions":len(result["motions"]),"catalog":str(destination)},ensure_ascii=False))
