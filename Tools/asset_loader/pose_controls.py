"""포즈 편집의 파츠 목록과 월드 축 화살표 표시. 창·작업자를 소유하지 않는다."""

from math import atan2, cos, hypot, sin
from ferrial_drive.ui.components import Rect


CATEGORIES = (("body", "몸체·IK"), ("fingers", "손가락"), ("equipment", "총·칼·칼집"), ("detail", "기타 파츠"))
FINGERS = (("all", "손가락 전체"), ("Thumb", "엄지"), ("Index", "검지"),
           ("Middle", "중지"), ("Ring", "약지"), ("Little", "소지"))
JOINTS = (("all", "관절 전체"), ("Base", "뿌리 관절"), ("01", "1번 관절"), ("02", "2번 관절"), ("03", "3번 관절"))
AXIS_COLORS = {"X": "#E88E83", "Y": "#8CBB9B", "Z": "#91B9E0"}


def rebuild(panel):
    values = {name: field.text for name, field in panel.fields.items()}
    panel.fields, panel.buttons = {}, []
    panel.button_styles, panel.button_markers = {}, {}
    panel.add_field("source", values.get("source", ""), Rect(40, 78, 684, 30))
    panel.add_field("frame", values.get("frame", "1"), Rect(560, 120, 80, 28))
    panel.add_field("distance", values.get("distance", ".05"), Rect(928, 254, 148, 28))
    panel.add_field("degrees", values.get("degrees", "5"), Rect(1084, 254, 152, 28))
    panel.button("찾기", Rect(732, 78, 72, 30), panel.browse)
    panel.button("모델 / 작업본 열기", Rect(812, 78, 224, 30), panel.open_model)
    panel.button("도형 샘플", Rect(1044, 78, 192, 30), lambda: panel.open_model(sample=True))
    for index, (key, label) in enumerate((("oblique", "사선"), ("front", "정면"), ("side", "측면"), ("back", "후면"), ("top", "위"))):
        panel.button(label, Rect(272+index*54, 120, 50, 28), lambda k=key: panel.send("view", name=k))
    panel.button("이동", Rect(648, 120, 56, 28), panel.seek)
    panel.button("◀", Rect(712, 120, 40, 28), lambda: panel.step(-1))
    panel.button("▶", Rect(756, 120, 40, 28), lambda: panel.step(1))
    panel.button("−", Rect(812, 120, 44, 28), lambda: panel.send("zoom", factor=1.15))
    panel.button("+", Rect(864, 120, 44, 28), lambda: panel.send("zoom", factor=1/1.15))
    for index, (key, label) in enumerate((("parts", "파츠"), ("motions", "동작"))):
        panel.button(label, Rect(40+index*110, 126, 102, 28), lambda k=key: panel.switch_list(k),
                     style="selected" if key == panel.list_tab else "input")
    if panel.list_tab == "parts":
        panel.choice(dict(CATEGORIES)[panel.part_category], list(CATEGORIES), Rect(40, 166, 212, 28), panel.choose_category)
        panel.add_field("filter", values.get("filter", ""), Rect(40, 202, 212, 28))
    for index, (mode, label) in enumerate((("translate", "월드 이동"), ("rotate", "월드 회전"))):
        panel.button(label, Rect(928+index*156, 196, 148, 28), lambda m=mode: panel.change_mode(m),
                     style="selected" if mode == panel.transform_mode else "input")
    for index, axis in enumerate("XYZ"):
        for sign, shift in ((-1, 0), (1, 44)):
            panel.button("", Rect(928+index*104+shift, 312, 40, 28), lambda a=axis, s=sign: panel.axis_step(a, s))
    panel.button("이전 프레임 파츠 복제", Rect(928, 420, 308, 30), lambda: panel.send("copy_previous", control=panel.selected))
    entry = panel.data.get("parts", {}).get(panel.selected, {}) if panel.data else {}
    if panel.selected in ("hand.L", "hand.R") or entry.get("category") == "fingers":
        panel.choice(dict(FINGERS)[panel.finger], list(FINGERS), Rect(928, 458, 180, 28), lambda value: panel.choose_finger(value))
        panel.choice(dict(JOINTS)[panel.finger_joint], list(JOINTS), Rect(1116, 458, 120, 28), lambda value: panel.choose_joint(value))
        panel.button("손가락 펴기", Rect(928, 494, 148, 28), lambda: panel.curl(-1))
        panel.button("손가락 굽히기", Rect(1084, 494, 152, 28), lambda: panel.curl(1))
    if panel.selected in ("object:Sword", "object:Scabbard"):
        panel.button("칼 → 칼집 자동 정렬", Rect(928, 532, 308, 30), panel.align_sword)
    panel.button("되돌리기 · Ctrl+Z", Rect(928, 568, 308, 30), lambda: panel.send("undo"))
    panel.button("현재 포즈 키 저장", Rect(928, 610, 308, 34), lambda: panel.send("key"), style="button")
    panel.button("작업본 저장", Rect(928, 652, 148, 30), lambda: panel.send("save"))
    panel.button("동작 출력", Rect(1084, 652, 152, 30), lambda: panel.send("export"))
    panel.button("출력 → 3D 렌더", Rect(928, 690, 308, 30), panel.to_render)
    if panel.focus not in panel.fields:
        panel.focus = None


def thick_line(renderer, start, end, color, width):
    length = hypot(end[0]-start[0], end[1]-start[1])
    if length < .001:
        return
    nx, ny = -(end[1]-start[1])/length, (end[0]-start[0])/length
    for index in range(width):
        offset = index-(width-1)/2
        renderer.line(start[0]+nx*offset, start[1]+ny*offset, end[0]+nx*offset, end[1]+ny*offset, color)


def arrow(renderer, start, end, color, size=7, width=1):
    thick_line(renderer, start, end, color, width)
    angle = atan2(end[1]-start[1], end[0]-start[0])
    for offset in (-.55, .55):
        thick_line(renderer, end, (end[0]-cos(angle+offset)*size, end[1]-sin(angle+offset)*size), color, width)


def axis_handles(panel):
    if not panel.data or panel.selected not in panel.data["points"]:
        return []
    uv = panel.data["points"][panel.selected]["uv"]
    x, y = panel.preview.x+uv[0]*panel.preview.width, panel.preview.y+(1-uv[1])*panel.preview.height
    result = []
    for index, axis in enumerate("XYZ"):
        dx, dy = panel.data["right"][index], -panel.data["up"][index]
        if hypot(dx, dy) < .15:
            continue
        for sign in (-1, 1):
            result.append({"axis": axis, "sign": sign, "origin": (x, y), "direction": (dx, dy),
                           "point": (x+dx*68*sign, y+dy*68*sign)})
    return result


def draw(panel):
    r, colors, data = panel.app.renderer, panel.app.theme["colors"], panel.data
    entries = data.get("parts", {}) if data else {}
    label = entries.get(panel.selected, {}).get("label", panel.selected)
    r.text("선택: "+label, 928, 170, "small", colors["text"], max_width=308)
    r.text("이동량", 928, 236, "small", colors["muted"])
    r.text("회전각 (도)", 1084, 236, "small", colors["muted"])
    for index, axis in enumerate("XYZ"):
        color = AXIS_COLORS[axis]
        base = 928+index*104
        r.text(axis, base+42, 290, "small", color, align="center")
        for sign, shift in ((-1, 0), (1, 44)):
            x, y = base+shift+20, 326
            thick_line(r, (x-5, y), (x+5, y), color, 2)
            if sign > 0:
                thick_line(r, (x, y-5), (x, y+5), color, 2)
    if data:
        if panel.list_tab == "motions":
            rows = [(clip["name"], clip["label"]) for clip in data["clips"]]
            offset, top, count = panel.clip_offset, 164, 18
            selected = data["active"]
        else:
            rows = panel.filtered_parts()
            offset, top, count, selected = panel.part_offset, 240, 16, panel.selected
        for index, (key, text) in enumerate(rows[offset:offset+count]):
            rect = Rect(40, top+index*28 if panel.list_tab == "parts" else top+index*30, 212, 26)
            r.rect(rect, colors["selected"] if key == selected else colors["input"])
            r.text(text, rect.x+8, rect.y+6, "small", colors["text"], max_width=196)
        with r.clip(panel.preview):
            for handle in axis_handles(panel):
                origin, point = handle["origin"], handle["point"]
                color = AXIS_COLORS[handle["axis"]]
                arrow(r, origin, point, color, size=10, width=3)
                r.text(("−" if handle["sign"] < 0 else "+")+handle["axis"], point[0]+5, point[1]-8, "small", color)
    if panel.selected in ("hand.L", "hand.R") or entries.get(panel.selected, {}).get("category") == "fingers":
        r.text("손가락: 선택한 손 기준", 928, 444, "small", colors["muted"], max_width=308)
    elif panel.selected.startswith("object:"):
        r.text("독립 파츠 · 자동 부착 없음", 928, 454, "small", colors["muted"], max_width=308)
    r.text("파츠 드래그 · 축 화살표 조작", 40, 710, "small", colors["muted"], max_width=212)
    r.text("Ctrl+Z: 편집 되돌리기", 40, 730, "small", colors["muted"], max_width=212)
