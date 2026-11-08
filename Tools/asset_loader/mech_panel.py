"""메카 레이어·동작·전환 시점 작업본을 편집하는 단일 창 패널."""

from copy import deepcopy

from ferrial_drive.ui.components import Rect
from .mech_plan import (CHECKS, DIRECTIONS, EVENTS, LAYERS, MOTIONS, OCCLUSION, STATUSES,
                        default_plan, load_plan, plan_path, save_plan)
from .production import frame_numbers
from .widgets import Panel


TABS = ("공통 렌더", "출력 단위", "동작·그리기 순서", "전환 시점", "무기 조건·검수")
EVENT_HINTS = ("손이 손잡이를 잡는 시점", "수납 부착점 → 손목", "칼집·장착부를 완전히 벗어남",
               "손목 → 수납 부착점", "빈손으로 전환", "수납 부착점 → 독립 위치·회전")


class MechPanel(Panel):
    title = "메카 · 무기 분리 작업"
    rect = Rect(48, 48, 1184, 704)

    def __init__(self, app):
        super().__init__(app)
        self.path = plan_path(app.asset_id, app.source)
        self.data = deepcopy(app.mech_drafts.get(str(self.path), default_plan(app.asset_id, app.source)))
        self.tab = self.layer = self.motion = self.direction = self.order_index = 0
        self.order_frame = None
        self.side, self.weapon = "left", "sword"
        self.saved = False
        self.labels = []
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
        self.labels.append((label, x, y - 24))
        self.add_field(name, value, Rect(x, y, width, 34))

    def remember(self):
        if self.tab == 0:
            for key in ("camera", "frames", "fps", "width", "height", "scale", "pivot"):
                self.data["render"][key] = self.value(key)
        elif self.tab == 1:
            row = self.data["layers"][LAYERS[self.layer][0]]
            for key in ("objects", "anchor", "empty_hand"):
                if key in self.fields:
                    row[key] = self.value(key)
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

    def rebuild(self):
        self.fields, self.buttons, self.labels, self.focus = {}, [], [], None
        for index, label in enumerate(TABS):
            self.button(label, Rect(72 + index * 226, 112, 214, 34), lambda i=index: self.switch(tab=i))
        self.button("작업본 저장", Rect(1052, 698, 156, 34), self.submit)
        self.button("저장본 불러오기", Rect(852, 698, 188, 34), self.reload)
        self.button("닫기", Rect(72, 698, 100, 34), self.close)
        if self.tab == 0:
            fields = (("camera", "공통 카메라 · Blender 오브젝트", 540),
                      ("frames", "기본 Blender 프레임 · 쉼표 구분", 540),
                      ("fps", "공통 FPS", 230), ("scale", "공통 정사영 범위", 230),
                      ("width", "이미지 너비 (px)", 230), ("height", "이미지 높이 (px)", 230),
                      ("pivot", "공통 기준점 X,Y · bottom-left", 300))
            positions = ((92, 212), (668, 212), (92, 302), (370, 302), (668, 302), (946, 302), (92, 392))
            for (key, label, width), (x, y) in zip(fields, positions):
                self.field(key, label, self.data["render"][key], x, y, width)
            purpose = "전투 로드아웃" if self.data["render"]["purpose"] == "combat" else "장비 선택 대표 자세"
            self.button(f"출력 용도: {purpose}", Rect(668, 392, 508, 34),
                        lambda: self.cycle(self.data["render"], "purpose", ("combat", "preview")))
        elif self.tab == 1:
            for index, (_, label, _) in enumerate(LAYERS):
                self.button(label, Rect(92, 184 + index * 44, 284, 34), lambda i=index: self.switch(layer=i))
            row = self.data["layers"][LAYERS[self.layer][0]]
            self.field("objects", "출력에 포함할 독립 오브젝트 · 쉼표 구분", row["objects"], 420, 226, 756)
            self.field("anchor", "부착 기준 · 본/오브젝트 이름", row["anchor"], 420, 322, 756)
            if LAYERS[self.layer][0] in ("left_hand", "right_hand"):
                self.field("empty_hand", "빈손 출력 오브젝트 · 필수 준비", row["empty_hand"], 420, 418, 756)
        elif self.tab in (2, 3):
            self.button("◀ 동작", Rect(92, 172, 108, 34), lambda: self.switch(motion=(self.motion - 1) % len(MOTIONS)))
            self.button("다음 동작 ▶", Rect(580, 172, 140, 34), lambda: self.switch(motion=(self.motion + 1) % len(MOTIONS)))
            if self.tab == 2:
                for index, (key, label) in enumerate((("clip", "클립 이름"), ("frames", "Blender 프레임 · 쉼표 구분 / 비우면 공통 프레임"),
                                                     ("reuse", "재사용할 동작 · 비우면 별도 제작"), ("notes", "팔·손목·몸통 동작 메모"))):
                    self.field(key, label, self.current_motion[key], 92, 252 + index * 86, 604)
                direction = DIRECTIONS[self.direction]
                self.button(f"방향: {direction} ▶", Rect(760, 172, 220, 34),
                            lambda: self.switch(direction=(self.direction + 1) % len(DIRECTIONS)))
                for index, key in enumerate(self.current_order):
                    self.button(f"{index + 1}. {dict((k, v) for k, v, _ in LAYERS)[key]}",
                                Rect(760, 224 + index * 34, 416, 30), lambda i=index: self.select_order(i))
                self.button("뒤로 ↑", Rect(760, 504, 130, 34), lambda: self.move_order(-1))
                self.button("앞으로 ↓", Rect(902, 504, 130, 34), lambda: self.move_order(1))
                self.button(self.current_motion["occlusion"][direction], Rect(1044, 504, 132, 34),
                            lambda: self.cycle(self.current_motion["occlusion"], direction, OCCLUSION))
                self.field("override_frame", "예외 편집할 Blender 프레임", self.order_frame or "", 760, 574, 170)
                self.button("프레임 순서 편집", Rect(946, 574, 230, 34), self.add_override)
                self.button("기본 순서로 돌아가기", Rect(760, 620, 238, 30), self.base_order)
                self.button("이 예외 삭제", Rect(1010, 620, 166, 30), self.clear_override)
            else:
                self.button("왼손" if self.side == "left" else "오른손", Rect(760, 172, 180, 34),
                            lambda: self.switch(side="right" if self.side == "left" else "left"))
                self.button("플라즈마 소드" if self.weapon == "sword" else "제식 기관단총", Rect(956, 172, 220, 34),
                            lambda: self.switch(weapon="gun" if self.weapon == "sword" else "sword"))
                events = {row["kind"]: row["frame"] for row in self.current_motion["events"]
                          if (row["side"], row["weapon"]) == (self.side, self.weapon)}
                for index, (key, label) in enumerate(EVENTS):
                    self.field(key, label, events.get(key, ""), 92, 262 + index * 64, 180)
        else:
            for index, (key, label) in enumerate(CHECKS):
                self.button(self.data["checks"][key], Rect(92, 184 + index * 46, 120, 32),
                            lambda k=key: self.cycle(self.data["checks"], k, STATUSES))
            for index, (key, label) in enumerate((("sword_reset_frame", "검 길이 복귀 시작 · 수납 동작 프레임 / 미정은 빈칸"),
                                                 ("gun_storage", "기관단총 수납 위치"), ("deferred", "미확정 사항"), ("notes", "검수 메모"))):
                self.field(key, label, self.data[key], 760, 222 + index * 112, 416)

    def select_order(self, index):
        self.order_index = index

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
        r.rect(Rect(72 + self.tab * 226, 146, 214, 3), c["accent"])
        r.text("작업 설정 편집 · Blender 분리 출력 / 연속 동작 / 게임 합성은 미구현", 420, 72, "small", c["warning"])
        for label, x, y in self.labels:
            r.text(label, x, y, "small", c["muted"])
        if self.tab == 0:
            lines = ("모든 출력 단위는 같은 카메라·배율·방향·프레임·크기·기준점 사용",
                     "무기를 파지한 하나의 장면에서 출력 · 레이어별 중앙 맞춤/자동 배율 금지",
                     "동작별 프레임은 동작 탭에서 지정하며, 해당 동작의 모든 레이어에 공통 적용",
                     "전투: 사용할 로드아웃의 필요한 모션부터 준비 · 장비 미리보기: 대표 자세 별도 출력")
            for index, line in enumerate(lines):
                r.text(line, 92, 478 + index * 38, "small", c["text"])
        elif self.tab == 1:
            r.rect(Rect(88, 184 + self.layer * 44, 3, 34), c["accent"])
            for index, line in enumerate(("본체는 손목까지 포함 · 좌우 손과 빈손은 별도 출력",
                                          "손·검·총·칼집은 독립 오브젝트 유지",
                                          "손+무기는 출력할 때 묶음 · 영구 메시 병합 금지",
                                          "분리 무기는 독립 위치·회전 · 칼집은 몸체에 유지")):
                r.text(line, 420, 490 + index * 36, "small", c["text"])
        elif self.tab in (2, 3):
            r.text(MOTIONS[self.motion][1], 220, 180, "body", c["text"])
            if self.tab == 2:
                r.rect(Rect(754, 224 + self.order_index * 34, 3, 30), c["accent"])
                r.text("위에서 아래로 뒤 → 앞 · 좌우 손 독립", 760, 152, "small", c["muted"])
                r.text("순서만으로 해결 못 하는 가림은 별도 결정", 92, 596, "small", c["warning"])
                rows = [str(row["frame"]) for row in self.current_motion["overrides"]
                        if row["direction"] == DIRECTIONS[self.direction]]
                r.text("프레임 예외: " + (", ".join(rows) or "없음"), 92, 626, "small", c["muted"], max_width=604)
                r.text("편집: " + (f"프레임 {self.order_frame}" if self.order_frame is not None else "기본 순서"),
                       92, 564, "small", c["accent"])
            else:
                r.text("Blender 원본 프레임 번호 · 빈칸은 미지정", 92, 218, "small", c["muted"])
                r.text("동작 프레임: " + self.motion_frames, 540, 218, "small", c["muted"], max_width=630)
                for index, line in enumerate(EVENT_HINTS):
                    r.text(line, 320, 270 + index * 64, "small", c["text"])
                r.text("위치·회전 연속성과 무기 중복/누락은 실제 동작으로 검수", 320, 640, "small", c["warning"])
        elif self.tab == 4:
            for index, (_, label) in enumerate(CHECKS):
                r.text(label, 232, 191 + index * 46, "small", c["text"], max_width=500)
            r.text("확인 상태는 사용자가 실제 검수 후 지정", 92, 588, "small", c["warning"])
        if not self.error:
            r.text("작업본 저장 완료" if self.saved else "작업본 편집 · 저장 전 검증 · 닫아도 이번 실행 중 입력 유지",
                   220, 708, "small", c["accent"], max_width=610)
