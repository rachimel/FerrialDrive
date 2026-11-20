"""텍스처 비교의 프로세스 메모리·GPU 질의·동일 화면 품질 계측."""

import ctypes as ct
import os

from .gpu_profile import bind_gl


class _ProcessMemoryCounters(ct.Structure):
    _fields_ = [("cb", ct.c_ulong), ("faults", ct.c_ulong)] + [
        (name, ct.c_size_t) for name in ("peak_working_set", "working_set", "peak_paged_pool",
                                         "paged_pool", "peak_nonpaged_pool", "nonpaged_pool",
                                         "pagefile", "peak_pagefile", "private_bytes")]


def process_memory():
    if os.name != "nt":
        return {"available": False, "reason": "Windows 프로세스 메모리 API가 아니다."}

    counters = _ProcessMemoryCounters()
    counters.cb = ct.sizeof(counters)
    handle = ct.windll.kernel32.GetCurrentProcess
    handle.restype = ct.c_void_p
    query = ct.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_ulong]
    if not query(handle(), ct.byref(counters), counters.cb):
        return {"available": False, "reason": "GetProcessMemoryInfo 실패"}
    return {"available": True, "working_set_bytes": counters.working_set,
            "peak_working_set_bytes": counters.peak_working_set, "private_bytes": counters.private_bytes}


class ProcessGpuMemory:
    """WDDM 프로세스 카운터. 텍스처 페이로드와 별개이며 실패 시 값을 대체하지 않는다."""

    def __init__(self):
        self.query = ct.c_void_p()
        self.counter = ct.c_void_p()
        self.shared_counter = ct.c_void_p()
        self.available = False
        self.reason = "Windows PDH GPU Process Memory 카운터 미지원"
        if os.name != "nt":
            return
        self.dll = ct.WinDLL("pdh.dll")
        self.dll.PdhOpenQueryW.argtypes = [ct.c_wchar_p, ct.c_size_t, ct.POINTER(ct.c_void_p)]
        self.dll.PdhAddEnglishCounterW.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_size_t, ct.POINTER(ct.c_void_p)]
        self.dll.PdhCollectQueryData.argtypes = [ct.c_void_p]
        self.dll.PdhCloseQuery.argtypes = [ct.c_void_p]
        self.dll.PdhGetFormattedCounterArrayW.argtypes = [ct.c_void_p, ct.c_uint, ct.POINTER(ct.c_uint),
                                                         ct.POINTER(ct.c_uint), ct.c_void_p]
        if self.dll.PdhOpenQueryW(None, 0, ct.byref(self.query)):
            return
        path = rf"\GPU Process Memory(pid_{os.getpid()}_*)\Dedicated Usage"
        error = self.dll.PdhAddEnglishCounterW(self.query, path, 0, ct.byref(self.counter))
        if not error:
            self.available = True
            shared_path = rf"\GPU Process Memory(pid_{os.getpid()}_*)\Shared Usage"
            if self.dll.PdhAddEnglishCounterW(self.query, shared_path, 0, ct.byref(self.shared_counter)):
                self.shared_counter = ct.c_void_p()
            self.dll.PdhCollectQueryData(self.query)
        else:
            self.reason += f" ({error & 0xffffffff:#x})"

    def sample(self):
        if not self.available:
            return {"available": False, "reason": self.reason}
        self.dll.PdhCollectQueryData(self.query)
        dedicated = self._values(self.counter)
        if not dedicated:
            return {"available": False, "reason": "유효한 WDDM GPU 카운터 표본이 없다."}
        shared = self._values(self.shared_counter) if self.shared_counter else None
        result = {"available": True, "dedicated_bytes": sum(dedicated.values()), "instances": dedicated,
                  "shared_available": shared is not None,
                  "shared_bytes": sum(shared.values()) if shared is not None else None,
                  "shared_instances": shared,
                  "semantics": "WDDM 프로세스 GPU 전용 메모리와 공유 시스템 메모리를 따로 기록한다."}
        return result

    def _values(self, counter):
        size, count = ct.c_uint(), ct.c_uint()
        self.dll.PdhGetFormattedCounterArrayW(counter, 0x200, ct.byref(size), ct.byref(count), None)
        if not size.value:
            return None
        buffer = ct.create_string_buffer(size.value)
        error = self.dll.PdhGetFormattedCounterArrayW(counter, 0x200, ct.byref(size), ct.byref(count), buffer)
        if error:
            return None

        class Value(ct.Structure):
            _fields_ = [("status", ct.c_uint), ("value", ct.c_double)]

        class Item(ct.Structure):
            _fields_ = [("name", ct.c_wchar_p), ("counter", Value)]

        items = ct.cast(buffer, ct.POINTER(Item))
        values = {items[i].name: int(items[i].counter.value) for i in range(count.value)
                  if items[i].counter.status in (0, 1)}
        return values or None

    def close(self):
        if self.query:
            self.dll.PdhCloseQuery(self.query)
            self.query = ct.c_void_p()


class GpuFrameTimer:
    def __init__(self, pico):
        self.available, self.pending, self.samples_ms = False, [], []
        self.active = None
        try:
            for name, result, args in (
                ("glGenQueries", None, [ct.c_int, ct.c_void_p]),
                ("glBeginQuery", None, [ct.c_uint, ct.c_uint]), ("glEndQuery", None, [ct.c_uint]),
                ("glGetQueryObjectiv", None, [ct.c_uint, ct.c_uint, ct.c_void_p]),
                ("glGetQueryObjectui64v", None, [ct.c_uint, ct.c_uint, ct.c_void_p]),
                ("glDeleteQueries", None, [ct.c_int, ct.c_void_p])):
                setattr(self, name, bind_gl(pico, name, result, args))
            self.available = True
        except RuntimeError:
            pass

    def begin(self):
        if self.available:
            query = ct.c_uint()
            self.glGenQueries(1, ct.byref(query))
            self.active = query
            self.glBeginQuery(0x88BF, query.value)

    def end(self):
        if self.active is not None:
            self.glEndQuery(0x88BF)
            self.pending.append(self.active)
            self.active = None
        self.collect()

    def collect(self):
        remaining = []
        for query in self.pending:
            ready = ct.c_int()
            self.glGetQueryObjectiv(query.value, 0x8867, ct.byref(ready))
            if ready.value:
                value = ct.c_uint64()
                self.glGetQueryObjectui64v(query.value, 0x8866, ct.byref(value))
                self.samples_ms.append(value.value / 1e6)
                self.glDeleteQueries(1, ct.byref(query))
            else:
                remaining.append(query)
        self.pending = remaining

    def close(self):
        self.collect()
        for query in self.pending:
            self.glDeleteQueries(1, ct.byref(query))
        self.pending.clear()


def image_quality(reference, candidate):
    """RGB 화면 PSNR·11x11 Gaussian SSIM. 같은 배경/크기/위상에서만 비교한다."""
    import numpy as np
    left, right = np.asarray(reference).astype(np.float64), np.asarray(candidate).astype(np.float64)
    if left.shape != right.shape or left.ndim != 3 or left.shape[2] < 3:
        raise ValueError("같은 크기의 색상 화면이 필요하다.")
    left, right = left[:, :, :3] / 255, right[:, :, :3] / 255
    error = np.mean((left-right)**2)
    axis = np.arange(-5, 6)
    kernel = np.exp(-(axis**2)/(2*1.5**2))
    kernel /= kernel.sum()

    def blur(values):
        for axis in (0, 1):
            padding = [(0, 0)] * values.ndim
            padding[axis] = (5, 5)
            padded = np.pad(values, padding, mode="reflect")
            result = np.zeros_like(values)
            for index, weight in enumerate(kernel):
                slices = [slice(None)] * values.ndim
                slices[axis] = slice(index, index + values.shape[axis])
                result += padded[tuple(slices)] * weight
            values = result
        return values

    a, b = blur(left), blur(right)
    va, vb = blur(left*left)-a*a, blur(right*right)-b*b
    covariance = blur(left*right)-a*b
    score = ((2*a*b+0.01**2)*(2*covariance+0.03**2)
             / ((a*a+b*b+0.01**2)*(va+vb+0.03**2)))
    visible = (np.max(np.abs(left-left[0, 0]), axis=2) > 1/255
               ) | (np.max(np.abs(right-right[0, 0]), axis=2) > 1/255)
    visible_error = np.mean((left[visible]-right[visible])**2) if visible.any() else 0
    return {"psnr_db": float(-10*np.log10(error)) if error else None,
            "ssim": float(np.mean(score)), "identical": bool(error == 0),
            "visible_union_psnr_db": float(-10*np.log10(visible_error)) if visible_error else None,
            "visible_union_ssim": float(np.mean(score[visible])) if visible.any() else 1.0,
            "ssim_window": "11x11 Gaussian sigma=1.5", "channels": "RGB composite"}
