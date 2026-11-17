"""새 Unreal 리그 작업본의 형상 인계·골격·제어점·포즈를 관리한다."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "automate/workspace"


def validate(request):
    prefix = request["asset_root"]
    if not prefix.startswith("/Game/MechLab/FreshRig") or ".." in prefix:
        raise ValueError("새 리그 소유 에셋 경로만 사용한다.")
    references = [request[key] for key in ("seed_mesh", "mesh") if key in request]
    if any(not path.startswith("/Game/MechLab/FreshRig") or ".." in path for path in references):
        raise ValueError("이 작업에서 새로 생성한 에셋만 읽거나 편집한다.")
    # 부품은 읽기만 한다. 결과는 위의 새 리그 경로에 조립한다.
    if any(not part["asset"].startswith("/Game/MechLab/") or ".." in part["asset"] for part in request.get("parts", [])):
        raise ValueError("메카 작업본의 부품만 참조한다.")
    if "fbx" in request:
        source = Path(request["fbx"]).resolve()
        if not source.is_relative_to(WORKSPACE) or source.suffix.lower() != ".fbx":
            raise ValueError("자동화 작업본의 형상 FBX만 읽는다.")
        if hashlib.sha256(source.read_bytes()).hexdigest() != request["fbx_sha256"]:
            raise ValueError("형상 FBX 해시 불일치")


def import_geometry(request):
    import unreal

    destination = request["asset_root"]
    if unreal.EditorAssetLibrary.does_directory_exist(destination):
        assets = unreal.EditorAssetLibrary.list_assets(destination, recursive=True)
        if assets:
            raise FileExistsError("기존 에셋이 있다. 먼저 상태를 확인한다: " + destination)
    if not request.get("skeletal"):
        raise ValueError("Static Mesh 입력은 기존 import_asset 도구를 사용한다.")
    pipeline = unreal.InterchangeGenericAssetsPipeline()
    common = pipeline.common_meshes_properties
    common.set_editor_property("force_all_mesh_as_type", unreal.InterchangeForceMeshType.IFMT_SKELETAL_MESH)
    common.set_editor_property("single_bone_skeleton", True)
    common.set_editor_property("bake_meshes", True)
    pipeline.mesh_pipeline.set_editor_property("import_skeletal_meshes", True)
    pipeline.mesh_pipeline.set_editor_property("import_static_meshes", False)
    pipeline.material_pipeline.set_editor_property("import_materials", False)
    parameters = unreal.ImportAssetParameters()
    parameters.set_editor_property("is_automated", True)
    parameters.set_editor_property("replace_existing", False)
    parameters.set_editor_property("override_pipelines", [unreal.SoftObjectPath(pipeline.get_path_name())])
    manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    source_data = unreal.InterchangeManager.create_source_data(request["fbx"])
    flag = "Interchange.FeatureFlags.Import.FBX"
    previous = unreal.SystemLibrary.get_console_variable_int_value(flag)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    try:
        unreal.SystemLibrary.execute_console_command(world, flag + " 1")
        objects = manager.import_asset(destination, source_data, parameters)
    finally:
        unreal.SystemLibrary.execute_console_command(world, flag + " " + str(previous))
    imported = []
    for asset in objects or []:
        path = asset.get_path_name()
        row = {"path": path, "class": asset.get_class().get_name()}
        if isinstance(asset, unreal.StaticMesh) and request.get("include_bounds"):
            bounds = asset.get_bounds()
            row["center_cm"] = [bounds.origin.x, bounds.origin.y, bounds.origin.z]
            row["extent_cm"] = [bounds.box_extent.x, bounds.box_extent.y, bounds.box_extent.z]
        if isinstance(asset, unreal.SkeletalMesh):
            modifier = unreal.SkeletonModifier()
            if not modifier.set_skeletal_mesh(asset):
                raise RuntimeError("가져온 새 Skeletal Mesh를 읽지 못했다.")
            row["bones"] = [str(name) for name in modifier.get_all_bone_names()]
            row["skeleton"] = asset.skeleton.get_path_name()
        imported.append(row)
        unreal.EditorAssetLibrary.save_loaded_asset(asset)
    if not any(row["class"] == "SkeletalMesh" for row in imported):
        raise RuntimeError("새 기본 골격이 있는 Skeletal Mesh를 생성하지 못했다.")
    return {"assets": imported, "count": len(imported), "source_has_rig": False,
            "note": "형상만 Unreal에서 변환한 초기 인계물이며 사용자 품질 승인 전이다."}


def inspect_assets(request):
    import unreal
    rows = []
    for path in unreal.EditorAssetLibrary.list_assets(request["asset_root"], recursive=True):
        asset = unreal.load_asset(path)
        row = {"path": path, "class": asset.get_class().get_name()}
        if isinstance(asset, unreal.StaticMesh) and request.get("include_bounds"):
            bounds = asset.get_bounds()
            row["center_cm"] = [bounds.origin.x, bounds.origin.y, bounds.origin.z]
            row["extent_cm"] = [bounds.box_extent.x, bounds.box_extent.y, bounds.box_extent.z]
        if isinstance(asset, unreal.SkeletalMesh):
            modifier = unreal.SkeletonModifier()
            modifier.set_skeletal_mesh(asset)
            row["bones"] = [str(name) for name in modifier.get_all_bone_names()]
            row["skeleton"] = asset.skeleton.get_path_name() if asset.skeleton else None
        rows.append(row)
    return {"assets": rows}


def build_rigid_rig(request):
    import unreal

    destination = request["asset_root"]
    existing = unreal.EditorAssetLibrary.list_assets(destination, recursive=True)
    expected_seed = {destination + "/SKEL_Fresh.SKEL_Fresh", destination + "/SK_Seed.SK_Seed"}
    if existing and not (request.get("resume_seed_only") and set(existing) == expected_seed):
        raise FileExistsError("기존 리그 작업본을 덮어쓰지 않는다: " + destination)
    seed = unreal.load_asset(request["seed_mesh"])
    if not isinstance(seed, unreal.SkeletalMesh):
        raise TypeError("Unreal에서 생성한 기본 Skeletal Mesh가 필요하다.")
    # seed는 이 작업이 Unreal에서 새로 생성한 단일 본 에셋이다.
    # Modifier의 commit은 seed 사본과 전용 seed Skeleton을 갱신한다.
    # 완성 골격을 다시 복제해 최종 메시 전용 Skeleton으로 사용한다.
    seed_copy = unreal.load_asset(destination + "/SK_Seed") if existing else unreal.EditorAssetLibrary.duplicate_asset(seed.get_path_name(), destination + "/SK_Seed")
    modifier = unreal.SkeletonModifier()
    if not modifier.set_skeletal_mesh(seed_copy):
        raise RuntimeError("기본 골격을 편집할 수 없다.")
    initial = [str(name) for name in modifier.get_all_bone_names()]
    bones = request["bones"]
    planned_names = ["Root"] + [bone["name"] for bone in bones]
    if initial != ["Root"] and not (request.get("resume_seed_only") and initial == planned_names):
        raise ValueError("새 단일 Root 또는 확인한 샘플 재개만 허용한다: " + str(initial))
    positions = {"Root": [0, 0, 0]}
    for bone in bones:
        parent = bone["parent"]
        position = bone["position_cm"]
        offset = [a - b for a, b in zip(position, positions[parent])]
        if initial == ["Root"] and not modifier.add_bone(bone["name"], parent, unreal.Transform(location=unreal.Vector(*offset))):
            raise RuntimeError("새 본 추가 실패: " + bone["name"])
        positions[bone["name"]] = position
    if initial == ["Root"] and not modifier.commit_skeleton_to_skeletal_mesh():
        raise RuntimeError("새 골격 저장 실패")
    for bone in bones:
        actual = modifier.get_bone_transform(bone["name"], global_=True).translation
        if max(abs(a - b) for a, b in zip([actual.x, actual.y, actual.z], bone["position_cm"])) > .001:
            raise ValueError("새 본 위치 불일치: " + bone["name"])
    skeleton = unreal.EditorAssetLibrary.duplicate_asset(seed_copy.skeleton.get_path_name(), destination + "/SKEL_Final")
    names = [str(name) for name in modifier.get_all_bone_names()]
    result, bindings = assemble_rigid_mesh(request["parts"], skeleton, names, destination + "/SK_FreshRig")
    for asset in [seed_copy.skeleton, skeleton, seed_copy, result]:
        unreal.EditorAssetLibrary.save_loaded_asset(asset)
    verify = unreal.SkeletonModifier()
    verify.set_skeletal_mesh(result)
    return {"mesh": result.get_path_name(), "skeleton": skeleton.get_path_name(),
            "bones": [str(name) for name in verify.get_all_bone_names()], "bindings": bindings,
            "source_rig_reused": False, "binding_policy": "rigid_per_part", "visual_review": "pending"}


def assemble_rigid_mesh(parts, skeleton, names, destination):
    """같은 골격·부품 웨이트로 전체/출력 단위 메시를 만든다."""
    import unreal
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        raise FileExistsError(destination)
    merged = unreal.DynamicMesh()
    weights = unreal.GeometryScript_BoneWeights
    weights.copy_bones_from_skeleton(skeleton, merged)
    weights.mesh_create_bone_weights(merged)
    materials = []
    bindings = []
    for part in parts:
        asset = unreal.load_asset(part["asset"])
        if not isinstance(asset, unreal.StaticMesh):
            raise TypeError("리그 없는 Static Mesh만 허용한다: " + part["asset"])
        mesh = unreal.DynamicMesh()
        mesh, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(
            asset, mesh, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
        if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
            raise RuntimeError("형상 읽기 실패: " + part["asset"])
        if part.get("deformation"):
            from part_deformation import apply_deformation
            apply_deformation(mesh, part["deformation"])
        weights.copy_bones_from_skeleton(skeleton, mesh)
        weights.mesh_create_bone_weights(mesh)
        index = names.index(part["bone"])
        weights.set_all_vertex_bone_weights(mesh, [unreal.GeometryScriptBoneWeight(bone_index=index, weight=1.0)])
        if part.get("axis_binding"):
            _, positions, gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
            if gaps:
                raise ValueError("구간 웨이트에는 연속된 정점 ID가 필요하다.")
            for vertex_id, point in enumerate(positions.convert_vector_list_to_array()):
                values = axis_bone_weights((point.x, point.y, point.z), part["axis_binding"])
                _, valid = weights.set_vertex_bone_weights(mesh, vertex_id,
                    [unreal.GeometryScriptBoneWeight(bone_index=names.index(bone), weight=value) for bone, value in values.items()])
                if not valid:
                    raise ValueError("정점 웨이트 작성 실패")
        part_materials, _, _, material_outcome = unreal.GeometryScript_AssetUtils.get_section_material_list_from_static_mesh(asset, unreal.GeometryScriptMeshReadLOD())
        if material_outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
            raise RuntimeError("재질 대응 읽기 실패")
        if part.get("material_override"):
            material = unreal.load_asset(part["material_override"])
            if not isinstance(material, unreal.MaterialInterface):
                raise ValueError("재질 덮어쓰기 에셋이 없다.")
            part_materials = [material for _ in part_materials]
        merged, materials = merged.append_mesh_with_materials(materials, mesh, part_materials, unreal.Transform())
        binding = {"asset": part["asset"], "bone": part["bone"], "bone_index": index}
        if part.get("deformation"):
            binding["deformation"] = part["deformation"]
        if part.get("axis_binding"):
            binding["axis_binding"] = part["axis_binding"]
        bindings.append(binding)
    options = unreal.GeometryScriptCreateNewSkeletalMeshAssetOptions()
    options.set_editor_property("materials", {"Material_" + str(i): material for i, material in enumerate(materials)})
    result, outcome = unreal.GeometryScript_NewAssetUtils.create_new_skeletal_mesh_asset_from_mesh(
        merged, skeleton, destination, options)
    if not result or outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
        raise RuntimeError("새 리그 메시 생성 실패")
    unreal.EditorAssetLibrary.save_loaded_asset(result)
    return result, bindings


def axis_bone_weights(point, settings):
    """명시한 축의 구간별 웨이트를 보간한다. 구간 밖에서는 끝값을 유지한다."""
    axis, knots = settings["axis"], settings["knots"]
    if axis not in (0, 1, 2) or len(knots) < 2:
        raise ValueError("웨이트 축과 두 개 이상의 구간점이 필요하다.")
    for value, weights in knots:
        if not math.isfinite(value) or not weights or any(not math.isfinite(w) or w < 0 for w in weights.values()) or abs(sum(weights.values()) - 1) > 1e-6:
            raise ValueError("각 구간점의 웨이트 합은 1이어야 한다.")
    if any(a[0] >= b[0] for a, b in zip(knots, knots[1:])):
        raise ValueError("웨이트 구간점은 엄격히 증가해야 한다.")
    value = point[axis]
    if not math.isfinite(value):
        raise ValueError("유한한 정점 좌표가 필요하다.")
    if value <= knots[0][0]:
        return dict(knots[0][1])
    if value >= knots[-1][0]:
        return dict(knots[-1][1])
    for a, b in zip(knots, knots[1:]):
        if a[0] <= value <= b[0]:
            t = (value-a[0])/(b[0]-a[0])
            return {bone: weight for bone in a[1].keys() | b[1].keys()
                    if (weight := a[1].get(bone, 0)*(1-t)+b[1].get(bone, 0)*t) > 1e-9}
    raise ValueError("웨이트 구간을 찾지 못했다.")


def import_static_geometry(request):
    """리그 없는 FBX와 명시한 단색 재질을 새 후보 경로에 가져온다."""
    import unreal
    from surface_assets import import_file, save_skeletal_material
    if unreal.EditorAssetLibrary.list_assets(request["asset_root"], recursive=True):
        raise FileExistsError(request["asset_root"])
    options = unreal.FbxImportUI()
    options.set_editor_property("automated_import_should_detect_type", False)
    options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
    options.set_editor_property("import_as_skeletal", False)
    options.set_editor_property("import_materials", False)
    options.set_editor_property("import_textures", False)
    options.static_mesh_import_data.set_editor_property("combine_meshes", False)
    if request.get("geometry_root"):
        root = request["geometry_root"]
        if not root.startswith("/Game/MechLab/FreshRig") or ".." in root:
            raise ValueError("확인한 새 형상 경로만 재사용한다.")
        assets = [unreal.load_asset(path) for path in unreal.EditorAssetLibrary.list_assets(root, recursive=True)]
        if len(assets) != request["expected_geometry_count"] or any(not isinstance(asset, unreal.StaticMesh) for asset in assets):
            raise ValueError("재사용할 형상 개수·유형이 다르다.")
    else:
        assets = import_file(request["fbx"], request["asset_root"] + "/Geometry", options)
    materials = []
    lib = unreal.MaterialEditingLibrary
    for row in request.get("materials", []):
        material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(row["name"], request["asset_root"] + "/Materials", unreal.Material, unreal.MaterialFactoryNew())
        color = lib.create_material_expression(material, unreal.MaterialExpressionConstant3Vector)
        color.set_editor_property("constant", unreal.LinearColor(*row["color"], 1))
        lib.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
        for key, prop in (("roughness", unreal.MaterialProperty.MP_ROUGHNESS), ("metallic", unreal.MaterialProperty.MP_METALLIC)):
            node = lib.create_material_expression(material, unreal.MaterialExpressionConstant)
            node.set_editor_property("r", row[key])
            lib.connect_material_property(node, "", prop)
        save_skeletal_material(material)
        materials.append(material.get_path_name())
    return {"assets": [{"path": asset.get_path_name(), "class": asset.get_class().get_name()} for asset in assets], "materials": materials,
            "source_rig_reused": False, "material_source": "explicit_base_color_roughness_metallic"}


def create_control_scene(request):
    import unreal

    root = request["asset_root"]
    sequence_path = root + "/LS_KeyPoses"
    map_path = root + "/MAP_Edit"
    if unreal.EditorAssetLibrary.does_asset_exist(sequence_path) or unreal.EditorAssetLibrary.does_asset_exist(map_path):
        raise FileExistsError("이미 편집 장면이 있다. 새로 만들지 않고 조회한다.")
    dirty = unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    if dirty:
        raise RuntimeError("저장되지 않은 맵이 있어 새 편집 장면을 열지 않는다.")
    mesh = unreal.load_asset(request["mesh"])
    if not isinstance(mesh, unreal.SkeletalMesh):
        raise TypeError("새 Skeletal Mesh가 필요하다.")
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = actors.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector())
    actor.set_actor_label("FreshRig_Editable")
    actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
    light = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 500))
    light.set_actor_rotation(unreal.Rotator(pitch=-35, yaw=-35, roll=0), False)
    actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 600))
    actors.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector())
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "LS_KeyPoses", root, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(12, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(request.get("frame_end", 12))
    binding = sequence.add_possessable(actor)
    unreal.ControlRigSequencerLibrary.find_or_create_control_rig_track(
        world, sequence, unreal.FKControlRig.static_class(), binding)
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    actors.set_selected_level_actors([actor])
    center, extent = actor.get_actor_bounds(False)
    radius = max(extent.x, extent.y, extent.z, 10)
    camera = center + unreal.Vector(radius * 3.2, radius * 3.2, radius * 1.0)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
        camera, unreal.MathLibrary.find_look_at_rotation(camera, center))
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    unreal.EditorLoadingAndSavingUtils.save_map(world, map_path)
    return {"sequence": sequence_path, "map": map_path, "mesh": mesh.get_path_name(),
            "status": "controls_initializing", "fps": 12}


def inspect_controls(request):
    import unreal
    sequence = unreal.load_asset(request["asset_root"] + "/LS_KeyPoses")
    library = unreal.ControlRigSequencerLibrary
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    rigs = library.get_control_rigs(sequence)
    if len(rigs) != 1:
        raise RuntimeError("제어 리그가 하나가 아니다.")
    rig = rigs[0].control_rig
    controls = [str(key.name) for key in rig.get_hierarchy().get_controls()]
    setting_class = unreal.load_class(None, "/Script/ControlRigEditor.ControlRigEditModeSettings")
    settings = unreal.get_default_object(setting_class)
    names = ["bOnlySelectRigControls", "bHideControlShapes", "bShowControlsAsOverlay", "bDisplayHierarchy"]
    before = {name: settings.get_editor_property(name) for name in names}
    if request.get("show_controls"):
        settings.set_editor_property("bOnlySelectRigControls", False)
        settings.set_editor_property("bHideControlShapes", False)
        settings.set_editor_property("bShowControlsAsOverlay", True)
        settings.set_editor_property("bDisplayHierarchy", True)
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_set_game_view(False)
    if request.get("select_control"):
        target = request["select_control"]
        if target not in controls:
            raise ValueError("없는 제어점: " + target)
        rig.select_control(target, True)
    return {"controls": controls, "selected": [str(name) for name in rig.current_control_selection()],
            "settings_before": before,
            "settings_after": {name: settings.get_editor_property(name) for name in names}}


def key_poses(request):
    import unreal
    sequence = unreal.load_asset(request["asset_root"] + "/LS_KeyPoses")
    if unreal.EditorAssetLibrary.get_metadata_tag(sequence, "fd_fresh_pose_keys"):
        raise RuntimeError("이미 작성한 키를 덮어쓰지 않는다.")
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    library = unreal.ControlRigSequencerLibrary
    rig = library.get_control_rigs(sequence)[0].control_rig
    controls = [str(key.name) for key in rig.get_hierarchy().get_controls()]
    base = {name: library.get_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(0)) for name in controls}
    for pose in request["poses"]:
        unknown = set(pose.get("controls", {})) - set(controls)
        if unknown:
            raise ValueError("없는 제어점: " + str(unknown))
        for name in controls:
            original = base[name]
            data = pose.get("controls", {}).get(name, {})
            delta = data.get("rotation_delta_deg", [0, 0, 0])
            shift = data.get("translation_delta_cm", [0, 0, 0])
            transform = unreal.EulerTransform(
                location=original.location + unreal.Vector(*shift),
                rotation=unreal.Rotator(pitch=original.rotation.pitch + delta[0],
                                        yaw=original.rotation.yaw + delta[1], roll=original.rotation.roll + delta[2]),
                scale=original.scale)
            library.set_local_control_rig_euler_transform(sequence, rig, name, unreal.FrameNumber(pose["frame"]), transform, set_key=True)
    unreal.EditorAssetLibrary.set_metadata_tag(sequence, "fd_fresh_pose_keys", "draft_v1")
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(request.get("display_frame", 0))
    return {"sequence": sequence.get_path_name(), "frames": [pose["frame"] for pose in request["poses"]],
            "controls": controls, "quality_approval": False}


def set_review_view(request):
    import unreal
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    matching = [actor for actor in actors.get_all_level_actors()
                if isinstance(actor, unreal.SkeletalMeshActor)
                and actor.skeletal_mesh_component.skeletal_mesh_asset
                and actor.skeletal_mesh_component.skeletal_mesh_asset.get_path_name().startswith(request["asset_root"] + "/")]
    if len(matching) != 1:
        raise ValueError("현재 맵에 이 작업본 메카가 하나 있어야 한다.")
    actor = matching[0]
    sequence = unreal.load_asset(request["asset_root"] + "/LS_KeyPoses")
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
    unreal.LevelSequenceEditorBlueprintLibrary.set_current_time(request.get("frame", 0))
    rig = unreal.ControlRigSequencerLibrary.get_control_rigs(sequence)[0].control_rig
    for name in rig.current_control_selection():
        rig.select_control(str(name), False)
    actors.set_selected_level_actors([])
    settings = unreal.get_default_object(unreal.load_class(None, "/Script/ControlRigEditor.ControlRigEditModeSettings"))
    settings.set_editor_property("bDisplayHierarchy", False)
    settings.set_editor_property("bHideControlShapes", True)
    directions = {"front": (1, 0, 0), "back": (-1, 0, 0), "left": (0, -1, 0),
                  "right": (0, 1, 0), "top": (0, 0, 1), "bottom": (0, 0, -1)}
    center, extent = actor.get_actor_bounds(False)
    radius = max(extent.x, extent.y, extent.z)
    camera = center + unreal.Vector(*directions[request["view"]]) * radius * 2.4
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    keys = list(editor.get_viewport_config_keys())
    key = editor.get_active_viewport_config_key()
    if key not in keys:
        if len(keys) != 1:
            raise RuntimeError("검사할 뷰포트를 특정할 수 없다: " + str(keys))
        key = keys[0]
    editor.set_level_viewport_camera_info(camera, unreal.MathLibrary.find_look_at_rotation(camera, center), key)
    editor.editor_set_game_view(True, key)
    editor.editor_invalidate_viewports()
    return {"view": request["view"], "frame": request.get("frame", 0), "radius_cm": radius,
            "viewport": str(key), "camera": str(editor.get_level_viewport_camera_info(key))}


def run(request):
    validate(request)
    if request["workspace_operation"] == "import_static_geometry":
        return import_static_geometry(request)
    if request["workspace_operation"] == "import_geometry":
        return import_geometry(request)
    if request["workspace_operation"] == "inspect_assets":
        return inspect_assets(request)
    if request["workspace_operation"] == "build_rigid_rig":
        return build_rigid_rig(request)
    if request["workspace_operation"] == "create_control_scene":
        return create_control_scene(request)
    if request["workspace_operation"] == "inspect_controls":
        return inspect_controls(request)
    if request["workspace_operation"] == "key_poses":
        return key_poses(request)
    if request["workspace_operation"] == "set_review_view":
        return set_review_view(request)
    raise ValueError("지원하지 않는 새 리그 작업")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import unreal
    data = json.loads(Path(os.environ["FD_UNITS_REQUEST"]).read_text(encoding="utf-8-sig"))
    report = ROOT / data["report"]
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        report.write_text(json.dumps(run(data), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        import traceback
        report.with_suffix(".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    unreal.SystemLibrary.quit_editor()
