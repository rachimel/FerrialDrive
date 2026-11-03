"""샘플 위치를 기준으로 해석하는 표현 설정. 실행 작업 폴더와 무관하다."""

import json
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
        missing = [str(path) for path in self.font_paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError("폰트 파일이 없다: " + ", ".join(missing))
        self.buttons = {
            scene: tuple(Button(entry["id"], entry["action"], entry["label"],
                                Rect(*entry["rect"]), entry.get("hit_padding", 0))
                         for entry in entries)
            for scene, entries in self.data["buttons"].items()
        }
        self._validate_buttons()

    def actor_anchor(self, owner: str) -> tuple[float, float]:
        if owner == "player":
            return self.window["width"] / 2, self.window["height"] / 2
        return tuple(self.layout[f"{owner}_anchor"])

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
