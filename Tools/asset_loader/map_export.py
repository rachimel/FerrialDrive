"""맵 이미지와 좌표 데이터를 새 폴더에 함께 출력한다. 원본은 수정하지 않는다."""

from contextlib import redirect_stdout
from copy import deepcopy
from ctypes import memmove, string_at
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from ferrial_drive.assets.maps import MapBundle


def composite_rgba(background, ground):
    """PNG의 straight-alpha를 유지한다. 투명 버퍼 blit의 색상 이중 감쇠를 피한다."""
    output = bytearray(background)
    for index in range(0, len(output), 4):
        front_alpha = ground[index + 3]
        if front_alpha == 0:
            continue
        if front_alpha == 255:
            output[index:index + 4] = ground[index:index + 4]
            continue
        back_alpha = background[index + 3]
        alpha = front_alpha * 255 + back_alpha * (255 - front_alpha)
        for channel in range(3):
            value = (ground[index + channel] * front_alpha * 255
                     + background[index + channel] * back_alpha * (255 - front_alpha))
            output[index + channel] = (value + alpha // 2) // alpha
        output[index + 3] = (alpha + 127) // 255
    return bytes(output)


def export_map(data, destination, *, base_dir):
    bundle = MapBundle.from_data(data, base_dir)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('출력 폴더가 이미 존재한다. 새 폴더를 지정한다.')
    with redirect_stdout(sys.stderr):
        import pico2d.pico2d as pico
    surfaces = []
    composite = None
    temporary = None
    try:
        for key in ('background', 'ground'):
            surface = pico.IMG_Load(str(bundle.paths[key]).encode('utf-8'))
            if not surface:
                raise ValueError(f'맵 이미지를 읽을 수 없다: {key}')
            surfaces.append(surface)
            if (surface.contents.w, surface.contents.h) != bundle.size:
                raise ValueError('맵 레이어의 실제 이미지 크기와 맵 크기가 다르다.')
        width, height = bundle.size
        composite = pico.SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, pico.SDL_PIXELFORMAT_RGBA32)
        if not composite or pico.SDL_FillRect(composite, None, 0) != 0:
            raise RuntimeError('맵 합성 버퍼 생성 실패')
        pixels = []
        for surface in surfaces:
            rgba = pico.SDL_ConvertSurfaceFormat(surface, pico.SDL_PIXELFORMAT_RGBA32, 0)
            if not rgba:
                raise RuntimeError('맵 RGBA 변환 실패')
            try:
                pixels.append(b''.join(string_at(rgba.contents.pixels + y * rgba.contents.pitch, width * 4)
                                       for y in range(height)))
            finally:
                pico.SDL_FreeSurface(rgba)
        combined = composite_rgba(*pixels)
        for y in range(height):
            memmove(composite.contents.pixels + y * composite.contents.pitch,
                    combined[y * width * 4:(y + 1) * width * 4], width * 4)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name('.' + destination.name + '.' + uuid4().hex)
        temporary.mkdir()
        output = deepcopy(data)
        for key in ('background', 'ground'):
            filename = key + bundle.paths[key].suffix.lower()
            shutil.copyfile(bundle.paths[key], temporary / filename)
            output[key] = filename
        output['composite'] = 'composite.png'
        if pico.IMG_SavePNG(composite, str(temporary / 'composite.png').encode('utf-8')) != 0:
            raise OSError('맵 합성 이미지 저장 실패')
        (temporary / 'bundle.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        MapBundle.load(temporary / 'bundle.json')
        os.rename(temporary, destination)
        return destination / 'bundle.json'
    finally:
        for surface in surfaces:
            pico.SDL_FreeSurface(surface)
        if composite:
            pico.SDL_FreeSurface(composite)
        if temporary is not None and temporary.exists():
            assert temporary.resolve().parent == destination.parent
            shutil.rmtree(temporary)
