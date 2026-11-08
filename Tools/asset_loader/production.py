"""저장된 모델·기존 리그/동작의 렌더 작업을 구성한다. Blender는 실행하지 않는다."""

from copy import deepcopy
import json
from math import isfinite
from pathlib import Path

from ferrial_drive.assets import AssetDefinition


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "samples/asset_load_test/render_config.json"
WORKSPACE = Path(__file__).with_name("workspace")


def frame_numbers(text):
    try:
        frames = [int(value.strip()) for value in text.split(",")]
    except ValueError as error:
        raise ValueError("프레임은 쉼표로 구분한 정수 목록이어야 한다.") from error
    if not frames or len(frames) > 256 or any(value < 0 for value in frames):
        raise ValueError("프레임은 0 이상의 정수로 최대 256개 지정한다.")
    # 렌더 원본은 한 번씩 출력하고 중복·역순은 조립 단계에서 지정한다.
    if len(set(frames)) != len(frames):
        raise ValueError("렌더 프레임은 중복 없이 지정한다. 반복은 조립 단계에서 설정한다.")
    return frames


def render_config(*, asset_id, animation_name, frames, fps, width, height,
                  ortho_scale, samples, root_object="", use_scene_camera=False, auto_fit=True, sharpen=0.35):
    AssetDefinition(asset_id, "image", DEFAULT_CONFIG)
    if not animation_name.strip() or "/" in animation_name or "\\" in animation_name:
        raise ValueError("동작 이름은 경로 구분자 없이 작성한다.")
    frames = frame_numbers(frames)
    fps, ortho_scale = float(fps), float(ortho_scale)
    if not isfinite(fps) or not 1 <= fps <= 240 or not fps.is_integer():
        raise ValueError("렌더 FPS는 1~240의 정수다. 조립 단계에서는 소수 FPS도 지원한다.")
    if not isfinite(ortho_scale) or ortho_scale <= 0:
        raise ValueError("정사영 범위는 양수여야 한다.")
    width, height, samples = int(width), int(height), int(samples)
    if not 16 <= width <= 2048 or not 16 <= height <= 2048 or width * len(frames) > 16384:
        raise ValueError("프레임 크기는 16~2048px이며 시트 가로는 16384px 이하여야 한다.")
    if not 1 <= samples <= 4096:
        raise ValueError("렌더 샘플은 1~4096 범위여야 한다.")
    config = deepcopy(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")))
    config.update(asset_id=asset_id, animation_name=animation_name.strip(), frames=frames,
                  fps=int(fps), frame_size_pixels=[width, height], root_object=root_object.strip(),
                  use_scene_camera=bool(use_scene_camera), auto_fit=bool(auto_fit) and not use_scene_camera)
    config["camera"]["ortho_scale"] = ortho_scale
    config["light"].update(position=[-3, -4, 12], energy=1400)
    config["use_scene_lighting"] = False
    config["render"].update(samples=samples, shadow_samples=samples)
    if type(sharpen) not in (int, float) or not isfinite(sharpen) or not 0 <= sharpen <= 2:
        raise ValueError("샤프닝 강도는 0~2 범위여야 한다.")
    config["postprocess"] = {"sharpen": sharpen}
    config.pop("note", None)
    return config
