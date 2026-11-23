"""페이지별 CPU 준비 Work와 제한된 병렬 대기열. SDL·OpenGL을 호출하지 않는다."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import mmap
from pathlib import Path
from threading import Lock

from ferrial_drive.diagnostics import TimingRecorder
from .texture_codecs import KtxDecoder, unpack_payload


DEFAULT_DECODE_WORKERS = 4


class TexturePageArchive:
    """완성된 페이지 묶음에서 독립적으로 압축된 바이트 범위를 읽는다."""

    def __init__(self):
        self.lock = Lock()
        self.files = {}

    def read(self, path, offset, length):
        with self.lock:
            view = self.files.get(path)
            if view is None:
                with path.open("rb") as stream:
                    view = self.files[path] = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        return view[offset:offset + length]

    def close(self):
        for view in self.files.values():
            view.close()
        self.files.clear()


@dataclass(frozen=True)
class TexturePagePayload:
    key: tuple
    size: tuple
    codec: str
    disk_bytes: int
    pixels: bytes
    compressed: bool


class TexturePageWork:
    """한 페이지의 읽기·검증·해제를 소유한다. lock은 상태·결과 교환에만 사용한다."""

    def __init__(self, page, directory, *, timings=None, ktx_library=None, archive=None):
        self.path = (Path(directory) / page["file"]).resolve()
        self.key = (self.path, page["sha256"])
        self.size = (page["width"], page["height"])
        self.codec = page["codec"]
        self.timings = timings or TimingRecorder(enabled=False)
        self.ktx_library = ktx_library
        self.archive = archive
        self.offset, self.length = page.get("offset"), page.get("length")
        self._lock = Lock()
        self._state = "pending"
        self._result = None

    @property
    def state(self):
        with self._lock:
            return self._state

    def run(self):
        """워커에서 페이지를 읽고 검증한 뒤 디코드한다."""
        with self._lock:
            if self._state != "pending":
                raise RuntimeError("같은 페이지 Work는 한 번만 실행한다.")
            self._state = "running"
        try:
            if min(self.size) < 1:
                raise ValueError("페이지 크기는 양수여야 한다.")
            with self.timings.scope("load.file_read"):
                if self.offset is None:
                    packed = self.path.read_bytes()
                else:
                    if self.offset < 0 or self.length is None or self.length < 1:
                        raise ValueError("아틀라스 페이지 바이트 범위가 올바르지 않다.")
                    if self.archive is not None:
                        packed = self.archive.read(self.path, self.offset, self.length)
                    else:
                        with self.path.open("rb") as stream:
                            stream.seek(self.offset)
                            packed = stream.read(self.length)
                    if len(packed) != self.length:
                        raise ValueError(f"아틀라스 페이지 범위가 잘렸다: {self.path.name}")
            with self.timings.scope("load.integrity"):
                if hashlib.sha256(packed).hexdigest() != self.key[1]:
                    raise ValueError(f"아틀라스 파일 해시 불일치: {self.path.name}")
            with self.timings.scope("load.decode"):
                # KTX 변환 객체도 Work별로 소유하며 여러 스레드가 공유하지 않는다.
                decoder = KtxDecoder(self.ktx_library) if self.codec == "ktx2_uastc" else None
                pixels, compressed = unpack_payload(self.codec, packed, *self.size, ktx=decoder)
            result = TexturePagePayload(self.key, self.size, self.codec, len(packed), pixels, compressed)
        except BaseException:
            with self._lock:
                self._state = "failed"
            raise
        with self._lock:
            self._result = result
            self._state = "ready"

    def take_result(self):
        """완료한 결과를 한 소비자에게 한 번 전달하고 Work의 큰 버퍼 참조를 해제한다."""
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("준비된 페이지 결과만 한 번 가져올 수 있다.")
            result, self._result = self._result, None
            self._state = "consumed"
            return result


def decoded_pages(pages, directory, *, workers=DEFAULT_DECODE_WORKERS, timings=None, ktx_library=None, executor=None):
    """요청 순서대로 전달한다. 진행·완료 대기 Work를 합쳐 workers개로 제한한다."""
    if type(workers) is not int or workers < 1:
        raise ValueError("페이지 작업자 수는 양수 정수여야 한다.")
    requests = iter(pages)
    pending = deque()
    owned = executor is None
    if owned:
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fdrive-texture")

    def submit_next():
        page = next(requests, None)
        if page is None:
            return False
        work = TexturePageWork(page, directory, timings=timings, ktx_library=ktx_library)
        pending.append((work, executor.submit(work.run)))
        return True

    try:
        for _ in range(workers):
            if not submit_next():
                break
        while pending:
            work, future = pending.popleft()
            # Future는 완료·예외 대기를, Work의 lock은 결과 소유권 교환을 담당한다.
            future.result()
            result = work.take_result()
            yield result
            del result
            submit_next()
    finally:
        for _, future in pending:
            future.cancel()
        if owned:
            executor.shutdown(wait=True, cancel_futures=True)
        pending.clear()
