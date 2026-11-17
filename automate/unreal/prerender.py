"""Unreal 시작 스크립트: 저장된 맵·Sequence의 Actor Layer를 MRQ로 출력한다."""
import json
import os
from pathlib import Path
import re

EXECUTOR = None


def start(request, queue=None):
    import unreal
    global EXECUTOR
    root = Path(__file__).resolve().parents[2]
    output = (root / request["output"]).resolve()
    if not output.is_relative_to(root / "output"):
        raise ValueError("렌더 결과는 프로젝트 output 안에 둔다.")
    if output.exists():
        raise FileExistsError(output)
    width, height = request["size"]
    count = request.get("frame_count", 1)
    step = request.get("frame_step", 1)
    if (type(count) is not int or not 1 <= count <= (4096 if request.get("pose_table") is True else 12)
            or type(step) is not int or not 1 <= step <= count or "body" not in request["layers"]):
        raise ValueError("body 레이어와 1~12 프레임이 필요하다.")
    if any(type(v) is not int or not 1 <= v <= 8192 for v in (width, height)) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) for key in request["layers"]):
        raise ValueError("해상도·레이어 ID 오류")
    if unreal.SystemLibrary.get_console_variable_int_value("r.CustomDepth") != 3:
        raise ValueError("프로젝트 Custom Depth-Stencil Pass를 Enabled with Stencil(r.CustomDepth=3)로 설정한다.")
    for key in ("map", "sequence"):
        if not request[key].startswith("/Game/") or not unreal.EditorAssetLibrary.does_asset_exist(request[key]):
            raise ValueError("저장된 맵·Sequence가 필요하다: " + key)
    subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    batch_member = queue is not None
    if queue is None:
        queue = subsystem.get_queue()
    if not batch_member and queue.get_jobs():
        raise RuntimeError("기존 렌더 작업이 있다. 덮어쓰지 않는다.")
    output.mkdir(parents=True)
    shadow = request.get("shadow")
    color_prefix = "color/" if shadow else ""
    layers = list(request["layers"])
    if shadow:
        if shadow["part_id"] in layers or shadow["receiver_layer"] in layers:
            raise ValueError("그림자·수신면·색상 파츠 ID는 서로 달라야 한다.")
        layers.append(shadow["receiver_layer"])
    configure_job(queue, request, output / color_prefix, layers)
    if shadow:
        reference={**request,**shadow.get("reference",{})}
        configure_job(queue, reference, output / "shadow_reference", [shadow["receiver_layer"]], shadowless=not bool(shadow.get("reference")), main_pass=False)
    if request.get("energy"):
        energy={**request,**request["energy"],"mask_pass":True}
        configure_job(queue,energy,output/"energy",list(request["layers"]),main_pass=False)
    if request.get("reference"):
        reference = {**request, **request["reference"]}
        configure_job(queue, reference, output / "reference", request["reference"].get("actor_layers", []))
    unreal.SystemLibrary.execute_console_command(None, "r.PostProcessing.PropagateAlpha 1")

    def finished(executor, success):
        state = {"success": success}
        try:
            if not success:
                raise RuntimeError("MRQ 렌더 실패")
            frames = []
            for index in range(request.get("frame_start", 0), request.get("frame_start", 0) + count, step):
                frame = {}
                for key in request["layers"]:
                    relative = f"{color_prefix}FinalImage{key}/{index:04d}.png"
                    if not (output / relative).is_file():
                        raise FileNotFoundError(relative)
                    frame[key] = relative
                frames.append(frame)
            manifest = {"version": 1, "type": "unreal_prerender", "asset_id": request["asset_id"],
                        "size": request["size"], "pivot": request["pivot"], "layers": request["layers"],
                        "renderer": "Unreal MRQ stencil layers", "engine": unreal.SystemLibrary.get_engine_version(),
                        "map": request["map"], "sequence": request["sequence"],
                        "source_frame_numbers": list(range(request.get("frame_start", 0), request.get("frame_start", 0) + count, step)),
                        "clips": [{"name": request["clip"], "fps": 12, "frames": frames, "order": request.get("order", list(request["layers"]))}]}
            if request.get("energy"):
                energy_frames=[{key:f"energy/FinalImage{key}/{index:04d}.png" for key in request["layers"]}
                               for index in manifest["source_frame_numbers"]]
                for frame in energy_frames:
                    for relative in frame.values():
                        if not (output/relative).is_file():
                            raise FileNotFoundError(relative)
                manifest["clips"][0]["energy_frames"]=energy_frames
            filename = "manifest.json"
            if shadow:
                pairs = [{"shadowed": f"color/FinalImage{shadow['receiver_layer']}/{index:04d}.png",
                          "clear": f"shadow_reference/FinalImage{shadow['receiver_layer']}/{index:04d}.png"}
                         for index in manifest["source_frame_numbers"]]
                for pair in pairs:
                    for relative in pair.values():
                        if not (output / relative).is_file():
                            raise FileNotFoundError(relative)
                manifest["shadow_pending"] = {"part_id": shadow["part_id"], "frames": pairs}
                filename = "native_manifest.json"
            if request.get("reference"):
                manifest["reference_frames"] = [f"reference/FinalImage/{index:04d}.png" for index in manifest["source_frame_numbers"]]
                manifest["reference_mask_frames"] = {name: [f"reference/FinalImage{name}/{index:04d}.png" for index in manifest["source_frame_numbers"]]
                                                     for name in request["reference"].get("actor_layers", [])}
            (output / filename).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception as error:
            state = {"success": False, "error": str(error)}
        (output / "status.json").write_text(json.dumps(state), encoding="utf-8")
        if request.get("quit_when_finished"):
            unreal.SystemLibrary.quit_editor()

    if batch_member:
        return finished
    EXECUTOR = unreal.MoviePipelinePIEExecutor()
    EXECUTOR.on_executor_finished_delegate.add_callable_unique(finished)
    unreal.EditorPythonScripting.set_keep_python_script_alive(True)
    subsystem.render_queue_with_executor_instance(EXECUTOR)


def start_batch(request):
    """새 출력 요청들을 같은 MRQ 큐에 넣고 각각의 완료 기록을 보존한다."""
    import unreal
    global EXECUTOR
    root = Path(__file__).resolve().parents[2]
    output = (root / request["output"]).resolve()
    members = request.get("requests", [])
    if not output.is_relative_to(root / "output") or output.exists():
        raise ValueError("일괄 보고는 새 output 경로가 필요하다.")
    if not isinstance(members, list) or not 1 <= len(members) <= 32:
        raise ValueError("일괄 렌더는 1~32개 요청이 필요하다.")
    destinations = [(root / member["output"]).resolve() for member in members]
    if len(set(destinations)) != len(destinations) or any(
            not path.is_relative_to(root / "output") or path.exists()
            or path == output or path.is_relative_to(output) or output.is_relative_to(path)
            for path in destinations):
        raise ValueError("개별 출력은 서로 다른 새 output 경로가 필요하다.")
    queue = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem).get_queue()
    if queue.get_jobs():
        raise RuntimeError("기존 렌더 작업이 있다. 덮어쓰지 않는다.")
    output.mkdir(parents=True)
    try:
        callbacks = [start({**member, "quit_when_finished": False}, queue=queue) for member in members]
    except Exception as error:
        (output / "status.json").write_text(json.dumps({"success": False, "error": str(error)}), encoding="utf-8")
        unreal.SystemLibrary.quit_editor()
        return

    def finished(executor, success):
        for callback in callbacks:
            callback(executor, success)
        states = [json.loads((path / "status.json").read_text(encoding="utf-8")) for path in destinations]
        result = {"success": bool(success) and all(state["success"] for state in states),
                  "renders": [{"manifest": str(Path(member["output"]) / "manifest.json"), **state}
                              for member, state in zip(members, states)]}
        (output / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (output / "status.json").write_text(json.dumps(result), encoding="utf-8")
        if request.get("quit_when_finished"):
            unreal.SystemLibrary.quit_editor()

    EXECUTOR = unreal.MoviePipelinePIEExecutor()
    EXECUTOR.on_executor_finished_delegate.add_callable_unique(finished)
    unreal.EditorPythonScripting.set_keep_python_script_alive(True)
    unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem).render_queue_with_executor_instance(EXECUTOR)


def configure_job(queue, request, output, layers, shadowless=False, main_pass=True):
    import unreal
    width, height = request["size"]
    count = request.get("frame_count", 1)
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.map = unreal.SoftObjectPath(request["map"])
    job.sequence = unreal.SoftObjectPath(request["sequence"])
    config = job.get_configuration()
    settings = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    settings.output_directory = unreal.DirectoryPath(str(output))
    settings.output_resolution = unreal.IntPoint(width, height)
    settings.file_name_format = "{render_pass}/{frame_number}"
    settings.zero_pad_frame_numbers = 4
    settings.use_custom_frame_rate = True
    settings.output_frame_rate = unreal.FrameRate(12, 1)
    settings.output_frame_step = request.get("frame_step", 1)
    settings.use_custom_playback_range = True
    settings.custom_start_frame = request.get("frame_start", 0)
    settings.custom_end_frame = request.get("frame_start", 0) + count
    render = config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    render.set_editor_property("actor_layers", [unreal.ActorLayer(name=key) for key in layers])
    render.set_editor_property("accumulator_includes_alpha", True)
    render.set_editor_property("disable_multisample_effects", True)
    cvars = config.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    for name in ("r.EyeAdaptationQuality", "r.BloomQuality", "r.MotionBlurQuality"):
        if not cvars.add_or_update_console_variable(name, 0.0):
            raise RuntimeError("출력 설정 실패: " + name)
    config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.override_anti_aliasing = True
    aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_NONE
    aa.spatial_sample_count = 1
    aa.temporal_sample_count = 1
    aa.engine_warm_up_count = 4


    render.set_editor_property("render_main_pass", main_pass)
    if shadowless:
        cvars.add_or_update_console_variable("r.ShadowQuality", 0.0)
        cvars.add_or_update_console_variable("r.AmbientOcclusionLevels",0.0)
    if request.get("mask_pass") or request.get("disable_tone_curve"):
        config.find_or_add_setting_by_class(unreal.MoviePipelineColorSetting).disable_tone_curve=True
    if request.get("mask_pass"):
        cvars.add_or_update_console_variable("r.TonemapperGamma",1.0)
    elif request.get("disable_tone_curve"):
        cvars.add_or_update_console_variable("r.TonemapperGamma",2.2)
    return job


if __name__ == "__main__":
    request = json.loads(Path(os.environ["FD_PRERENDER_REQUEST"]).read_text(encoding="utf-8-sig"))
    (start_batch if "requests" in request else start)(request)
