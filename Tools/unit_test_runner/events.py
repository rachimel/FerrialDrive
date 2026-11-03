"""실행기 창이 받는 파일 드롭 묶음."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FilesDropped:
    paths: tuple[Path, ...]
