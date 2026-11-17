"""기존 Unreal 골격을 보존해 출력 단위 메시·공유 포즈·검증 장면을 만든다."""
import json
import os
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parents[2]


def partition_parts(plan, groups):
    known = {part["id"]: part for part in plan["parts"]}
    result, used = {}, set()
    for key, ids in groups.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
            raise ValueError("출력 단위 ID 오류")
        if not ids or len(ids) != len(set(ids)) or any(i not in known or i in used for i in ids):
            raise ValueError("없는 부품·중복·빈 출력 단위: " + key)
        used.update(ids)
        result[key] = [known[i] for i in ids]
    if used != set(known):
        raise ValueError("출력 단위에서 빠진 부품: " + str(sorted(set(known) - used)))
    return result


def prepare(request):
    import unreal
    from rig_workspace import assemble_rigid_mesh
    plan = json.loads((ROOT / request["rig_plan"]).read_text(encoding="utf-8"))
    groups = partition_parts(plan, request["groups"])
    prefix = request["asset_root"]
    if not prefix.startswith("/Game/MechLab/RenderUnits_") or ".." in prefix:
        raise ValueError("출력 후보 전용 경로가 필요하다.")
    if unreal.EditorAssetLibrary.list_assets(prefix, recursive=True):
        raise FileExistsError(prefix)
    source = unreal.load_asset(request["source_mesh"])
    if not isinstance(source, unreal.SkeletalMesh):
        raise ValueError("기존 Unreal 리그 메시가 필요하다.")
    modifier = unreal.SkeletonModifier()
    modifier.set_skeletal_mesh(source)
    names = [str(n) for n in modifier.get_all_bone_names()]
    animation = unreal.load_asset(request["animation"]) if request.get("animation") else None
    if request.get("animation") and (not isinstance(animation, unreal.AnimSequence) or animation.get_editor_property("skeleton") != source.skeleton):
        raise ValueError("같은 Skeleton의 AnimSequence가 필요하다.")
    if request.get("validation_motion") and animation:
        raise ValueError("제작용 동작과 검증용 동작을 함께 지정할 수 없다.")
    count = request.get("frame_count", 2)
    if type(count) is not int or not 1 <= count <= (4096 if request.get("pose_table") is True else 12):
        raise ValueError("1~12 프레임이 필요하다.")
    if request.get("reference_from_parts"):
        source, _ = assemble_rigid_mesh(plan["parts"], source.skeleton, names, prefix + "/SK_Reference")
    meshes, rows = {}, {}
    for key, parts in groups.items():
        if request.get("reuse_mesh_root") or key in request.get("reuse_meshes", {}):
            path = (request["reuse_meshes"][key] if key in request.get("reuse_meshes", {})
                    else request["reuse_mesh_root"] + "/SK_" + key)
            mesh = unreal.load_asset(path)
            if not isinstance(mesh, unreal.SkeletalMesh) or mesh.skeleton != source.skeleton:
                raise ValueError("재사용할 출력 메시의 골격 불일치: " + key)
            bindings = [{"asset": p["asset"], "bone": p["bone"], "bone_index": names.index(p["bone"])} for p in parts]
        else:
            mesh, bindings = assemble_rigid_mesh(parts, source.skeleton, names, prefix + "/SK_" + key)
        check = unreal.SkeletonModifier()
        check.set_skeletal_mesh(mesh)
        if [str(n) for n in check.get_all_bone_names()] != names:
            raise RuntimeError("분리 후 골격 불일치: " + key)
        meshes[key] = mesh
        rows[key] = {"mesh": mesh.get_path_name(), "parts": [p["id"] for p in parts], "bindings": bindings}
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    master = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector())
    master.set_actor_label("PoseMaster")
    master.set_editor_property("layers", [unreal.Name("unsplit_reference")])
    controller = master.skeletal_mesh_component
    controller.set_skeletal_mesh_asset(source)
    controller.set_editor_property("visibility_based_anim_tick_option", unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
    controller.set_visibility(False)
    controller.set_cast_shadow(True)
    controller.set_editor_property("cast_hidden_shadow", True)
    followers = []
    for key, mesh in meshes.items():
        actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector())
        actor.set_actor_label(key)
        actor.set_editor_property("layers", [unreal.Name(key)])
        actor.attach_to_actor(master, unreal.Name("None"), unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        component = actor.skeletal_mesh_component
        component.set_skeletal_mesh_asset(mesh)
        component.set_leader_pose_component(controller, True, False)
        component.set_cast_shadow(False)
        followers.append(component)
    create_shadow_receiver(actors, prefix, request.get("receiver_gray",1.0))
    pitch, yaw, roll = request.get("light_rotation", [-65, -150, 0])
    lighting = request.get("lighting", {})
    if lighting.get("source_lights"):
        for row in lighting["source_lights"]:
            if row["type"] != "AREA":
                raise ValueError("현재 원본 면광원만 지원한다.")
            matrix = row["matrix_world"]
            position = unreal.Vector(matrix[0][3]*100,-matrix[1][3]*100,matrix[2][3]*100)
            direction = unreal.Vector(-matrix[0][2],matrix[1][2],-matrix[2][2])
            light = actors.spawn_actor_from_class(unreal.RectLight,position)
            light.set_actor_label("Source_"+row["name"])
            light.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(position,position+direction),False)
            component = light.get_component_by_class(unreal.RectLightComponent)
            component.set_mobility(unreal.ComponentMobility.MOVABLE)
            component.set_editor_property("intensity_units",unreal.LightUnits.LUMENS)
            component.set_editor_property("attenuation_radius",lighting.get("attenuation_radius_cm",10000.0))
            component.set_editor_property("intensity",row["energy"]*lighting.get("power_scale",1.0))
            component.set_editor_property("source_width",row["size"]*100)
            component.set_editor_property("source_height",(row["size_y"] if row["shape"] == "RECTANGLE" else row["size"])*100)
            component.set_light_color(unreal.LinearColor(*row["color"],1),False)
    else:
        light = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 900))
        light.set_actor_rotation(unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll), False)
        light.light_component.set_editor_property("intensity", lighting.get("key_intensity", 3.0))
        if lighting.get("fill_intensity", 0):
            fill = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 800))
            fp, fy, fr = lighting.get("fill_rotation", [-25, 30, 0])
            fill.set_actor_rotation(unreal.Rotator(pitch=fp, yaw=fy, roll=fr), False)
            fill.light_component.set_editor_property("intensity", lighting["fill_intensity"])
    if lighting.get("environment"):
        sky = actors.spawn_actor_from_class(unreal.SkyLight,unreal.Vector(0,0,900))
        component = sky.get_component_by_class(unreal.SkyLightComponent)
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
        component.set_editor_property("source_type",unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
        component.set_editor_property("cubemap",unreal.load_asset(lighting["environment"]))
        component.set_editor_property("intensity",lighting.get("environment_intensity",1.0))
    camera = actors.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(*request["camera"]["position"]))
    target = unreal.Vector(*request["camera"]["target"])
    camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(camera.get_actor_location(), target), False)
    camera.camera_component.set_editor_property("projection_mode", unreal.CameraProjectionMode.ORTHOGRAPHIC)
    camera.camera_component.set_editor_property("ortho_width", request["camera"]["width_cm"])
    camera.camera_component.set_editor_property("aspect_ratio", request["size"][0] / request["size"][1])
    unreal.EditorLoadingAndSavingUtils.save_map(world, prefix + "/MAP_Render")
    if request.get("validation_motion"):
        animation = create_validation_motion(source, modifier, names, prefix)
    write_sequence(prefix, "LS_Render", master, camera, animation, count)
    unreal.EditorLoadingAndSavingUtils.save_map(world, prefix + "/MAP_Render")
    # 분리 전 전체 메시를 같은 조명·동작으로 비교하는 별도 장면이다.
    controller.set_visibility(True)
    controller.set_cast_shadow(True)
    for component in followers:
        component.set_visibility(False)
        component.set_cast_shadow(False)
    unreal.EditorLoadingAndSavingUtils.save_map(world, prefix + "/MAP_Reference")
    # Save As 뒤 새 맵을 다시 열어 참조 Sequence의 Actor 경로를 고정한다.
    unreal.EditorLoadingAndSavingUtils.load_map(prefix + "/MAP_Reference")
    current = actors.get_all_level_actors()
    master = next(actor for actor in current if actor.get_actor_label() == "PoseMaster")
    camera = next(actor for actor in current if isinstance(actor, unreal.CameraActor))
    write_sequence(prefix, "LS_Reference", master, camera, animation, count)
    rotation = camera.get_actor_rotation()
    right = unreal.MathLibrary.get_right_vector(rotation)
    up = unreal.MathLibrary.get_up_vector(rotation)
    offset = unreal.Vector() - target
    pixels = request["size"][0] / request["camera"]["width_cm"]
    dot = lambda a, b: a.x*b.x + a.y*b.y + a.z*b.z
    pivot = [request["size"][0]/2 + dot(offset, right)*pixels,
             request["size"][1]/2 + dot(offset, up)*pixels]
    report = {"source_mesh": source.get_path_name(), "skeleton": source.skeleton.get_path_name(), "bones": names,
              "parts": rows, "count": sum(len(p) for p in groups.values()), "map": prefix + "/MAP_Render", "sequence": prefix + "/LS_Render",
              "reference_map": prefix + "/MAP_Reference", "reference_sequence": prefix + "/LS_Reference", "pivot": pivot,
              "animation": animation.get_path_name() if animation else None, "validation_motion": bool(request.get("validation_motion")),
              "frame_count": count, "shadow_caster": "PoseMaster full mesh", "light_rotation": [pitch, yaw, roll], "lighting":lighting}
    if request.get("energy_materials"):
        unreal.EditorLoadingAndSavingUtils.load_map(prefix+"/MAP_Render")
        for actor in actors.get_all_level_actors():
            if not isinstance(actor,unreal.SkeletalMeshActor):
                continue
            component=actor.skeletal_mesh_component
            for index in range(component.get_num_materials()):
                material=component.get_material(index)
                path=material.get_path_name()
                if path not in request["energy_materials"]:
                    raise ValueError("에너지 재질 대응 누락: "+path)
                component.set_material(index,unreal.load_asset(request["energy_materials"][path]))
        world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.EditorLoadingAndSavingUtils.save_map(world,prefix+"/MAP_Energy")
        unreal.EditorLoadingAndSavingUtils.load_map(prefix+"/MAP_Energy")
        current=actors.get_all_level_actors()
        master=next(a for a in current if a.get_actor_label()=="PoseMaster")
        camera=next(a for a in current if isinstance(a,unreal.CameraActor))
        write_sequence(prefix,"LS_Energy",master,camera,animation,count)
        report["energy_map"]=prefix+"/MAP_Energy"
        report["energy_sequence"]=prefix+"/LS_Energy"
    report_path = ROOT / request["report"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def create_validation_motion(source, modifier, names, prefix):
    """손목만 움직이는 진단 동작. 제작용 KeyPose 후보가 아니다."""
    import unreal
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.AnimSequenceFactory()
    factory.target_skeleton = source.skeleton
    animation = tools.create_asset("A_SplitCheck", prefix, unreal.AnimSequence, factory)
    data = animation.get_editor_property("controller")
    data.open_bracket("출력 단위 가동 검사", False)
    data.set_frame_rate(unreal.FrameRate(60, 1), False)
    data.set_frame_rate(unreal.FrameRate(12, 1), False)
    # 압축 기본 30fps에서도 정수 샘플 길이인 0.5초를 사용한다.
    data.set_number_of_frames(unreal.FrameNumber(6), False)
    for name in names:
        t = modifier.get_bone_transform(name)
        data.add_bone_curve(name, False)
        changed = unreal.Rotator(pitch=0, yaw=0, roll=15).quaternion() if name == "hand_l" else t.rotation
        data.set_bone_track_keys(name, [t.translation] * 7, [t.rotation] + [changed] * 6, [t.scale3d] * 7, False)
    data.close_bracket(False)
    unreal.EditorAssetLibrary.save_loaded_asset(animation)
    return animation


def create_shadow_receiver(actors, prefix, gray=1.0):
    import unreal
    floor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, -.5))
    floor.set_actor_label("ShadowReceiver")
    floor.set_editor_property("layers", [unreal.Name("shadow_receiver")])
    floor.static_mesh_component.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Plane.Plane"))
    floor.set_actor_scale3d(unreal.Vector(100, 100, 1))
    floor.static_mesh_component.set_cast_shadow(False)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_ShadowReceiver", prefix, unreal.Material, unreal.MaterialFactoryNew())
    expression = unreal.MaterialEditingLibrary.create_material_expression(material, unreal.MaterialExpressionConstant3Vector)
    expression.set_editor_property("constant", unreal.LinearColor(gray, gray, gray, 1))
    unreal.MaterialEditingLibrary.connect_material_property(expression, "", unreal.MaterialProperty.MP_BASE_COLOR)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    floor.static_mesh_component.set_material(0, material)

    return floor


def write_sequence(prefix, name, master, camera, animation=None, count=2):
    import unreal
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sequence = tools.create_asset(name, prefix, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(12, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(count)
    if animation:
        binding = sequence.add_possessable(master)
        track = binding.add_track(unreal.MovieSceneSkeletalAnimationTrack)
        section = track.add_section()
        params = section.get_editor_property("params")
        params.set_editor_property("animation", animation)
        section.set_editor_property("params", params)
        section.set_range(0, count)
    camera_binding = sequence.add_possessable(camera)
    cut = sequence.add_track(unreal.MovieSceneCameraCutTrack).add_section()
    cut.set_range(0, count)
    identity = unreal.MovieSceneObjectBindingID()
    identity.set_editor_property("guid", camera_binding.get_id())
    cut.set_camera_binding_id(identity)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    return sequence


def shadow_reference(request):
    """같은 광원 품질에서 투사체만 끈 그림자 기준 장면."""
    import unreal
    prefix=request["asset_root"]
    if not prefix.startswith("/Game/MechLab/RenderUnits_") or unreal.EditorAssetLibrary.list_assets(prefix,recursive=True):
        raise ValueError("새 기준 장면 경로가 필요하다.")
    unreal.EditorLoadingAndSavingUtils.load_map(request["map"])
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in actors.get_all_level_actors():
        if isinstance(actor,unreal.SkeletalMeshActor):
            actor.skeletal_mesh_component.set_cast_shadow(False)
            actor.skeletal_mesh_component.set_editor_property("cast_hidden_shadow",False)
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.EditorLoadingAndSavingUtils.save_map(world,prefix+"/MAP_Clear")
    unreal.EditorLoadingAndSavingUtils.load_map(prefix+"/MAP_Clear")
    current=actors.get_all_level_actors()
    master=next(a for a in current if a.get_actor_label()=="PoseMaster")
    camera=next(a for a in current if isinstance(a,unreal.CameraActor))
    write_sequence(prefix,"LS_Clear",master,camera,unreal.load_asset(request["animation"]),request["frame_count"])
    (ROOT/request["report"]).write_text(json.dumps({"map":prefix+"/MAP_Clear","sequence":prefix+"/LS_Clear"},indent=2),encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import unreal
    request = json.loads(Path(os.environ["FD_UNITS_REQUEST"]).read_text(encoding="utf-8"))
    try:
        if request.get("shadow_reference_only"):
            shadow_reference(request)
        elif request.get("scenes"):
            if not 1 <= len(request["scenes"]) <= 32:
                raise ValueError("출력 장면은 1~32개가 필요하다.")
            for scene in request["scenes"]:
                (shadow_reference if scene.get("shadow_reference_only") else prepare)(scene)
            target = ROOT / request["report"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"scenes": [scene["report"] for scene in request["scenes"]]}, indent=2), encoding="utf-8")
        else:
            prepare(request)
    except Exception:
        import traceback
        error = ROOT / request["report"]
        error.parent.mkdir(parents=True, exist_ok=True)
        error.with_suffix(".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    unreal.SystemLibrary.quit_editor()
