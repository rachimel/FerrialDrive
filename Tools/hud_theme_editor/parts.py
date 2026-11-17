"""편집 부위의 색 역할과 팔레트 상속 해석. 창·렌더러에 의존하지 않는다."""

# UiV2View의 위젯별 그리기 경로에서 사용하는 역할이다. 실제 프레임에서 수집한 역할도 합친다.
WIDGET_ROLES = {
    "global": ("crosshair", "warning"),
    "health": ("accent", "text", "muted", "panel_surface", "health_loss", "ui_accent"),
    "resources": ("ui_accent", "text", "muted", "panel", "panel_surface"),
    "weapons": ("ui_accent", "text", "muted", "panel_surface", "weapon_outline"),
    "swap_slot": ("ui_accent", "text", "panel_surface"),
    "dash": ("ui_accent", "text"),
    "minimap": ("ui_accent", "accent", "enemy", "muted", "text", "panel", "panel_surface"),
    "radar": ("ui_accent",),
    "target": ("enemy", "health_loss", "panel_surface", "text", "muted", "ui_accent"),
    "lock": ("ui_accent", "text", "background"),
    "counters": ("counter_plaque", "counter_shadow", "text", "muted"),
    "damage": ("damage_number",),
    "dialogue": ("ui_accent", "text", "panel", "panel_surface"),
    "menus": ("background", "ui_accent", "text", "muted", "panel", "panel_surface"),
}

SHORT_LABELS = {"global": "공통 HUD", "health": "플레이어 체력", "resources": "에너지·필살기",
                "weapons": "무기 카드", "swap_slot": "스왑 슬롯", "dash": "부스트 안내",
                "minimap": "미니맵", "radar": "레이더", "target": "표적", "lock": "록온",
                "counters": "HIT·DAMAGE", "damage": "피해 숫자", "dialogue": "대화창", "menus": "메뉴"}

PALETTE_LABELS = {"background": "배경", "panel": "패널", "panel_surface": "표면",
                  "weapon_name_plate": "이름표", "weapon_outline": "무기선", "panel_hover": "가리킴",
                  "panel_pressed": "누름", "hud_button": "HUD", "hud_button_hover": "HUD↑",
                  "hud_button_pressed": "HUD↓", "hud_button_text": "HUD글자", "menu_button": "메뉴",
                  "menu_button_hover": "메뉴↑", "menu_button_pressed": "메뉴↓", "menu_button_text": "메뉴글자",
                  "line": "구분선", "panel_border": "외곽", "grid": "눈금", "text": "글자", "muted": "보조",
                  "ui_accent": "강조", "accent": "체력", "crosshair": "조준점", "warning": "경고",
                  "enemy": "적체력", "health_loss": "감소", "damage_number": "피해",
                  "counter_shadow": "그림자", "counter_plaque": "받침"}


def palette_usages(document, palette, observed=()):
    """같은 HEX가 아닌 팔레트 식별자와 실제 상속·재정의 관계로 사용처를 찾는다."""
    inherited = document["widgets"].get("global", {})
    usages = {}
    for widget, roles in WIDGET_ROLES.items():
        roles = set(roles) | {item["role"] for item in observed if item["widget"] == widget}
        bindings = {**inherited, **document["widgets"].get(widget, {})}
        matches = [role for role in sorted(roles) if bindings.get(role) == palette]
        if matches:
            usages[widget] = matches
    return usages


def delete_palette_color(document, name):
    """삭제한 팔레트의 모든 연결을 해제하여 기존 HUD의 Fallback 경로를 사용한다."""
    if name not in document["palette"]:
        return 0
    del document["palette"][name]
    removed = 0
    for bindings in document["widgets"].values():
        for role, palette in tuple(bindings.items()):
            if palette == name:
                del bindings[role]
                removed += 1
    return removed
