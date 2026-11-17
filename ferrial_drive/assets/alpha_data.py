"""원본 PNG에 대응하는 R8 제작 데이터. 런타임은 이미지 라이브러리에 의존하지 않는다."""

from hashlib import sha256
from io import BytesIO
from math import ceil
import os
from pathlib import Path
import struct
import tempfile


ALPHA_MAGIC = b"FDALPHA1"
ALPHA_HEADER = struct.Struct("<8sII32s32s")
ALPHA_SCALES = (1.0, 0.5, 0.25, 0.125)


def alpha_data_path(source, *, scale=None):
    source = Path(source)
    if scale is not None and scale not in ALPHA_SCALES:
        raise ValueError("그림자 배율은 1, 0.5, 0.25, 0.125 중 하나다.")
    suffix = "" if scale is None else f".x{int(1/scale)}"
    return source.with_suffix(source.suffix + ".alpha8" + suffix)


def alpha_dimensions(size, scale):
    if scale not in ALPHA_SCALES:
        raise ValueError("그림자 배율은 1, 0.5, 0.25, 0.125 중 하나다.")
    return tuple(max(1,ceil(value*scale)) for value in size)


def png_dimensions(source):
    """전체 이미지 디코딩 없이 원본 시트의 논리 크기를 확인한다."""
    with Path(source).open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("알파 전용 데이터의 원본은 PNG여야 한다.")
    return struct.unpack(">II", header[16:24])


def read_alpha_data(source, *, scale=None):
    """파일 부재·원본 변경은 None, 손상된 제작 데이터는 오류로 구분한다."""
    source = Path(source)
    try:
        stream = alpha_data_path(source,scale=scale).open("rb")
    except FileNotFoundError:
        return None
    with stream:
        header = stream.read(ALPHA_HEADER.size)
        if len(header) != ALPHA_HEADER.size:
            raise ValueError("알파 전용 데이터 헤더가 잘렸다.")
        magic, width, height, source_hash, alpha_hash = ALPHA_HEADER.unpack(header)
        if magic != ALPHA_MAGIC or min(width, height) < 1:
            raise ValueError("알파 전용 데이터 규격 오류")
        expected_size = width * height
        if os.fstat(stream.fileno()).st_size != ALPHA_HEADER.size + expected_size:
            raise ValueError("알파 전용 데이터 크기 불일치")
        if sha256(source.read_bytes()).digest() != source_hash:
            return None
        if scale is not None and (width,height) != alpha_dimensions(png_dimensions(source),scale):
            raise ValueError("그림자 데이터와 요청한 배율이 다르다.")
        alpha = stream.read(expected_size)
    if len(alpha) != expected_size or sha256(alpha).digest() != alpha_hash:
        raise ValueError("알파 전용 데이터 해시 불일치")
    return width, height, alpha


def prepare_alpha_data(source, *, scale=1.0, scaled_path=False):
    """PNG 원본을 보존하고 같은 폴더의 호환/배율 알파 파일을 원자적으로 갱신한다."""
    from PIL import Image

    if scale not in ALPHA_SCALES:
        raise ValueError("그림자 배율은 1, 0.5, 0.25, 0.125 중 하나다.")
    source = Path(source)
    source_bytes = source.read_bytes()
    with Image.open(BytesIO(source_bytes)) as image:
        source_width, source_height = image.size
        channel = image.convert("RGBA").getchannel("A")
        width, height = alpha_dimensions((source_width,source_height),scale)
        if scale != 1:
            channel = channel.resize((width, height), Image.Resampling.BOX)
        alpha = channel.tobytes()
    destination = alpha_data_path(source,scale=scale if scaled_path else None)
    header = ALPHA_HEADER.pack(ALPHA_MAGIC, width, height,
                               sha256(source_bytes).digest(), sha256(alpha).digest())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".alpha-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(header)
            stream.write(alpha)
        if source.read_bytes() != source_bytes:
            raise RuntimeError("변환 중 원본 이미지가 변경됐다. 다시 준비한다.")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"source": str(source), "alpha_data": str(destination), "width": width, "height": height,
            "source_size": [source_width, source_height], "scale": scale,
            "source_bytes": len(source_bytes), "alpha_bytes": len(alpha), "file_bytes": len(header) + len(alpha)}
