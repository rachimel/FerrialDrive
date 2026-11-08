"""제작 도구·Blender·게임 상태에 의존하지 않는 에셋 읽기 규격."""

from .sprites import SpriteBundle, SpritePlayback
from .catalog import AssetCatalog, AssetDefinition, detect_kind
from .manager import AssetManager

__all__ = ['SpriteBundle', 'SpritePlayback', 'AssetCatalog', 'AssetDefinition', 'AssetManager', 'detect_kind']
