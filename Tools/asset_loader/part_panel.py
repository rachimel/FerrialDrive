"""새 파츠·복제 파츠·상태의 안정적인 ID를 지정하는 작은 입력 패널."""

from ferrial_drive.ui.components import Rect
from .part_model import add_part, add_state
from .widgets import Panel


def available_id(prefix, existing):
    result, number = prefix[:58], 1
    while result.casefold() in {key.casefold() for key in existing}:
        result = prefix[:58] + "_" + str(number)
        number += 1
    return result


class PartPanel(Panel):
    rect = Rect(340, 220, 600, 380)
    error_y = 506
    button_surface = "input"

    def __init__(self, parent, *, duplicate=False, state=False):
        self.title = "상태 추가" if state else "파츠 복제" if duplicate else "파츠 추가"
        super().__init__(parent.app, parent=parent)
        self.duplicate, self.state, self.template = duplicate, state, None
        prefix = "state" if state else parent.part_key + "_copy" if duplicate else "part"
        name = "새 상태" if state else parent.current_part["name"] + " 복제" if duplicate else "새 파츠"
        existing = parent.current_part["states"] if state else parent.data["layers"]
        self.add_field("id", available_id(prefix, existing), Rect(364, 318, 552, 34))
        self.add_field("name", name, Rect(364, 392, 552, 34))
        self.focus = "id"
        self.button("추가", Rect(796, 544, 120, 32), self.submit, style="button")
        self.button("취소", Rect(664, 544, 120, 32), self.close)
        if not state and not duplicate:
            self.choice("파츠 템플릿", [(None, "빈 파츠"), ("thrusters", "등 스러스터 · 수직/수평/전환")],
                        Rect(364, 450, 552, 32), self.select_template)

    def select_template(self, value):
        self.template = value
        if value == "thrusters":
            self.fields["id"].text = available_id("back_thrusters", self.parent.data["layers"])
            self.fields["name"].text = "등 스러스터"
            for field in self.fields.values():
                field.cursor = len(field.text)

    def submit(self):
        key = self.value("id")
        if self.state:
            add_state(self.parent.data, self.parent.part_key, key, self.value("name"))
            self.parent.part_state = key
            self.parent.current_motion["part_states"][self.parent.part_key] = key
        else:
            add_part(self.parent.data, key, self.value("name"),
                     duplicate=self.parent.part_key if self.duplicate else None, template=self.template)
            self.parent.part_key = key
            self.parent.part_state = self.parent.current_motion["part_states"].get(key, self.parent.current_part["default_state"])
            self.parent.part_offset = max(0, len(self.parent.data["layers"]) - 15)
        self.parent.saved = False
        self.parent.rebuild()
        self.close()

    def draw(self):
        super().draw()
        r, c = self.app.renderer, self.app.theme["colors"]
        r.text("고유 ID · 생성 후 고정", 364, 294, "small", c["muted"])
        r.text("표시 이름", 364, 370, "small", c["muted"])
        self.draw_choices()
