"""Pico2D 창·이벤트를 사용하는 직접 OpenGL 렌더러 후보."""

from contextlib import contextmanager
import ctypes as ct
from dataclasses import dataclass
from math import cos, radians, sin
from struct import Struct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


TEXTURE_2D = 0x0DE1
FRAMEBUFFER = 0x8D40
RGBA = 0x1908
RGBA8 = 0x8058
UNSIGNED_BYTE = 0x1401
COLOR_BUFFER = 0x4000
TRIANGLES = 0x0004
QUADS = 0x0007
SDL_VERTEX = Struct("=ffBBBBff")


def pointed(pointer, structure):
    if isinstance(pointer, structure):
        return pointer
    return ct.cast(pointer, ct.POINTER(structure)).contents


def store(pointer, structure, value):
    if pointer:
        pointed(pointer, structure).value = value


def address(pointer):
    return ct.cast(pointer, ct.c_void_p).value


@dataclass
class TargetState:
    scale: tuple = (1.0, 1.0)
    viewport: tuple | None = None
    clip: tuple | None = None


@dataclass
class GlTexture:
    handle: object
    name: int
    pixel_format: int
    access: int
    width: int
    height: int
    framebuffer: int = 0
    modulation: tuple = (255, 255, 255, 255)
    blend: int = 0
    scale: int = 0


class NativeGlRenderer:
    """SDL 표면은 CPU 입력으로 읽고, 텍스처·프레임버퍼·그리기는 직접 관리한다."""

    def __init__(self, pico, window, vsync):
        self.pico, self.window = pico, window
        self.vsync = False
        self.context = pico.SDL_GL_CreateContext(window)
        if not self.context:
            raise RuntimeError("직접 OpenGL 컨텍스트를 만들 수 없다.")
        self.textures = {}
        self.draw_color = (0, 0, 0, 255)
        self.draw_blend = pico.SDL_BLENDMODE_NONE
        self.screen = self.state = TargetState()
        self.target = None
        self.logical_size = (0, 0)
        self.drawable_size = self._read_output_size()
        self._draw_ready = False
        self._actual_blend = None
        self._texture_enabled = False
        self._actual_texture = None
        self._blend = {
            0: None,
            1: (0x0302, 0x0303, 1, 0x0303),
            2: (0x0302, 1, 0, 1),
            4: (0x0306, 0, 0, 1),
            8: (0x0306, 0x0303, 0x0306, 0x0303),
        }
        try:
            vertex = pico.SDL_Vertex
            if (ct.sizeof(vertex), vertex.position.offset, vertex.color.offset, vertex.tex_coord.offset) != (
                    SDL_VERTEX.size, 0, 8, 12):
                raise RuntimeError("SDL 꼭짓점 배치가 직접 OpenGL 경로와 다르다.")
            if pico.SDL_GL_MakeCurrent(window, self.context):
                raise RuntimeError("직접 OpenGL 컨텍스트를 선택할 수 없다.")
            pico.SDL_GL_SetSwapInterval(int(vsync))
            self.vsync = pico.SDL_GL_GetSwapInterval() != 0
            self._bind()
            self._target_state()
        except BaseException:
            self.close()
            raise

    def _bind(self):
        u, i, f, b, ptr = ct.c_uint, ct.c_int, ct.c_float, ct.c_ubyte, ct.c_void_p
        signatures = {
            "GetIntegerv": (None, [u, ptr]), "GetError": (u, []),
            "GenTextures": (None, [i, ptr]), "DeleteTextures": (None, [i, ptr]),
            "ActiveTexture": (None, [u]), "BindTexture": (None, [u, u]),
            "TexParameteri": (None, [u, u, i]), "TexImage2D": (None, [u, i, i, i, i, i, u, u, ptr]),
            "TexSubImage2D": (None, [u, i, i, i, i, i, u, u, ptr]), "PixelStorei": (None, [u, i]),
            "GenFramebuffers": (None, [i, ptr]), "DeleteFramebuffers": (None, [i, ptr]),
            "BindFramebuffer": (None, [u, u]), "FramebufferTexture2D": (None, [u, u, u, u, i]),
            "CheckFramebufferStatus": (u, [u]), "BindBuffer": (None, [u, u]), "BindVertexArray": (None, [u]),
            "UseProgram": (None, [u]), "Viewport": (None, [i, i, i, i]), "Scissor": (None, [i, i, i, i]),
            "Enable": (None, [u]), "Disable": (None, [u]), "ColorMask": (None, [b, b, b, b]),
            "ClearColor": (None, [f, f, f, f]), "Clear": (None, [u]),
            "BlendFuncSeparate": (None, [u, u, u, u]), "BlendEquationSeparate": (None, [u, u]),
            "MatrixMode": (None, [u]), "LoadIdentity": (None, []), "Ortho": (None, [ct.c_double] * 6),
            "TexEnvi": (None, [u, u, i]), "EnableClientState": (None, [u]), "DisableClientState": (None, [u]),
            "VertexPointer": (None, [i, u, i, ptr]), "ColorPointer": (None, [i, u, i, ptr]),
            "TexCoordPointer": (None, [i, u, i, ptr]), "ClientActiveTexture": (None, [u]),
            "DrawElements": (None, [u, i, u, ptr]), "DrawArrays": (None, [u, i, i]),
            "ReadPixels": (None, [i, i, i, i, u, u, ptr]),
        }
        for method, (result, arguments) in signatures.items():
            setattr(self, method, bind_gl(self.pico, "gl" + method, result, arguments))

    def integer(self, option):
        value = ct.c_int()
        self.GetIntegerv(option, ct.byref(value))
        return value.value

    def _read_output_size(self):
        width, height = ct.c_int(), ct.c_int()
        self.pico.SDL_GL_GetDrawableSize(self.window, ct.byref(width), ct.byref(height))
        return width.value, height.value

    def target_size(self):
        return self.drawable_size if self.target is None else (self.target.width, self.target.height)

    def viewport(self):
        sx, sy = self.state.scale
        width, height = self.target_size()
        return self.state.viewport or (0, 0, int(width / sx), int(height / sy))

    def _target_state(self):
        self.external_draw()
        self.BindFramebuffer(FRAMEBUFFER, self.target.framebuffer if self.target else 0)
        _, height = self.target_size()
        x, y, width, viewport_height = self.viewport()
        sx, sy = self.state.scale
        px, py, pw, ph = int(x * sx), int(y * sy), int(width * sx), int(viewport_height * sy)
        output_y = height - py - ph if self.target is None else py
        self.Viewport(px, output_y, pw, ph)
        self._apply_clip()
        if width > 0 and viewport_height > 0:
            self.MatrixMode(0x1701)
            self.LoadIdentity()
            bottom, top = (viewport_height, 0) if self.target is None else (0, viewport_height)
            self.Ortho(0, width, bottom, top, -1, 1)
            self.MatrixMode(0x1700)
            self.LoadIdentity()

    def _apply_clip(self):
        if self.state.clip is None:
            self.Disable(0x0C11)
        else:
            _, height = self.target_size()
            x, y, _, _ = self.viewport()
            sx, sy = self.state.scale
            px, py = int(x * sx), int(y * sy)
            left, top, wide, tall = self.state.clip
            cx, cy, cw, ch = int(left * sx), int(top * sy), int(wide * sx), int(tall * sy)
            clip_y = height - py - cy - ch if self.target is None else py + cy
            self.Enable(0x0C11)
            self.Scissor(px + cx, clip_y, max(0, cw), max(0, ch))

    def external_draw(self):
        if self._draw_ready:
            self._set_textured(False)
            self.DisableClientState(0x8076)
            self.DisableClientState(0x8074)
            self._draw_ready = False

    def resize_window(self):
        self.drawable_size = self._read_output_size()
        self._update_logical_viewport()

    def set_target(self, renderer, handle):
        texture = self.texture_for(handle)
        if texture is self.target:
            return 0
        if texture is not None and not texture.framebuffer:
            return -1
        self.target = texture
        self.state = self.screen if texture is None else TargetState()
        self._target_state()
        return 0

    def get_target(self, renderer):
        return None if self.target is None else self.target.handle

    def set_viewport(self, renderer, rectangle):
        viewport = None
        if rectangle:
            rect = pointed(rectangle, self.pico.SDL_Rect)
            viewport = rect.x, rect.y, rect.w, rect.h
        if self.state.viewport != viewport:
            self.state.viewport = viewport
            self._target_state()
        return 0

    def get_viewport(self, renderer, rectangle):
        rect = pointed(rectangle, self.pico.SDL_Rect)
        rect.x, rect.y, rect.w, rect.h = self.viewport()

    def set_clip(self, renderer, rectangle):
        clip = None
        if rectangle:
            rect = pointed(rectangle, self.pico.SDL_Rect)
            clip = rect.x, rect.y, rect.w, rect.h
        if self.state.clip != clip:
            self.state.clip = clip
            self._apply_clip()
        return 0

    def get_clip(self, renderer, rectangle):
        rect = pointed(rectangle, self.pico.SDL_Rect)
        rect.x, rect.y, rect.w, rect.h = self.state.clip or (0, 0, 0, 0)

    def clip_enabled(self, renderer):
        return self.state.clip is not None

    def set_scale(self, renderer, x, y):
        if x <= 0 or y <= 0:
            return -1
        if self.state.scale != (x, y):
            self.state.scale = (x, y)
            self._target_state()
        return 0

    def get_scale(self, renderer, x, y):
        store(x, ct.c_float, self.state.scale[0])
        store(y, ct.c_float, self.state.scale[1])

    def set_logical_size(self, renderer, width, height):
        self.logical_size = width, height
        self.resize_window()
        return 0

    def _update_logical_viewport(self):
        width, height = self.logical_size
        if width > 0 and height > 0:
            actual_width, actual_height = self.drawable_size
            scale = min(actual_width / width, actual_height / height)
            if scale > 0:
                self.screen.viewport = (int((actual_width / scale - width) * .5),
                                        int((actual_height / scale - height) * .5), width, height)
                self.screen.scale = scale, scale
        else:
            self.screen.viewport = None
            self.screen.scale = 1.0, 1.0
        self._target_state()

    def window_to_logical(self, x, y):
        width, height = ct.c_int(), ct.c_int()
        self.pico.SDL_GetWindowSize(self.window, ct.byref(width), ct.byref(height))
        output_width, output_height = self.drawable_size
        scale_x, scale_y = self.screen.scale
        left, top = (self.screen.viewport or (0, 0))[:2]
        return (int(x * output_width / max(1, width.value) / scale_x - left),
                int(y * output_height / max(1, height.value) / scale_y - top))

    def get_output_size(self, renderer, width, height):
        w, h = self.target_size()
        store(width, ct.c_int, w)
        store(height, ct.c_int, h)
        return 0

    def get_info(self, renderer, info):
        result = pointed(info, self.pico.SDL_RendererInfo)
        result.name = b"opengl"
        result.flags = self.pico.SDL_RENDERER_ACCELERATED | self.pico.SDL_RENDERER_TARGETTEXTURE
        if self.vsync:
            result.flags |= self.pico.SDL_RENDERER_PRESENTVSYNC
        result.num_texture_formats = 2
        result.texture_formats[0] = self.pico.SDL_PIXELFORMAT_RGBA32
        result.texture_formats[1] = self.pico.SDL_PIXELFORMAT_RGBA8888
        result.max_texture_width = result.max_texture_height = self.integer(0x0D33)
        return 0

    def _format(self, pixel_format):
        p = self.pico
        if pixel_format == p.SDL_PIXELFORMAT_RGBA32:
            return RGBA, UNSIGNED_BYTE
        if pixel_format == p.SDL_PIXELFORMAT_RGBA8888:
            return RGBA, 0x8035
        raise ValueError(f"직접 OpenGL 픽셀 형식 미지원: {pixel_format:#x}")

    def texture_for(self, handle):
        return self.textures[address(handle)] if handle else None

    @contextmanager
    def _bind_texture(self, texture):
        active = self.integer(0x84E0)
        self.ActiveTexture(0x84C0)
        bound = self.integer(0x8069)
        self.BindTexture(TEXTURE_2D, texture)
        try:
            yield
        finally:
            self.BindTexture(TEXTURE_2D, bound)
            self.ActiveTexture(active)

    @contextmanager
    def _pixel_transfer(self, *, pack, row_length):
        buffer_target, buffer_binding = (0x88EB, 0x88ED) if pack else (0x88EC, 0x88EF)
        swap_bytes = 0x0D00 if pack else 0x0CF0
        first = 0x0D02 if pack else 0x0CF2
        options = (swap_bytes, *range(first, first + 4))
        previous = [self.integer(option) for option in options]
        buffer = self.integer(buffer_binding)
        self.BindBuffer(buffer_target, 0)
        for option, value in zip(options, (0, row_length, 0, 0, 1)):
            self.PixelStorei(option, value)
        try:
            yield
        finally:
            for option, value in zip(options, previous):
                self.PixelStorei(option, value)
            self.BindBuffer(buffer_target, buffer)

    def create_texture(self, renderer, pixel_format, access, width, height):
        if width <= 0 or height <= 0 or max(width, height) > self.integer(0x0D33):
            return None
        gl_format, gl_type = self._format(pixel_format)
        name, framebuffer = ct.c_uint(), ct.c_uint()
        self.GenTextures(1, ct.byref(name))
        previous_draw, previous_read = self.integer(0x8CA6), self.integer(0x8CAA)
        try:
            with self._bind_texture(name.value), self._pixel_transfer(pack=False, row_length=0):
                for option, value in ((0x2800, 0x2600), (0x2801, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
                    self.TexParameteri(TEXTURE_2D, option, value)
                self.TexImage2D(TEXTURE_2D, 0, RGBA8, width, height, 0, gl_format, gl_type, None)
                if access == self.pico.SDL_TEXTUREACCESS_TARGET:
                    self.GenFramebuffers(1, ct.byref(framebuffer))
                    self.BindFramebuffer(FRAMEBUFFER, framebuffer.value)
                    self.FramebufferTexture2D(FRAMEBUFFER, 0x8CE0, TEXTURE_2D, name.value, 0)
                    if self.CheckFramebufferStatus(FRAMEBUFFER) != 0x8CD5:
                        raise RuntimeError("직접 OpenGL 렌더 타깃이 불완전하다.")
            error = self.GetError()
            if error:
                raise RuntimeError(f"직접 OpenGL 텍스처 초기화 실패: GL {error:#x}")
        except BaseException:
            if framebuffer.value:
                self.DeleteFramebuffers(1, ct.byref(framebuffer))
            self.DeleteTextures(1, ct.byref(name))
            raise
        finally:
            self.BindFramebuffer(0x8CA9, previous_draw)
            self.BindFramebuffer(0x8CA8, previous_read)
        handle = ct.pointer(self.pico.SDL_Texture())
        self.textures[address(handle)] = GlTexture(handle, name.value, pixel_format, access, width, height,
                                                   framebuffer.value)
        return handle

    def destroy_texture(self, handle):
        texture = self.textures.pop(address(handle), None)
        if texture is None:
            return
        if self._actual_texture == texture.name:
            self._actual_texture = None
        if texture is self.target:
            self.set_target(self, None)
        if texture.framebuffer:
            self.DeleteFramebuffers(1, ct.byref(ct.c_uint(texture.framebuffer)))
        self.DeleteTextures(1, ct.byref(ct.c_uint(texture.name)))

    def update_texture(self, handle, rectangle, pixels, pitch):
        texture = self.texture_for(handle)
        if rectangle:
            rect = pointed(rectangle, self.pico.SDL_Rect)
            x, y, width, height = rect.x, rect.y, rect.w, rect.h
        else:
            x, y, width, height = 0, 0, texture.width, texture.height
        if (not pixels or width <= 0 or height <= 0 or min(x, y) < 0
                or x + width > texture.width or y + height > texture.height or pitch < width * 4 or pitch % 4):
            return -1
        gl_format, gl_type = self._format(texture.pixel_format)
        with self._bind_texture(texture.name), self._pixel_transfer(pack=False, row_length=pitch // 4):
            self.TexSubImage2D(TEXTURE_2D, 0, x, y, width, height, gl_format, gl_type, pixels)
        return 0

    def texture_from_surface(self, renderer, surface):
        p = self.pico
        converted = p.SDL_ConvertSurfaceFormat(surface, p.SDL_PIXELFORMAT_RGBA32, 0)
        if not converted:
            return None
        try:
            image = converted.contents
            handle = self.create_texture(renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC,
                                         image.w, image.h)
            if not handle:
                return None
            if self.update_texture(handle, None, image.pixels, image.pitch):
                self.destroy_texture(handle)
                return None
            original = surface.contents
            blend = p.SDL_BLENDMODE_BLEND if original.format.contents.Amask else p.SDL_BLENDMODE_NONE
            self.set_texture_blend(handle, blend)
            return handle
        finally:
            p.SDL_FreeSurface(converted)

    def load_texture(self, renderer, filename):
        p = self.pico
        surface = p.IMG_Load(filename)
        if not surface:
            return None
        try:
            return self.texture_from_surface(renderer, surface)
        finally:
            p.SDL_FreeSurface(surface)

    def query_texture(self, handle, pixel_format, access, width, height):
        texture = self.texture_for(handle)
        store(pixel_format, ct.c_uint, texture.pixel_format)
        store(access, ct.c_int, texture.access)
        store(width, ct.c_int, texture.width)
        store(height, ct.c_int, texture.height)
        return 0

    def set_texture_color(self, handle, red, green, blue):
        texture = self.texture_for(handle)
        texture.modulation = red, green, blue, texture.modulation[3]
        return 0

    def get_texture_color(self, handle, red, green, blue):
        for pointer, value in zip((red, green, blue), self.texture_for(handle).modulation[:3]):
            store(pointer, ct.c_ubyte, value)
        return 0

    def set_texture_alpha(self, handle, alpha):
        texture = self.texture_for(handle)
        texture.modulation = (*texture.modulation[:3], alpha)
        return 0

    def get_texture_alpha(self, handle, alpha):
        store(alpha, ct.c_ubyte, self.texture_for(handle).modulation[3])
        return 0

    def set_texture_blend(self, handle, blend):
        self.texture_for(handle).blend = blend
        return 0

    def get_texture_blend(self, handle, blend):
        store(blend, ct.c_int, self.texture_for(handle).blend)
        return 0

    def set_texture_scale(self, handle, scale):
        texture = self.texture_for(handle)
        if texture.scale == scale:
            return 0
        texture.scale = scale
        with self._bind_texture(texture.name):
            gl_filter = 0x2600 if scale == self.pico.SDL_ScaleModeNearest else 0x2601
            self.TexParameteri(TEXTURE_2D, 0x2800, gl_filter)
            self.TexParameteri(TEXTURE_2D, 0x2801, gl_filter)
        return 0

    def gl_bind_texture(self, handle, width, height):
        self.external_draw()
        self.BindTexture(TEXTURE_2D, self.texture_for(handle).name)
        store(width, ct.c_float, 1.0)
        store(height, ct.c_float, 1.0)
        return 0

    def gl_unbind_texture(self, handle):
        self.external_draw()
        self.BindTexture(TEXTURE_2D, 0)
        return 0

    def set_draw_color(self, renderer, red, green, blue, alpha):
        self.draw_color = red, green, blue, alpha
        return 0

    def get_draw_color(self, renderer, red, green, blue, alpha):
        for pointer, value in zip((red, green, blue, alpha), self.draw_color):
            store(pointer, ct.c_ubyte, value)
        return 0

    def set_draw_blend(self, renderer, blend):
        self.draw_blend = blend
        return 0

    def get_draw_blend(self, renderer, blend):
        store(blend, ct.c_int, self.draw_blend)
        return 0

    def _apply_blend(self, blend):
        if blend == self.pico.SDL_BLENDMODE_NONE:
            self.Disable(0x0BE2)
            return
        self.Enable(0x0BE2)
        factors = self._blend.get(blend)
        operations = 0x8006, 0x8006
        if factors is None:
            factor_map = (0, 0, 1, 0x0300, 0x0301, 0x0302, 0x0303, 0x0306, 0x0307, 0x0304, 0x0305)
            operation_map = (0x8006, 0x8006, 0x800A, 0x800B, 0x8007, 0x8008)
            factors = tuple(factor_map[(blend >> shift) & 15] for shift in (4, 8, 20, 24))
            operations = tuple(operation_map[(blend >> shift) & 15] for shift in (0, 16))
        self.BlendFuncSeparate(*factors)
        self.BlendEquationSeparate(*operations)

    def clear(self, renderer):
        self._target_state()
        self.Disable(0x0C11)
        self.ColorMask(1, 1, 1, 1)
        self.ClearColor(*(value / 255 for value in self.draw_color))
        self.Clear(COLOR_BUFFER)
        self._target_state()
        return 0

    def _draw(self, vertices, count, mode, texture=None, indices=None, index_count=0):
        if not count:
            return 0
        _, _, width, height = self.viewport()
        if width <= 0 or height <= 0:
            return 0
        if not self._draw_ready:
            self.UseProgram(0)
            self.BindVertexArray(0)
            self.BindBuffer(0x8892, 0)
            self.BindBuffer(0x8893, 0)
            for flag in (0x0B44, 0x0B71, 0x0B50, 0x0BC0):
                self.Disable(flag)
            self.ColorMask(1, 1, 1, 1)
            self.ActiveTexture(0x84C0)
            self.ClientActiveTexture(0x84C0)
            self.Disable(TEXTURE_2D)
            self.DisableClientState(0x8078)
            self.EnableClientState(0x8074)
            self.EnableClientState(0x8076)
            self._draw_ready = True
            self._actual_blend = None
            self._actual_texture = None
        blend = texture.blend if texture else self.draw_blend
        if blend != self._actual_blend:
            self._apply_blend(blend)
            self._actual_blend = blend
        self._set_textured(texture is not None)
        if texture and self._actual_texture != texture.name:
            self.BindTexture(TEXTURE_2D, texture.name)
            self._actual_texture = texture.name
        vertex = self.pico.SDL_Vertex
        start, stride = address(vertices), ct.sizeof(vertex)
        self.VertexPointer(2, 0x1406, stride, start + vertex.position.offset)
        self.ColorPointer(4, UNSIGNED_BYTE, stride, start + vertex.color.offset)
        if texture:
            self.TexCoordPointer(2, 0x1406, stride, start + vertex.tex_coord.offset)
        if indices and index_count:
            self.DrawElements(mode, index_count, 0x1405, indices)
        else:
            self.DrawArrays(mode, 0, count)
        return 0

    def _set_textured(self, enabled):
        if enabled == self._texture_enabled:
            return
        if enabled:
            self.Enable(TEXTURE_2D)
            self.TexEnvi(0x2300, 0x2200, 0x2100)
            self.EnableClientState(0x8078)
        else:
            self.Disable(TEXTURE_2D)
            self.DisableClientState(0x8078)
        self._texture_enabled = enabled

    def _vertices(self, points, color, texels=None):
        if texels is None:
            return b"".join(SDL_VERTEX.pack(x, y, *color, 0, 0) for x, y in points)
        return b"".join(SDL_VERTEX.pack(x, y, *color, u, v)
                        for (x, y), (u, v) in zip(points, texels, strict=True))

    def geometry(self, renderer, handle, vertices, count, indices, index_count):
        return self._draw(vertices, count, TRIANGLES, self.texture_for(handle), indices, index_count)

    def _shape(self, points, mode):
        vertices = self._vertices(points, self.draw_color)
        return self._draw(vertices, len(points), mode)

    def _rect(self, rectangle, structure):
        if rectangle:
            rect = pointed(rectangle, structure)
            return rect.x, rect.y, rect.w, rect.h
        _, _, width, height = self.viewport()
        return 0, 0, width, height

    @staticmethod
    def quad(x, y, width, height):
        return ((x, y), (x + width, y), (x + width, y + height), (x, y + height))

    def fill_rect(self, renderer, rectangle):
        return self._shape(self.quad(*self._rect(rectangle, self.pico.SDL_Rect)), QUADS)

    def fill_rects(self, renderer, rectangles, count):
        points = [point for index in range(count) for rect in (rectangles[index],)
                  for point in self.quad(rect.x, rect.y, rect.w, rect.h)]
        return self._shape(points, QUADS)

    def draw_rect(self, renderer, rectangle):
        x, y, width, height = self._rect(rectangle, self.pico.SDL_Rect)
        return self._shape(self.quad(x + .5, y + .5, width - 1, height - 1), 0x0002)

    def draw_point(self, renderer, x, y):
        return self._shape(((x + .5, y + .5),), 0x0000)

    def draw_line(self, renderer, x1, y1, x2, y2):
        return self._shape(((x1 + .5, y1 + .5), (x2 + .5, y2 + .5)), 0x0001)

    def draw_lines(self, renderer, points, count):
        return self._shape(tuple((points[index].x + .5, points[index].y + .5) for index in range(count)), 0x0003)

    def copy(self, renderer, handle, source, destination):
        return self._copy(handle, source, destination, self.pico.SDL_Rect)

    def copy_float(self, renderer, handle, source, destination):
        return self._copy(handle, source, destination, self.pico.SDL_FRect)

    def copy_extended(self, renderer, handle, source, destination, angle, center, flip):
        return self._copy(handle, source, destination, self.pico.SDL_Rect, angle, center, flip)

    def copy_extended_float(self, renderer, handle, source, destination, angle, center, flip):
        return self._copy(handle, source, destination, self.pico.SDL_FRect, angle, center, flip)

    def _copy(self, handle, source, destination, structure, angle=0, center=None, flip=0):
        p = self.pico
        texture = self.texture_for(handle)
        x, y, width, height = self._rect(destination, structure)
        source_quad = (self._rect(source, p.SDL_Rect) if source else (0, 0, texture.width, texture.height))
        left, top, wide, tall = source_quad
        u0, u1 = left / texture.width, (left + wide) / texture.width
        v0, v1 = top / texture.height, (top + tall) / texture.height
        if flip & p.SDL_FLIP_HORIZONTAL:
            u0, u1 = u1, u0
        if flip & p.SDL_FLIP_VERTICAL:
            v0, v1 = v1, v0
        points = self.quad(x, y, width, height)
        if angle:
            if center:
                point = pointed(center, p.SDL_FPoint if structure is p.SDL_FRect else p.SDL_Point)
                pivot_x, pivot_y = x + point.x, y + point.y
            else:
                pivot_x, pivot_y = x + width * .5, y + height * .5
            cosine, sine = cos(radians(angle)), sin(radians(angle))
            points = tuple((pivot_x + dx * cosine - dy * sine, pivot_y + dx * sine + dy * cosine)
                           for px, py in points for dx, dy in ((px - pivot_x, py - pivot_y),))
        texels = ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
        return self._draw(self._vertices(points, texture.modulation, texels), 4, QUADS, texture)

    def read_pixels(self, renderer, rectangle, pixel_format, pixels, pitch):
        output_width, output_height = self.target_size()
        x, y, width, height = (self._rect(rectangle, self.pico.SDL_Rect) if rectangle
                               else (0, 0, output_width, output_height))
        if (not pixels or width <= 0 or height <= 0 or min(x, y) < 0 or
                x + width > output_width or y + height > output_height or pitch < width * 4):
            return -1
        gl_format, gl_type = self._format(pixel_format)
        buffer = (ct.c_ubyte * (width * height * 4))()
        self._target_state()
        bottom = output_height - y - height if self.target is None else y
        with self._pixel_transfer(pack=True, row_length=0):
            self.ReadPixels(x, bottom, width, height, gl_format, gl_type, buffer)
        for row in range(height):
            source = height - 1 - row if self.target is None else row
            ct.memmove(address(pixels) + row * pitch, ct.addressof(buffer) + source * width * 4, width * 4)
        return 0

    def flush(self, renderer):
        self.external_draw()
        return 0

    def present(self, renderer):
        self.external_draw()
        self.pico.SDL_GL_SwapWindow(self.window)

    def close(self):
        if self.context:
            for texture in list(self.textures.values()):
                self.destroy_texture(texture.handle)
            self.pico.SDL_GL_DeleteContext(self.context)
            self.context = None


class PicoNativeGl:
    """Pico2D가 창·입출력을 열 때 렌더러 생성과 렌더 호출을 OpenGL로 연결한다."""

    METHODS = {
        "SDL_GetRendererInfo": "get_info",
        "SDL_GetRendererOutputSize": "get_output_size",
        "SDL_RenderSetLogicalSize": "set_logical_size",
        "SDL_RenderGetScale": "get_scale",
        "SDL_RenderSetScale": "set_scale",
        "SDL_RenderGetViewport": "get_viewport",
        "SDL_RenderSetViewport": "set_viewport",
        "SDL_RenderGetClipRect": "get_clip",
        "SDL_RenderSetClipRect": "set_clip",
        "SDL_RenderIsClipEnabled": "clip_enabled",
        "SDL_GetRenderTarget": "get_target",
        "SDL_SetRenderTarget": "set_target",
        "SDL_CreateTexture": "create_texture",
        "SDL_DestroyTexture": "destroy_texture",
        "SDL_CreateTextureFromSurface": "texture_from_surface",
        "IMG_LoadTexture": "load_texture",
        "SDL_QueryTexture": "query_texture",
        "SDL_UpdateTexture": "update_texture",
        "SDL_SetTextureScaleMode": "set_texture_scale",
        "SDL_SetTextureBlendMode": "set_texture_blend",
        "SDL_GetTextureBlendMode": "get_texture_blend",
        "SDL_SetTextureColorMod": "set_texture_color",
        "SDL_GetTextureColorMod": "get_texture_color",
        "SDL_SetTextureAlphaMod": "set_texture_alpha",
        "SDL_GetTextureAlphaMod": "get_texture_alpha",
        "SDL_GL_BindTexture": "gl_bind_texture",
        "SDL_GL_UnbindTexture": "gl_unbind_texture",
        "SDL_SetRenderDrawColor": "set_draw_color",
        "SDL_GetRenderDrawColor": "get_draw_color",
        "SDL_SetRenderDrawBlendMode": "set_draw_blend",
        "SDL_GetRenderDrawBlendMode": "get_draw_blend",
        "SDL_RenderClear": "clear",
        "SDL_RenderGeometry": "geometry",
        "SDL_RenderFillRect": "fill_rect",
        "SDL_RenderFillRects": "fill_rects",
        "SDL_RenderDrawRect": "draw_rect",
        "SDL_RenderDrawPoint": "draw_point",
        "SDL_RenderDrawLine": "draw_line",
        "SDL_RenderDrawLines": "draw_lines",
        "SDL_RenderCopy": "copy",
        "SDL_RenderCopyF": "copy_float",
        "SDL_RenderCopyEx": "copy_extended",
        "SDL_RenderCopyExF": "copy_extended_float",
        "SDL_RenderReadPixels": "read_pixels",
        "SDL_RenderFlush": "flush",
        "SDL_RenderPresent": "present",
    }

    def __init__(self, pico):
        self.pico = pico
        self.renderer = None
        self.originals = {}
        self._replace("SDL_CreateWindow", self._create_window)
        self._replace("SDL_CreateRenderer", self._create_renderer)
        self._replace("SDL_DestroyRenderer", self._destroy_renderer)

    def _replace(self, name, function):
        self.originals[name] = getattr(self.pico, name)
        setattr(self.pico, name, function)

    def _create_window(self, title, x, y, width, height, flags):
        p = self.pico
        for option, value in ((p.SDL_GL_DOUBLEBUFFER, 1), (p.SDL_GL_CONTEXT_MAJOR_VERSION, 4),
                              (p.SDL_GL_CONTEXT_MINOR_VERSION, 3),
                              (p.SDL_GL_CONTEXT_PROFILE_MASK, p.SDL_GL_CONTEXT_PROFILE_COMPATIBILITY)):
            if p.SDL_GL_SetAttribute(option, value):
                raise RuntimeError("직접 OpenGL 컨텍스트 조건을 설정할 수 없다.")
        return self.originals["SDL_CreateWindow"](title, x, y, width, height, flags | p.SDL_WINDOW_OPENGL)

    def _create_renderer(self, window, index, flags):
        if not window:
            raise RuntimeError("직접 OpenGL 창을 만들 수 없다.")
        renderer = self.renderer = NativeGlRenderer(self.pico, window,
                                                     bool(flags & self.pico.SDL_RENDERER_PRESENTVSYNC))
        self.pico.fdrive_native_gl = renderer
        for name, method in self.METHODS.items():
            self._replace(name, getattr(renderer, method))
        # 기존 캐시 키의 포인터 규약을 유지한다. SDL 렌더러는 생성하지 않는다.
        return ct.pointer(self.pico.SDL_Renderer())

    def _destroy_renderer(self, renderer):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None

    def restore(self):
        try:
            self._destroy_renderer(self.renderer)
        finally:
            for name, original in self.originals.items():
                setattr(self.pico, name, original)
            self.originals.clear()
            if hasattr(self.pico, "fdrive_native_gl"):
                del self.pico.fdrive_native_gl
