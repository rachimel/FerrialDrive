"""기존 동작을 변경하지 않고 MRQ 색상·정/역방향 벡터·중간 정답을 출력한다."""

import json
import os
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = None


def create_sequence(request, master, camera, name, fps, reverse=False):
    import unreal
    prefix = request["asset_root"]
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sequence = tools.create_asset(name, prefix, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    sequence.set_display_rate(unreal.FrameRate(fps, 1))
    count = round(request["duration_seconds"] * fps) + 1
    sequence.set_playback_start(0)
    sequence.set_playback_end(count)
    track = sequence.add_possessable(master).add_track(unreal.MovieSceneSkeletalAnimationTrack)
    section = track.add_section()
    params = section.get_editor_property("params")
    params.set_editor_property("animation", unreal.load_asset(request["animation"]))
    params.set_editor_property("reverse", reverse)
    # 마지막 키와 정확히 같은 시각이 다음 반복의 첫 키로 환산되는 것을 피한다.
    params.set_editor_property("end_frame_offset", unreal.FrameNumber(-1))
    section.set_editor_property("params", params)
    section.set_range(0, count)
    camera_binding = sequence.add_possessable(camera)
    cut = sequence.add_track(unreal.MovieSceneCameraCutTrack).add_section()
    cut.set_range(0, count)
    identity = unreal.MovieSceneObjectBindingID()
    identity.set_editor_property("guid", camera_binding.get_id())
    cut.set_camera_binding_id(identity)
    unreal.EditorAssetLibrary.save_loaded_asset(sequence)
    return sequence, count


def configure(queue, request, name, sequence, fps, count, vectors):
    import unreal
    from prerender import configure_job
    output = ROOT / request["output"] / name
    job = configure_job(queue, {**request, "sequence": sequence.get_path_name(),
                                "frame_count": 1, "frame_start": 0, "disable_tone_curve": True}, output, ["unsplit_reference"])
    config = job.get_configuration()
    settings = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    settings.output_frame_rate = unreal.FrameRate(fps, 1)
    settings.custom_start_frame = 0
    settings.custom_end_frame = count
    deferred = config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    deferred.set_editor_property("additional_post_process_materials", [])
    if vectors:
        material = unreal.load_asset("/MovieRenderPipeline/Materials/MovieRenderQueue_MotionVectors")
        if not material:
            raise RuntimeError("Unreal 기본 모션 벡터 패스가 없다.")
        field = unreal.MoviePipelinePostProcessPass()
        field.set_editor_property("enabled", True)
        field.set_editor_property("name", "MotionVectors")
        field.set_editor_property("material", material)
        field.set_editor_property("high_precision_output", True)
        field.set_editor_property("use_lossless_compression", True)
        deferred.set_editor_property("additional_post_process_materials", [field])
        exr = config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_EXR)
        exr.set_editor_property("multilayer", False)
    aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.engine_warm_up_count = 8
    aa.render_warm_up_count = 8
    aa.render_warm_up_frames = True
    return {"name": name, "sequence": sequence.get_path_name(), "fps": fps, "frames": count,
            "vectors": vectors}


def prepare_capture(request, queue):
    import unreal
    output = (ROOT / request["output"]).resolve()
    if not output.is_relative_to(ROOT / "output") or output.exists():
        raise ValueError("output 아래 새 렌더 경로가 필요하다.")
    prefix = request["asset_root"]
    if not prefix.startswith("/Game/MechLab/Interpolation_") or unreal.EditorAssetLibrary.list_assets(prefix, recursive=True):
        raise ValueError("보간 검증용 새 Sequence 경로가 필요하다.")
    for name in ("map", "animation"):
        if not unreal.EditorAssetLibrary.does_asset_exist(request[name]):
            raise FileNotFoundError("현재 렌더 프로젝트에 에셋이 없다: " + request[name])
    if not unreal.EditorLoadingAndSavingUtils.load_map(request["map"]):
        raise RuntimeError("검증용 원본 맵을 열 수 없다.")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    master = next(actor for actor in actors if actor.get_actor_label() == "PoseMaster")
    camera = next(actor for actor in actors if isinstance(actor, unreal.CameraActor))
    output.mkdir(parents=True)
    unreal.SystemLibrary.execute_console_command(None, "r.PostProcessing.PropagateAlpha 1")
    jobs = []
    passes = request.get("passes", ["forward", "reverse", "reference", "energy"])
    if not passes or any(name not in ("forward", "reverse", "reference", "energy") for name in passes):
        raise ValueError("지원하는 네이티브 출력 패스 목록이 필요하다.")
    for name, fps, reverse, vectors in (("forward", request["source_fps"], False, True),
                                        ("reverse", request["source_fps"], True, True),
                                        ("reference", request["reference_fps"], False, False)):
        if name not in passes:
            continue
        sequence, count = create_sequence(request, master, camera, "LS_" + name, fps, reverse)
        jobs.append(configure(queue, request, name, sequence, fps, count, vectors))
    if request.get("energy_map") and "energy" in passes:
        if not unreal.EditorLoadingAndSavingUtils.load_map(request["energy_map"]):
            raise RuntimeError("같은 기체의 Energy Mask 맵을 열 수 없다.")
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        master = next(actor for actor in actors if actor.get_actor_label() == "PoseMaster")
        camera = next(actor for actor in actors if isinstance(actor, unreal.CameraActor))
        master.skeletal_mesh_component.set_visibility(True)
        for actor in actors:
            if isinstance(actor, unreal.SkeletalMeshActor) and actor != master:
                actor.skeletal_mesh_component.set_visibility(False)
        mask_map = prefix + "/MAP_EnergyReference"
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        unreal.EditorLoadingAndSavingUtils.save_map(world, mask_map)
        unreal.EditorLoadingAndSavingUtils.load_map(mask_map)
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        master = next(actor for actor in actors if actor.get_actor_label() == "PoseMaster")
        camera = next(actor for actor in actors if isinstance(actor, unreal.CameraActor))
        sequence, count = create_sequence(request, master, camera, "LS_EnergyMask", request["source_fps"])
        jobs.append(configure(queue, {**request, "map": mask_map}, "energy", sequence,
                              request["source_fps"], count, False))
    provenance = {"request": request, "engine": unreal.SystemLibrary.get_engine_version(), "jobs": jobs,
                  "source_animation_modified": False, "capture": "native MRQ motion vectors; reverse playback"}
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def start(request):
    import unreal
    global EXECUTOR
    sys.path.insert(0, str(Path(__file__).parent))
    subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = subsystem.get_queue()
    if queue.get_jobs():
        raise RuntimeError("기존 MRQ 작업을 덮어쓰지 않는다.")
    outputs = [prepare_capture(item, queue) for item in request.get("captures", [request])]
    output = ROOT / request["output"]
    output.mkdir(parents=True, exist_ok=True)

    def finished(executor, success):
        for directory in {output, *outputs}:
            (directory / "status.json").write_text(json.dumps({"success": bool(success)}), encoding="utf-8")
        unreal.SystemLibrary.quit_editor()

    EXECUTOR = unreal.MoviePipelinePIEExecutor()
    EXECUTOR.on_executor_finished_delegate.add_callable_unique(finished)
    unreal.EditorPythonScripting.set_keep_python_script_alive(True)
    subsystem.render_queue_with_executor_instance(EXECUTOR)


if __name__ == "__main__":
    import unreal
    request = json.loads(Path(os.environ["FD_MOTION_REQUEST"]).read_text(encoding="utf-8"))
    try:
        start(request)
    except Exception:
        output = ROOT / request["output"]
        output.mkdir(parents=True, exist_ok=True)
        (output / "status.json").write_text(json.dumps({"success": False, "error": traceback.format_exc()}), encoding="utf-8")
        unreal.SystemLibrary.quit_editor()
