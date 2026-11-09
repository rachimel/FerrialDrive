"""매핑 프리셋 이름을 입력하는 작은 하위 패널."""

from ferrial_drive.ui.components import Rect
from .mech_presets import save_mapping
from .widgets import Panel


class MechPresetPanel(Panel):
    title = "출력 매핑 프리셋 저장"
    rect = Rect(340, 252, 600, 280)

    def __init__(self, parent):
        super().__init__(parent.app, parent=parent)
        self.add_field("name", parent.app.asset_id, Rect(364, 326, 552, 36))
        self.focus = "name"
        self.fields["name"].selected = True
        self.button("저장", Rect(796, 472, 120, 36), self.submit)
        self.button("취소", Rect(664, 472, 120, 36), self.close)

    def submit(self):
        save_mapping(self.value("name"), self.parent.data)
        self.parent.rebuild()
        self.close()
