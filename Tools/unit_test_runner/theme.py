"""도구 공통 theme_reference에서 실행기 역할만 읽는다."""

from theme_reference import load_theme, rgb

_THEME = load_theme()
RUNNER_COLORS = {role: rgb(value) for role, value in _THEME["colors"].items()}
RUNNER_FONTS = {role: (_THEME["fonts"][role]["path"], _THEME["fonts"][role]["size"])
                for role in ("title", "body")}
