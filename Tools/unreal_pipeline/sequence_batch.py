"""왕복 동작 묶음의 숫자 준비·Blender 반환·독립 재로딩 검사를 담당한다."""
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rows(matrix):
    return [list(row) for row in matrix]


def prepare_batch(request):
    import bpy
    import numpy as np
    from mathutils import Matrix, Quaternion, Vector
    mapping = read(request["transfer_map"])
    reference = read(request["reference"])
    if "result" in reference:
        reference = reference["result"]["structuredContent"]["context"]["result"]
    data = read(request["motion_data"])
    source = Path(mapping["source"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != mapping["source_sha256"]:
        raise ValueError("기준 모델 해시 불일치")
    destination = Path(request["output"])
    if destination.exists():
        raise FileExistsError(destination)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    rig = bpy.data.objects[request["rig"]]
    if rig.animation_data:
        rig.animation_data.action = None
        for track in rig.animation_data.nla_tracks:
            track.mute = True
    world = Matrix(mapping["rig_world"])
    refs = {k.lower(): v for k, v in reference["bones"].items()}
    def unreal_matrix(name):
        value = refs[name.lower()]
        x, y, z, w = value["rotation"]
        return Matrix.LocRotScale(Vector(value["translation"]), Quaternion((w, x, y, z)), Vector(value["scale"]))
    source_bind = {name: world @ Matrix(value) for name, value in mapping["source_pose_matrices"].items()}
    x = np.array([[*m.translation, 1] for m in source_bind.values()])
    y = np.array([list(unreal_matrix(mapping["bone_map"][n]).translation) for n in source_bind])
    affine = np.linalg.lstsq(x, y, rcond=None)[0].T
    coordinate_map = Matrix([*affine.tolist(), [0, 0, 0, 1]])
    error = float(np.max(np.linalg.norm(x @ affine.T-y, axis=1)))
    if error > .01:
        raise ValueError(f"본 위치 좌표계 대응 불일치: {error} cm")
    source_all = dict(source_bind)
    names = dict(mapping["bone_map"])
    for name, external in mapping["object_controls"].items():
        source_all[name] = world @ Matrix(mapping["helper_pose_matrices"][name])
        names[name] = external
    correction = {n: (coordinate_map @ m).inverted() @ unreal_matrix(names[n]) for n, m in source_all.items()}
    order = [b.name for b in rig.data.bones]
    output = {"fps": 12, "source_sha256": mapping["source_sha256"],
              "reference_motion_data": str(Path(request["motion_data"]).resolve()),
              "coordinate_fit_error_cm": error, "coordinate_map": rows(coordinate_map), "clips": []}
    optional = read(request["sword_idle_data"])["clips"][0]["samples"] if request.get("sword_idle_data") else None
    for clip in data["clips"]:
        count = min(len(clip["samples"]), 12)
        indices = [round(i*(len(clip["samples"])-1)/max(count-1, 1)) for i in range(count)]
        for event in clip.get("events", []):
            target = round(event["frame"]*(count-1)/max(len(clip["samples"])-1, 1))
            indices[target] = event["frame"]
        if indices != sorted(indices) or len(set(indices)) != count:
            raise ValueError("핵심 이벤트를 보존한 프레임 선택 실패: " + clip["name"])
        item = {"name": clip["name"], "loop": clip.get("loop", False), "frames": [],
                "reference_sample_indices": indices, "properties": [], "events": []}
        for frame, index in enumerate(indices):
            sample = clip["samples"][index]
            if clip["name"] == "sword_idle" and optional:
                # 최신 정지 후보 세 개를 부드러운 반복 초안으로 연결한다.
                phase = frame/count*len(optional)
                first, second = int(phase)%len(optional), (int(phase)+1)%len(optional)
                t = (1-math.cos((phase%1)*math.pi))/2
                sample = {"bones": {}, "objects": optional[first].get("objects", {}),
                          "properties": optional[first].get("properties", {})}
                for name in optional[first]["bones"]:
                    a, b = Matrix(optional[first]["bones"][name]), Matrix(optional[second]["bones"][name])
                    la, qa, sa = a.decompose()
                    lb, qb, sb = b.decompose()
                    sample["bones"][name] = rows(Matrix.LocRotScale(la.lerp(lb,t), qa.slerp(qb,t), sa.lerp(sb,t)))
            for name, matrix in sample["bones"].items():
                rig.pose.bones[name].matrix_basis = Matrix(matrix)
            for name, matrix in sample.get("objects", {}).items():
                bpy.data.objects[name].matrix_basis = Matrix(matrix)
            for name, props in sample.get("properties", {}).items():
                for key, value in props.items():
                    bpy.data.objects[name][key] = value
                    bpy.data.objects[name].update_tag()
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = rig.evaluated_get(graph)
            desired = {n: evaluated.matrix_world @ evaluated.pose.bones[n].matrix for n in order}
            for name in mapping["object_controls"]:
                obj_world = bpy.data.objects[name].evaluated_get(graph).matrix_world
                desired[name] = obj_world @ Matrix(mapping["object_bind_world"][name]).inverted() @ source_all[name]
            values = {}
            for name, matrix in desired.items():
                ue = coordinate_map @ matrix @ correction[name]
                location, rotation, scale = ue.decompose()
                values[names[name]] = {"translation": list(location), "rotation": [rotation.x, rotation.y, rotation.z, rotation.w], "scale": list(scale)}
            item["frames"].append(values)
            item["properties"].append(sample.get("properties", {}))
        for event in clip.get("events", []):
            item["events"].append({**event, "frame": indices.index(event["frame"])})
        output["clips"].append(item)
    output["status"] = "unreal_key_input_draft"
    write(destination, output)
    print("RESULT " + json.dumps({"clips": len(output["clips"]), "frames": sum(len(c["frames"]) for c in output["clips"]), "coordinate_fit_error_cm": error}))


def curve_list(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def key_transform(obj, frame, previous):
    from mathutils import Quaternion, Vector
    if obj.rotation_mode == "QUATERNION":
        quaternion = obj.rotation_quaternion.copy()
    elif obj.rotation_mode == "AXIS_ANGLE":
        angle, x, y, z = obj.rotation_axis_angle
        quaternion = Quaternion(Vector((x,y,z)),angle)
    else:
        quaternion = obj.rotation_euler.to_quaternion()
    key = obj.path_from_id() if hasattr(obj, "bone") else obj.name
    if key in previous:
        quaternion.make_compatible(previous[key])
    previous[key] = quaternion.copy()
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = quaternion
        channel = "rotation_quaternion"
    elif obj.rotation_mode == "AXIS_ANGLE":
        axis, angle = quaternion.to_axis_angle()
        obj.rotation_axis_angle = (angle, *axis)
        channel = "rotation_axis_angle"
    else:
        obj.rotation_euler = quaternion.to_euler(obj.rotation_mode, obj.rotation_euler)
        channel = "rotation_euler"
    for path in ("location", channel, "scale"):
        obj.keyframe_insert(path, frame=frame)


def imported_targets(request, mapping, filename, count):
    import bpy
    from mathutils import Matrix
    original = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(filename), use_anim=True, anim_offset=0)
    imported = [o for o in bpy.data.objects if o not in original]
    rigs = [o for o in imported if o.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("반환 FBX의 리그가 하나가 아니다.")
    incoming = rigs[0]
    world = Matrix(mapping["rig_world"])
    correction = {n: (incoming.matrix_world @ incoming.data.bones[e].matrix_local).inverted() @ world @ Matrix(mapping["source_pose_matrices"][n]) for n,e in mapping["bone_map"].items()}
    object_correction = {n: (incoming.matrix_world @ incoming.data.bones[e].matrix_local).inverted() @ Matrix(mapping["object_bind_world"][n]) for n,e in mapping.get("object_controls",{}).items()}
    def sample(frame):
        bpy.context.scene.frame_set(int(frame), subframe=frame%1)
        evaluated = incoming.evaluated_get(bpy.context.evaluated_depsgraph_get())
        pose = {n: world.inverted() @ evaluated.matrix_world @ evaluated.pose.bones[e].matrix @ correction[n] for n,e in mapping["bone_map"].items()}
        objects = {n: evaluated.matrix_world @ evaluated.pose.bones[e].matrix @ object_correction[n] for n,e in mapping.get("object_controls",{}).items()}
        return pose, objects
    return imported, sample


def import_batch(request):
    import bpy
    from mathutils import Matrix
    mapping, data = read(request["transfer_map"]), read(request["batch_file"])
    output = Path(request["output_blend"])
    if output.exists():
        raise FileExistsError(output)
    if hashlib.sha256(Path(mapping["source"]).read_bytes()).hexdigest() != mapping["source_sha256"]:
        raise ValueError("원본 해시 불일치")
    base_return = request.get("base_return")
    if base_return and hashlib.sha256(Path(base_return).read_bytes()).hexdigest() != request["base_return_sha256"]:
        raise ValueError("수정 대상 반환본 해시 불일치")
    bpy.ops.wm.open_mainfile(filepath=base_return or mapping["source"])
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = data["fps"], 1
    rig = bpy.data.objects[request["rig"]]
    modes = {b.name:b.rotation_mode for b in rig.pose.bones}
    action = rig.animation_data.action if base_return else bpy.data.actions.new(request.get("action_name", "Unreal_41_Draft"))
    action.use_fake_user = True
    rig.animation_data_create().action = action
    keyed_paths = {bone.path_from_id(channel) for bone in rig.pose.bones for channel in ("location","rotation_euler","rotation_quaternion","rotation_axis_angle","scale")}
    muted_drivers = []
    for driver in rig.animation_data.drivers:
        if driver.data_path in keyed_paths:
            driver.mute = True
            muted_drivers.append([driver.data_path,driver.array_index])
    if rig.animation_data:
        for track in rig.animation_data.nla_tracks:
            track.mute = True
    for name in mapping["object_controls"]:
        obj = bpy.data.objects[name]
        for constraint in obj.constraints:
            constraint.mute = True
        obj.animation_data_clear()
        # 무기 루트는 90도 부근의 Euler 특이점을 피한다. 원래 본 모드는 유지한다.
        obj.rotation_mode = "QUATERNION"
    clips, cursor, max_error = [], 1, 0
    for clip in data["clips"]:
        filename = Path(request["fbx_directory"]) / (clip["name"] + ".fbx")
        imported, sample = imported_targets(request, mapping, filename, len(clip["frames"]))
        targets = [sample(f) for f in range(len(clip["frames"]))]
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
        previous = {}
        for frame, (poses, objects) in enumerate(targets, cursor):
            scene.frame_set(frame)
            for name, matrix in ([] if base_return else poses.items()):
                bone = rig.pose.bones[name]
                kwargs = {"invert":True}
                if bone.parent:
                    kwargs.update(parent_matrix=poses[bone.parent.name], parent_matrix_local=bone.parent.bone.matrix_local)
                bone.matrix_basis = bone.bone.convert_local_to_pose(matrix,bone.bone.matrix_local,**kwargs)
                key_transform(bone,frame,previous)
            for name, matrix in objects.items():
                obj = bpy.data.objects[name]
                obj.matrix_world = matrix
                key_transform(obj,frame,previous)
            for name, properties in clip["properties"][frame-cursor].items():
                obj = bpy.data.objects[name]
                for key,value in properties.items():
                    obj[key] = value
                    obj.keyframe_insert('["'+key+'"]',frame=frame)
            bpy.context.view_layer.update()
        scene.timeline_markers.new(clip["name"],frame=cursor)
        record = {"name":clip["name"],"start":cursor,"end":cursor+len(targets)-1,"fps":data["fps"],"loop":clip["loop"],"events":clip["events"],"fbx":str(filename)}
        native_request = Path(request["batch_file"]).parent/(clip["name"]+".request.json")
        if native_request.exists():
            record["unreal_sequence"] = read(native_request)["sequence"]
        clips.append(record)
        cursor += len(targets)+1
    for obj in [rig,*[bpy.data.objects[n] for n in mapping["object_controls"]],bpy.data.objects.get("BasicWeapons")]:
        if obj and obj.animation_data and obj.animation_data.action:
            for curve in curve_list(obj.animation_data.action):
                for point in curve.keyframe_points:
                    point.interpolation = "CONSTANT" if '["' in curve.data_path else "LINEAR"
    scene.frame_start, scene.frame_end = 1, cursor-2
    scene.frame_set(1)
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    write(output.with_suffix(".clips.json"), {"fps":data["fps"],"clips":clips,"source_sha256":mapping["source_sha256"],"action":action.name,"rotation_modes_preserved":modes=={b.name:b.rotation_mode for b in rig.pose.bones},"object_rotation_mode":"QUATERNION","objects_only_repair":bool(base_return),"muted_transform_drivers":muted_drivers,"status":"draft_user_review_pending"})
    print("RESULT " + json.dumps({"clips":len(clips),"frame_end":scene.frame_end,"output":str(output)}))


def verify_batch(request):
    import bpy
    from blender_transfer import orientation_error
    mapping = read(request["transfer_map"])
    catalog = read(Path(request["output_blend"]).with_suffix(".clips.json"))
    bpy.ops.wm.open_mainfile(filepath=mapping["source"])
    original_contract = structure_signature(request["rig"])
    bpy.ops.wm.open_mainfile(filepath=request["output_blend"])
    returned_contract = structure_signature(request["rig"])
    rig = bpy.data.objects[request["rig"]]
    results = []
    object_diagnostics = []
    for clip in catalog["clips"]:
        if request.get("clip_names") and clip["name"] not in request["clip_names"]:
            continue
        count = clip["end"]-clip["start"]+1
        imported, sample = imported_targets(request,mapping,clip["fbx"],count)
        errors = []
        for local in range(count):
            poses, objects = sample(local)
            bpy.context.scene.frame_set(clip["start"]+local)
            graph = bpy.context.evaluated_depsgraph_get()
            actual = rig.evaluated_get(graph)
            for name, expected in poses.items():
                found=actual.pose.bones[name].matrix
                errors.append(((found.translation-expected.translation).length,orientation_error(found,expected),name,local))
            for name, expected in objects.items():
                found=bpy.data.objects[name].evaluated_get(graph).matrix_world
                angle_error = orientation_error(found,expected)
                errors.append(((found.translation-expected.translation).length,angle_error,name,local))
                if angle_error > .01 and not any(d["clip"] == clip["name"] for d in object_diagnostics):
                    obj = bpy.data.objects[name]
                    object_diagnostics.append({"clip":clip["name"],"object":name,"frame":local,
                        "expected":rows(expected),"actual":rows(found),"basis":rows(obj.matrix_basis),
                        "parent_world":rows(obj.parent.matrix_world),"mode":obj.rotation_mode,
                        "expected_decomposition":[list(v) for v in expected.decompose()]})
        results.append({"name":clip["name"],"samples":len(errors),"max_position_error":max(e[0] for e in errors),"max_angle_error":max(e[1] for e in errors),
                        "worst_positions":sorted(errors,reverse=True)[:5],"worst_angles":sorted(errors,key=lambda e:e[1],reverse=True)[:5]})
        for obj in imported:
            bpy.data.objects.remove(obj,do_unlink=True)
    source_unchanged=hashlib.sha256(Path(mapping["source"]).read_bytes()).hexdigest()==mapping["source_sha256"]
    structure_preserved = original_contract == returned_contract
    passed=source_unchanged and structure_preserved and all(c["max_position_error"]<.0001 and c["max_angle_error"]<.0001 for c in results)
    report={"passed":passed,"source_hash_unchanged":source_unchanged,"structure_preserved":structure_preserved,
            "source_contract":original_contract,"return_contract":returned_contract,"clips":results,"object_diagnostics":object_diagnostics,"scope":"저장·재로딩한 정수 프레임의 본·무기 위치·회전 및 원본 메시·UV·웨이트·재질 슬롯·rest 본·패킹 이미지. 연속 간섭·사용감·게임 재생은 별도다."}
    write(request["verification_output"],report)
    print("RESULT "+json.dumps({"passed":passed,"clips":len(results),"samples":sum(c["samples"] for c in results),"max_position_error":max(c["max_position_error"] for c in results),"max_angle_error":max(c["max_angle_error"] for c in results)}))


def structure_signature(rig_name):
    import bpy
    def signature(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    meshes = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        meshes[obj.name] = signature({"vertices":[list(v.co) for v in mesh.vertices],
            "polygons":[(list(p.vertices),p.material_index,p.use_smooth) for p in mesh.polygons],
            "uv":{uv.name:[list(loop.uv) for loop in uv.data] for uv in mesh.uv_layers},
            "weights":[[(obj.vertex_groups[g.group].name,g.weight) for g in v.groups] for v in mesh.vertices],
            "materials":[m.name if m else None for m in mesh.materials],
            "parent":obj.parent.name if obj.parent else None,"parent_type":obj.parent_type,"parent_bone":obj.parent_bone})
    rig = bpy.data.objects[rig_name]
    bones = signature([(b.name,b.parent.name if b.parent else None,rows(b.matrix_local),b.length) for b in rig.data.bones])
    images = {im.name:hashlib.sha256(bytes(im.packed_file.data)).hexdigest() for im in bpy.data.images if im.packed_file}
    return {"objects":sorted(o.name for o in bpy.data.objects),"meshes":meshes,"rest_bones":bones,"packed_images":images}


def review_batch(request):
    import bpy
    import shutil
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"blender_pipeline"))
    from model_review import render_review, capture_fixture, write_pending_review, digest
    bpy.ops.wm.open_mainfile(filepath=request["output_blend"])
    directory = Path(request["review_output"])
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory/"candidate.blend"
    if candidate.exists():
        raise FileExistsError(candidate)
    shutil.copyfile(request["output_blend"], candidate)
    evidence, fixtures = [], {}
    if request["review"].get("per_clip"):
        catalog = read(Path(request["output_blend"]).with_suffix(".clips.json"))
        for clip in catalog["clips"]:
            config = {**request["review"],"frames":list(range(clip["start"],clip["end"]+1))}
            fixture = capture_fixture(config)
            fixtures[clip["name"]] = fixture
            still_fixture = {**fixture,"frames":[(clip["start"]+clip["end"])//2]}
            images = render_review(config,directory/"poses"/clip["name"],still_fixture)
            for item in images:
                item["file"] = "poses/"+clip["name"]+"/"+item["file"]
            evidence.extend(images)
        fixture = fixtures
    else:
        fixture = capture_fixture(request["review"])
        evidence = render_review(request["review"],directory,fixture)
    for item in evidence:
        item["kind"] = "after"
    write(directory/"review_fixture.json", fixture)
    write_pending_review(directory,request["review"]["intent"],evidence,digest(candidate),fixture)
    write(directory/"report.json", {"candidate_sha256":digest(candidate),"review_checkpoint":"awaiting_ai_review",
                                   "visual_approval":False,"quality_checks_run":False})
    if request.get("preview"):
        preview = []
        if request["review"].get("per_clip"):
            for name, bounds in fixtures.items():
                fixture = {**bounds,"views":request["preview"]["views"],"sizes":{"game":request["preview"].get("game_size",240)}}
                preview.extend(render_review(request["preview"],directory/"frames",fixture))
        else:
            fixture = capture_fixture(request["preview"])
            fixture["sizes"] = {"game":request["preview"].get("game_size",240)}
            preview = render_review(request["preview"],directory/"frames",fixture)
        write(directory/"preview_frames.json",preview)
    print("RESULT "+json.dumps({"review":request["review_output"]}))


def run(request):
    {"prepare_batch":prepare_batch,"import_batch":import_batch,"verify_batch":verify_batch,"review_batch":review_batch}[request["operation"]](request)
