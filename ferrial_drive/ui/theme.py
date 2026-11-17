"""HUD 팔레트·위젯 연결·원자적 저장과 선택적 실행 중 갱신. 창을 소유하지 않는다."""

from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
import json
import os
from pathlib import Path
import re
import tempfile
from time import monotonic


DEFAULT_THEME_PATH = Path(__file__).resolve().parents[2] / "data/settings/hud_theme.json"
WIDGET_LABELS = {"global": "전체 기본값", "health": "플레이어 체력", "resources": "에너지·필살기",
                 "weapons": "무기 카드", "swap_slot": "무장 스왑 슬롯", "dash": "부스트 안내",
                 "minimap": "미니맵", "radar": "중앙 레이더", "target": "표적 체력",
                 "lock": "록온", "counters": "HIT·DAMAGE", "damage": "개별 피해 숫자",
                 "dialogue": "대화창", "menus": "메뉴·일시정지·설정"}
COLOR_LABELS = {"ui_accent": "기본 선·강조", "accent": "주 채움·체력", "text": "밝은 글자",
                "muted": "보조 글자", "background": "화면 배경", "panel": "패널 바탕",
                "panel_surface": "패널 표면", "line": "구분선", "crosshair": "조준점",
                "enemy": "적 체력", "health_loss": "체력 감소", "damage_number": "피해 숫자",
                "warning": "경고", "panel_border": "패널 외곽", "counter_shadow": "카운터 그림자",
                "counter_plaque": "카운터 받침", "menu_button": "메뉴 버튼", "menu_button_text": "메뉴 버튼 글자"}
COLOR_LABELS.update({"weapon_name_plate": "무기 이름표", "weapon_outline": "무기 외곽선",
    "panel_hover": "패널 가리킴", "panel_pressed": "패널 누름", "hud_button": "HUD 버튼",
    "hud_button_hover": "HUD 버튼 가리킴", "hud_button_pressed": "HUD 버튼 누름", "hud_button_text": "HUD 버튼 글자",
    "menu_button_hover": "메뉴 버튼 가리킴", "menu_button_pressed": "메뉴 버튼 누름", "grid": "눈금"})


def validate_theme(document):
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("HUD 테마 버전은 1이어야 한다.")
    palette, widgets = document.get("palette"), document.get("widgets")
    if not isinstance(palette, dict) or not isinstance(widgets, dict):
        raise ValueError("팔레트와 위젯 연결이 필요하다.")
    for name, value in palette.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("팔레트 색은 이름과 #RRGGBB 값이어야 한다.")
    for widget, bindings in widgets.items():
        if widget not in WIDGET_LABELS or not isinstance(bindings, dict):
            raise ValueError("지원하지 않는 위젯 연결이다.")
        if any(not isinstance(role, str) or not isinstance(color, str) or color not in palette for role, color in bindings.items()):
            raise ValueError("위젯에서 참조한 팔레트 색이 없다.")
    return deepcopy(document)


def default_theme(colors):
    colors = {key: value for key, value in colors.items() if key not in ("energy", "energy_fill")}
    return {"version": 1, "name": "스틸 블루", "palette": colors,
            "widgets": {key: ({name: name for name in colors} if key == "global" else {}) for key in WIDGET_LABELS}}


def save_theme(path, document):
    document = validate_theme(document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class ThemeWatcher:
    def __init__(self, path=DEFAULT_THEME_PATH):
        self.path = Path(path)
        self.signature = None
        self.next_poll = 0
        self.document = None
        self.error = None

    def poll(self, *, force=False):
        now = monotonic()
        if not force and now < self.next_poll:
            return False
        self.next_poll = now + .2
        try:
            stat = self.path.stat()
            signature = stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return False
        if signature == self.signature:
            return False
        self.signature = signature
        try:
            candidate = validate_theme(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError) as error:
            self.error = str(error)
            return False
        self.document, self.error = candidate, None
        return True


def resolve_widget_colors(base_colors, document, widget):
    """저장 테마의 전체·위젯 연결을 원본 색에 적용한다."""
    colors = dict(base_colors)
    for scope in ("global", widget):
        for role, name in (document["widgets"].get(scope, {}) if document else {}).items():
            if role in colors and role not in ("energy", "energy_fill"):
                colors[role] = document["palette"][name]
    return colors


@contextmanager
def widget_colors(view, widget):
    document = getattr(view, "hud_theme", None)
    if document is None and not getattr(view, "overdrive_palette", False):
        yield
        return
    previous, accent = dict(view.config.colors), view.ui_accent
    colors = resolve_widget_colors(view.base_theme_colors, document, widget)
    transform = getattr(view, "transform_ui_colors", None)
    if transform is not None:
        colors = transform(colors)
    if getattr(view, "theme_preview_active", False) and document is not None:
        from ferrial_drive.diagnostics.theme_preview import PreviewColor
        bindings = {**document["widgets"].get("global", {}), **document["widgets"].get(widget, {})}
        colors = {role: (PreviewColor(color, widget, role, bindings.get(role))
                         if role not in ("energy", "energy_fill") else color)
                  for role, color in colors.items()}
    view.config.colors.clear()
    view.config.colors.update(colors)
    view.ui_accent = colors["ui_accent"]
    try:
        yield
    finally:
        view.config.colors.clear()
        view.config.colors.update(previous)
        view.ui_accent = accent


def themed_widget(widget):
    def decorate(method):
        @wraps(method)
        def wrapped(view, *args, **kwargs):
            if getattr(view, "hud_theme", None) is None and not getattr(view, "overdrive_palette", False):
                return method(view, *args, **kwargs)
            with widget_colors(view, widget):
                return method(view, *args, **kwargs)
        return wrapped
    return decorate
