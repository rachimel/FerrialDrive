"""Asset Tool 화면에서 포즈를 직접 편집한다. Blender 창은 열지 않는다."""

from pathlib import Path
from math import hypot
from uuid import uuid4

from ferrial_drive.assets import AssetDefinition
from ferrial_drive.assets.catalog import read_document
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.ui.components import Rect
from Tools.pose_tool.session import PoseSession
from .widgets import Panel
from .file_panel import FilePanel
from . import pose_controls


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
        self.list_tab, self.part_category = "parts", "body"
        self.part_offset = 0
        self.transform_mode = "translate"
        self.finger, self.finger_joint = "all", "all"
        self.add_field("source", source or "", Rect(40, 78, 684, 30))
        pose_controls.rebuild(self)

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
        entry = self.data.get("parts", {}).get(key) if self.data else None
        if entry and entry["category"] != self.part_category:
            self.part_category, self.part_offset = entry["category"], 0
        if entry and entry["category"] == "fingers":
            name = key.removeprefix("bone:").split(".")[0]
            self.finger = next((prefix for prefix in ("Thumb", "Index", "Middle", "Ring", "Little") if name.startswith(prefix)), "all")
            self.finger_joint = name[len(self.finger):] if self.finger != "all" else "all"
            self.transform_mode = "rotate"
        elif key in ("hand.L", "hand.R"):
            self.finger, self.finger_joint = "all", "all"
        pose_controls.rebuild(self)

    def switch_list(self, value):
        self.list_tab = value
        pose_controls.rebuild(self)

    def choose_category(self, value):
        self.part_category, self.part_offset = value, 0
        if "filter" in self.fields:
            self.fields["filter"].text = ""
        pose_controls.rebuild(self)

    def change_mode(self, value):
        self.transform_mode = value
        pose_controls.rebuild(self)

    def choose_finger(self, value):
        self.finger = value
        pose_controls.rebuild(self)

    def choose_joint(self, value):
        self.finger_joint = value
        pose_controls.rebuild(self)

    def filtered_parts(self):
        text = self.value("filter").casefold() if "filter" in self.fields else ""
        entries = self.data.get("parts", {}) if self.data else {}
        result = [(key, entry["label"]) for key, entry in entries.items()
                  if entry["category"] == self.part_category and (not text or text in (key+entry["label"]).casefold())]
        self.part_offset = min(self.part_offset, max(0, len(result)-16))
        return result

    def axis_step(self, axis, sign):
        if self.transform_mode == "rotate":
            self.rotate(axis, sign)
        else:
            self.send("translate", control=self.selected, axis=axis, amount=float(self.value("distance"))*sign)

    def curl(self, sign):
        entry = self.data.get("parts", {}).get(self.selected, {}) if self.data else {}
        if self.selected not in ("hand.L", "hand.R") and entry.get("category") != "fingers":
            raise ValueError("조절할 손 또는 손가락 파츠를 선택한다.")
        self.send("fingers", side=self.selected[-1], finger=self.finger, joint=self.finger_joint,
                  degrees=float(self.value("degrees"))*sign)

    def align_sword(self):
        self.send("align_sword")
        self.select("object:Sword")

    def handle_event(self, event):
        pico = self.app.pico
        if event.type == getattr(pico, "SDL_KEYDOWN", -1) and event.key == getattr(pico, "SDLK_z", -2) and getattr(event, "mod", 0) & pico.KMOD_CTRL:
            self.attempt(lambda: self.send("undo"))
            return
        super().handle_event(event)

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
            if self.list_tab == "motions":
                self.clip_offset = max(0, min(max(0, len(data["clips"])-18), self.clip_offset-event.y))
            else:
                self.part_offset = max(0, min(max(0, len(self.filtered_parts())-16), self.part_offset-event.y))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            if self.list_tab == "parts" and 40 <= event.x < 252 and 240 <= event.y < 688:
                index = self.part_offset+int((event.y-240)//28)
                parts = self.filtered_parts()
                if index < len(parts):
                    self.select(parts[index][0])
            elif self.list_tab == "motions" and 40 <= event.x < 252 and 164 <= event.y < 704:
                index = self.clip_offset + (event.y-164)//30
                if index < len(data["clips"]):
                    self.attempt(lambda: self.send("clip", name=data["clips"][index]["name"]))
            elif self.preview.contains(event.x, event.y) and not self.session.busy:
                axes = [(hypot(event.x-h["point"][0], event.y-h["point"][1]), h) for h in pose_controls.axis_handles(self)]
                if axes and min(axes, key=lambda pair: pair[0])[0] < 11:
                    handle = min(axes, key=lambda pair: pair[0])[1]
                    if self.transform_mode == "rotate":
                        self.attempt(lambda: self.axis_step(handle["axis"], handle["sign"]))
                    else:
                        self.drag = {"x": event.x, "y": event.y, "world": data["points"][self.selected]["world"],
                                     "scale": data["scale"], "axis": handle, "gesture": uuid4().hex, "moved": False}
                    return
                visible = [(hypot(event.x-x, event.y-y), key) for key, x, y in self.projected_points()]
                if visible and min(visible)[0] < 16:
                    self.select(min(visible)[1])
                    self.drag = {"x": event.x, "y": event.y, "world": data["points"][self.selected]["world"],
                                 "right": data["right"], "up": data["up"], "scale": data["scale"],
                                 "gesture": uuid4().hex, "moved": False}
        elif event.type == pico.SDL_MOUSEMOTION and self.drag:
            drag = self.drag
            dx, dy = event.x-drag["x"], event.y-drag["y"]
            if hypot(dx, dy) < 3:
                return
            drag["moved"] = True
            unit = drag["scale"]/self.preview.height
            if "axis" in drag:
                ax, ay = drag["axis"]["direction"]
                amount = (dx*ax+dy*ay)/(ax*ax+ay*ay)*unit
                target = [drag["world"][i]+(amount if i == "XYZ".index(drag["axis"]["axis"]) else 0) for i in range(3)]
            else:
                target = [drag["world"][i]+drag["right"][i]*dx*unit-drag["up"][i]*dy*unit for i in range(3)]
            command = "bend" if self.selected.startswith("pole.") else "move"
            self.attempt(lambda: self.send(command, control=self.selected, world=target, gesture=drag["gesture"]))
        elif event.type == pico.SDL_MOUSEBUTTONUP and event.button == pico.SDL_BUTTON_LEFT:
            if self.drag and "axis" in self.drag and not self.drag["moved"]:
                handle = self.drag["axis"]
                self.attempt(lambda: self.axis_step(handle["axis"], handle["sign"]))
            self.drag = None

    def projected_points(self):
        for key, point in self.data["points"].items():
            category = self.data.get("parts", {}).get(key, {}).get("category", "body")
            if category != self.part_category and key != self.selected:
                continue
            x, y, z = point["uv"]
            if z > 0 and 0 <= x <= 1 and 0 <= y <= 1:
                yield key, self.preview.x+x*self.preview.width, self.preview.y+(1-y)*self.preview.height

    def draw(self):
        self.title = "포즈 편집" + (" · "+self.loaded_source.name if self.loaded_source else " · 도형 샘플" if self.is_sample else "")
        super().draw()
        r, colors, data = self.app.renderer, self.app.theme["colors"], self.data
        r.rect(self.preview, colors["background"])
        if self.resource:
            self.resource.draw("image", 0, self.preview.x+self.preview.width/2,
                               800-self.preview.y-self.preview.height, scale=1)
        if data:
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
                        label = data.get("parts", {}).get(key, {}).get("label", LABELS.get(key, key))
                        r.text(label, x+10, y-20, "small", colors["text"])
            status = "계산·미리보기 갱신 중" if self.session.busy else "포즈 키 미저장" if data["dirty"] else "작업본 미저장" if data["file_dirty"] else "저장됨"
            r.text(f"{data['active']} · {data['frame']} / {data['start']}–{data['end']} · {status}", 272, 724,
                   "small", colors["warning"] if self.session.busy or data["dirty"] or data["file_dirty"] else colors["muted"], max_width=640)
            if max(data["errors"].values(), default=0) > .005:
                r.text("목표가 가동 범위를 벗어남", 928, 726, "small", colors["warning"])
        else:
            r.text("모델 준비 중" if self.session else "모델 또는 도형 샘플을 연다.", 416, 400, "body", colors["muted"])
        pose_controls.draw(self)
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
