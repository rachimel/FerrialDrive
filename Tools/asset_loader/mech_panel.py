"""메카 레이어·동작·전환 시점 작업본을 편집하는 단일 창 패널."""

from copy import deepcopy

from ferrial_drive.ui.components import Rect
from .mech_plan import (CHECKS, DIRECTIONS, ENERGY_MODES, EVENTS, MOTIONS, OCCLUSION, STATUSES,
                        default_plan, load_plan, plan_path, save_plan, with_energy_defaults)
from .production import frame_numbers
from .widgets import Panel
from .mech_presets import ORDER_PRESETS, apply_all_directions, apply_mapping, apply_order_preset, mapping_options
from .mech_preview import draw_preview
from .part_model import remove_part, remove_state


TABS = ("공통 렌더", "출력 파츠", "동작·순서", "전환 시점", "무기 조건·검수", "조립 미리보기")
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
        self.data = with_energy_defaults(app.mech_drafts.get(str(self.path), default_plan(app.asset_id, app.source)))
        self.tab = self.layer = self.motion = self.direction = self.order_index = 0
        self.order_frame = None
        self.side, self.weapon = "left", "sword"
        self.saved = False
        self.labels = []
        self.advanced = self.help_open = self.frame_options = False
        self.layer_view = "color"
        self.part_key, self.part_state = "body", "base"
        self.part_offset = self.order_offset = 0
        self.preview_resource, self.preview_time = None, 0.0
        self.preview_is_sample = False
        self.sample_paths = None
        self.preview_playing = True
        self.rebuild()
        if str(self.path) not in app.mech_drafts and self.path.exists():
            self.attempt(self.reload)
        mech = getattr(app.handle.resource, "mech", None)
        if mech and not any(row["sheet"] for row in self.data["layers"].values()):
            from .mech_export import import_mech
            import_mech(self.data, mech)
            first = next(iter(mech.clips)).split("/", 1)[0]
            self.motion = next((i for i, (key, _) in enumerate(MOTIONS) if key == first), 0)
            self.tab = 5
            self.rebuild()
        if any(row["sheet"] for row in self.data["layers"].values()):
            self.attempt(self.refresh_preview)

    @property
    def motion_key(self):
        return MOTIONS[self.motion][0]

    @property
    def direction_name(self):
        return DIRECTIONS[self.direction]

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

    @property
    def current_part(self):
        return self.data["layers"][self.part_key]

    @property
    def current_variant(self):
        return self.current_part if self.part_state == "base" else self.current_part["states"][self.part_state]

    def field(self, name, label, value, x, y, width=300):
        self.labels.append((label, x, y - 20))
        self.add_field(name, value, Rect(x, y, width, 30))

    def remember(self):
        if self.tab == 0:
            for key in ("camera", "frames", "fps", "width", "height", "scale", "pivot"):
                if key in self.fields:
                    self.data["render"][key] = self.value(key)
        elif self.tab == 1:
            for field in ("anchor", "empty_hand"):
                name = f"{self.part_key}.{field}"
                if name in self.fields:
                    self.current_part[field] = self.value(name)
            for field in ("objects", "clip", "sheet", "energy_sheet"):
                name = f"{self.part_key}.{field}"
                if name in self.fields:
                    self.current_variant[field] = self.value(name)
            if "part_name" in self.fields:
                self.current_part["name"] = self.value("part_name")
            if "state_name" in self.fields:
                self.current_variant["name"] = self.value("state_name")
            name = f"{self.part_key}.energy_source"
            if name in self.fields:
                self.current_variant["energy_mask"]["source"] = self.value(name)
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
        if layer is not None:
            self.part_key = list(self.data["layers"])[layer]
        if layer is not None or motion is not None:
            self.part_state = self.current_motion["part_states"].get(self.part_key, self.current_part["default_state"])
        self.saved = False
        self.rebuild()
        if self.preview_is_sample and motion is not None:
            self.load_sample_preview()

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
        if key == "enabled" and self.preview_resource and not self.preview_is_sample:
            self.attempt(self.refresh_preview)

    def select_layer_view(self, value):
        self.remember()
        self.layer_view = value
        self.rebuild()

    def select_part(self, key):
        self.remember()
        self.part_key = key
        self.part_state = self.current_motion["part_states"].get(key, self.current_part["default_state"])
        self.rebuild()

    def select_state(self, state):
        self.remember()
        self.part_state = state
        self.current_motion["part_states"][self.part_key] = state
        self.saved = False
        self.rebuild()

    def part_dialog(self, *, duplicate=False, state=False):
        from .part_panel import PartPanel
        self.remember()
        self.app.set_panel(PartPanel(self, duplicate=duplicate, state=state))

    def delete_part(self):
        self.remember()
        remove_part(self.data, self.part_key)
        self.part_key, self.part_state, self.saved = "body", "base", False
        self.order_index = min(self.order_index, len(self.current_order) - 1)
        self.rebuild()

    def delete_state(self):
        self.remember()
        remove_state(self.data, self.part_key, self.part_state)
        self.part_state, self.saved = "base", False
        self.rebuild()

    def default_state(self):
        self.remember()
        self.current_part["default_state"] = self.part_state
        self.saved = False
        self.rebuild()

    def use_mapping(self, preset):
        self.remember()
        apply_mapping(self.data, preset)
        self.saved = False
        self.rebuild()

    def save_mapping(self):
        from .mech_preset_panel import MechPresetPanel
        self.remember()
        self.app.set_panel(MechPresetPanel(self))

    def order_preset(self, preset):
        self.remember()
        apply_order_preset(self.data, self.motion_key, self.direction_name, preset, self.order_frame)
        self.saved = False
        self.rebuild()

    def all_directions(self):
        self.remember()
        apply_all_directions(self.data, self.motion_key, self.direction_name, self.order_frame)
        self.saved = False
        self.rebuild()

    def browse_sheet(self, layer, key):
        from .file_panel import FilePanel
        self.remember()
        target = self.current_variant
        def selected(path):
            target[key] = str(path)
            self.saved = False
            self.rebuild()
        self.app.set_panel(FilePanel(self.app, selected, extensions={".json"},
            initial=target[key] or self.app.source.parent, parent=self))

    def refresh_preview(self):
        from ferrial_drive.assets.pico_assets import PicoAssetBackend
        from .mech_export import mech_document
        self.remember()
        candidate = PicoAssetBackend(self.app.filtering).load(mech_document(self.data))
        if self.preview_resource:
            self.preview_resource.close()
        self.preview_resource, self.preview_time = candidate, 0.0
        self.preview_is_sample = False

    def sample_preview(self):
        from samples.mech_asset.make_sample import write_sample
        from .production import ROOT
        self.remember()
        self.sample_paths = write_sample(ROOT / "output/asset_loader/mech_sample")
        self.load_sample_preview()

    def load_sample_preview(self):
        from ferrial_drive.assets.pico_assets import PicoAssetBackend
        from .mech_export import mech_document
        data = default_plan(self.app.asset_id, self.app.source)
        for layer, row in self.sample_paths.items():
            data["layers"][layer].update(row)
        for motion in data["motions"].values():
            motion["clip"] = ""
        data["motions"][self.motion_key]["clip"] = "equipped_idle"
        candidate = PicoAssetBackend(self.app.filtering).load(mech_document(data))
        if self.preview_resource:
            self.preview_resource.close()
        self.preview_resource, self.preview_time = candidate, 0.0
        self.preview_is_sample = True

    def export(self):
        from .mech_export import copy_mech
        from .library import asset_directory
        self.refresh_preview()
        result = copy_mech(self.preview_resource.mech, asset_directory(self.app.asset_id))
        if not self.app.open_source(result, kind="mech", asset_id=self.app.asset_id):
            raise ValueError(self.app.message)
        self.app.message = f"분리 시트 내보내기 완료: {result}"
        self.close()

    def rebuild(self):
        if self.part_key not in self.data["layers"]:
            self.part_key = "body"
        if self.part_state != "base" and self.part_state not in self.current_part["states"]:
            self.part_state = self.current_part["default_state"]
        self.fields, self.buttons, self.labels, self.focus = {}, [], [], None
        self.button_styles, self.button_markers, self.choice_popup = {}, {}, None
        for index, label in enumerate(TABS):
            y = (116, 154, 240, 278, 404, 316)[index]
            self.button(label, Rect(32, y, 192, 32), lambda i=index: self.switch(tab=i),
                        style="selected" if index == self.tab else "input")
        self.button("저장", Rect(1144, 736, 96, 32), self.submit, style="button")
        self.button("저장본 불러오기", Rect(964, 736, 168, 32), self.reload)
        self.button("분리 시트 내보내기", Rect(772, 736, 180, 32), self.export)
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
            self.button("추가", Rect(264, 92, 88, 30), self.part_dialog)
            self.button("복제", Rect(360, 92, 76, 30), lambda: self.part_dialog(duplicate=True))
            self.button("삭제", Rect(444, 92, 76, 30), self.delete_part)
            self.choice("구성 프리셋", mapping_options(), Rect(744, 92, 292, 30), self.use_mapping)
            self.button("프리셋 저장", Rect(1048, 92, 168, 30), self.save_mapping)
            keys = list(self.data["layers"])
            self.part_offset = min(self.part_offset, max(0, len(keys) - 15))
            for index, key in enumerate(keys[self.part_offset:self.part_offset + 15]):
                self.button(self.data["layers"][key]["name"], Rect(264, 150 + index * 34, 252, 32),
                            lambda value=key: self.select_part(value), style="selected" if key == self.part_key else "input")
            for value, label, x in (("color", "부착·오브젝트", 536), ("energy", "에너지 마스크", 768), ("sheets", "분리 시트", 1000)):
                self.button(label, Rect(x, 138, 216, 30), lambda selected=value: self.select_layer_view(selected),
                            style="selected" if self.layer_view == value else "input")
            part, variant, key = self.current_part, self.current_variant, self.part_key
            self.field("part_name", "파츠 이름", part["name"], 536, 210, 400)
            self.button("표시 ON" if part["enabled"] else "표시 OFF", Rect(948, 210, 268, 30),
                        lambda: self.choose(part, "enabled", not part["enabled"]))
            options = [("base", "기본")] + [(state, row["name"]) for state, row in part["states"].items()]
            label = dict(options)[self.part_state]
            self.choice("상태: " + label, options, Rect(536, 284, 320, 30), self.select_state)
            self.button("상태 추가", Rect(868, 284, 160, 30), lambda: self.part_dialog(state=True))
            self.button("상태 삭제", Rect(1040, 284, 176, 30), self.delete_state)
            if self.part_state != "base":
                self.field("state_name", "상태 이름", variant["name"], 536, 366, 400)
                self.button("상태 표시 ON" if variant["enabled"] else "상태 표시 OFF", Rect(948, 366, 268, 30),
                            lambda: self.choose(variant, "enabled", not variant["enabled"]))
            if self.layer_view == "color":
                self.field(f"{key}.anchor", "공통 부착점", part["anchor"], 536, 430, 680)
                self.field(f"{key}.objects", "오브젝트 · 쉼표 구분", variant["objects"], 536, 494, 680)
                self.field(f"{key}.empty_hand", "대체 오브젝트 · 빈손 등 (선택)", part["empty_hand"], 536, 558, 680)
            elif self.layer_view == "energy":
                mask = variant["energy_mask"]
                self.choice(dict(ENERGY_MODES)[mask["mode"]], ENERGY_MODES, Rect(536, 430, 320, 30),
                            lambda value: self.choose(mask, "mode", value))
                self.field(f"{key}.energy_source", "마스크 입력 · 재질/노드 또는 오브젝트", mask["source"], 536, 494, 680)
            else:
                for field, label, y in (("sheet", "색상 시트 JSON", 430), ("energy_sheet", "에너지 마스크 시트 JSON", 494)):
                    self.field(f"{key}.{field}", label, variant[field], 536, y, 624)
                    self.button("…", Rect(1172, y, 44, 30), lambda value=field: self.browse_sheet(key, value))
                self.field(f"{key}.clip", "상태 클립 접두사 · 비우면 본체 동작과 동일", variant["clip"], 536, 558, 680)
            self.button("이 상태를 기본으로", Rect(536, 620, 216, 30), self.default_state)
        elif self.tab in (2, 3, 5):
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
                self.choice("순서 프리셋", ORDER_PRESETS, Rect(744, 142, 224, 30), self.order_preset)
                self.button("현재 동작 전체 방향 적용", Rect(980, 142, 236, 30), self.all_directions)
                self.order_offset = min(self.order_offset, max(0, len(self.current_order) - 10))
                for slot, key in enumerate(self.current_order[self.order_offset:self.order_offset + 10]):
                    index = self.order_offset + slot
                    self.button(f"{index + 1}. {self.data['layers'][key]['name']}",
                                Rect(744, 196 + slot * 24, 472, 23), lambda i=index: self.select_order(i),
                                style="selected" if index == self.order_index else "input")
                self.button("↑ 뒤로", Rect(744, 454, 112, 30), lambda: self.move_order(-1))
                self.button("↓ 앞으로", Rect(868, 454, 112, 30), lambda: self.move_order(1))
                self.button("도형 예제", Rect(568, 434, 128, 30), self.sample_preview)
                self.disclosure("프레임별 순서", Rect(744, 504, 224, 30),
                                lambda: self.toggle("frame_options"), expanded=self.frame_options)
                if self.frame_options:
                    self.field("override_frame", "Blender 프레임", self.order_frame if self.order_frame is not None else "", 744, 568, 144)
                    self.button("이 프레임 편집", Rect(900, 568, 164, 30), self.add_override)
                    self.button("기본 순서", Rect(1076, 568, 140, 30), self.base_order)
                    if self.order_frame is not None:
                        self.button("현재 예외 삭제", Rect(744, 610, 180, 30), self.clear_override)
            elif self.tab == 5:
                self.choice("방향: " + self.direction_name, [(i, value) for i, value in enumerate(DIRECTIONS)],
                            Rect(600, 98, 144, 32), lambda value: self.switch(direction=value))
                self.button("재생/정지", Rect(760, 98, 136, 32), lambda: self.toggle("preview_playing"))
                self.button("시트 갱신", Rect(908, 98, 148, 32), self.refresh_preview)
                self.button("도형 예제", Rect(1068, 98, 148, 32), self.sample_preview)
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
                self.choice(self.data["checks"][key], [(value, value) for value in STATUSES], Rect(264, 150 + index * 38, 96, 30),
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
        self.order_offset = min(max(self.order_offset, target - 9), target)
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
        if self.preview_resource:
            self.attempt(self.refresh_preview)

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
        self.close_resources()
        super().close()

    def close_resources(self):
        if self.preview_resource:
            self.preview_resource.close()
            self.preview_resource = None

    def update(self, delta_seconds):
        if self.preview_playing:
            self.preview_time += delta_seconds

    def content_event(self, event):
        if event.type != self.app.pico.SDL_MOUSEWHEEL:
            return
        if self.tab == 1 and Rect(264, 150, 252, 510).contains(*self.app.mouse):
            self.remember()
            self.part_offset = max(0, min(max(0, len(self.data["layers"]) - 15), self.part_offset - event.y * 3))
            self.rebuild()
        elif self.tab == 2 and Rect(744, 196, 472, 240).contains(*self.app.mouse):
            self.remember()
            self.order_offset = max(0, min(max(0, len(self.current_order) - 10), self.order_offset - event.y * 3))
            self.rebuild()

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
        for label, y in (("모델·출력", 92), ("애니메이션", 216), ("확인", 380)):
            r.text(label, 40, y, "section", c["text"])
        for label, x, y in self.labels:
            r.text(label, x, y, "small", c["muted"])
        if self.tab == 0:
            r.text("장면·프레임", 264, 96, "body", c["text"])
            r.text("이미지·재생", 264, 200, "body", c["text"])
            r.text("출력 용도", 900, 234, "small", c["muted"])
            r.text("모든 레이어에 같은 카메라·크기·기준점 적용", 264, 452, "small", c["muted"])
        elif self.tab == 1:
            r.text(f"파츠 {len(self.data['layers'])} · 휠 이동", 264, 130, "small", c["muted"])
            r.text("ID: " + self.part_key, 536, 244, "small", c["muted"], max_width=680)
            r.text("현재 동작의 상태 · " + MOTIONS[self.motion][1], 536, 264, "small", c["muted"], max_width=680)
            if self.part_state == "base":
                r.text("기본 상태 · 파츠의 공통 입력 사용", 536, 354, "small", c["muted"])
            else:
                r.text("상태 ID: " + self.part_state, 536, 326, "small", c["muted"], max_width=680)
            if self.layer_view == "energy":
                r.text("색상은 발광 없이 · 마스크는 선형 데이터", 536, 550, "small", c["muted"])
            r.text("기본 상태: " + self.current_part["default_state"], 768, 628, "small", c["muted"], max_width=448)
        elif self.tab in (2, 3, 5):
            if self.tab == 2:
                r.text("그리기 순서 · 위에서 아래로 뒤 → 앞", 744, 176, "small", c["muted"])
                rows = [str(row["frame"]) for row in self.current_motion["overrides"]
                        if row["direction"] == DIRECTIONS[self.direction]]
                r.text("프레임 예외: " + (", ".join(rows) or "없음"), 264, 690, "small", c["muted"], max_width=432)
                r.text("편집: " + (f"프레임 {self.order_frame}" if self.order_frame is not None else "기본 순서"),
                       1000, 462, "small", c["accent"])
                r.text("조립 미리보기", 264, 442, "section", c["text"])
                draw_preview(self, Rect(264, 474, 432, 208))
            elif self.tab == 5:
                draw_preview(self, Rect(264, 150, 952, 530))
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
                r.text(label, 376, 158 + index * 38, "small", c["text"], max_width=504)
            r.text("실제 결과를 검수한 뒤 상태 지정", 264, 560, "small", c["muted"])
        if self.help_open:
            explanations = (
                ("한 장면에서 모든 레이어를 출력한다. 레이어별 자동 맞춤은 사용하지 않는다.",
                 "세부 설정에서 정사영 범위와 기준점을 조정한다. 동작별 프레임은 비우면 공통 값을 사용한다."),
                ("파츠를 추가·복제·삭제하고 선택한 파츠의 부착점·시트·상태를 편집한다. 이름을 바꿔도 ID는 유지한다.",
                 "상태 시트가 비어 있으면 기본 시트를 사용한다. 새 색상 시트를 지정한 상태의 마스크는 따로 연결한다."),
                ("기본 순서와 프레임별 예외는 독립적이다. 프레임별 순서를 펼쳐 특정 프레임을 편집한다.",
                 "몸 앞뒤를 동시에 가로지르는 무기는 가림 방식에서 추가 분할 또는 가림 처리를 지정한다."),
                ("재생 인덱스가 아닌 Blender 원본 프레임을 입력한다.",
                 "부착 전후의 위치·회전 연속성과 무기 중복/누락은 실제 동작에서 확인한다."),
                ("검 길이 복귀 시작은 수납 동작에 포함된 프레임으로 지정한다.",
                 "손·팔 수납과 에임 보정기 접기는 미정이다. 검수 상태는 자동 검증 결과가 아니다."),
                ("연결한 분리 시트를 게임 공통 재생부로 합성한다. 시트 갱신으로 파일 변경을 다시 읽는다.",
                 "내보내기는 합쳐진 PNG를 만들지 않고 색상·마스크 시트와 합성 메타데이터를 보관한다."),
            )
            r.rect(Rect(264, 654, 952, 44), c["input"])
            for index, line in enumerate(explanations[self.tab]):
                r.text(line, 274, 660 + index * 18, "small", c["muted"], max_width=930)
        r.line(264, 726, 1240, 726, c["line"])
        if not self.error:
            r.text("저장 완료" if self.saved else "작업본 · Blender 분리 렌더 미연결", 264, 746, "small", c["muted"])
        self.draw_choices()
