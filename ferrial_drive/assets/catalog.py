"""에셋 ID 등록·상대 경로·기존 시트/번들 규격. 창을 생성하지 않는다."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile

from .sprites import SpriteBundle, SpriteSheet


KINDS = {"image", "sheet", "bundle"}


@dataclass(frozen=True)
class AssetDefinition:
    asset_id: str
    kind: str
    source: Path

    def __post_init__(self):
        if not isinstance(self.asset_id, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", self.asset_id):
            raise ValueError("에셋 ID는 영문·숫자·밑줄·점·하이픈으로 작성한다.")
        if self.kind not in KINDS:
            raise ValueError(f"지원하지 않는 에셋 종류: {self.kind}")
        object.__setattr__(self, "source", Path(self.source).resolve())


class AssetCatalog:
    def __init__(self, definitions=(), *, path=None):
        self.path = Path(path).resolve() if path is not None else None
        self.definitions = {}
        for definition in definitions:
            self.add(definition)

    def add(self, definition):
        if definition.asset_id in self.definitions:
            raise ValueError(f"이미 등록된 에셋 ID: {definition.asset_id}")
        self.definitions[definition.asset_id] = definition

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("assets"), list):
            raise ValueError("지원하지 않는 에셋 카탈로그 규격이다.")
        result = cls(path=path)
        for row in data["assets"]:
            if not isinstance(row, dict) or not isinstance(row.get("source"), str) or not row["source"].strip():
                raise ValueError("등록 항목에 source 경로가 필요하다.")
            result.add(AssetDefinition(row["id"], row["kind"], path.parent / row["source"]))
        return result

    def save(self, path=None):
        destination = Path(path).resolve() if path is not None else self.path
        if destination is None:
            raise ValueError("카탈로그 저장 경로가 필요하다.")
        rows = []
        for definition in self.definitions.values():
            try:
                source = Path(os.path.relpath(definition.source, destination.parent)).as_posix()
            except ValueError:
                source = definition.source.as_posix()
            rows.append({"id": definition.asset_id, "kind": definition.kind, "source": source})
        payload = json.dumps({"version": 1, "assets": rows}, ensure_ascii=False, indent=2) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                             prefix=destination.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.path = destination
        return destination


@dataclass(frozen=True)
class AssetDocument:
    definition: AssetDefinition
    sheets: dict
    dependencies: tuple
    suggested_id: str | None = None
    default_clip: str | None = None


def detect_kind(source):
    source = Path(source)
    if source.suffix.lower() != ".json":
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            raise ValueError("PNG/JPG/BMP 이미지 또는 시트·번들 JSON을 선택한다.")
        return "image"
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and all(key in data for key in ("body", "shadow", "directions")):
        return "bundle"
    if isinstance(data, dict) and all(key in data for key in ("image", "animations")):
        return "sheet"
    raise ValueError("SSheetCutil 시트 또는 프리렌더 번들 JSON이 아니다.")


def _read_document(definition):
    source = definition.source
    if not source.is_file():
        raise FileNotFoundError(source)
    if definition.kind == "image":
        return AssetDocument(definition, {}, (source,))
    if definition.kind == "sheet":
        sheet = SpriteSheet.load(source)
        return AssetDocument(definition, {"body": sheet}, (source, sheet.image_path))
    bundle = SpriteBundle.load(source)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    paths = (source, (source.parent / data["body"]).resolve(),
             (source.parent / data["shadow"]).resolve(), bundle.body.image_path, bundle.shadow.image_path)
    return AssetDocument(definition, {"body": bundle.body, "shadow": bundle.shadow},
                         tuple(dict.fromkeys(paths)), bundle.asset_id, next(iter(bundle.directions.values())))


def read_document(definition):
    try:
        return _read_document(definition)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError(f"에셋 메타데이터 규격 오류: {definition.source.name}: {error}") from error
