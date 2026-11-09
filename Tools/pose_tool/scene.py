"""Blender 네이티브 제약으로 편집하고 기존 리그에 포즈를 전달한다."""

import hashlib
from contextlib import contextmanager
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from .profile import validate_profile, clip_ranges


PREFIX = "FDPOSE_"
STATE = "fd_pose_state"


def state():
    return json.loads(bpy.context.scene[STATE])


def store(data):
    bpy.context.scene[STATE] = json.dumps(data, ensure_ascii=False)


def controls():
    return {o["fd_pose_control"]: o for o in bpy.data.objects if "fd_pose_control" in o}


def palm_offset(rig, key, limb):
    return Vector((0, rig.data.bones[limb["end"]].length * .5, 0)) if key.startswith("hand.") else Vector((0, 0, 0))


def target_matrix(worlds, rig, key, limb):
    return worlds[limb["end"]] @ Matrix.Translation(palm_offset(rig, key, limb))


def wrist_target(collection, key, control, offset):
    if not offset.length:
        return control
    target = bpy.data.objects.new(PREFIX + "WristTarget." + key, None)
    collection.objects.link(target)
    target.parent = control
    target.matrix_basis = Matrix.Translation(-offset)
    target.empty_display_size = 0
    target.hide_select = True
    return target


def upgrade_palm_handles():
    """초기 작업본의 손목 컨트롤 키를 손바닥 컨트롤로 옮기며 포즈를 보존한다."""
    data = state()
    if data.get("palm_handles"):
        return
    from mathutils import Quaternion
    rig, proxy = rig_objects()
    ctrls = controls()
    collection = bpy.data.collections[PREFIX + "Controls"]
    offsets = {}
    for key, limb in data["profile"]["limbs"].items():
        offset = palm_offset(rig, key, limb)
        if not offset.length:
            continue
        offsets[key] = offset
        obj = ctrls[key]
        active = obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None
        actions = {session["controls"][key] for session in data["sessions"].values() if session["controls"].get(key)}
        if active:
            actions.add(active)
        for action_name in actions:
            assign_action(obj, action_name)
            curves = {(c.data_path, c.array_index): c for c in all_curves(obj.animation_data.action)}
            samples = []
            for frame in range(int(obj.animation_data.action.frame_range[0]), int(obj.animation_data.action.frame_range[1])+1):
                read = lambda name, count, default: [curves[(name, i)].evaluate(frame) if (name, i) in curves else default[i] for i in range(count)]
                old = Matrix.LocRotScale(Vector(read("location", 3, (0, 0, 0))),
                                        Quaternion(read("rotation_quaternion", 4, (1, 0, 0, 0))),
                                        Vector(read("scale", 3, (1, 1, 1))))
                samples.append((frame, (old @ Matrix.Translation(offset)).translation))
            for frame, location in samples:
                obj.location = location
                obj.keyframe_insert("location", frame=frame)
        assign_action(obj, active)
        rest = Matrix([obj["fd_pose_rest"][i:i+4] for i in range(0, 16, 4)])
        obj["fd_pose_rest"] = [v for row in rest @ Matrix.Translation(offset) for v in row]
        target = wrist_target(collection, key, obj, offset)
        proxy.pose.bones[limb["lower"]].constraints[PREFIX + "IK"].target = target
    eq = data["profile"].get("equipment", {})
    main = offsets.get("hand." + eq.get("main_hand", "R"), Vector((0, 0, 0)))
    support = offsets.get("hand." + eq.get("support_hand", "L"), Vector((0, 0, 0)))
    for session in data["sessions"].values():
        if session.get("support"):
            session["support"] = [list(row) for row in Matrix.Translation(-main) @ Matrix(session["support"]) @ Matrix.Translation(support)]
    anchor = bpy.data.objects.get(PREFIX + "SupportAnchor")
    if anchor:
        anchor.matrix_basis = Matrix.Translation(-main) @ anchor.matrix_basis @ Matrix.Translation(support)
    data["palm_handles"] = True
    store(data)
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)


def update():
    bpy.context.view_layer.update()


def all_curves(action):
    if action is None:
        return
    if hasattr(action, "layers") and action.is_action_layered:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def linear_keys(action):
    for curve in all_curves(action):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"


def assign_action(obj, name):
    anim = obj.animation_data_create()
    anim.action = bpy.data.actions.get(name) if name else None
    if anim.action and hasattr(anim, "action_suitable_slots") and anim.action_suitable_slots:
        anim.action_slot = anim.action_suitable_slots[0]


def key_transform(obj, frame):
    for channel in ("location", "rotation_quaternion", "scale"):
        obj.keyframe_insert(channel, frame=frame)


def rig_objects():
    data = state()
    return bpy.data.objects[data["profile"]["rig"]], bpy.data.objects[data["proxy"]]


def source_mode(enabled):
    original, _ = rig_objects()
    saved = state()["original_constraints"]
    for bone in original.pose.bones:
        for con in bone.constraints:
            if con.name.startswith(PREFIX):
                con.mute = enabled
            else:
                con.mute = saved[bone.name][con.name] if enabled else True
    update()


def proxy_constraints(mute):
    _, proxy = rig_objects()
    for bone in proxy.pose.bones:
        for con in bone.constraints:
            con.mute = mute
    update()


def world_bones(rig):
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {b.name: evaluated.matrix_world @ b.matrix for b in evaluated.pose.bones}


def local_basis(rig, worlds):
    """부모의 평가 행렬을 사용해 최종 자세를 로컬 값으로 변환한다."""
    inverse = rig.matrix_world.inverted()
    poses = {name: inverse @ matrix for name, matrix in worlds.items()}
    result = {}
    for bone in rig.data.bones:
        kwargs = {"parent_matrix": poses[bone.parent.name],
                  "parent_matrix_local": bone.parent.matrix_local} if bone.parent else {}
        result[bone.name] = bone.convert_local_to_pose(poses[bone.name], bone.matrix_local,
                                                     invert=True, **kwargs)
    return result


def create_control(collection, key, matrix, size, display="CUBE", parent=None):
    obj = bpy.data.objects.new(PREFIX + key, None)
    collection.objects.link(obj)
    obj.empty_display_type = display
    obj.empty_display_size = size
    obj.show_in_front = True
    obj.show_name = False
    obj.rotation_mode = "QUATERNION"
    obj.parent = parent
    obj.matrix_world = matrix
    obj.empty_display_size = size / max(matrix.to_scale().length / math.sqrt(3), 1e-6)
    obj["fd_pose_control"] = key
    obj["fd_pose_rest"] = [v for row in matrix for v in row]
    obj.color = (0.30, 0.74, 0.90, 1) if key.endswith(".L") else (0.92, 0.52, 0.41, 1)
    if "." not in key:
        obj.color = (0.57, 0.68, 0.73, 1)
    return obj


def pole_position(worlds, limb):
    origin = worlds[limb["upper"]].translation
    elbow = worlds[limb["lower"]].translation
    end = worlds[limb["end"]].translation
    axis = (end - origin).normalized()
    bend = elbow - origin - axis * (elbow - origin).dot(axis)
    if bend.length < 1e-5:
        bend = worlds[limb["upper"]].to_3x3().col[0]
        bend -= axis * bend.dot(axis)
    if bend.length < 1e-5:
        bend = axis.cross(Vector((0, 0, 1)))
    return elbow + bend.normalized() * max((elbow-origin).length, (end-elbow).length)


def calibrate_pole(proxy, limb, desired):
    """현재 굽힘·roll을 유지하는 pole angle을 네이티브 IK 평가로 찾는다."""
    con = proxy.pose.bones[limb["lower"]].constraints[PREFIX + "IK"]
    names = (limb["upper"], limb["lower"])

    def error(angle):
        con.pole_angle = angle
        update()
        evaluated = proxy.evaluated_get(bpy.context.evaluated_depsgraph_get())
        angles = [(evaluated.matrix_world @ evaluated.pose.bones[n].matrix).to_quaternion().rotation_difference(
            desired[n].to_quaternion()).angle for n in names]
        return sum(min(angle, math.tau-angle) ** 2 for angle in angles)

    con.pole_angle = 0
    update()
    actual = world_bones(proxy)
    origin = desired[limb["upper"]].translation
    axis = (desired[limb["end"]].translation-origin).normalized()
    current = actual[limb["lower"]].translation-origin
    target = desired[limb["lower"]].translation-origin
    current -= axis * current.dot(axis)
    target -= axis * target.dot(axis)
    delta = math.atan2(axis.dot(current.cross(target)), current.dot(target))
    wrap = lambda angle: (angle + math.pi) % math.tau - math.pi
    best = min((0, delta, -delta), key=lambda angle: error(wrap(angle)))
    if error(wrap(best)) > 1e-5:
        step = math.tau / 16
        best = min(((-math.pi + i * step) for i in range(16)), key=error)
        for _ in range(12):
            best = min((wrap(best-step), wrap(best), wrap(best+step)), key=error)
            step *= .5
    con.pole_angle = wrap(best)
    update()
    return con.pole_angle


@contextmanager
def suspend_meshes():
    """IK 보정은 메시를 입력으로 사용하지 않는다. 반복 평가 비용만 잠시 끈다."""
    meshes = [(obj, obj.hide_viewport) for obj in bpy.data.objects if obj.type == "MESH"]
    try:
        for obj, _ in meshes:
            obj.hide_viewport = True
        yield
    finally:
        for obj, hidden in meshes:
            obj.hide_viewport = hidden
        update()


def calibrate_samples(proxy, limbs, samples):
    with suspend_meshes():
        for frame, desired in samples:
            bpy.context.scene.frame_set(frame)
            for limb in limbs.values():
                calibrate_pole(proxy, limb, desired)
                proxy.pose.bones[limb["lower"]].constraints[PREFIX + "IK"].keyframe_insert("pole_angle", frame=frame)


def prepare(profile, source_path=None, metadata=None):
    if STATE in bpy.context.scene:
        raise ValueError("이미 Pose Tool 작업본이다. 작업본을 그대로 연다.")
    profile = validate_profile(profile)
    original = bpy.data.objects.get(profile["rig"])
    if not original or original.type != "ARMATURE":
        raise ValueError(f"Armature 없음: {profile['rig']}")
    if original.library:
        raise ValueError("링크된 Armature는 로컬 작업본으로 준비한다.")
    needed = list(profile["body"].values()) + [n for limb in profile["limbs"].values() for n in limb.values()]
    for name in needed:
        if name not in original.pose.bones:
            raise ValueError(f"매핑한 본 없음: {name}")
    worlds = world_bones(original)
    for limb in profile["limbs"].values():
        upper, lower, end = [original.pose.bones[limb[k]] for k in ("upper", "lower", "end")]
        if lower.parent != upper or (worlds[end.name].translation - original.matrix_world @ lower.tail).length > 1e-3:
            raise ValueError("두 관절 IK는 직접 연결된 upper/lower와 lower.tail 위치의 end가 필요하다.")
    if any(o.name.startswith(PREFIX) for o in bpy.data.objects):
        raise ValueError("FDPOSE_ 이름 충돌")
    clips = clip_ranges(bpy.context.scene, metadata)
    source = Path(source_path or bpy.data.filepath).resolve() if (source_path or bpy.data.filepath) else None
    data = {"version": 1, "palm_handles": True, "profile": profile, "source": str(source) if source else None,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest() if source else None,
            "clips": clips, "active": None, "sessions": {},
            "original_constraints": {b.name: {c.name: c.mute for c in b.constraints} for b in original.pose.bones}}
    collection = bpy.data.collections.new(PREFIX + "Controls")
    bpy.context.scene.collection.children.link(collection)
    proxy = original.copy()
    proxy.data = original.data.copy()
    proxy.name = PREFIX + "Rig"
    collection.objects.link(proxy)
    proxy.animation_data_clear()
    proxy.hide_render = True
    proxy.hide_select = True
    proxy.display_type = "WIRE"
    proxy.show_in_front = False
    for bone in proxy.pose.bones:
        for con in list(bone.constraints):
            bone.constraints.remove(con)
    # 복사한 데이터의 드라이버는 원본 본/장치를 다시 참조할 수 있으므로 제거한다.
    if proxy.data.animation_data:
        proxy.data.animation_data_clear()
    data["proxy"] = proxy.name
    store(data)
    size = max(original.dimensions.length * .025, .06)
    base = bpy.data.objects.new(PREFIX + "Root", None)
    collection.objects.link(base)
    base.matrix_world = original.matrix_world
    base.hide_viewport = False
    base.hide_select = True
    base.empty_display_size = 0
    body_by_bone = {bone: key for key, bone in profile["body"].items()}
    created = {}
    ordered = sorted(profile["body"].items(), key=lambda pair: len(original.pose.bones[pair[1]].parent_recursive))
    for key, name in ordered:
        ancestor = original.pose.bones[name].parent
        while ancestor and ancestor.name not in body_by_bone:
            ancestor = ancestor.parent
        parent = created[body_by_bone[ancestor.name]] if ancestor else base
        obj = create_control(collection, key, worlds[name], size * (2 if key in ("pelvis", "chest") else 1.2), "CIRCLE", parent)
        obj["fd_pose_rest"] = [v for row in original.matrix_world @ original.data.bones[name].matrix_local for v in row]
        created[key] = obj
        con = proxy.pose.bones[name].constraints.new("COPY_TRANSFORMS")
        con.name, con.target = PREFIX + "Body", obj
        con.target_space = con.owner_space = "WORLD"
    for key, limb in profile["limbs"].items():
        end = create_control(collection, key, target_matrix(worlds, original, key, limb), size, "CUBE", base)
        offset = palm_offset(original, key, limb)
        end["fd_pose_rest"] = [v for row in original.matrix_world @ original.data.bones[limb["end"]].matrix_local @ Matrix.Translation(offset) for v in row]
        target = wrist_target(collection, key, end, offset)
        pole_matrix = Matrix.Translation(pole_position(worlds, limb))
        pole = create_control(collection, "pole." + key, pole_matrix, size * .65, "SPHERE", base)
        con = proxy.pose.bones[limb["lower"]].constraints.new("IK")
        con.name, con.target, con.pole_target = PREFIX + "IK", target, pole
        con.chain_count, con.use_stretch, con.iterations = 2, False, 128
        con = proxy.pose.bones[limb["end"]].constraints.new("COPY_ROTATION")
        con.name, con.target = PREFIX + "End", end
        con.target_space = con.owner_space = "WORLD"
    proxy_constraints(True)
    for bone in original.pose.bones:
        con = bone.constraints.new("COPY_TRANSFORMS")
        con.name, con.target, con.subtarget = PREFIX + "Result", proxy, bone.name
        con.target_space = con.owner_space = "WORLD"
        con.mute = True
    original.hide_select = True
    proxy.hide_set(True)
    # hide_set은 뷰포트의 본 표시만 숨긴다. 제약 평가에는 사용된다.
    activate_clip(clips[0]["name"])
    for obj in bpy.context.scene.objects:
        if "fd_pose_control" not in obj:
            obj.hide_select = True
            if obj.type in ("EMPTY", "ARMATURE") and not obj.name.startswith(PREFIX):
                obj.hide_set(True)
    return state()


def support_pin(enabled):
    data = state()
    spec = data["profile"].get("equipment", {})
    ctrls = controls()
    main = ctrls["hand." + spec.get("main_hand", "R")]
    support = ctrls["hand." + spec.get("support_hand", "L")]
    con = support.constraints.get(PREFIX + "Support")
    if not enabled:
        if con:
            world = support.matrix_world.copy()
            support.constraints.remove(con)
            support.matrix_world = world
        return
    if con:
        return
    # 주 손 컨트롤을 기준으로 현재 파지를 유지한다. 원본 무기를 참조하면 리그 순환이 생긴다.
    anchor = bpy.data.objects.get(PREFIX + "SupportAnchor")
    if anchor is None:
        anchor = bpy.data.objects.new(PREFIX + "SupportAnchor", None)
        bpy.data.collections[PREFIX + "Controls"].objects.link(anchor)
    anchor.parent = main
    anchor.matrix_world = support.matrix_world
    anchor.hide_select = True
    anchor.empty_display_size = 0
    con = support.constraints.new("COPY_TRANSFORMS")
    con.name, con.target = PREFIX + "Support", anchor
    con.owner_space = con.target_space = "WORLD"
    update()


def stash_session(data):
    if data["active"]:
        _, proxy = rig_objects()
        data["sessions"][data["active"]] = {
            "proxy": proxy.animation_data.action.name if proxy.animation_data and proxy.animation_data.action else None,
            "controls": {key: obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None
                         for key, obj in controls().items()},
            "angles": {key: proxy.pose.bones[limb["lower"]].constraints[PREFIX + "IK"].pole_angle
                       for key, limb in data["profile"]["limbs"].items()},
        }
        anchor = bpy.data.objects.get(PREFIX + "SupportAnchor")
        pinned = any(obj.constraints.get(PREFIX + "Support") for obj in controls().values())
        data["sessions"][data["active"]]["support"] = [list(row) for row in anchor.matrix_basis] if pinned and anchor else None
        for name in [data["sessions"][data["active"]]["proxy"], *data["sessions"][data["active"]]["controls"].values()]:
            if name:
                bpy.data.actions[name].use_fake_user = True


def activate_clip(name):
    data = state()
    clip = next(c for c in data["clips"] if c["name"] == name)
    if data["active"] == name:
        bpy.context.scene.frame_set(clip["start"])
        return
    stash_session(data)
    support_pin(False)
    original, proxy = rig_objects()
    ctrls = controls()
    cached = data["sessions"].get(name)
    data["active"] = name
    store(data)
    if cached:
        assign_action(proxy, cached["proxy"])
        for key, obj in ctrls.items():
            assign_action(obj, cached["controls"][key])
        for key, limb in data["profile"]["limbs"].items():
            proxy.pose.bones[limb["lower"]].constraints[PREFIX + "IK"].pole_angle = cached["angles"][key]
    else:
        source_mode(True)
        proxy_constraints(True)
        samples = []
        for frame in range(clip["start"], clip["end"] + 1):
            bpy.context.scene.frame_set(frame)
            samples.append((frame, world_bones(original)))
        assign_action(proxy, None)
        for obj in ctrls.values():
            assign_action(obj, None)
        for frame, worlds in samples:
            bpy.context.scene.frame_set(frame)
            for bone_name, basis in local_basis(proxy, worlds).items():
                bone = proxy.pose.bones[bone_name]
                bone.rotation_mode = "QUATERNION"
                bone.matrix_basis = basis
                key_transform(bone, frame)
            for key, bone_name in data["profile"]["body"].items():
                ctrls[key].matrix_world = worlds[bone_name]
                update()
                key_transform(ctrls[key], frame)
            for key, limb in data["profile"]["limbs"].items():
                ctrls[key].matrix_world = target_matrix(worlds, original, key, limb)
                ctrls["pole." + key].matrix_world = Matrix.Translation(pole_position(worlds, limb))
                key_transform(ctrls[key], frame)
                key_transform(ctrls["pole." + key], frame)
        proxy.animation_data.action.name = PREFIX + name + "_pose"
        for key, obj in ctrls.items():
            obj.animation_data.action.name = PREFIX + name + "_" + key
            linear_keys(obj.animation_data.action)
        linear_keys(proxy.animation_data.action)
        proxy_constraints(False)
        # 본의 로컬 roll과 부모 자세에 맞는 pole angle은 프레임별로 다를 수 있다.
        calibrate_samples(proxy, data["profile"]["limbs"], samples)
        for curve in all_curves(proxy.animation_data.action):
            if curve.data_path.endswith(".pole_angle"):
                for point in curve.keyframe_points:
                    point.interpolation = "CONSTANT"
    proxy_constraints(False)
    source_mode(False)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = clip["start"], clip["end"]
    scene.render.fps = clip["fps"]
    scene.frame_set(clip["start"])
    if cached and cached.get("support"):
        support_pin(True)
        bpy.data.objects[PREFIX + "SupportAnchor"].matrix_basis = Matrix(cached["support"])
        update()
    stash_session(data)
    store(data)


def key_pose():
    frame = bpy.context.scene.frame_current
    for obj in controls().values():
        pin = obj.constraints.get(PREFIX + "Support")
        if pin:
            world = obj.matrix_world.copy()
            pin.mute = True
            obj.matrix_world = world
        key_transform(obj, frame)
        if pin:
            pin.mute = False
        linear_keys(obj.animation_data.action)
    update()
    data = state()
    equipment = data["profile"].get("equipment", {})
    obj = bpy.data.objects.get(equipment.get("object", ""))
    if obj:
        # 원래 장비 Action은 첫 편집 시 복사한다.
        if obj.animation_data and obj.animation_data.action and not obj.animation_data.action.name.startswith(PREFIX):
            obj.animation_data.action = obj.animation_data.action.copy()
            obj.animation_data.action.name = PREFIX + "Equipment"
        for prop in equipment.get("properties", []):
            if prop in obj:
                obj.keyframe_insert(f'["{prop}"]', frame=frame)
                for curve in all_curves(obj.animation_data.action):
                    if curve.data_path == f'["{prop}"]':
                        for point in curve.keyframe_points:
                            point.interpolation = "CONSTANT"
    return frame


def mirror_pose(direction="BOTH"):
    support_pin(False)
    data, ctrls = state(), controls()
    original, _ = rig_objects()
    reflection = Matrix.Identity(4)
    reflection["XYZ".index(data["profile"]["mirror_axis"])]["XYZ".index(data["profile"]["mirror_axis"])] = -1
    reflection = original.matrix_world @ reflection @ original.matrix_world.inverted()
    matrices = {key: obj.matrix_world.copy() for key, obj in ctrls.items()}
    results = {}
    for key, obj in ctrls.items():
        if direction == "L_TO_R" and not key.endswith(".R"):
            continue
        if direction == "R_TO_L" and not key.endswith(".L"):
            continue
        source_key = key[:-1] + ("R" if key.endswith(".L") else "L") if key.endswith((".L", ".R")) else key
        if source_key not in ctrls:
            continue
        if key.startswith("pole."):
            results[key] = Matrix.Translation(reflection @ matrices[source_key].translation)
        else:
            source_rest = Matrix([ctrls[source_key]["fd_pose_rest"][i:i+4] for i in range(0, 16, 4)])
            target_rest = Matrix([obj["fd_pose_rest"][i:i+4] for i in range(0, 16, 4)])
            results[key] = reflection @ (matrices[source_key] @ source_rest.inverted()) @ reflection.inverted() @ target_rest
    def depth(obj):
        count = 0
        while obj.parent:
            obj = obj.parent
            count += 1
        return count
    for key in sorted(results, key=lambda k: depth(ctrls[k])):
        ctrls[key].matrix_world = results[key]
        update()


def save_work(destination):
    path = Path(destination).resolve()
    data = state()
    if data["source"] and path == Path(data["source"]).resolve():
        raise ValueError("원본 경로에는 저장할 수 없다.")
    if path.suffix.lower() != ".blend":
        raise ValueError(".blend 작업본 경로가 필요하다.")
    stash_session(data)
    store(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    return path


def export_clip(destination):
    """편집한 동작만 기존 animation_pipeline의 표본 JSON 계약으로 출력한다."""
    data = state()
    clip = next(c for c in data["clips"] if c["name"] == data["active"])
    path = Path(destination).resolve()
    if path.exists():
        raise FileExistsError("출력 폴더가 이미 있다. 새 폴더를 지정한다.")
    original, _ = rig_objects()
    equipment = data["profile"].get("equipment", {})
    eq = bpy.data.objects.get(equipment.get("object", ""))
    current = bpy.context.scene.frame_current
    samples = []
    try:
        for frame in range(clip["start"], clip["end"] + 1):
            bpy.context.scene.frame_set(frame)
            sample = {"frame": frame, "bones": {name: [list(row) for row in matrix]
                       for name, matrix in local_basis(original, world_bones(original)).items()}}
            if data.get("independent_parts"):
                sample["objects"] = {name: [list(row) for row in bpy.data.objects[name].matrix_basis]
                                     for name in data["independent_parts"]}
            if eq:
                sample["properties"] = {eq.name: {p: eq[p] for p in equipment.get("properties", []) if p in eq}}
            samples.append(sample)
    finally:
        bpy.context.scene.frame_set(current)
    # 기존 파이프라인의 검증·게임 출력 설정을 그대로 재사용한다.
    path.mkdir(parents=True)
    source = Path(data["source"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != data["source_sha256"]:
        raise ValueError("원본이 바뀌었다. 새 작업본에서 다시 시작한다.")
    # 원본 제약을 뮤트한 출력용 기반 장면을 별도 사본으로 저장한다.
    mute_states = [(con, con.mute) for bone in original.pose.bones for con in bone.constraints]
    try:
        for con, _ in mute_states:
            con.mute = True
        bpy.ops.wm.save_as_mainfile(filepath=str(path / "base.blend"), copy=True)
    finally:
        for con, mute in mute_states:
            con.mute = mute
        update()
    events = []
    for event in clip.get("events", []):
        # 초기 작업본에 저장된 clips.json의 전역 이벤트도 재개할 수 있다.
        frame = clip["frames"][event["clip_frame"]]-clip["start"] if "clip_frame" in event else event["frame"]
        events.append({k: v for k, v in event.items() if k not in ("frame", "clip_frame")} | {"frame": frame})
    result = {"version": 1, "asset_id": "pose_edit", "source": "base.blend",
              "source_sha256": hashlib.sha256((path / "base.blend").read_bytes()).hexdigest(),
              "rig": original.name, "root": data["profile"].get("root", original.parent.name if original.parent else original.name),
              "fps": clip["fps"], "clips": [{"name": clip["name"], "label": clip["label"],
                        "events": events, "samples": samples}]}
    from Tools.blender_pipeline.animation_pipeline import validate
    validate(result)
    (path / "poses.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return path / "poses.json"
