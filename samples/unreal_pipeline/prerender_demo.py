"""게임 에셋 없는 Unreal 파츠 렌더 시연. 겹치는 기본 상자와 고정 카메라를 만든다."""
import json
import os
from pathlib import Path
import sys
import unreal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automate/unreal"))
import prerender


def main():
    request = json.loads(Path(os.environ["FD_PRERENDER_REQUEST"]).read_text(encoding="utf-8"))
    if unreal.EditorAssetLibrary.does_asset_exist(request["map"]) and unreal.EditorAssetLibrary.does_asset_exist(request["sequence"]):
        prerender.start(request)
        return
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    base = request["map"].rsplit("/", 1)[0]
    for key, position, scale, color in [
        ("body", (0, 0, 120), (.6, 1.1, 1.5), (.12, .35, .7, 1)),
        ("weapon", (45, 30, 120), (.25, 1.2, .25), (.8, .15, .05, 1)),
    ]:
        material = tools.create_asset("M_" + key, base, unreal.Material, unreal.MaterialFactoryNew())
        material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        expression = unreal.MaterialEditingLibrary.create_material_expression(material, unreal.MaterialExpressionConstant3Vector)
        expression.set_editor_property("constant", unreal.LinearColor(*color))
        unreal.MaterialEditingLibrary.connect_material_property(expression, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        unreal.MaterialEditingLibrary.recompile_material(material)
        unreal.EditorAssetLibrary.save_loaded_asset(material)
        actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*position))
        actor.set_actor_label(key)
        actor.set_editor_property("layers", [unreal.Name(key)])
        actor.static_mesh_component.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube.Cube"))
        actor.static_mesh_component.set_material(0, material)
        actor.set_actor_scale3d(unreal.Vector(*scale))
    camera = actors.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(400, 0, 120), unreal.Rotator(0, 180, 0))
    camera.camera_component.set_editor_property("projection_mode", unreal.CameraProjectionMode.ORTHOGRAPHIC)
    camera.camera_component.set_editor_property("ortho_width", 300.0)
    camera.camera_component.set_editor_property("aspect_ratio", 1.0)
    if request.get("shadow"):
        from render_units import create_shadow_receiver
        create_shadow_receiver(actors, base)
        light = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 500))
        light.set_actor_rotation(unreal.Rotator(pitch=-65, yaw=-150, roll=0), False)
        light.light_component.set_editor_property("intensity", 3.0)
        camera.set_actor_location(unreal.Vector(400, 350, 350), False, False)
        camera.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(camera.get_actor_location(), unreal.Vector(0, 0, 80)), False)
        camera.camera_component.set_editor_property("ortho_width", 450.0)
        # 모든 레이어와 그림자가 공유할 실제 월드 원점의 bottom-left 좌표다.
        rotation = camera.get_actor_rotation()
        right = unreal.MathLibrary.get_right_vector(rotation)
        up = unreal.MathLibrary.get_up_vector(rotation)
        offset = unreal.Vector(0, 0, -80)
        dot = lambda a, b: a.x*b.x + a.y*b.y + a.z*b.z
        request["pivot"] = [request["size"][0]/2 + dot(offset, right)*request["size"][0]/450,
                            request["size"][1]/2 + dot(offset, up)*request["size"][0]/450]
    unreal.EditorLoadingAndSavingUtils.save_map(world, request["map"])
    sequence = tools.create_asset("LS_Demo", base, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(12, 1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(2)
    binding = sequence.add_possessable(camera)
    track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
    section = track.add_section()
    section.set_range(0, 2)
    identity = unreal.MovieSceneObjectBindingID()
    identity.set_editor_property("guid", binding.get_id())
    section.set_camera_binding_id(identity)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    unreal.EditorLoadingAndSavingUtils.save_map(world, request["map"])
    prerender.start(request)


try:
    main()
except Exception:
    import traceback
    target = ROOT / "output/unreal_prerender_demo/startup_error.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(traceback.format_exc(), encoding="utf-8")
    unreal.SystemLibrary.quit_editor()
