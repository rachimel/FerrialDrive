"""열린 Pico2D 캔버스에 같은 발 기준점으로 그림자·본체를 합성한다."""

from ctypes import byref, c_int
from .pico_opacity import DEFAULT_SHADOW_OPACITY, shadow_opacity as modulate_shadow


class PicoSprite:
    def __init__(self, bundle):
        import pico2d.pico2d as pico

        self.pico, self.bundle = pico, bundle
        self.textures = {}
        try:
            for layer, sheet in (('shadow', bundle.shadow), ('body', bundle.body)):
                texture = pico.IMG_LoadTexture(pico.renderer, str(sheet.image_path).encode('utf-8'))
                if not texture:
                    raise OSError(f'이미지 로딩 실패: {sheet.image_path}')
                self.textures[layer] = texture
                width, height = c_int(), c_int()
                pico.SDL_QueryTexture(texture, None, None, byref(width), byref(height))
                if (width.value, height.value) != sheet.size:
                    raise ValueError('PNG 실제 크기와 시트 메타데이터가 다르다.')
                pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
        except BaseException:
            self.close()
            raise

    def draw(self, direction, frame_index, x, y, *, scale=1.0, body=True, shadow=True,
             shadow_opacity=DEFAULT_SHADOW_OPACITY):
        """x/y는 화면 왼쪽 아래 원점의 지면 피봇이다."""
        pico = self.pico
        name = self.bundle.directions[direction]
        for layer, sheet, visible in (('shadow', self.bundle.shadow, shadow), ('body', self.bundle.body, body)):
            if not visible:
                continue
            frame = sheet.clips[name].frames[frame_index]
            left, bottom, width, height = frame.rect
            source = pico.SDL_Rect(left, sheet.size[1] - bottom - height, width, height)
            destination = pico.to_sdl_rect(x - frame.pivot[0] * scale, y - frame.pivot[1] * scale,
                                           width * scale, height * scale)
            if layer == 'shadow':
                with modulate_shadow(pico, self.textures[layer], shadow_opacity):
                    pico.SDL_RenderCopy(pico.renderer, self.textures[layer], source, destination)
            else:
                pico.SDL_RenderCopy(pico.renderer, self.textures[layer], source, destination)

    def close(self):
        for texture in self.textures.values():
            self.pico.SDL_DestroyTexture(texture)
        self.textures.clear()
