"""샘플 위치를 기준으로 해석하는 표현 설정. 실행 작업 폴더와 무관하다."""

import json
from math import hypot, isfinite
from pathlib import Path

from .components import Button, Rect


class UiConfig:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.colors = self.data["colors"]
        self.labels = self.data["labels"]
        self.layout = self.data["layout"]
        self.window = self.data["window"]
        self.font_paths = {
            role: (self.path.parent / entry["path"]).resolve()
            for role, entry in self.data["fonts"].items()
        }
        self.font_sizes = {role: entry["size"] for role, entry in self.data["fonts"].items()}
        metal = self.data["panel_style"].get("metallic", {})
        if not isinstance(metal.get("enabled", False), bool):
            raise ValueError("패널 금속 효과 사용 여부는 불리언이어야 한다.")
        if metal.get("enabled", False):
            for key in ("contrast", "grain_strength"):
                value = metal[key]
                if not isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("패널 금속 효과의 명암·결 강도는 0~1이어야 한다.")
        tracking = self.layout["counter_stack"].get("label_letter_spacing_pixels", 0)
        if not isfinite(tracking) or tracking < 0:
            raise ValueError("카운터 레이블 자간은 0 이상의 유한한 픽셀 값이어야 한다.")
        for key in ("crosshair_thickness_pixels", "crosshair_cross_thickness_pixels"):
            thickness = self.layout[key]
            if not isfinite(thickness) or not 0 < thickness < 36:
                raise ValueError("크로스헤어 두께는 0 초과 36 미만의 유한한 픽셀 값이어야 한다.")
        for key in ("dim_opacity", "panel_fill_opacity"):
            alpha = self.data["pause"][key]
            if not isfinite(alpha) or not 0 <= alpha <= 1:
                raise ValueError("일시정지 배경·패널 알파는 0~1이어야 한다.")
        counter = self.data["damage_counter"]
        samples = counter["blur_samples"]
        if not isinstance(samples, int) or not 0 <= samples <= 12:
            raise ValueError("카운터 블러 샘플 수는 0~12의 정수여야 한다.")
        if not isfinite(counter["blur_shutter_seconds"]) or counter["blur_shutter_seconds"] < 0:
            raise ValueError("카운터 블러 셔터 시간은 0 이상의 유한한 초 단위 값이어야 한다.")
        if not isfinite(counter["blur_opacity"]) or not 0 <= counter["blur_opacity"] <= 1:
            raise ValueError("카운터 블러 알파는 0~1이어야 한다.")
        if not isfinite(counter["outgoing_fade_power"]) or counter["outgoing_fade_power"] <= 0:
            raise ValueError("카운터 이전 숫자의 감쇠 지수는 양수인 유한한 값이어야 한다.")
        direction = counter["blur_direction"]
        if (len(direction) != 2 or not all(isfinite(value) for value in direction)
                or not 0 < hypot(*direction) < float("inf")):
            raise ValueError("카운터 블러 방향은 영벡터가 아닌 유한한 2차원 벡터여야 한다.")
        if not isfinite(counter["blur_length_pixels"]) or counter["blur_length_pixels"] < 0:
            raise ValueError("카운터 블러 길이는 0 이상의 유한한 픽셀 값이어야 한다.")
        health_bar = self.data["player_hp_bar"]
        if not all(isfinite(health_bar[key]) and health_bar[key] >= 3
                   for key in ("width_pixels", "height_pixels")):
            raise ValueError("플레이어 HP 바의 폭·높이는 3px 이상의 유한한 값이어야 한다.")
        if not isfinite(health_bar["side_offset_pixels"]) or health_bar["side_offset_pixels"] <= 0:
            raise ValueError("플레이어 HP 바의 좌우 거리는 양수인 유한한 픽셀 값이어야 한다.")
        self._validate_radar()
        missing = [f"{role} ({path.name})" for role, path in self.font_paths.items()
                   if not path.is_file()]
        if missing:
            raise FileNotFoundError("폰트 파일이 없다: " + ", ".join(missing))
        self.buttons = {
            scene: tuple(Button(entry["id"], entry["action"], entry["label"],
                                Rect(*entry["rect"]), entry.get("hit_padding", 0),
                                enabled=entry.get("enabled", True))
                         for entry in entries)
            for scene, entries in self.data["buttons"].items()
        }
        self._validate_buttons()

    def actor_anchor(self, owner: str) -> tuple[float, float]:
        if owner == "player":
            return self.window["width"] / 2, self.window["height"] / 2
        return tuple(self.layout[f"{owner}_anchor"])

    def _validate_radar(self):
        settings = self.data["radar"]
        dimension_keys = ("radius_pixels", "range_units", "arrow_length_pixels", "arrow_half_width_pixels")
        dimensions = (settings[key] for key in dimension_keys)
        if not all(isfinite(value) and value > 0 for value in dimensions):
            raise ValueError("레이더 반경·감지 거리·화살표 크기는 양수여야 한다.")
        min_scale = settings.get("arrow_min_scale", 0.45)
        if not isfinite(min_scale) or not 0 < min_scale <= 1:
            raise ValueError("레이더 삼각형 최소 크기 비율은 0 초과 1 이하여야 한다.")
        min_opacity = settings.get("arrow_min_opacity", 0.25)
        if not isfinite(min_opacity) or not 0 <= min_opacity <= 1:
            raise ValueError("레이더 삼각형 최소 알파는 0~1이어야 한다.")
        thickness = settings["ring_thickness_pixels"]
        if not isfinite(thickness) or thickness <= 0:
            raise ValueError("레이더 링 두께는 양수인 유한한 픽셀 값이어야 한다.")

    def _validate_buttons(self):
        """초기 초안은 판정 영역을 겹치지 않게 유지한다."""
        for buttons in self.buttons.values():
            ids = [button.button_id for button in buttons]
            if len(ids) != len(set(ids)):
                raise ValueError("장면 내 버튼 ID가 중복됐다.")
            for index, first in enumerate(buttons):
                if first.rect.width <= 0 or first.rect.height <= 0 or first.hit_padding < 0:
                    raise ValueError("버튼 크기는 양수, 판정 여유 폭은 0 이상이어야 한다.")
                for second in buttons[index + 1:]:
                    a, b = first.rect, second.rect
                    padding = first.hit_padding + second.hit_padding
                    if (a.x < b.x + b.width + padding and b.x < a.x + a.width + padding
                            and a.y < b.y + b.height + padding and b.y < a.y + a.height + padding):
                        raise ValueError("버튼 판정 영역 겹침: 배치 또는 판정 여유 폭 조정 필요")
