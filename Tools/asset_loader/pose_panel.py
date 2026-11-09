"""Asset Tool 화면에서 포즈를 직접 편집한다. Blender 창은 열지 않는다."""

from pathlib import Path
from math import hypot

from ferrial_drive.assets import AssetDefinition
from ferrial_drive.assets.catalog import read_document
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.ui.components import Rect
from Tools.pose_tool.session import PoseSession
from .widgets import Panel
from .file_panel import FilePanel


LABELS = {"pelvis": "골반", "waist": "허리", "chest": "몸통", "head": "머리",
          "shoulder.L": "왼쪽 어깨", "shoulder.R": "오른쪽 어깨",
          "hand.L": "왼손바닥", "hand.R": "오른손바닥", "foot.L": "왼발", "foot.R": "오른발",
          "pole.hand.L": "왼쪽 팔꿈치", "pole.hand.R": "오른쪽 팔꿈치",
          "pole.foot.L": "왼쪽 무릎", "pole.foot.R": "오른쪽 무릎"}


class PosePanel(Panel):
    title = "포즈 편집"
    rect = Rect(16, 16, 1248, 768)
    button_surface = "input"
    error_x, error_y, error_width = 40, 748, 1170
    preview = Rect(272, 160, 640, 560)

    def __init__(self, app, source=None):
        super().__init__(app)
        self.session = self.resource = None
        self.loaded_revision = -1
        self.loaded_source = None
        self.is_sample = False
        self.selected = "hand.R"
        self.clip_offset = 0
        self.drag = None
        self.add_field("source", source or "", Rect(40, 78, 684, 30))
        self.add_field("frame", "1", Rect(560, 120, 80, 28))
        self.add_field("degrees", "5", Rect(1000, 450, 68, 28))
        self.button("찾기", Rect(732, 78, 72, 30), self.browse)
        self.button("모델 / 작업본 열기", Rect(812, 78, 224, 30), self.open_model)
        self.button("도형 샘플", Rect(1044, 78, 192, 30), lambda: self.open_model(sample=True))
        for index, (key, label) in enumerate((("oblique", "사선"), ("front", "정면"), ("side", "측면"), ("back", "후면"), ("top", "위"))):
            self.button(label, Rect(272+index*54, 120, 50, 28), lambda k=key: self.send("view", name=k))
        self.button("이동", Rect(648, 120, 56, 28), self.seek)
        self.button("◀", Rect(712, 120, 40, 28), lambda: self.step(-1))
        self.button("▶", Rect(756, 120, 40, 28), lambda: self.step(1))
        self.button("−", Rect(812, 120, 44, 28), lambda: self.send("zoom", factor=1.15))
        self.button("+", Rect(864, 120, 44, 28), lambda: self.send("zoom", factor=1/1.15))
        for index, key in enumerate(LABELS):
            self.button(LABELS[key], Rect(928+(index % 2)*156, 168+(index//2)*32, 148, 28), lambda k=key: self.select(k))
        self.button("좌 → 우", Rect(928, 490, 96, 28), lambda: self.send("mirror", direction="L_TO_R"))
        self.button("우 → 좌", Rect(1032, 490, 96, 28), lambda: self.send("mirror", direction="R_TO_L"))
        self.button("전체 반전", Rect(1136, 490, 100, 28), lambda: self.send("mirror", direction="BOTH"))
        for index, axis in enumerate("XYZ"):
            self.button(axis+" −", Rect(928+index*104, 418, 48, 28), lambda a=axis: self.rotate(a, -1))
            self.button(axis+" +", Rect(980+index*104, 418, 48, 28), lambda a=axis: self.rotate(a, 1))
        self.button("보조손 고정", Rect(928, 532, 148, 28), lambda: self.send("support", enabled=True))
        self.button("고정 해제", Rect(1084, 532, 152, 28), lambda: self.send("support", enabled=False))
        for index, (prop, label) in enumerate((("sword_stowed", "검"), ("gun_stowed", "총"))):
            self.button(label+" 수납/파지", Rect(928+index*156, 568, 148, 28), lambda p=prop: self.toggle_equipment(p))
        self.button("현재 포즈 키 저장", Rect(928, 610, 308, 34), lambda: self.send("key"), style="button")
        self.button("작업본 저장", Rect(928, 652, 148, 30), lambda: self.send("save"))
        self.button("동작 출력", Rect(1084, 652, 152, 30), lambda: self.send("export"))
        self.button("출력 → 3D 렌더", Rect(928, 690, 308, 30), self.to_render)

    @property
    def data(self):
        return self.session.state if self.session and self.session.state else None

    def browse(self):
        self.app.set_panel(FilePanel(self.app, self.load_source, extensions={".blend"},
                                    initial=self.value("source") or Path(__file__).resolve().parents[2] / "data/models", parent=self))

    def load_source(self, path):
        path = Path(path).expanduser().resolve()
        self.fields["source"].text = str(path)
        self.fields["source"].cursor = len(str(path))
        if self.loaded_source != path or self.session is None or getattr(self.session, "error", None):
            self.open_model()

    def open_model(self, *, sample=False):
        if self.session and self.data and (self.data["dirty"] or self.data["file_dirty"] or self.session.busy):
            raise ValueError("현재 작업을 저장하고 계산 완료 후 새 모델을 연다.")
        source = None if sample else Path(self.value("source").strip('"')).expanduser().resolve()
        if not sample and (source.suffix.lower() != ".blend" or not source.is_file()):
            raise ValueError("포즈를 편집할 .blend 모델 또는 작업본을 선택한다.")
        self.close_resources()
        self.loaded_revision = -1
        self.session = PoseSession(source, sample=sample, clip=self.app.clip_name or None)
        self.loaded_source = source
        self.is_sample = sample
        self.app.model_source = source
        if sample:
            self.fields["source"].text = ""
        self.clip_offset = 0

    def send(self, command, **fields):
        if not self.session or self.data is None:
            raise ValueError("모델 준비가 끝난 뒤 조작한다.")
        self.session.send(command, **fields)

    def select(self, key):
        self.selected = key
        self.focus = None

    def seek(self):
        self.send("frame", frame=int(self.value("frame")))

    def submit(self):
        self.seek() if self.focus == "frame" else None

    def step(self, delta):
        if self.data:
            self.send("frame", frame=min(self.data["end"], max(self.data["start"], self.data["frame"]+delta)))

    def rotate(self, axis, sign):
        self.send("rotate", control=self.selected, axis=axis, degrees=float(self.value("degrees"))*sign)

    def toggle_equipment(self, prop):
        if not self.data or prop not in self.data["equipment"]:
            raise ValueError("이 모델에는 해당 장비 제어가 없다.")
        self.send("equipment", property=prop, value=0.0 if self.data["equipment"][prop] > .5 else 1.0)

    def to_render(self):
        if not self.data or not self.data.get("exported"):
            raise ValueError("먼저 현재 동작을 출력한다.")
        if self.session.busy or self.data["dirty"] or self.data["file_dirty"]:
            raise ValueError("편집한 현재 동작을 다시 출력하고 완료 후 전달한다.")
        from .editors import RenderPanel
        panel = RenderPanel(self.app)
        panel.load_preset(Path(self.data["exported"]))
        self.app.set_panel(panel)

    def update(self, delta_seconds):
        if not self.session:
            return
        self.session.poll()
        if self.session.error:
            self.error = self.session.error
        elif self.loaded_revision != self.session.revision and self.session.state:
            definition = AssetDefinition("pose_preview", "image", self.session.directory / "preview.png")
            candidate = PicoAssetBackend("linear").load(read_document(definition))
            if self.resource:
                self.resource.close()
            self.resource = candidate
            self.loaded_revision = self.session.revision
            self.error = ""
            if self.focus != "frame":
                self.fields["frame"].text = str(self.data["frame"])

    def content_event(self, event):
        pico, data = self.app.pico, self.data
        if not data or self.choice_popup:
            return
        if event.type == pico.SDL_MOUSEWHEEL and 40 <= self.app.mouse[0] <= 252:
            self.clip_offset = max(0, min(max(0, len(data["clips"])-18), self.clip_offset-event.y))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            if 40 <= event.x < 252 and 164 <= event.y < 704:
                index = self.clip_offset + (event.y-164)//30
                if index < len(data["clips"]):
                    self.attempt(lambda: self.send("clip", name=data["clips"][index]["name"]))
            elif self.preview.contains(event.x, event.y) and not self.session.busy:
                visible = [(hypot(event.x-x, event.y-y), key) for key, x, y in self.projected_points()]
                if visible and min(visible)[0] < 16:
                    self.selected = min(visible)[1]
                    self.drag = (event.x, event.y, data["points"][self.selected]["world"],
                                 data["right"], data["up"], data["scale"])
        elif event.type == pico.SDL_MOUSEMOTION and self.drag:
            x, y, world, right, up, scale = self.drag
            dx, dy = (event.x-x)/self.preview.height*scale, (event.y-y)/self.preview.height*scale
            target = [world[i]+right[i]*dx-up[i]*dy for i in range(3)]
            command = "bend" if self.selected.startswith("pole.") else "move"
            self.attempt(lambda: self.send(command, control=self.selected, world=target))
        elif event.type == pico.SDL_MOUSEBUTTONUP and event.button == pico.SDL_BUTTON_LEFT:
            self.drag = None

    def projected_points(self):
        for key, point in self.data["points"].items():
            x, y, z = point["uv"]
            if z > 0 and 0 <= x <= 1 and 0 <= y <= 1:
                yield key, self.preview.x+x*self.preview.width, self.preview.y+(1-y)*self.preview.height

    def draw(self):
        self.title = "포즈 편집" + (" · "+self.loaded_source.name if self.loaded_source else " · 도형 샘플" if self.is_sample else "")
        for index, key in enumerate(LABELS):
            self.button_styles[(928+(index % 2)*156, 168+(index//2)*32)] = "selected" if key == self.selected else "input"
        super().draw()
        r, colors, data = self.app.renderer, self.app.theme["colors"], self.data
        r.rect(self.preview, colors["background"])
        if self.resource:
            self.resource.draw("image", 0, self.preview.x+self.preview.width/2,
                               800-self.preview.y-self.preview.height, scale=1)
        r.text("동작", 40, 132, "body", colors["text"])
        r.text("컨트롤 · 기체 좌우 기준", 928, 132, "small", colors["muted"])
        r.text("회전 · 월드 축", 928, 394, "small", colors["muted"])
        r.text("회전각", 928, 457, "small", colors["muted"])
        r.text("도", 1078, 457, "small", colors["muted"])
        if data:
            for index, clip in enumerate(data["clips"][self.clip_offset:self.clip_offset+18]):
                rect = Rect(40, 164+index*30, 212, 28)
                r.rect(rect, colors["selected"] if clip["name"] == data["active"] else colors["input"])
                r.text(clip["label"], rect.x+8, rect.y+7, "small", colors["text"], max_width=196)
            with r.clip(self.preview):
                for key, x, y in self.projected_points():
                    color = colors["button_hover"] if key == self.selected else colors["accent"]
                    size = 6 if key == self.selected else 4
                    if key.startswith("pole."):
                        pole_uv = data["points"][key].get("pole_uv")
                        if pole_uv:
                            dx = (pole_uv[0]*self.preview.width+self.preview.x)-x
                            dy = (self.preview.y+(1-pole_uv[1])*self.preview.height)-y
                            distance = hypot(dx, dy)
                            if distance > 1:
                                r.line(x, y, x+dx/distance*22, y+dy/distance*22, colors["muted"])
                    r.rect(Rect(x-size-1, y-size-1, size*2+2, size*2+2), colors["background"])
                    if key.startswith("pole."):
                        for a, b in (((x, y-size), (x+size, y)), ((x+size, y), (x, y+size)),
                                     ((x, y+size), (x-size, y)), ((x-size, y), (x, y-size))):
                            r.line(*a, *b, color)
                    else:
                        r.rect(Rect(x-size, y-size, size*2, size*2), color, filled=key == self.selected)
                    if key == self.selected:
                        r.text(LABELS.get(key, key), x+10, y-20, "small", colors["text"])
            status = "계산·미리보기 갱신 중" if self.session.busy else "포즈 키 미저장" if data["dirty"] else "작업본 미저장" if data["file_dirty"] else "저장됨"
            r.text(f"{data['active']} · {data['frame']} / {data['start']}–{data['end']} · {status}", 272, 724,
                   "small", colors["warning"] if self.session.busy or data["dirty"] or data["file_dirty"] else colors["muted"], max_width=640)
            if max(data["errors"].values(), default=0) > .005:
                r.text("목표가 가동 범위를 벗어남", 928, 726, "small", colors["warning"])
        else:
            r.text("모델 준비 중" if self.session else "모델 또는 도형 샘플을 연다.", 416, 400, "body", colors["muted"])
        r.text("손잡이를 끌어 이동", 40, 710, "small", colors["muted"])
        r.text("회전은 오른쪽 X / Y / Z", 40, 730, "small", colors["muted"])
        r.text("팔꿈치·무릎: 관절 위 손잡이로 굽힘 방향 조절", 272, 704, "small", colors["muted"], max_width=640)
        if data:
            r.text("작업본: "+data["work"], 40, 762, "small", colors["muted"], max_width=1168)
        self.draw_choices()

    def close_resources(self):
        if self.session:
            self.session.close()
            self.session = None
        if self.resource:
            self.resource.close()
            self.resource = None
