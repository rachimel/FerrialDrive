"""검 Trail 결의 사전 준비와 공개 도형 시연용 픽셀을 관리한다."""

import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import tempfile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


FLOW_WIDTH = 512
FLOW_HEIGHT = 128
FLOW_GENERATOR_VERSION = 1
DEFAULT_FLOW_DIRECTORY = Path(__file__).resolve().parents[2] / 'data/runtime/effects/sword_trail'


def flow_recipe(settings, *, width=FLOW_WIDTH, height=FLOW_HEIGHT):
    strands, softness = settings.get('flow_strands', 18), settings.get('flow_softness', .018)
    if (type(width) is not int or type(height) is not int or min(width, height) < 2
            or type(strands) is not int or strands < 1
            or not isinstance(softness, (int, float)) or not isfinite(softness) or not 0 < softness < .2):
        raise ValueError('Trail 결의 크기·가닥 수·부드러움 오류')
    return dict(version=FLOW_GENERATOR_VERSION, width=width, height=height, strands=strands, softness=softness)


def flow_texture_path(settings, directory=None, *, width=FLOW_WIDTH, height=FLOW_HEIGHT):
    recipe = flow_recipe(settings, width=width, height=height)
    key = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode('utf-8')).hexdigest()[:20]
    return Path(directory if directory is not None else DEFAULT_FLOW_DIRECTORY) / f'flow_{key}.trailflow'


def _generate_flow_pixels(recipe):
    from ferrial_drive.rendering.sword_trail_texture import trail_flow_pixels

    return trail_flow_pixels(recipe['width'], recipe['height'], strands=recipe['strands'], softness=recipe['softness'])


def load_flow_texture(settings, directory=None, *, width=FLOW_WIDTH, height=FLOW_HEIGHT, generate_if_missing=False):
    """준비 파일을 검증하고, 공개 도형 시연은 파일이 없을 때 메모리에서 준비할 수 있다."""
    expected = flow_recipe(settings, width=width, height=height)
    path = flow_texture_path(settings, directory, width=width, height=height)
    if not path.is_file():
        if generate_if_missing:
            return expected, _generate_flow_pixels(expected)
        raise FileNotFoundError(f'Trail 결 준비 파일이 없다: {path}. '
                                'python automate/run.py trail-texture --config 설정.json으로 먼저 준비한다.')
    try:
        with ZipFile(path) as archive:
            if archive.getinfo('manifest.json').file_size > 4096:
                raise ValueError('Trail 결 메타데이터 크기 오류')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('recipe') != expected:
                raise ValueError('Trail 결 준비 설정이 현재 설정과 다르다.')
            if archive.getinfo('pixels.rgba').file_size != width * height * 4:
                raise ValueError('Trail 결 RGBA 크기 오류')
            pixels = archive.read('pixels.rgba')
            if hashlib.sha256(pixels).hexdigest() != manifest.get('rgba_sha256'):
                raise ValueError('Trail 결 RGBA 해시 불일치')
    except (BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f'Trail 결 준비 파일 오류: {path}') from error
    return expected, pixels


def prepare_flow_texture(settings, directory=None, *, width=FLOW_WIDTH, height=FLOW_HEIGHT):
    """제작 단계에서만 기존 생성기를 실행한다. 정상 기존 파일은 재사용한다."""
    recipe = flow_recipe(settings, width=width, height=height)
    path = flow_texture_path(settings, directory, width=width, height=height)
    reused = path.is_file()
    if reused:
        _, pixels = load_flow_texture(settings, directory, width=width, height=height)
    else:
        pixels = _generate_flow_pixels(recipe)
        manifest = dict(recipe=recipe, rgba_sha256=hashlib.sha256(pixels).hexdigest())
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.trail-', suffix='.tmp', delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with ZipFile(temporary_path, 'w', compression=ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
                archive.writestr('pixels.rgba', pixels)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return dict(path=str(path.resolve()), recipe=recipe, rgba_bytes=len(pixels),
                rgba_sha256=hashlib.sha256(pixels).hexdigest(), file_bytes=path.stat().st_size, reused=reused)
