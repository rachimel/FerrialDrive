"""UHD 630 검토용 OpenGL 기능 가드. GPU 처리량·드라이버를 에뮬레이션하지 않는다."""

from contextvars import ContextVar
import ctypes as ct
import os
import re


_ACTIVE = ContextVar("fdrive_gpu_profile", default=None)

# 현재 프로젝트가 사용하는 OpenGL <= 4.5 기능만 허용한다. 새 함수는 검토 후 추가한다.
PROJECT_GL_FUNCTIONS = frozenset("""glActiveTexture glAttachShader glBegin glBeginQuery glBindBuffer glBindBufferBase glBindTexture
glBlendEquationSeparate glBlendFuncSeparate glBufferData glBufferSubData glClearBufferData
glClientWaitSync glCompileShader glCompressedTexImage2D glCompressedTexSubImage2D glCopyBufferSubData glCreateProgram
glCreateShader glDeleteBuffers glDeleteProgram glDeleteQueries glDeleteShader glDeleteSync
glDeleteTextures glDisable glDispatchCompute glDrawArraysIndirect glDrawArraysInstanced
glEnable glEnd glEndQuery glFenceSync glFinish glFlush glGenBuffers glGenQueries glGenTextures
glGetBufferSubData glGetError glGetInteger64v glGetIntegeri_v glGetIntegerv glGetProgramInfoLog
glGetProgramiv glGetQueryiv glGetQueryObjectiv glGetQueryObjectui64v glGetShaderInfoLog
glGetShaderiv glGetString glGetStringi glGetTexLevelParameteriv glGetUniformLocation glIsEnabled glLinkProgram
glMemoryBarrier glPixelStorei glPopAttrib glPopClientAttrib glPushAttrib glPushClientAttrib
glScissor glShaderSource glTexCoord2f glTexImage2D glTexParameteri
glTexStorage2D glTexSubImage2D glUniform1f glUniform1i glUniform1ui glUniform2f glUniform4f glUniform4fv
glUseProgram glVertex2f glViewport
""".split())

# 실기에서 조회하지 않은 보수적 검사 상한이다. UHD 630 실측값으로 취급하지 않는다.
CAPS = {0x0D33: 16384, 0x8B4D: 16, 0x8872: 16, 0x90DE: 128 * 1024**2,
        0x90DD: 8, 0x90EB: 1024, 0x8262: 32768}


class GpuProfileViolation(RuntimeError):
    pass


def raw_bind_gl(pico, name, result, arguments):
    address = pico.SDL_GL_GetProcAddress(name.encode())
    if not address:
        raise RuntimeError("OpenGL 기능 미지원: " + name)
    prototype = ct.WINFUNCTYPE if os.name == "nt" else ct.CFUNCTYPE
    return prototype(result, *arguments)(address)


def bind_gl(pico, name, result, arguments):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.check_function(name)
    function = raw_bind_gl(pico, name, result, arguments)
    return profile.wrap(name, function) if profile is not None else function


class Uhd630Profile:
    """프로젝트 GL 호출과 SDL_CreateTexture를 검사하는 단일 렌더 스레드용 범위."""

    def __init__(self, pico):
        self.pico = pico
        self.bound_functions, self.violations = set(), []
        self.actual_caps, self.caps = {}, dict(CAPS)
        self.shader_versions = set()
        self.token = self.original_create = None
        self.original_loaders = {}

    def reject(self, message):
        self.violations.append(message)
        raise GpuProfileViolation(message)

    def check_function(self, name):
        if name not in PROJECT_GL_FUNCTIONS:
            self.reject("UHD 630 검토 프로필에서 허용하지 않은 함수: " + name)
        self.bound_functions.add(name)

    def texture_size(self, width, height):
        if min(width, height) < 0 or max(width, height) > self.caps[0x0D33]:
            self.reject(f"2D 텍스처 크기 상한 초과: {width}x{height}")

    def shader_source(self, source):
        # 주석 안의 지시문은 제외한다. 전체 GLSL 자원 사용 분석은 수행하지 않는다.
        source = source.replace(b"\\\r\n", b"").replace(b"\\\n", b"")
        source = re.sub(rb"/\*.*?\*/|//[^\n]*", b"", source, flags=re.S)
        versions = re.findall(rb"^\s*#\s*version\s+(\d+)", source, re.M)
        for value in versions:
            self.shader_versions.add(int(value))
            if int(value) > 450:
                self.reject("GLSL 450 초과 셰이더")
        if re.search(rb"^\s*#\s*extension\s+\S+\s*:\s*(require|enable|warn)", source, re.M):
            self.reject("프로필 밖 GLSL 확장 활성화")
        local = dict((axis.decode(), int(value)) for axis, value in
                     re.findall(rb"local_size_([xyz])\s*=\s*(\d+)\b", source))
        if local:
            sizes = [local.get(axis, 1) for axis in "xyz"]
            if any(value > limit for value, limit in zip(sizes, (1024, 1024, 64))) or sizes[0]*sizes[1]*sizes[2] > 1024:
                self.reject("Compute local workgroup 상한 초과")

    def wrap(self, name, function):
        checked = {"glShaderSource", "glTexImage2D", "glCompressedTexImage2D", "glTexSubImage2D",
                   "glTexStorage2D", "glCompressedTexSubImage2D",
                   "glBufferData", "glDispatchCompute", "glActiveTexture", "glBindBufferBase",
                   "glGetIntegerv", "glGetInteger64v", "glGetIntegeri_v", "glTexParameteri"}
        if name not in checked:
            return function

        def guarded(*args):
            if name == "glShaderSource":
                strings = ct.cast(args[2], ct.POINTER(ct.c_void_p))
                lengths = ct.cast(args[3], ct.POINTER(ct.c_int)) if args[3] else None
                self.shader_source(b"".join(ct.string_at(strings[i], lengths[i]) if lengths and lengths[i] >= 0
                                           else ct.string_at(strings[i]) for i in range(args[1])))
            elif name in ("glTexImage2D", "glCompressedTexImage2D"):
                self.texture_size(args[3], args[4])
                if name == "glCompressedTexImage2D" and args[2] not in (0x8E8C, 0x8E8D, 0x8E8E, 0x8E8F):
                    self.reject("프로필 밖 압축 텍스처 형식")
            elif name == "glTexStorage2D":
                self.texture_size(args[3], args[4])
            elif name in ("glTexSubImage2D", "glCompressedTexSubImage2D"):
                self.texture_size(args[2] + args[4], args[3] + args[5])
                if name == "glCompressedTexSubImage2D" and args[6] not in (0x8E8C, 0x8E8D, 0x8E8E, 0x8E8F):
                    self.reject("지원하지 않는 압축 텍스처 형식이다.")
            elif name == "glBufferData" and args[1] > self.caps[0x90DE]:
                self.reject("단일 버퍼 128MiB 상한 초과")
            elif name == "glDispatchCompute" and any(value > 65535 for value in args):
                self.reject("Compute dispatch 상한 초과")
            elif name == "glActiveTexture" and args[0] - 0x84C0 >= self.caps[0x8B4D]:
                self.reject("동시 텍스처 단위 상한 초과")
            elif name == "glBindBufferBase" and args[0] == 0x90D2 and args[1] >= self.caps[0x90DD]:
                self.reject("SSBO binding 상한 초과")
            elif name == "glTexParameteri" and args[1] == 0x84FE:
                self.reject("선택적 이방성 필터 확장 사용")
            result = function(*args)
            if name in ("glGetIntegerv", "glGetInteger64v") and args[0] in self.caps:
                integer = ct.c_int64 if name == "glGetInteger64v" else ct.c_int
                value = ct.cast(args[1], ct.POINTER(integer))
                value[0] = min(value[0], self.caps[args[0]])
            elif name == "glGetIntegeri_v" and args[0] in (0x91BE, 0x91BF):
                limit = 65535 if args[0] == 0x91BE else (1024, 1024, 64)[args[1]]
                value = ct.cast(args[2], ct.POINTER(ct.c_int))
                value[0] = min(value[0], limit)
            return result

        return guarded

    def __enter__(self):
        if _ACTIVE.get() is not None:
            raise RuntimeError("GPU 프로필은 중첩할 수 없다.")
        get_integer = raw_bind_gl(self.pico, "glGetIntegerv", None, [ct.c_uint, ct.c_void_p])
        for enum, ceiling in CAPS.items():
            value = ct.c_int()
            get_integer(enum, ct.byref(value))
            if value.value <= 0:
                raise RuntimeError(f"GPU 제한 조회 실패: {enum:#x}")
            self.actual_caps[enum] = value.value
            self.caps[enum] = min(value.value, ceiling)
        self.original_create = self.pico.SDL_CreateTexture
        self.original_loaders = {name: getattr(self.pico, name) for name in
                                 ("SDL_CreateTextureFromSurface", "IMG_LoadTexture")}

        def create(renderer, pixel_format, access, width, height):
            self.texture_size(width, height)
            return self.original_create(renderer, pixel_format, access, width, height)

        self.pico.SDL_CreateTexture = create
        # 이미지·글꼴 경로는 SDL 내부에서 텍스처를 만든다. 반환 직후 크기를 확인한다.
        for name, original in self.original_loaders.items():

            def checked_load(*args, function=original):
                texture = function(*args)
                if texture:
                    width, height = ct.c_int(), ct.c_int()
                    if self.pico.SDL_QueryTexture(texture, None, None, ct.byref(width), ct.byref(height)) != 0:
                        self.pico.SDL_DestroyTexture(texture)
                        self.reject("SDL 텍스처 크기 조회 실패")
                    try:
                        self.texture_size(width.value, height.value)
                    except BaseException:
                        self.pico.SDL_DestroyTexture(texture)
                        raise
                return texture

            setattr(self.pico, name, checked_load)
        self.token = _ACTIVE.set(self)
        return self

    def __exit__(self, *exc):
        self.pico.SDL_CreateTexture = self.original_create
        for name, function in self.original_loaders.items():
            setattr(self.pico, name, function)
        _ACTIVE.reset(self.token)

    def report(self):
        return {"name": "uhd630_gl45_conservative", "actual_caps": {hex(k): v for k, v in self.actual_caps.items()},
                "effective_caps": {hex(k): v for k, v in self.caps.items()},
                "bound_functions": sorted(self.bound_functions), "shader_versions": sorted(self.shader_versions),
                "violations": self.violations,
                "coverage": "프로젝트 공통 bind_gl와 SDL 텍스처 생성 3경로. SDL/드라이버 내부 GL 호출 및 전체 GLSL 자원 검증 제외.",
                "semantics": "UHD 630 실측 프로필이 아닌 보수적 기능 가드. 처리량·대역폭·VRAM 용량을 재현하지 않는다."}
