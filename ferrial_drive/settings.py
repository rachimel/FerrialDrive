"""게임 사용자 설정과 원자적 저장. UI·창·에셋 로딩을 소유하지 않는다."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile


TEXTURE_QUALITY_SCALES = {"high": 1.0, "medium": 0.75, "low": 0.5}
SHADOW_QUALITY_SCALES = {"high": 0.5, "medium": 0.25, "low": 0.125}
DEFAULT_TEXTURE_QUALITY = "low"
UPSCALE_AA_MODES = ("off", "smaa")
DEFAULT_UPSCALE_AA = "smaa"
SCREEN_RESOLUTIONS = ((1280, 720), (1600, 900), (1920, 1080))
DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "data/settings/game_settings.json"


@dataclass(frozen=True)
class GameSettings:
    texture_quality: str = DEFAULT_TEXTURE_QUALITY
    show_key_hints: bool = True
    screen_resolution: tuple[int, int] | None = None
    effects_volume_percent: int = 100
    upscale_aa: str = DEFAULT_UPSCALE_AA

    language: str = "en"

    def __post_init__(self):
        if self.language not in ("en", "ko"):
            raise ValueError("지원 언어는 en 또는 ko다.")
        if self.texture_quality not in TEXTURE_QUALITY_SCALES:
            raise ValueError("텍스처 품질은 high/medium/low 중 하나다.")
        if type(self.show_key_hints) is not bool:
            raise ValueError("사용키 표시는 bool이어야 한다.")
        if self.screen_resolution is not None and (
                type(self.screen_resolution) is not tuple
                or len(self.screen_resolution) != 2
                or any(type(value) is not int for value in self.screen_resolution)
                or self.screen_resolution not in SCREEN_RESOLUTIONS):
            raise ValueError("화면 해상도는 1280×720, 1600×900, 1920×1080 중 하나다.")
        if type(self.effects_volume_percent) is not int or not 0 <= self.effects_volume_percent <= 100:
            raise ValueError("효과음 음량은 0~100의 정수여야 한다.")
        if self.upscale_aa not in UPSCALE_AA_MODES:
            raise ValueError("확대 안티앨리어싱은 off 또는 smaa여야 한다.")

    @property
    def texture_scale(self):
        return TEXTURE_QUALITY_SCALES[self.texture_quality]

    @property
    def shadow_scale(self):
        return SHADOW_QUALITY_SCALES[self.texture_quality]


class GameSettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH

    def _document(self):
        if not self.path.is_file():
            return {"version": 1, "graphics": {}}
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("graphics"), dict):
            raise ValueError("게임 설정 파일의 형식이 올바르지 않다.")
        if "interface" in data and not isinstance(data["interface"], dict):
            raise ValueError("인터페이스 설정 형식이 올바르지 않다.")
        if "audio" in data and not isinstance(data["audio"], dict):
            raise ValueError("사운드 설정 형식이 올바르지 않다.")
        return data

    def load(self):
        data = self._document()
        resolution = data["graphics"].get("screen_resolution")
        if isinstance(resolution, list):
            resolution = tuple(resolution)
        return GameSettings(data["graphics"].get("texture_quality", DEFAULT_TEXTURE_QUALITY),
                            data.get("interface", {}).get("show_key_hints", True), resolution,
                            data.get("audio", {}).get("effects_volume_percent", 100),
                            data["graphics"].get("upscale_aa", DEFAULT_UPSCALE_AA),
                            language=data.get("interface", {}).get("language", "en"))

    def save(self, settings):
        if not isinstance(settings, GameSettings):
            raise TypeError("GameSettings가 필요하다.")
        data = self._document()
        data["graphics"]["texture_quality"] = settings.texture_quality
        data["graphics"]["screen_resolution"] = settings.screen_resolution
        data["graphics"]["upscale_aa"] = settings.upscale_aa
        data.setdefault("interface", {})["show_key_hints"] = settings.show_key_hints
        data["interface"]["language"] = settings.language
        data.setdefault("audio", {})["effects_volume_percent"] = settings.effects_volume_percent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="settings-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


def resolve_texture_profile(profiles, settings, directory):
    name = settings.texture_quality
    if name not in profiles:
        raise ValueError(f"선택한 텍스처 품질의 에셋 설정이 없다: {name}")
    path = (Path(directory) / profiles[name]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"선택한 텍스처 품질의 에셋이 없다: {path}")
    return path
