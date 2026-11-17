"""검정 그림자의 원래 알파를 R8로 보존하는 Pico2D OpenGL 텍스처."""

import ctypes as ct

from ferrial_drive.assets.alpha_data import alpha_dimensions, png_dimensions, read_alpha_data
from ferrial_drive.diagnostics.texture_metrics import bind_gl
from .pico_interpolation import read_rgba_image


def load_alpha_texture(pico, path, sampler, *, expected_size=None, scale=None):
    if expected_size is not None and png_dimensions(path) != expected_size:
        raise ValueError(f"그림자 PNG 크기와 시트 메타데이터 불일치: {path}")
    prepared = read_alpha_data(path,scale=scale)
    if prepared is None and scale is not None:
        legacy = read_alpha_data(path)
        if legacy is not None and legacy[:2] == alpha_dimensions(png_dimensions(path),scale):
            prepared = legacy
        else:
            raise FileNotFoundError(f"그림자 {scale:g}배 데이터가 없다. alpha-textures --quality-profiles로 준비한다: {path}")
    if prepared is None:
        width, height, rgba = read_rgba_image(pico, path)
        alpha = rgba[3::4]
    else:
        width, height, alpha = prepared
    texture = pico.SDL_CreateTexture(pico.renderer, pico.SDL_PIXELFORMAT_RGBA32,
                                     pico.SDL_TEXTUREACCESS_STATIC, width, height)
    if not texture:
        raise RuntimeError("그림자 알파 텍스처 생성 실패")
    upload = bind_gl(pico, "glTexImage2D", None,
                     [ct.c_uint, ct.c_int, ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                      ct.c_uint, ct.c_uint, ct.c_void_p])
    parameter = bind_gl(pico, "glTexParameteri", None, [ct.c_uint, ct.c_uint, ct.c_int])
    pixel_store = bind_gl(pico, "glPixelStorei", None, [ct.c_uint, ct.c_int])
    query = bind_gl(pico, "glGetTexLevelParameteriv", None, [ct.c_uint, ct.c_int, ct.c_uint, ct.c_void_p])
    try:
        if pico.SDL_SetTextureScaleMode(texture,pico.SDL_ScaleModeLinear):
            raise RuntimeError("그림자 Bilinear 필터 설정 실패")
        with sampler.batch():
            was_enabled = sampler.glIsEnabled(0x0DE1)
            texw, texh = ct.c_float(), ct.c_float()
            if pico.SDL_GL_BindTexture(texture, ct.byref(texw), ct.byref(texh)):
                raise RuntimeError("그림자 알파 OpenGL 연결 실패")
            unpack_keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
            unpack_state = [sampler.integer(key) for key in unpack_keys]
            try:
                for key, value in zip(unpack_keys, (1, 0, 0, 0)):
                    pixel_store(key, value)
                upload(0x0DE1, 0, 0x8229, width, height, 0, 0x1903, 0x1401, ct.create_string_buffer(alpha))
            finally:
                for key, value in zip(unpack_keys, unpack_state):
                    pixel_store(key, value)
            # 색상은 검정, 알파는 원래 입력의 A를 담은 R 채널로 재구성한다.
            for name in (0x8E42, 0x8E43, 0x8E44):
                parameter(0x0DE1, name, 0)
            parameter(0x0DE1, 0x8E45, 0x1903)
            actual = ct.c_int()
            query(0x0DE1, 0, 0x1003, ct.byref(actual))
            if actual.value != 0x8229:
                raise RuntimeError("그림자 텍스처가 실제 R8로 생성되지 않았다.")
            pico.SDL_GL_UnbindTexture(texture)
            (sampler.glEnable if was_enabled else sampler.glDisable)(0x0DE1)
        return texture
    except BaseException:
        pico.SDL_DestroyTexture(texture)
        raise
