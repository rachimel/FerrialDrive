"""열린 Pico2D 렌더러에 이미지·시트·번들을 올리는 공통 백엔드."""

from ctypes import byref, c_int, c_void_p, cast
from contextlib import ExitStack, contextmanager, nullcontext

from .sprites import SpriteClip, SpriteFrame
from .pico_opacity import DEFAULT_SHADOW_OPACITY, shadow_opacity as modulate_shadow
from ferrial_drive.rendering.bicubic import acquire_sampler


class PicoAssetBackend:
    def __init__(self, filtering='bicubic', *, layers=None, alpha_layers=(), alpha_scale=None):
        self.filtering = filtering
        self.layers = None if layers is None else tuple(layers)
        self.alpha_layers = tuple(alpha_layers)
        self.alpha_scale = alpha_scale

    def load(self, document):
        return PicoAssetResource(document, filtering=self.filtering, layers=self.layers,
                                 alpha_layers=self.alpha_layers, alpha_scale=self.alpha_scale)


class PicoAssetResource:
    def __init__(self, document, *, filtering='bicubic', layers=None, alpha_layers=(), alpha_scale=None):
        import pico2d.pico2d as pico

        if not pico.renderer:
            raise RuntimeError("에셋 로딩 전에 Pico2D 렌더러를 열어야 한다.")
        self.pico = pico
        self.definition = document.definition
        self.suggested_id = document.suggested_id or document.definition.source.stem
        self.textures = {}
        self.sizes = {}
        self.texture_sizes = {}
        self.estimated_bytes = 0
        self.closed = False
        self.clips = {}
        self.sampler = None
        self.alpha_layers, self.alpha_scale = tuple(alpha_layers), alpha_scale
        self.mech = document.mech
        self.map_bundle = document.map_bundle
        try:
            selected_layers = layers
            layers = ({"body": document.definition.source} if not document.sheets
                      else {layer: sheet.image_path for layer, sheet in document.sheets.items()})
            if selected_layers is not None:
                if (not selected_layers and not document.sheets) or any(layer not in layers for layer in selected_layers):
                    raise ValueError("선택한 에셋 레이어가 없다.")
                layers = {layer: layers[layer] for layer in selected_layers}
            self.layer_paths = dict(layers)
            loaded = {}
            for layer, path in layers.items():
                alpha_only = layer in alpha_layers
                key = (path, alpha_only)
                if key not in loaded:
                    if alpha_only:
                        from .alpha_data import png_dimensions
                        from ferrial_drive.rendering.pico_alpha_texture import load_alpha_texture
                        if self.sampler is None:
                            self.sampler = acquire_sampler(pico)
                        if self.sampler is None:
                            raise RuntimeError("알파 단일 채널 적재에는 OpenGL이 필요하다.")
                        logical_size = document.sheets[layer].size if document.sheets else png_dimensions(path)
                        texture = load_alpha_texture(pico, path, self.sampler, expected_size=logical_size, scale=alpha_scale)
                    else:
                        texture = pico.IMG_LoadTexture(pico.renderer, str(path).encode("utf-8"))
                    if not texture:
                        raise OSError(f"이미지 로딩 실패: {path}")
                    self.textures[layer] = texture
                    width, height = c_int(), c_int()
                    if pico.SDL_QueryTexture(texture, None, None, byref(width), byref(height)) != 0:
                        raise RuntimeError(f"이미지 크기 조회 실패: {path}")
                    texture_size = (width.value, height.value)
                    # 축소 텍스처도 원래 프레임·피봇 좌표로 표시한다.
                    size = logical_size if alpha_only else texture_size
                    loaded[key] = (texture, size, texture_size)
                    self.estimated_bytes += texture_size[0] * texture_size[1] * (1 if alpha_only else 4)
                    pico.SDL_SetTextureBlendMode(texture, pico.SDL_BLENDMODE_BLEND)
                texture, size, texture_size = loaded[key]
                self.textures[layer], self.sizes[layer] = texture, size
                self.texture_sizes[layer] = texture_size
                if document.sheets and size != document.sheets[layer].size:
                    raise ValueError(f"PNG 실제 크기와 시트 메타데이터 불일치: {path}")
            if document.sheets:
                self.clips = (self.map_bundle.clips if self.map_bundle else
                              self.mech.clips if self.mech else document.sheets["body"].clips)
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
        for layer,texture in self.textures.items():
            self._set_texture_filter(layer,texture)

    def _set_texture_filter(self,layer,texture):
        linear = self.filtering == 'linear' or (self.filtering == 'bicubic' and
                                               (layer in self.alpha_layers or layer == 'shadow'))
        quality = self.pico.SDL_ScaleModeLinear if linear else self.pico.SDL_ScaleModeNearest
        if self.pico.SDL_SetTextureScaleMode(texture,quality) != 0:
            raise RuntimeError('텍스처 표시 필터 설정 실패')

    def render_batch(self):
        return self.sampler.batch() if self.filtering == 'bicubic' else nullcontext()

    @contextmanager
    def opacity(self, opacity):
        """공유 텍스처를 한 번씩 조절하고 중첩·예외 뒤에도 이전 알파를 복원한다."""
        if self.closed:
            raise RuntimeError("해제한 에셋이다.")
        with ExitStack() as stack:
            seen = set()
            for texture in self.textures.values():
                identity = cast(texture, c_void_p).value
                if identity not in seen:
                    seen.add(identity)
                    stack.enter_context(modulate_shadow(self.pico, texture, opacity))
            yield

    def draw(self, clip_name, frame_index, x, y, *, scale=1.0, body=True, shadow=True,
             shadow_opacity=DEFAULT_SHADOW_OPACITY, layer_order=None, part_states=None, part_visibility=None):
        if self.closed:
            raise RuntimeError("해제한 에셋이다.")
        if self.map_bundle:
            self.draw_map(clip_name, x, y, scale, background=body, ground=shadow)
            return
        if self.mech:
            if body and scale > 0:
                order = self.mech.order(clip_name, frame_index) if layer_order is None else layer_order
                selection = self.mech.selection(clip_name, part_states, part_visibility)
                with self.render_batch():
                    for layer in order:
                        if layer in selection:
                            key, source = selection[layer]
                            self._draw_sheet(key, self.mech.sheets[key].clips[source].frames[frame_index], x, y, scale)
            return
        self.draw_frame(self.clips[clip_name].frames[frame_index], x, y,
                        scale=scale, body=body, shadow=shadow, shadow_opacity=shadow_opacity)

    def draw_map(self, view, x, y, scale, *, background=True, ground=True):
        if scale <= 0:
            return
        frame = next(iter(self.clips.values())).frames[0]
        layers = ('body',) if view == 'background' else ('ground',) if view == 'ground' else ('body', 'ground')
        with self.render_batch():
            for layer in layers:
                if (layer == 'body' and background) or (layer == 'ground' and ground):
                    self._draw_sheet(layer, frame, x, y, scale)
        if view == 'walkable':
            pico = self.pico
            pico.SDL_SetRenderDrawBlendMode(pico.renderer, pico.SDL_BLENDMODE_BLEND)
            pico.SDL_SetRenderDrawColor(pico.renderer, 70, 220, 130, 95)
            # 화면 픽셀 단위 스캔라인. 오목한 다각형도 같은 좌표로 표시한다.
            canvas_height = pico.get_canvas_height()
            canvas_width = pico.get_canvas_width()
            for polygon in self.map_bundle.data['walkable']:
                points = [(x + px * scale, canvas_height - y - py * scale) for px, py in polygon]
                for row in range(max(0, int(min(py for _, py in points))),
                                 min(canvas_height, int(max(py for _, py in points)) + 1)):
                    crossings = []
                    sample = row + 0.5
                    for a, b in zip(points, points[1:] + points[:1]):
                        if (a[1] > sample) != (b[1] > sample):
                            crossings.append(a[0] + (sample - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
                    crossings.sort()
                    for left, right in zip(crossings[::2], crossings[1::2]):
                        left, right = max(0, round(left)), min(canvas_width - 1, round(right))
                        if left <= right:
                            pico.SDL_RenderDrawLine(pico.renderer, left, row, right, row)

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
            target = self.target_rect(frame, x, y, scale)
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

    def _draw_sheet(self, layer, frame, x, y, scale):
        left, bottom, width, height = frame.rect
        source = self.pico.SDL_Rect(left, self.sizes[layer][1] - bottom - height, width, height)
        target = self.target_rect(frame, x, y, scale)
        self._copy(layer, source, target)

    def target_rect(self, frame, x, y, scale):
        """최종 정수 픽셀 크기로 피봇을 계산해 축소 시 중심의 밀림을 막는다."""
        width, height = frame.rect[2:]
        target_width, target_height = round(width * scale), round(height * scale)
        left = round(x - frame.pivot[0] * target_width / width)
        top = round(self.pico.get_canvas_height() - y - (height - frame.pivot[1]) * target_height / height)
        return self.pico.SDL_Rect(left, top, target_width, target_height)

    @contextmanager
    def prepare_alpha_scale(self, scale):
        """설정 저장 후에만 교체한다. 논리 크기·프레임·피봇·클립은 유지한다."""
        if self.closed:
            raise RuntimeError("해제한 에셋이다.")
        from ferrial_drive.rendering.pico_alpha_texture import load_alpha_texture
        staged, installed = {}, False
        try:
            for layer in self.alpha_layers:
                if layer not in self.textures or scale == self.alpha_scale:
                    continue
                old = self.textures[layer]
                identity = cast(old,c_void_p).value
                if identity in staged:
                    staged[identity]["layers"].append(layer)
                    continue
                width,height = c_int(),c_int()
                if self.pico.SDL_QueryTexture(old,None,None,byref(width),byref(height)):
                    raise RuntimeError("그림자 크기 조회 실패")
                before = width.value*height.value
                texture = load_alpha_texture(self.pico,self.layer_paths[layer],self.sampler,
                                             expected_size=self.sizes[layer],scale=scale)
                row = {"old":old,"new":texture,"before":before,"layers":[layer]}
                staged[identity] = row
                self._set_texture_filter(layer,texture)
                if self.pico.SDL_QueryTexture(texture,None,None,byref(width),byref(height)):
                    raise RuntimeError("새 그림자 크기 조회 실패")
                row["after"] = width.value*height.value
                row["size"] = (width.value,height.value)

            def apply():
                nonlocal installed
                if installed:
                    raise RuntimeError("그림자 교체를 이미 적용했다.")
                for row in staged.values():
                    for layer in row["layers"]:
                        self.textures[layer] = row["new"]
                        self.texture_sizes[layer] = row["size"]
                self.estimated_bytes += sum(row["after"]-row["before"] for row in staged.values())
                self.alpha_scale = scale
                installed = True
            yield apply
        finally:
            for row in staged.values():
                self.pico.SDL_DestroyTexture(row["old"] if installed else row["new"])

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
