"""메카 레이어·동작·전환 시점 작업본을 편집하는 단일 창 패널."""

from copy import deepcopy

from ferrial_drive.ui.components import Rect
from .mech_plan import (CHECKS, DIRECTIONS, EVENTS, LAYERS, MOTIONS, OCCLUSION, STATUSES,
                        default_plan, load_plan, plan_path, save_plan)
from .production import frame_numbers
from .widgets import Panel


TABS = ("공통 렌더", "출력 단위", "동작·순서", "전환 시점", "무기 조건·검수")
EVENT_HINTS = ("손이 손잡이를 잡는 시점", "수납 부착점 → 손목", "칼집·장착부를 완전히 벗어남",
               "손목 → 수납 부착점", "빈손으로 전환", "수납 부착점 → 독립 위치·회전")


class MechPanel(Panel):
    title = "메카 설정"
    rect = Rect(16, 16, 1248, 768)
    button_surface = "input"
    error_x, error_y = 264, 706
    error_width = 976

    def __init__(self, app):
        super().__init__(app)
        self.path = plan_path(app.asset_id, app.source)
        self.data = deepcopy(app.mech_drafts.get(str(self.path), default_plan(app.asset_id, app.source)))
        self.tab = self.layer = self.motion = self.direction = self.order_index = 0
        self.order_frame = None
        self.side, self.weapon = "left", "sword"
        self.saved = False
        self.labels = []
        self.advanced = self.help_open = self.frame_options = False
        self.rebuild()
        if str(self.path) not in app.mech_drafts and self.path.exists():
            self.attempt(self.reload)

    @property
    def current_motion(self):
        return self.data["motions"][MOTIONS[self.motion][0]]

    @property
    def motion_frames(self):
        return self.current_motion["frames"] or self.data["render"]["frames"]

    @property
    def current_order(self):
        direction = DIRECTIONS[self.direction]
        if self.order_frame is not None:
            return next(row["order"] for row in self.current_motion["overrides"]
                        if (row["direction"], row["frame"]) == (direction, self.order_frame))
        return self.current_motion["orders"][direction]

    def field(self, name, label, value, x, y, width=300):
        self.labels.append((label, x, y - 20))
        self.add_field(name, value, Rect(x, y, width, 30))

    def remember(self):
        if self.tab == 0:
            for key in ("camera", "frames", "fps", "width", "height", "scale", "pivot"):
                if key in self.fields:
                    self.data["render"][key] = self.value(key)
        elif self.tab == 1:
            for layer, _, _ in LAYERS:
                for key in ("objects", "anchor", "empty_hand"):
                    name = f"{layer}.{key}"
                    if name in self.fields:
                        self.data["layers"][layer][key] = self.value(name)
        elif self.tab == 2:
            for key in ("clip", "frames", "reuse", "notes"):
                self.current_motion[key] = self.value(key)
        elif self.tab == 3:
            # 빈칸은 미지정이며 다른 손·무기의 이벤트는 유지한다.
            events = [row for row in self.current_motion["events"]
                      if (row["side"], row["weapon"]) != (self.side, self.weapon)]
            for key, _ in EVENTS:
                text = self.value(key)
                if text:
                    try:
                        frame = int(text)
                    except ValueError as error:
                        raise ValueError("전환 프레임은 정수로 지정한다.") from error
                    if frame not in frame_numbers(self.motion_frames):
                        raise ValueError("전환 시점은 선택 동작의 Blender 프레임에서 지정한다.")
                    events.append({"kind": key, "side": self.side, "weapon": self.weapon, "frame": frame})
            self.current_motion["events"] = events
        elif self.tab == 4:
            for key in ("sword_reset_frame", "gun_storage", "deferred", "notes"):
                self.data[key] = self.value(key)

    def switch(self, *, tab=None, layer=None, motion=None, direction=None, side=None, weapon=None):
        self.remember()
        for key, value in locals().copy().items():
            if key in ("tab", "layer", "motion", "direction", "side", "weapon") and value is not None:
                setattr(self, key, value)
        if motion is not None or direction is not None:
            self.order_frame = None
        self.saved = False
        self.rebuild()

    def cycle(self, mapping, key, choices):
        self.remember()
        mapping[key] = choices[(choices.index(mapping[key]) + 1) % len(choices)]
        self.saved = False
        self.rebuild()

    def toggle(self, name):
        self.remember()
        setattr(self, name, not getattr(self, name))
        self.rebuild()

    def choose(self, mapping, key, value):
        self.remember()
        mapping[key], self.saved = value, False
        self.rebuild()

    def rebuild(self):
        self.fields, self.buttons, self.labels, self.focus = {}, [], [], None
        self.button_styles, self.button_markers, self.choice_popup = {}, {}, None
        for index, label in enumerate(TABS):
            y = (116, 154, 240, 278, 364)[index]
            self.button(label, Rect(32, y, 192, 32), lambda i=index: self.switch(tab=i),
                        style="selected" if index == self.tab else "input")
        self.button("저장", Rect(1144, 736, 96, 32), self.submit, style="button")
        self.button("저장본 불러오기", Rect(964, 736, 168, 32), self.reload)
        self.button("미리보기로", Rect(32, 736, 192, 32), self.close)
        self.disclosure("도움말", Rect(32, 684, 192, 30), lambda: self.toggle("help_open"), expanded=self.help_open)
        if self.tab == 0:
            for key, label, x, y, width in (("camera", "카메라 오브젝트", 264, 150, 460),
                    ("frames", "기본 프레임 · 쉼표 구분", 756, 150, 460),
                    ("width", "너비 (px)", 264, 254, 210), ("height", "높이 (px)", 494, 254, 210),
                    ("fps", "FPS", 724, 254, 144)):
                self.field(key, label, self.data["render"][key], x, y, width)
            purpose = "전투 로드아웃" if self.data["render"]["purpose"] == "combat" else "장비 선택 대표 자세"
            self.choice(purpose, [("combat", "전투 로드아웃"), ("preview", "장비 선택 대표 자세")], Rect(900, 254, 316, 30),
                        lambda value: self.choose(self.data["render"], "purpose", value))
            self.disclosure("세부 설정", Rect(264, 316, 172, 30), lambda: self.toggle("advanced"), expanded=self.advanced)
            if self.advanced:
                self.field("scale", "정사영 범위", self.data["render"]["scale"], 264, 390, 300)
                self.field("pivot", "기준점 X,Y · bottom-left", self.data["render"]["pivot"], 596, 390, 300)
        elif self.tab == 1:
            for index, (layer, _, _) in enumerate(LAYERS):
                y, row = 150 + index * 46, self.data["layers"][layer]
                self.add_field(f"{layer}.objects", row["objects"], Rect(432, y, 348, 30))
                self.add_field(f"{layer}.anchor", row["anchor"], Rect(796, y, 188, 30))
                if layer in ("left_hand", "right_hand"):
                    self.add_field(f"{layer}.empty_hand", row["empty_hand"], Rect(1000, y, 216, 30))
        elif self.tab in (2, 3):
            self.choice("동작: " + MOTIONS[self.motion][1], [(i, label) for i, (_, label) in enumerate(MOTIONS)],
                        Rect(264, 98, 320, 32), lambda value: self.switch(motion=value))
            if self.tab == 2:
                for index, (key, label) in enumerate((("clip", "클립 이름"), ("frames", "프레임 · 비우면 공통 값"),
                                                     ("reuse", "재사용 동작 · 비우면 별도 제작"), ("notes", "동작 메모"))):
                    self.field(key, label, self.current_motion[key], 264, 188 + index * 64, 432)
                direction = DIRECTIONS[self.direction]
                self.choice("방향: " + direction, [(i, value) for i, value in enumerate(DIRECTIONS)], Rect(744, 98, 144, 32),
                            lambda value: self.switch(direction=value))
                self.choice("가림: " + self.current_motion["occlusion"][direction], [(value, value) for value in OCCLUSION],
                            Rect(900, 98, 316, 32), lambda value: self.choose(self.current_motion["occlusion"], direction, value))
                for index, key in enumerate(self.current_order):
                    self.button(f"{index + 1}. {dict((k, v) for k, v, _ in LAYERS)[key]}",
                                Rect(744, 188 + index * 32, 472, 30), lambda i=index: self.select_order(i),
                                style="selected" if index == self.order_index else "input")
                self.button("↑ 뒤로", Rect(744, 454, 112, 30), lambda: self.move_order(-1))
                self.button("↓ 앞으로", Rect(868, 454, 112, 30), lambda: self.move_order(1))
                self.disclosure("프레임별 순서", Rect(744, 504, 224, 30),
                                lambda: self.toggle("frame_options"), expanded=self.frame_options)
                if self.frame_options:
                    self.field("override_frame", "Blender 프레임", self.order_frame if self.order_frame is not None else "", 744, 568, 144)
                    self.button("이 프레임 편집", Rect(900, 568, 164, 30), self.add_override)
                    self.button("기본 순서", Rect(1076, 568, 140, 30), self.base_order)
                    if self.order_frame is not None:
                        self.button("현재 예외 삭제", Rect(744, 610, 180, 30), self.clear_override)
            else:
                for side, label, x in (("left", "왼손", 616), ("right", "오른손", 708)):
                    self.button(label, Rect(x, 98, 84, 32), lambda value=side: self.switch(side=value),
                                style="selected" if self.side == side else "input")
                self.choice("플라즈마 소드" if self.weapon == "sword" else "제식 기관단총",
                            [("sword", "플라즈마 소드"), ("gun", "제식 기관단총")], Rect(824, 98, 392, 32),
                            lambda value: self.switch(weapon=value))
                events = {row["kind"]: row["frame"] for row in self.current_motion["events"]
                          if (row["side"], row["weapon"]) == (self.side, self.weapon)}
                for index, (key, _) in enumerate(EVENTS):
                    self.add_field(key, events.get(key, ""), Rect(504, 188 + index * 52, 112, 30))
        else:
            for index, (key, label) in enumerate(CHECKS):
                self.choice(self.data["checks"][key], [(value, value) for value in STATUSES], Rect(264, 150 + index * 42, 96, 30),
                            lambda value, k=key: self.choose(self.data["checks"], k, value))
            for index, (key, label) in enumerate((("sword_reset_frame", "검 길이 복귀 · 수납 프레임 / 빈칸은 미정"),
                                                 ("gun_storage", "총 수납 위치"), ("deferred", "미확정 사항"), ("notes", "검수 메모"))):
                self.field(key, label, self.data[key], 904, 150 + index * 80, 312)

    def select_order(self, index):
        self.order_index = index
        self.remember()
        self.rebuild()

    def move_order(self, delta):
        self.remember()
        order = self.current_order
        target = max(0, min(len(order) - 1, self.order_index + delta))
        order.insert(target, order.pop(self.order_index))
        self.order_index = target
        self.saved = False
        self.rebuild()

    def add_override(self):
        frame = int(self.value("override_frame"))
        self.remember()
        if frame not in frame_numbers(self.motion_frames):
            raise ValueError("선택 동작에 포함된 Blender 프레임을 지정한다.")
        direction = DIRECTIONS[self.direction]
        if not any((row["direction"], row["frame"]) == (direction, frame) for row in self.current_motion["overrides"]):
            self.current_motion["overrides"].append({"direction": direction, "frame": frame,
                                                     "order": list(self.current_motion["orders"][direction])})
        self.order_frame = frame
        self.saved = False
        self.rebuild()

    def base_order(self):
        self.remember()
        self.order_frame = None
        self.rebuild()

    def clear_override(self):
        self.remember()
        self.current_motion["overrides"] = [row for row in self.current_motion["overrides"]
                                            if (row["direction"], row["frame"]) != (DIRECTIONS[self.direction], self.order_frame)]
        self.order_frame = None
        self.saved = False
        self.rebuild()

    def reload(self):
        candidate = load_plan(self.path, asset_id=self.app.asset_id, source=self.app.source)
        self.data, self.saved = candidate, True
        self.order_frame = None
        self.rebuild()

    def submit(self):
        self.remember()
        save_plan(self.path, self.data)
        self.app.mech_drafts[str(self.path)] = deepcopy(self.data)
        self.saved = True

    def close(self):
        # 미완성 작업도 실행 중에는 복원하며 파일 저장의 검증과 구분한다.
        try:
            self.remember()
        except ValueError as problem:
            self.error = str(problem)
            return
        self.app.mech_drafts[str(self.path)] = deepcopy(self.data)
        super().close()

    def handle_event(self, event):
        if self.focus is not None and event.type in (self.app.pico.SDL_TEXTINPUT, self.app.pico.SDL_KEYDOWN):
            self.saved = False
        super().handle_event(event)

    def draw(self):
        super().draw()
        r, c = self.app.renderer, self.app.theme["colors"]
        r.line(240, 80, 240, 768, c["line"])
        r.text(TABS[self.tab], 264, 36, "body", c["text"])
        r.text(self.app.asset_id, 620, 40, "small", c["muted"], max_width=540)
        for label, y in (("모델·출력", 92), ("애니메이션", 216), ("확인", 340)):
            r.text(label, 40, y, "small", c["muted"])
        for label, x, y in self.labels:
            r.text(label, x, y, "small", c["muted"])
        if self.tab == 0:
            r.text("장면·프레임", 264, 96, "body", c["text"])
            r.text("이미지·재생", 264, 200, "body", c["text"])
            r.text("출력 용도", 900, 234, "small", c["muted"])
            r.text("모든 레이어에 같은 카메라·크기·기준점 적용", 264, 452, "small", c["muted"])
        elif self.tab == 1:
            for label, x in (("출력 단위", 264), ("오브젝트 · 쉼표 구분", 432), ("부착 기준", 796), ("빈손 오브젝트", 1000)):
                r.text(label, x, 118, "small", c["muted"])
            for index, (_, label, _) in enumerate(LAYERS):
                r.text(label, 264, 158 + index * 46, "small", c["text"], max_width=156)
            r.text("손·무기·칼집은 독립 유지 · 손+무기는 출력 시 묶음", 264, 548, "small", c["muted"])
        elif self.tab in (2, 3):
            if self.tab == 2:
                r.text("그리기 순서 · 위에서 아래로 뒤 → 앞", 744, 160, "small", c["muted"])
                rows = [str(row["frame"]) for row in self.current_motion["overrides"]
                        if row["direction"] == DIRECTIONS[self.direction]]
                r.text("프레임 예외: " + (", ".join(rows) or "없음"), 264, 504, "small", c["muted"], max_width=432)
                r.text("편집: " + (f"프레임 {self.order_frame}" if self.order_frame is not None else "기본 순서"),
                       1000, 462, "small", c["accent"])
            else:
                for label, x in (("전환", 264), ("프레임", 504), ("부착·상태 변화", 648)):
                    r.text(label, x, 160, "small", c["muted"])
                for index, ((_, label), hint) in enumerate(zip(EVENTS, EVENT_HINTS)):
                    r.text(label, 264, 196 + index * 52, "small", c["text"])
                    r.text(hint, 648, 196 + index * 52, "small", c["muted"])
                r.text("사용 프레임: " + self.motion_frames + " · 빈칸은 미지정", 264, 536, "small", c["muted"], max_width=950)
        elif self.tab == 4:
            r.text("검수 상태", 264, 96, "body", c["text"])
            r.text("무기 설정", 904, 96, "body", c["text"])
            for index, (_, label) in enumerate(CHECKS):
                r.text(label, 376, 158 + index * 42, "small", c["text"], max_width=504)
            r.text("실제 결과를 검수한 뒤 상태 지정", 264, 526, "small", c["muted"])
        if self.help_open:
            explanations = (
                ("한 장면에서 모든 레이어를 출력한다. 레이어별 자동 맞춤은 사용하지 않는다.",
                 "세부 설정에서 정사영 범위와 기준점을 조정한다. 동작별 프레임은 비우면 공통 값을 사용한다."),
                ("본체는 손목까지 포함한다. 좌우 손과 빈손을 별도로 지정한다.",
                 "칼집은 본체에 남으며 분리된 무기는 독립 위치·회전으로 표시한다."),
                ("기본 순서와 프레임별 예외는 독립적이다. 프레임별 순서를 펼쳐 특정 프레임을 편집한다.",
                 "몸 앞뒤를 동시에 가로지르는 무기는 가림 방식에서 추가 분할 또는 가림 처리를 지정한다."),
                ("재생 인덱스가 아닌 Blender 원본 프레임을 입력한다.",
                 "부착 전후의 위치·회전 연속성과 무기 중복/누락은 실제 동작에서 확인한다."),
                ("검 길이 복귀 시작은 수납 동작에 포함된 프레임으로 지정한다.",
                 "손·팔 수납과 에임 보정기 접기는 미정이다. 검수 상태는 자동 검증 결과가 아니다."),
            )
            r.rect(Rect(264, 654, 952, 44), c["input"])
            for index, line in enumerate(explanations[self.tab]):
                r.text(line, 274, 660 + index * 18, "small", c["muted"], max_width=930)
        r.line(264, 726, 1240, 726, c["line"])
        if not self.error:
            r.text("저장 완료" if self.saved else "설정 작업본 · 분리 출력 미연결", 264, 746, "small", c["muted"])
        self.draw_choices()
