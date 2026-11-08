"""열린 Pico2D 렌더러에 이미지·시트·번들을 올리는 공통 백엔드."""

from ctypes import byref, c_int, c_void_p, cast
from contextlib import nullcontext

from .sprites import SpriteClip, SpriteFrame
from .pico_opacity import DEFAULT_SHADOW_OPACITY, shadow_opacity as modulate_shadow
from ferrial_drive.rendering.bicubic import acquire_sampler


class PicoAssetBackend:
    def __init__(self, filtering='bicubic'):
        self.filtering = filtering

    def load(self, document):
        return PicoAssetResource(document, filtering=self.filtering)


class PicoAssetResource:
    def __init__(self, document, *, filtering='bicubic'):
        import pico2d.pico2d as pico

        if not pico.renderer:
            raise RuntimeError("에셋 로딩 전에 Pico2D 렌더러를 열어야 한다.")
        self.pico = pico
        self.definition = document.definition
        self.suggested_id = document.suggested_id or document.definition.source.stem
        self.textures = {}
        self.sizes = {}
        self.estimated_bytes = 0
        self.closed = False
        self.clips = {}
        self.sampler = None
        try:
            layers = ({"body": document.definition.source} if not document.sheets
                      else {layer: sheet.image_path for layer, sheet in document.sheets.items()})
            loaded = {}
            for layer, path in layers.items():
                if path not in loaded:
                    texture = pico.IMG_LoadTexture(pico.renderer, str(path).encode("utf-8"))
                    if not texture:
                        raise OSError(f"이미지 로딩 실패: {path}")
                    self.textures[layer] = texture
                    width, height = c_int(), c_int()
                    if pico.SDL_QueryTexture(texture, None, None, byref(width), byref(height)) != 0:
                        raise RuntimeError(f"이미지 크기 조회 실패: {path}")
                    size = (width.value, height.value)
                    loaded[path] = (texture, size)
                    self.estimated_bytes += size[0] * size[1] * 4
                    pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
                texture, size = loaded[path]
                self.textures[layer], self.sizes[layer] = texture, size
                if document.sheets and size != document.sheets[layer].size:
                    raise ValueError(f"PNG 실제 크기와 시트 메타데이터 불일치: {path}")
            if document.sheets:
                self.clips = document.sheets["body"].clips
            else:
                width, height = self.sizes["body"]
                self.clips = {"image": SpriteClip(1.0, (SpriteFrame((0, 0, width, height), (width / 2, 0)),))}
            self.default_clip = document.default_clip or next(iter(self.clips))
            self.set_filtering(filtering)
        except BaseException:
            self.close()
            raise

    def set_filtering(self, mode):
        if mode not in ('nearest', 'linear', 'bicubic'):
            raise ValueError('지원하지 않는 표시 필터다.')
        if mode == 'bicubic' and self.sampler is None:
            self.sampler = acquire_sampler(self.pico)
        self.filtering = 'linear' if mode == 'bicubic' and self.sampler is None else mode
        quality = self.pico.SDL_ScaleModeLinear if self.filtering == 'linear' else self.pico.SDL_ScaleModeNearest
        for texture in self.textures.values():
            if self.pico.SDL_SetTextureScaleMode(texture, quality) != 0:
                raise RuntimeError('텍스처 표시 필터 설정 실패')

    def render_batch(self):
        return self.sampler.batch() if self.filtering == 'bicubic' else nullcontext()

    def draw(self, clip_name, frame_index, x, y, *, scale=1.0, body=True, shadow=True,
             shadow_opacity=DEFAULT_SHADOW_OPACITY):
        if self.closed:
            raise RuntimeError("해제한 에셋이다.")
        self.draw_frame(self.clips[clip_name].frames[frame_index], x, y,
                        scale=scale, body=body, shadow=shadow, shadow_opacity=shadow_opacity)

    def draw_frame(self, frame, x, y, *, scale=1.0, body=True, shadow=True,
                   shadow_opacity=DEFAULT_SHADOW_OPACITY):
        if self.closed:
            raise RuntimeError("해제한 에셋이다.")
        if scale <= 0:
            return
        with self.render_batch():
            self._draw_layers(frame, x, y, scale, body, shadow, shadow_opacity)

    def _draw_layers(self, frame, x, y, scale, body, shadow, shadow_opacity):
        pico = self.pico
        left, bottom, width, height = frame.rect
        for layer, visible in (("shadow", shadow), ("body", body)):
            if not visible or layer not in self.textures:
                continue
            source = pico.SDL_Rect(left, self.sizes[layer][1] - bottom - height, width, height)
            target = pico.to_sdl_rect(x - frame.pivot[0] * scale, y - frame.pivot[1] * scale,
                                      width * scale, height * scale)
            if layer == "shadow":
                with modulate_shadow(pico, self.textures[layer], shadow_opacity):
                    self._copy(layer, source, target)
            else:
                self._copy(layer, source, target)

    def _copy(self, layer, source, target):
        if self.filtering == 'bicubic':
            self.sampler.draw(self.textures[layer], self.sizes[layer], source, target)
        else:
            self.pico.SDL_RenderCopy(self.pico.renderer, self.textures[layer], source, target)

    def close(self):
        if not self.closed:
            self.closed = True
            seen = set()
            for texture in self.textures.values():
                identity = cast(texture, c_void_p).value
                if identity not in seen:
                    seen.add(identity)
                    self.pico.SDL_DestroyTexture(texture)
            self.textures.clear()
            if self.sampler is not None:
                self.sampler.release()
                self.sampler = None
