"""로컬 KTX2·Oodle 인코더와 BC7 데이터. import 시 SDK·창을 로드하지 않는다."""

import ctypes as ct
import os
from pathlib import Path
from shutil import which
import subprocess
import zlib


def bc7_size(width, height):
    if width < 1 or height < 1:
        raise ValueError("텍스처 크기는 양수다.")
    return ((width + 3) // 4) * ((height + 3) // 4) * 16


def texture_payload_size(codec, width, height):
    """드라이버 정렬을 제외한 저장 형식의 논리 페이로드 크기다."""
    if width < 1 or height < 1:
        raise ValueError("텍스처 크기는 양수다.")
    channels = {"rgba_zlib": 4, "rgb8_zlib": 3, "rg8_zlib": 2, "a8_zlib": 1}
    if codec in channels:
        return width * height * channels[codec]
    if codec in ("bc7_zlib", "ktx2_uastc"):
        return bc7_size(width, height)
    raise ValueError("지원하지 않는 아틀라스 형식이다.")


class OodleSurface(ct.Structure):
    _fields_ = [("pixels", ct.c_void_p), ("row_stride_bytes", ct.c_ssize_t),
                ("width", ct.c_int32), ("height", ct.c_int32)]


class OodleOptions(ct.Structure):
    _fields_ = [(name, ct.c_int32) for name in
                ("effort", "metric", "bcn_flags", "universal_tiling", "rdo_flags",
                 "use_bc3_alpha_lambda", "bc3_alpha_lambda")] + [("reserved", ct.c_uint32 * 8)]


class OodleEncoder:
    """설치된 SDK를 참조한다. DLL·헤더·라이브러리를 복사하거나 재배포하지 않는다."""

    def __init__(self, library):
        self.library_path = Path(library).resolve()
        self.dll = ct.CDLL(str(self.library_path))
        self.encode = self.dll.OodleTex_EncodeBCN_RDO_Ex
        self.encode.restype = ct.c_int
        self.encode.argtypes = [ct.c_int, ct.c_void_p, ct.c_ssize_t,
                                ct.POINTER(OodleSurface), ct.c_ssize_t, ct.c_int, ct.c_void_p,
                                ct.c_int, ct.POINTER(OodleOptions), ct.c_int, ct.c_void_p]

    def bc7(self, pixels, width, height, *, rdo_lambda=30):
        if len(pixels) != width * height * 4 or rdo_lambda < 0:
            raise ValueError("RGBA 크기 또는 RDO 설정 오류")
        source = ct.create_string_buffer(pixels)
        target = ct.create_string_buffer(bc7_size(width, height))
        surface = OodleSurface(ct.cast(source, ct.c_void_p), width * 4, width, height)
        options = OodleOptions()
        options.effort = 20
        error = self.encode(11, target, len(target) // 16, ct.byref(surface), 1, 1,
                            None, rdo_lambda, ct.byref(options), -1, None)
        if error:
            raise RuntimeError(f"Oodle BC7 인코딩 실패: {error}")
        return target.raw


def find_ktx_library():
    """파츠 KTX2 프로필에 사용할 로컬 libktx를 찾는다."""
    if configured := os.getenv("FDRIVE_KTX_LIBRARY"):
        return Path(configured).resolve(strict=True)
    if executable := which("ktx"):
        library = Path(executable).with_name("ktx.dll")
        if library.is_file():
            return library
    tool_dir = Path(__file__).resolve().parents[2] / "automate/bin"
    candidates = sorted(tool_dir.glob("ktx-*/bin/ktx.dll"), reverse=True)
    if candidates:
        return candidates[0]
    raise FileNotFoundError("KTX2 색상에 libktx가 필요하다. FDRIVE_KTX_LIBRARY에 ktx.dll 경로를 지정한다.")


class KtxDecoder:
    """공식 libktx로 UASTC를 BC7으로 변환한다. CPU RGBA 디코딩을 거치지 않는다."""

    def __init__(self, library):
        self.library_path = Path(library).resolve()
        self.dll = ct.CDLL(str(self.library_path))
        signatures = {
            "ktxTexture2_CreateFromMemory": (ct.c_int, [ct.c_void_p, ct.c_size_t, ct.c_uint, ct.POINTER(ct.c_void_p)]),
            "ktxTexture2_TranscodeBasis": (ct.c_int, [ct.c_void_p, ct.c_int, ct.c_uint]),
            "ktxTexture_GetData": (ct.c_void_p, [ct.c_void_p]),
            "ktxTexture_GetDataSize": (ct.c_size_t, [ct.c_void_p]),
            "ktxTexture2_Destroy": (None, [ct.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, args

    def bc7(self, data, width, height):
        source = ct.create_string_buffer(data)
        texture = ct.c_void_p()
        error = self.dll.ktxTexture2_CreateFromMemory(source, len(data), 1, ct.byref(texture))
        if error:
            raise ValueError(f"KTX2 로딩 실패: {error}")
        try:
            error = self.dll.ktxTexture2_TranscodeBasis(texture, 6, 0)
            if error:
                raise RuntimeError(f"KTX2→BC7 변환 실패: {error}")
            size = self.dll.ktxTexture_GetDataSize(texture)
            if size != bc7_size(width, height):
                raise ValueError("한 레벨의 BC7 크기와 다르다.")
            return ct.string_at(self.dll.ktxTexture_GetData(texture), size)
        finally:
            self.dll.ktxTexture2_Destroy(texture)


def encode_ktx(executable, raw_path, destination, width, height):
    command = [str(executable), "create", "--format", "R8G8B8A8_UNORM", "--raw",
               "--width", str(width), "--height", str(height), "--assign-tf", "linear",
               "--encode", "uastc", "--uastc-quality", "2", "--uastc-rdo",
               "--uastc-rdo-l", "1", "--uastc-rdo-m", "--threads", "1", "--zstd", "6",
               str(raw_path), str(destination)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError("KTX 인코딩 실패: " + result.stderr[-2000:])


def unpack_payload(codec, data, width, height, *, ktx=None):
    if codec in ("rgba_zlib", "rgb8_zlib", "rg8_zlib", "a8_zlib", "bc7_zlib"):
        expected = texture_payload_size(codec, width, height)
        stream = zlib.decompressobj()
        payload = stream.decompress(data, expected + 1)
        if len(payload) != expected or not stream.eof or stream.unused_data:
            raise ValueError("압축 데이터 크기가 선언과 다르다.")
        return payload, codec == "bc7_zlib"
    if codec == "ktx2_uastc":
        if ktx is None:
            raise RuntimeError("KTX2 변환에 libktx 경로가 필요하다.")
        return ktx.bc7(data, width, height), True
    raise ValueError("지원하지 않는 아틀라스 형식이다.")
