"""OpenGL 프로그램의 컴파일·링크·uniform 위치와 수명."""

import ctypes as ct

from ferrial_drive.diagnostics.gpu_profile import bind_gl


VERTEX_STAGE = 0x8B31
FRAGMENT_STAGE = 0x8B30
COMPUTE_STAGE = 0x91B9


class ShaderProgram:
    def __init__(self, pico, stages, uniforms=()):
        uint, integer, pointer = ct.c_uint, ct.c_int, ct.c_void_p
        signatures = {
            "glCreateShader": (uint, [uint]),
            "glShaderSource": (None, [uint, integer, pointer, pointer]),
            "glCompileShader": (None, [uint]),
            "glGetShaderiv": (None, [uint, uint, pointer]),
            "glGetShaderInfoLog": (None, [uint, integer, pointer, pointer]),
            "glDeleteShader": (None, [uint]),
            "glCreateProgram": (uint, []),
            "glAttachShader": (None, [uint, uint]),
            "glLinkProgram": (None, [uint]),
            "glGetProgramiv": (None, [uint, uint, pointer]),
            "glGetProgramInfoLog": (None, [uint, integer, pointer, pointer]),
            "glDeleteProgram": (None, [uint]),
            "glGetUniformLocation": (integer, [uint, ct.c_char_p]),
        }
        gl = {name: bind_gl(pico, name, result, args) for name, (result, args) in signatures.items()}
        self.handle = 0
        self._delete = gl["glDeleteProgram"]
        shaders = []
        try:
            for stage, source in stages:
                shader = gl["glCreateShader"](stage)
                if not shader:
                    raise RuntimeError(f"OpenGL 셰이더 생성 실패 ({stage:#x})")
                shaders.append(shader)
                code = ct.c_char_p(source)
                gl["glShaderSource"](shader, 1, ct.byref(code), None)
                gl["glCompileShader"](shader)
                self._check(shader, 0x8B81, gl["glGetShaderiv"], gl["glGetShaderInfoLog"],
                            f"OpenGL 셰이더 컴파일 실패 ({stage:#x})")
            self.handle = gl["glCreateProgram"]()
            if not self.handle:
                raise RuntimeError("OpenGL 프로그램 생성 실패")
            for shader in shaders:
                gl["glAttachShader"](self.handle, shader)
            gl["glLinkProgram"](self.handle)
            self._check(self.handle, 0x8B82, gl["glGetProgramiv"], gl["glGetProgramInfoLog"],
                        "OpenGL 프로그램 링크 실패")
            self.uniforms = {name: gl["glGetUniformLocation"](self.handle, name.encode()) for name in uniforms}
        except BaseException:
            self.close()
            raise
        finally:
            for shader in shaders:
                gl["glDeleteShader"](shader)

    @staticmethod
    def _check(handle, status, inspect, read_log, description):
        result = ct.c_int()
        inspect(handle, status, ct.byref(result))
        if not result.value:
            inspect(handle, 0x8B84, ct.byref(result))
            message = ct.create_string_buffer(max(1, result.value))
            read_log(handle, len(message), None, message)
            raise RuntimeError(f"{description} ({message.value.decode(errors='replace')})")

    def close(self):
        if self.handle:
            self._delete(self.handle)
            self.handle = 0
