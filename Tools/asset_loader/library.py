"""data/catalog의 로컬 샘플·완성 에셋·등록 목록. import 시 파일을 쓰지 않는다."""

from datetime import datetime
from pathlib import Path
import shutil
from uuid import uuid4

from ferrial_drive.assets import AssetCatalog, AssetDefinition
from ferrial_drive.assets.catalog import read_document
from .assembly import SpriteAssembly


ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT = ROOT / "data/catalog"
DEFAULT_CATALOG = LIBRARY_ROOT / "catalog.json"
SAMPLE_ROOT = LIBRARY_ROOT / "samples/asset_loader"
SAMPLE = SAMPLE_ROOT / "bundle.json"
PRERENDER_ROOT = LIBRARY_ROOT / "prerender"
PUBLIC_SAMPLE = ROOT / "samples/asset_loader"
SAMPLE_FILES = ("image.png", "body.png", "shadow.png", "body.json", "shadow.json", "bundle.json", "catalog.json")


def prepare_library(root=LIBRARY_ROOT, *, sample_source=PUBLIC_SAMPLE):
    root, sample_source = Path(root).resolve(), Path(sample_source).resolve()
    sample = root / "samples/asset_loader"
    sample.mkdir(parents=True, exist_ok=True)
    (root / "prerender").mkdir(exist_ok=True)
    for name in SAMPLE_FILES:
        destination = sample / name
        if not destination.exists():
            shutil.copyfile(sample_source / name, destination)
    catalog_path = root / "catalog.json"
    if not catalog_path.exists():
        catalog = AssetCatalog.load(sample / "catalog.json")
        catalog.save(catalog_path)
    return AssetCatalog.load(catalog_path)


def asset_directory(asset_id, *, root=PRERENDER_ROOT):
    AssetDefinition(asset_id, "image", PUBLIC_SAMPLE / "image.png")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    return Path(root).resolve() / asset_id / stamp


def store_asset(definition, *, image_size=None, root=LIBRARY_ROOT):
    root = Path(root).resolve()
    document = read_document(definition)
    if all(root in path.parents for path in document.dependencies):
        return definition
    destination = asset_directory(definition.asset_id, root=root / "prerender")
    if definition.kind == "image":
        destination.mkdir(parents=True)
        target = destination / ("image" + definition.source.suffix.lower())
        try:
            shutil.copyfile(definition.source, target)
        except OSError:
            assert destination.resolve().parent.parent == root / "prerender"
            if target.exists():
                target.unlink()
            destination.rmdir()
            raise
        return AssetDefinition(definition.asset_id, "image", target)
    target = SpriteAssembly(definition, image_size=image_size).save(destination, asset_id=definition.asset_id)
    return AssetDefinition(definition.asset_id, definition.kind, target)
