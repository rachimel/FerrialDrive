"""Blender 프레임을 SSheetCutil 호환 시트·프로젝트 JSON으로 패킹한다."""

from ctypes import string_at
import json
from pathlib import Path


def pack_rendered_frames(source):
    # 패킹은 SDL surface만 사용하며 창·렌더러·Blender를 요구하지 않는다.
    import pico2d.pico2d as pico

    source = Path(source).resolve()
    data = json.loads(source.read_text(encoding='utf-8'))
    width, height = data['frame_size_pixels']
    directions = data['directions']
    columns = len(directions[0]['frames'])
    if len(directions) != 8 or not columns or any(len(row['frames']) != columns for row in directions):
        raise ValueError('이 샘플은 같은 프레임 수의 8방향이 필요하다.')
    sheet_width, sheet_height = width * columns, height * len(directions)
    report = []
    animation_name = data.get('animation_name', 'walk')
    for layer in ('body', 'shadow'):
        sheet = pico.SDL_CreateRGBSurfaceWithFormat(0, sheet_width, sheet_height, 32, pico.SDL_PIXELFORMAT_RGBA32)
        if not sheet:
            raise RuntimeError('시트 surface 생성 실패')
        animations = []
        try:
            pico.SDL_FillRect(sheet, None, 0)
            for row_index, row in enumerate(directions):
                frames = []
                for column, entry in enumerate(row['frames']):
                    path = source.parent / entry[layer]
                    surface = pico.IMG_Load(str(path).encode('utf-8'))
                    if not surface:
                        raise OSError(f'렌더 프레임을 읽을 수 없다: {path}')
                    rgba = None
                    try:
                        if (surface.contents.w, surface.contents.h) != (width, height):
                            raise ValueError(f'프레임 크기 불일치: {path}')
                        rgba = pico.SDL_ConvertSurfaceFormat(surface, pico.SDL_PIXELFORMAT_RGBA32, 0)
                        if not rgba:
                            raise RuntimeError('RGBA 픽셀 변환 실패')
                        pixels = rgba.contents
                        raw = string_at(pixels.pixels, pixels.pitch * height)
                        alpha = b''.join(raw[y * pixels.pitch + 3:y * pixels.pitch + width * 4:4]
                                         for y in range(height))
                        if max(alpha) < 16 or min(alpha) != 0:
                            raise ValueError(f'비어 있거나 투명 배경이 없는 프레임: {path}')
                        edge = alpha[:width] + alpha[-width:] + alpha[::width] + alpha[width - 1::width]
                        if max(edge) > 8:
                            raise ValueError(f'프레임 경계 잘림: {path}')
                        report.append({'path': entry[layer], 'edge_alpha_max': max(edge),
                                       'visible_pixels': sum(value > 8 for value in alpha)})
                        # 투명 surface 위에 합성하지 않고 RGBA를 그대로 복사한다.
                        pico.SDL_SetSurfaceBlendMode(rgba, pico.SDL_BLENDMODE_NONE)
                        target = pico.SDL_Rect(column * width, row_index * height, width, height)
                        if pico.SDL_BlitSurface(rgba, None, sheet, target) != 0:
                            raise RuntimeError('시트 복사 실패')
                    finally:
                        if rgba:
                            pico.SDL_FreeSurface(rgba)
                        pico.SDL_FreeSurface(surface)
                    frames.append({'rect': [column * width, sheet_height - (row_index + 1) * height, width, height],
                                   'pivot': data['pivot']})
                animations.append({'name': f'{animation_name}/{row["id"]}', 'fps': data['fps'], 'frames': frames})
            sheet_path = source.parent / f'{layer}.png'
            if pico.IMG_SavePNG(sheet, str(sheet_path).encode('utf-8')) != 0:
                raise OSError('PNG 시트 저장 실패')
        finally:
            pico.SDL_FreeSurface(sheet)
        project = {'version': 1, 'coordinates': 'bottom-left',
                   'image': {'path': f'{layer}.png', 'size': [sheet_width, sheet_height]},
                   'animations': animations, 'event_bindings': {}}
        (source.parent / f'{layer}.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
    bundle = {'version': 1, 'asset_id': data['asset_id'], 'body': 'body.json', 'shadow': 'shadow.json',
              'directions': {row['id']: f'{animation_name}/{row["id"]}' for row in directions},
              'config_sha256': data['config_sha256'], 'blender_version': data['blender_version']}
    (source.parent / 'pixel_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    result = source.parent / 'bundle.json'
    # 모든 이미지·검사가 성공한 뒤에만 완성 번들의 진입점을 쓴다.
    result.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
