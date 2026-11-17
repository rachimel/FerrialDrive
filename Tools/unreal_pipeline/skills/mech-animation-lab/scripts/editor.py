"""실험 프로젝트의 편집 가능한 FK 키와 출력본을 관리한다."""
import hashlib
import json
from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_success


def load_request(request_path):
    import unreal
    project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())).resolve()
    workspace = project.parent
    request_file = Path(request_path).resolve()
    automation_workspace = workspace.parents[3] / "automate/workspace"
    if not (project / "MechAnimationLab.uproject").is_file() or not (
            request_file.is_relative_to(workspace) or request_file.is_relative_to(automation_workspace)):
        raise ValueError("실험 프로젝트와 workspace의 요청만 허용한다.")
    request = json.loads(request_file.read_text(encoding="utf-8-sig"))
    for key in ("mesh", "sequence", "animation", "map", "new_mesh"):
        if key in request and not request[key].startswith("/Game/MechLab/"):
            raise ValueError("실험 에셋 경로만 허용한다.")
    return workspace, request


def inspect(request):
    import unreal
    if request.get("inspect_rigging_api"):
        names = [name for name in dir(unreal) if any(
            token in name for token in ("SkeletonModifier", "GeometryScript", "ControlRigBlueprint", "RigHierarchyController", "SkeletalMeshFactory", "SkeletalMeshEditing"))]
        selected = request.get("symbols", [])
        api = {}
        for name in selected:
            if name not in dir(unreal) or name.startswith("_"):
                api[name] = {"available": False}
                continue
            value = getattr(unreal, name)
            api[name] = {"available": True, "doc": getattr(value, "__doc__", ""),
                         "members": {member: getattr(getattr(value, member), "__doc__", "")
                                     for member in dir(value) if not member.startswith("_")
                                     and any(token in member.lower() for token in ("bone", "mesh", "skeleton", "weight", "control", "blueprint", "node", "asset", "manager", "source", "convert"))}}
        dirty = {}
        for reader in ("get_dirty_map_packages", "get_dirty_content_packages"):
            function = getattr(unreal.EditorLoadingAndSavingUtils, reader, None)
            dirty[reader] = [item.get_path_name() for item in function()] if function else None
        return {"engine": unreal.SystemLibrary.get_engine_version(),
                "project": unreal.Paths.project_dir(), "symbols": names, "api": api, "dirty": dirty}
    library = unreal.ControlRigSequencerLibrary
    names = ["find_or_create_control_rig_track", "get_control_rigs",
             "get_local_control_rig_euler_transform", "set_local_control_rig_euler_transform"]
    docs = {name: getattr(library, name).__doc__ for name in names}
    docs["export_anim_sequence"] = unreal.SequencerTools.export_anim_sequence.__doc__
    state = {}
    sequence = unreal.load_asset(request["sequence"])
    if sequence:
        state["rigs"] = [{"controls": [str(k.name) for k in p.control_rig.get_hierarchy().get_controls()]} for p in library.get_control_rigs(sequence)]
        proxies = library.get_control_rigs(sequence)
        if proxies:
            state["chest_yaw_samples"] = {str(frame): library.get_local_control_rig_euler_transform(sequence, proxies[0].control_rig, "chest_CONTROL", unreal.FrameNumber(frame)).rotation.yaw for frame in (0, 15, 30)}
            rig = proxies[0].control_rig
            hierarchy = rig.get_hierarchy()
            state["selected_controls"] = [str(n) for n in rig.current_control_selection()]
            state["waist_rotation_samples"] = {}
            for frame in (0, 15, 30):
                value = library.get_local_control_rig_euler_transform(sequence, rig, "waist_CONTROL", unreal.FrameNumber(frame))
                state["waist_rotation_samples"][str(frame)] = [value.rotation.pitch, value.rotation.yaw, value.rotation.roll]
            state["torso_hierarchy"] = [{"name": str(key.name),
                "parent": str(hierarchy.get_first_parent(key).name),
                "local": str(hierarchy.get_local_transform(key)),
                "global": str(hierarchy.get_global_transform(key))}
                for key in [*hierarchy.get_bones(), *hierarchy.get_controls()]
                if str(key.name).lower() in {"pelvis", "waist", "chest", "pelvis_control", "waist_control", "chest_control"}]
    state["actors"] = [{"label": a.get_actor_label(), "bones": [str(a.skeletal_mesh_component.get_bone_name(i)) for i in range(a.skeletal_mesh_component.get_num_bones())]} for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if isinstance(a, unreal.SkeletalMeshActor)]
    return {"engine": unreal.SystemLibrary.get_engine_version(), "api": docs, "state": state,
            "mesh_exists": unreal.EditorAssetLibrary.does_asset_exist(request["mesh"]),
            "assets": unreal.EditorAssetLibrary.list_assets("/Game/MechLab", recursive=False)}


def create_clip(request):
    import unreal
    if unreal.EditorAssetLibrary.does_asset_exist(request["sequence"]):
        raise FileExistsError(request["sequence"])
    mesh = unreal.load_asset(request["mesh"])
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise ValueError("Skeletal Mesh를 찾지 못했다.")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0))
    actor.set_actor_label("PlayerMech_AnimationLab")
    component = actor.skeletal_mesh_component
    component.set_skeletal_mesh_asset(mesh)
    package, name = request["sequence"].rsplit("/", 1)
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, package, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(30, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(31)
    binding = sequence.add_possessable(actor)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    library = unreal.ControlRigSequencerLibrary
    library.find_or_create_control_rig_track(world, sequence, unreal.FKControlRig.static_class(), binding)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    proxies = library.get_control_rigs(sequence)
    if len(proxies) != 1:
        raise RuntimeError("FK Control Rig가 하나가 아니다.")
    rig = proxies[0].control_rig
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    if not unreal.EditorAssetLibrary.does_asset_exist(request["map"]):
        unreal.EditorLoadingAndSavingUtils.save_map(world, request["map"])
    return {"sequence": sequence.get_path_name(), "status": "awaiting_rig_initialization"}


def key_clip(request):
    import unreal
    sequence = unreal.load_asset(request["sequence"])
    if unreal.EditorAssetLibrary.get_metadata_tag(sequence, "fd_lab_keys"):
        raise RuntimeError("이미 키를 작성한 초안이다. 사용자 수정을 덮어쓰지 않는다.")
    library = unreal.ControlRigSequencerLibrary
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
    proxies = library.get_control_rigs(sequence)
    if not proxies:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        library.find_or_create_control_rig_track(world, sequence, unreal.FKControlRig.static_class(), sequence.get_bindings()[0])
        unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        return {"status": "awaiting_rig_initialization"}
    rig = proxies[0].control_rig
    controls = [str(key.name) for key in rig.get_hierarchy().get_controls()]
    target = next((name for name in controls if name.lower() == "chest_control"), None)
    if target is None:
        raise RuntimeError("Chest FK 제어점이 없다: " + repr(controls))
    base = library.get_local_control_rig_euler_transform(sequence, rig, target, unreal.FrameNumber(0))
    for frame, yaw in [(0, 0), (15, 8), (30, 0)]:
        value = unreal.EulerTransform(location=base.location,
            rotation=unreal.Rotator(pitch=base.rotation.pitch, yaw=base.rotation.yaw + yaw,
                                    roll=base.rotation.roll), scale=base.scale)
        library.set_local_control_rig_euler_transform(sequence, rig, target,
            unreal.FrameNumber(frame), value, set_key=True)
    unreal.EditorAssetLibrary.set_metadata_tag(sequence, "fd_lab_keys", "initial")
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    prepare_view(request)
    return {"sequence": sequence.get_path_name(),
            "controls": controls, "edited_control": target, "frames": [0, 15, 30],
            "user_edit_status": "awaiting_user", "visual_review": "not_run"}


def prepare_view(request):
    import unreal
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = next(a for a in actors.get_all_level_actors() if a.get_actor_label() == request.get("actor_label", "PlayerMech_AnimationLab"))
    actors.set_selected_level_actors([actor])
    center, extent = actor.get_actor_bounds(False)
    radius = max(extent.x, extent.y, extent.z)
    camera = center + unreal.Vector(radius * 2.8, radius * 2.8, radius * 1.3)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(camera, unreal.MathLibrary.find_look_at_rotation(camera, center))


def export_clip(workspace, request):
    import unreal
    filename = Path(request["output_fbx"]).resolve()
    if not filename.is_relative_to(workspace) or filename.exists():
        raise ValueError("workspace 내부의 새 출력 경로만 허용한다.")
    if unreal.EditorAssetLibrary.does_asset_exist(request["animation"]):
        raise FileExistsError(request["animation"])
    sequence = unreal.load_asset(request["sequence"])
    actors = [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
              if a.get_actor_label() == request.get("actor_label", "PlayerMech_AnimationLab")]
    if len(actors) != 1:
        raise RuntimeError("실험 메카 Actor가 하나가 아니다.")
    component = actors[0].skeletal_mesh_component
    if component.skeletal_mesh_asset.skeleton is None:
        raise RuntimeError("교환 메시의 Skeleton 파일 참조가 없다. 새 베이크 에셋을 만들지 않는다.")
    factory = unreal.AnimSequenceFactory()
    factory.target_skeleton = component.skeletal_mesh_asset.skeleton
    package, name = request["animation"].rsplit("/", 1)
    animation = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, package, unreal.AnimSequence, factory)
    if "fps" in request:
        # 빈 AnimSequence의 기본 30fps와 12fps의 공배수를 거쳐 초기화한다.
        controller = animation.get_editor_property("controller")
        controller.set_frame_rate(unreal.FrameRate(60, 1), False)
        controller.set_frame_rate(unreal.FrameRate(request["fps"], 1), False)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    bindings = sequence.get_bindings()
    if len(bindings) != 1:
        raise RuntimeError("실험 Sequence 바인딩이 하나가 아니다.")
    options = unreal.AnimSeqExportOption()
    options.export_transforms = True
    options.export_morph_targets = False
    options.export_attribute_curves = False
    options.export_material_curves = False
    if "fps" in request:
        options.use_custom_frame_rate = True
        options.custom_frame_rate = unreal.FrameRate(request["fps"], 1)
        options.use_custom_time_range = True
        options.custom_start_frame = unreal.FrameNumber(0)
        options.custom_end_frame = unreal.FrameNumber(request["frame_end"])
    if not unreal.SequencerTools.export_anim_sequence(world, sequence, animation, options, bindings[0], False):
        raise RuntimeError("본 애니메이션 베이크 실패")
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    unreal.EditorAssetLibrary.save_loaded_asset(animation)
    filename.parent.mkdir(parents=True, exist_ok=True)
    task = unreal.AssetExportTask()
    task.object, task.filename = animation, str(filename)
    task.automated, task.prompt, task.selected = True, False, False
    task.exporter = unreal.AnimSequenceExporterFBX()
    task.options = unreal.FbxExportOption()
    task.options.export_preview_mesh = False
    if not unreal.Exporter.run_asset_export_task(task) or not filename.is_file():
        raise RuntimeError("FBX 출력 실패")
    return {"animation": animation.get_path_name(), "fbx": str(filename),
            "bytes": filename.stat().st_size, "sha256": hashlib.sha256(filename.read_bytes()).hexdigest()}


def import_mesh_candidate(workspace, request):
    import unreal
    filename = Path(request["source_fbx"]).resolve()
    if not filename.is_relative_to(workspace) or not filename.is_file():
        raise ValueError("workspace 내부의 FBX만 허용한다.")
    if unreal.EditorAssetLibrary.does_asset_exist(request["new_mesh"]):
        raise FileExistsError(request["new_mesh"])
    original = unreal.load_asset(request["mesh"])
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_as_skeletal = True
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    if request.get("reuse_skeleton", True):
        options.skeleton = original.skeleton
    options.import_animations = False
    options.import_materials = False
    options.import_textures = False
    options.create_physics_asset = False
    package, name = request["new_mesh"].rsplit("/", 1)
    task = unreal.AssetImportTask()
    task.filename, task.destination_path, task.destination_name = str(filename), package, name
    task.automated, task.save, task.replace_existing = True, True, False
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    candidate = unreal.load_asset(request["new_mesh"])
    if not isinstance(candidate, unreal.SkeletalMesh) or (request.get("reuse_skeleton", True) and candidate.skeleton != original.skeleton):
        raise RuntimeError("후보 메시가 기존 Skeleton을 재사용하지 못했다.")
    original_materials = {str(slot.material_slot_name): slot.material_interface for slot in original.materials}
    slots = candidate.get_editor_property("materials")
    for slot in slots:
        if str(slot.material_slot_name) not in original_materials:
            raise RuntimeError("후보의 재질 슬롯이 원본과 다르다.")
        slot.material_interface = original_materials[str(slot.material_slot_name)]
    candidate.set_editor_property("materials", slots)
    unreal.EditorAssetLibrary.save_loaded_asset(candidate.skeleton)
    unreal.EditorAssetLibrary.save_loaded_asset(candidate)
    return {"candidate": candidate.get_path_name(), "skeleton_reused": candidate.skeleton == original.skeleton, "materials": len(slots)}


def batch_data(workspace, request):
    filename = Path(request["batch_file"]).resolve()
    if not filename.is_relative_to(workspace):
        raise ValueError("workspace 내부 동작 데이터만 허용한다.")
    data = json.loads(filename.read_text(encoding="utf-8-sig"))
    clip = next(c for c in data["clips"] if c["name"] == request["clip"])
    if not 1 <= len(clip["frames"]) <= 12 or data["fps"] != 12:
        raise ValueError("12fps, 최대 12프레임 요청이 필요하다.")
    return data, clip


def batch_actor(request, create=False):
    import unreal
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    label = request["actor_label"]
    actors = [a for a in subsystem.get_all_level_actors() if a.get_actor_label() == label]
    if not actors and create:
        actor = subsystem.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(1000, 0, 0))
        actor.set_actor_label(label)
        actor.skeletal_mesh_component.set_skeletal_mesh_asset(unreal.load_asset(request["mesh"]))
        actors = [actor]
    if len(actors) != 1 or actors[0].skeletal_mesh_component.skeletal_mesh_asset != unreal.load_asset(request["mesh"]):
        raise RuntimeError("새 작업 Actor·메시가 일치하지 않는다.")
    return actors[0]


def create_batch_clip(workspace, request):
    import unreal
    data, clip = batch_data(workspace, request)
    if unreal.EditorAssetLibrary.does_asset_exist(request["sequence"]):
        raise FileExistsError(request["sequence"])
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world.get_path_name().split(".",1)[0] != request["map"]:
        raise RuntimeError("작업 맵을 먼저 연 뒤 클립을 만든다. 클립 작성 중 다른 이름으로 레벨을 저장하지 않는다.")
    existed = any(a.get_actor_label() == request["actor_label"] for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors())
    actor = batch_actor(request, create=True)
    if not existed and not unreal.EditorLevelLibrary.save_current_level():
        raise RuntimeError("새 Actor가 있는 현재 작업 맵 저장 실패")
    package, name = request["sequence"].rsplit("/", 1)
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, package, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(data["fps"], 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(len(clip["frames"]))
    binding = sequence.add_possessable(actor)
    unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(world, sequence, unreal.FKControlRig.static_class(), binding)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    return {"sequence": sequence.get_path_name(), "frames": len(clip["frames"]), "fps": data["fps"], "status": "awaiting_rig_initialization"}


def inspect_batch(request):
    import unreal
    sequence = unreal.load_asset(request["sequence"])
    if not sequence:
        return {"status":"sequence_missing", "sequence_exists":False}
    library = unreal.ControlRigSequencerLibrary
    proxies = library.get_control_rigs(sequence)
    if len(proxies) != 1:
        return {"status": "awaiting_rig_initialization"}
    hierarchy = proxies[0].control_rig.get_hierarchy()
    def pack(value):
        return {"translation": [value.translation.x, value.translation.y, value.translation.z],
                "rotation": [value.rotation.x, value.rotation.y, value.rotation.z, value.rotation.w],
                "scale": [value.scale3d.x, value.scale3d.y, value.scale3d.z]}
    keys = sum(len(channel.get_keys()) for binding in sequence.get_bindings() for track in binding.get_tracks()
               for section in track.get_sections() for channel in section.get_all_channels())
    return {"status": "ready" if hierarchy.get_controls() else "awaiting_rig_initialization", "sequence_exists":True,"key_count":keys,
            "key_metadata":unreal.EditorAssetLibrary.get_metadata_tag(sequence,"fd_lab_keys"),
            "engine": unreal.SystemLibrary.get_engine_version(),
            "bones": {str(k.name): pack(hierarchy.get_global_transform(k, initial=True)) for k in hierarchy.get_bones()},
            "controls": [str(k.name) for k in hierarchy.get_controls()],
            "actors": [{"label":a.get_actor_label(),"path":a.get_path_name(),
                        "mesh":a.skeletal_mesh_component.skeletal_mesh_asset.get_path_name(),
                        "bones":a.skeletal_mesh_component.get_num_bones(),
                        "animation_mode":str(a.skeletal_mesh_component.get_editor_property("animation_mode"))}
                       for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
                       if isinstance(a,unreal.SkeletalMeshActor)],
            "rig_methods": [n for n in dir(proxies[0].control_rig) if any(s in n.lower() for s in ("init","execute","evaluate","binding","mesh"))],
            "world_set_api": library.set_control_rig_world_transform.__doc__,
            "world_get_api": library.get_control_rig_world_transform.__doc__,
            "export_options": [n for n in dir(unreal.AnimSeqExportOption()) if "frame" in n or "range" in n]}


def key_batch_clip(workspace, request):
    import math
    import unreal
    data, clip = batch_data(workspace, request)
    sequence = unreal.load_asset(request["sequence"])
    if unreal.EditorAssetLibrary.get_metadata_tag(sequence, "fd_lab_keys"):
        raise RuntimeError("이미 작성한 초안을 덮어쓰지 않는다.")
    actor = batch_actor(request)
    offset = actor.get_actor_location()
    library = unreal.ControlRigSequencerLibrary
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    rig = library.get_control_rigs(sequence)[0].control_rig
    controls = {str(k.name).lower(): str(k.name) for k in rig.get_hierarchy().get_controls()}
    if not controls:
        raise RuntimeError("FK 제어점이 초기화되지 않았다. 바인딩과 다음 틱을 먼저 확인한다.")
    errors = []
    for frame, poses in enumerate(clip["frames"]):
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(frame)
        for bone, pose in poses.items():
            control = controls[bone.lower() + "_control"]
            position, rotation, scale = pose["translation"], pose["rotation"], pose["scale"]
            transform = unreal.Transform()
            transform.translation = unreal.Vector(position[0]+offset.x, position[1]+offset.y, position[2]+offset.z)
            transform.rotation = unreal.Quat(*rotation)
            transform.scale3d = unreal.Vector(*scale)
            library.set_control_rig_world_transform(sequence, rig, control, unreal.FrameNumber(frame), transform, set_key=True)
        for bone, pose in poses.items():
            actual = library.get_control_rig_world_transform(sequence, rig, controls[bone.lower()+"_control"], unreal.FrameNumber(frame))
            expected = pose["translation"]
            errors.append(math.sqrt((actual.translation.x-offset.x-expected[0])**2 +
                                    (actual.translation.y-offset.y-expected[1])**2 +
                                    (actual.translation.z-offset.z-expected[2])**2))
    for binding in sequence.get_bindings():
        for track in binding.get_tracks():
            for section in track.get_sections():
                for channel in section.get_all_channels():
                    for key in channel.get_keys():
                        if hasattr(key, "set_interpolation_mode"):
                            key.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_LINEAR)
    unreal.EditorAssetLibrary.set_metadata_tag(sequence, "fd_lab_keys", "batch_initial")
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    return {"sequence": sequence.get_path_name(), "frames": len(clip["frames"]),
            "keyed_poses": len(errors), "max_control_position_error_cm": max(errors), "user_edit_status": "awaiting_user"}


def export_batch_clip(workspace, request):
    data, clip = batch_data(workspace, request)
    batch_actor(request)
    return export_clip(workspace, {**request, "fps": data["fps"], "frame_end": len(clip["frames"])-1})


def rebind_batch_clip(workspace, request):
    import unreal
    batch_data(workspace,request)
    sequence = unreal.load_asset(request["sequence"])
    if unreal.EditorAssetLibrary.get_metadata_tag(sequence,"fd_lab_keys") not in ("","batch_initial"):
        raise RuntimeError("기존 실험·사용자 편집 Sequence의 바인딩은 변경하지 않는다.")
    actor = batch_actor(request)
    def key_signature():
        keys = []
        for binding in sequence.get_bindings():
            for track in binding.get_tracks():
                for section in track.get_sections():
                    for channel in section.get_all_channels():
                        keys.append([(k.get_time().frame_number.value,k.get_time().sub_frame,k.get_value()) for k in channel.get_keys()])
        return hashlib.sha256(json.dumps(keys).encode()).hexdigest()
    before = key_signature()
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem).replace_binding_with_actors([actor],sequence.get_bindings()[0])
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    if key_signature() != before:
        raise RuntimeError("바인딩 수정 전후의 키가 달라졌다.")
    return {"sequence":sequence.get_path_name(),"actor":actor.get_actor_label(),"status":"awaiting_rig_initialization","keys_preserved":True,"keys_sha256":before}


def bind_mesh_candidate(request):
    import unreal
    candidate = unreal.load_asset(request["new_mesh"])
    original = unreal.load_asset(request["mesh"])
    repairing_missing = request.get("repair_missing_skeleton",False) and original.skeleton is None and candidate.skeleton is not None
    if not isinstance(candidate, unreal.SkeletalMesh) or (candidate.skeleton != original.skeleton and not repairing_missing):
        raise RuntimeError("후보 메시와 기존 Skeleton이 일치하지 않는다.")
    sequence = unreal.load_asset(request["sequence"])
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    sequence_file = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())) / (request["sequence"][6:] + ".uasset")
    sequence_hash = hashlib.sha256(sequence_file.read_bytes()).hexdigest()
    actors = [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
              if a.get_actor_label() == request.get("actor_label","PlayerMech_AnimationLab")]
    if len(actors) != 1:
        raise RuntimeError("실험 메카 Actor가 하나가 아니다.")
    component = actors[0].skeletal_mesh_component
    if component.skeletal_mesh_asset not in (original, candidate):
        raise RuntimeError("Actor가 예상하지 못한 메시를 사용한다.")
    before = component.skeletal_mesh_asset.get_path_name()
    component.set_skeletal_mesh_asset(candidate)
    unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
    unreal.EditorLoadingAndSavingUtils.save_map(
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world(), request["map"])
    return {"before": before, "after": component.skeletal_mesh_asset.get_path_name(),
            "bones": component.get_num_bones(), "sequence": sequence.get_path_name(),
            "sequence_file_unchanged": hashlib.sha256(sequence_file.read_bytes()).hexdigest() == sequence_hash}


@skill_entry
def main(operation, request_path, **kwargs):
    import unreal
    workspace, request = load_request(request_path)
    if operation == "inspect":
        result = inspect(request)
    elif operation == "rig_workspace":
        import sys
        module_path = str(workspace.parents[3] / "automate/unreal")
        if module_path not in sys.path:
            sys.path.insert(0, module_path)
        import rig_workspace
        import importlib
        importlib.reload(rig_workspace)
        result = rig_workspace.run(request)
    elif operation == "create_clip":
        result = create_clip(request)
    elif operation == "key_clip":
        result = key_clip(request)
    elif operation == "export_clip":
        result = export_clip(workspace, request)
    elif operation == "import_mesh_candidate":
        result = import_mesh_candidate(workspace, request)
    elif operation == "bind_mesh_candidate":
        result = bind_mesh_candidate(request)
    elif operation == "inspect_batch":
        result = inspect_batch(request)
    elif operation == "create_batch_clip":
        result = create_batch_clip(workspace, request)
    elif operation == "key_batch_clip":
        result = key_batch_clip(workspace, request)
    elif operation == "export_batch_clip":
        result = export_batch_clip(workspace, request)
    elif operation == "rebind_batch_clip":
        result = rebind_batch_clip(workspace,request)
    elif operation == "open_clip":
        sequence = unreal.load_asset(request["sequence"])
        result = {"opened": unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)}
        prepare_view(request)
        frame = request.get("frame",15)
        unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(frame)
        proxies = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)
        if proxies:
            rig = proxies[0].control_rig
            rig.clear_control_selection()
            rig.select_control(request.get("selected_control","chest_CONTROL"), True)
            result.update(frame=frame, selected_controls=[str(n) for n in rig.current_control_selection()])
    else:
        raise ValueError("지원하지 않는 작업이다.")
    return skill_success("메카 애니메이션 실험 작업 완료", result=result)
