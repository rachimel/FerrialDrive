"""전체 프레임 모션 벡터를 기존 방향·콤보 재생 시간과 연결한다."""

import json
import hashlib
from math import isfinite
from pathlib import Path

from ferrial_drive.assets.pico_opacity import shadow_opacity
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from .motion_vectors import EASING_CODES, load_clip
from .pico_interpolation import PicoFrameInterpolator, read_rgba_image


def validate_source_assets(data, directory, expected_sources=()):
    """보간 카탈로그가 현재 파츠 메타데이터를 대상으로 만들어졌는지 확인한다."""
    declared = {}
    for row in data.get("source_assets", []):
        path = (Path(directory) / row["path"]).resolve()
        if path in declared or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("보간 제작 입력과 현재 파츠 메타데이터가 다르다. 보간 데이터를 다시 출력한다.")
        declared[path] = row
    if expected_sources and {Path(path).resolve() for path in expected_sources} != set(declared):
        raise ValueError("현재 UI 에셋과 보간 카탈로그의 제작 대상이 다르다.")


class PicoMotionSprite:
    """좌표는 화면 왼쪽 위 기준이다. 창·입력·시간 갱신은 호출자가 소유한다."""

    rim_light = (0, 0, 0, 0)

    def __init__(self, pico, source, *, easing="smoothstep", shutter_seconds=0.016,
                 blur_direction="trailing", blur_strength=0.65, expected_sources=(), cache_capacity=None, timings=None):
        source = Path(source).resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("clips"), list) or not data["clips"]:
            raise ValueError("방향별 모션 스프라이트 카탈로그가 필요하다.")
        validate_source_assets(data, source.parent, expected_sources)
        if (easing not in EASING_CODES or blur_direction not in ("trailing", "centered", "leading")
                or not isfinite(shutter_seconds) or shutter_seconds < 0
                or not isfinite(blur_strength) or not 0 <= blur_strength <= 1):
            raise ValueError("위상 곡선·노출·블러 설정 오류")
        self.pico = pico
        self.easing, self.shutter_seconds = easing, shutter_seconds
        self.blur_direction, self.blur_strength = blur_direction, blur_strength
        self.clips, self.motion_clips, self.placements = {}, {}, {}
        self.closed = False
        self.interpolator = PicoFrameInterpolator(pico, cache_capacity=len(data["clips"]) if cache_capacity is None else cache_capacity, timings=timings)
        self.estimated_bytes = 0
        try:
            for row in data["clips"]:
                name = row["name"]
                if not isinstance(name, str) or not name or name in self.clips:
                    raise ValueError("동작 이름이 비었거나 중복됐다.")
                pivot, pixel_scale, loop = row["pivot_top_left"], row["pixel_scale"], row["loop"]
                if (not isinstance(pivot, list) or len(pivot) != 2
                        or any(type(v) not in (int, float) or not isfinite(v) for v in pivot)
                        or type(pixel_scale) not in (int, float) or not isfinite(pixel_scale)
                        or pixel_scale <= 0 or type(loop) is not bool):
                    raise ValueError("피봇·원본 픽셀 배율·반복 설정 오류")
                # 클립 내 공유 경계 PNG는 한 번만 디코딩한다.
                images = {}

                def read_image(path):
                    if path not in images:
                        with self.interpolator.timings.scope("load.png_read_decode"):
                            images[path] = read_rgba_image(pico, path)
                    return images[path]

                with self.interpolator.timings.scope("load.motion_read_decode"):
                    motion = load_clip(source.parent / row["path"], read_image)
                pair = motion.pairs[0]
                self.motion_clips[name] = motion
                self.placements[name] = (tuple(pivot), pixel_scale, loop)
                frame = SpriteFrame((0, 0, pair.width, pair.height), (pivot[0], pair.height - pivot[1]))
                self.clips[name] = SpriteClip(1 / pair.duration_seconds, (frame,) * len(motion.pairs))
                self.interpolator.set_clip(motion)
                self.estimated_bytes += pair.width * pair.height * len(motion.pairs) * 16
        except BaseException:
            self.close()
            raise

    def draw(self, clip_name, elapsed_seconds, x, y, *, scale=1.0, opacity=1.0, easing=None, playback_speed=1.0,
             tint=(1, 1, 1), tint_mix=0, blur=True, brightness=1):
        if self.closed:
            raise RuntimeError("해제한 모션 스프라이트다.")
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0 or not isfinite(scale) or scale < 0:
            raise ValueError("재생 시간·배율은 0 이상의 유한한 값이어야 한다.")
        if not isfinite(playback_speed) or playback_speed <= 0:
            raise ValueError("재생 속도는 양수여야 한다.")
        motion = self.motion_clips[clip_name]
        pivot, pixel_scale, loop = self.placements[clip_name]
        phase = elapsed_seconds / motion.duration_seconds
        phase = phase % 1 if loop else min(1.0, phase)
        pair = motion.pairs[0]
        factor = scale * pixel_scale
        destination = self.pico.SDL_Rect(round(x - pivot[0] * factor), round(y - pivot[1] * factor),
                                         round(pair.width * factor), round(pair.height * factor))
        self.interpolator.set_clip(motion)
        with shadow_opacity(self.pico, self.interpolator.textures[0], opacity):
            self.interpolator.draw(phase, destination, easing=easing or self.easing,
                                   shutter_seconds=min(self.shutter_seconds * playback_speed, motion.duration_seconds) if blur else 0,
                                   blur_direction=self.blur_direction, blur_strength=self.blur_strength,
                                   tint=tint, tint_mix=tint_mix, rim_light=self.rim_light, brightness=brightness)

    def close(self):
        self.interpolator.close()
        self.motion_clips.clear()
        self.clips.clear()
        self.placements.clear()
        self.closed = True
