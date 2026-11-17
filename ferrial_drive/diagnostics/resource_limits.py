"""소유한 Windows 자식에만 Job CPU·커밋 메모리·affinity 제한을 적용한다."""

import ctypes as ct
from dataclasses import dataclass
import json
import os
import subprocess


@dataclass(frozen=True)
class ResourceLimits:
    logical_cpus: int = 8
    cpu_percent: float = 50
    memory_mib: int = 1024

    def __post_init__(self):
        if type(self.logical_cpus) is not int or self.logical_cpus < 1:
            raise ValueError("논리 CPU 수는 양수 정수여야 한다.")
        if isinstance(self.cpu_percent, bool) or not .01 <= self.cpu_percent <= 100:
            raise ValueError("CPU 상한은 0.01 이상 100 이하 %여야 한다.")
        if type(self.memory_mib) is not int or self.memory_mib < 64:
            raise ValueError("메모리 상한은 64MiB 이상의 정수여야 한다.")


class _Basic(ct.Structure):
    _fields_ = [("process_time", ct.c_int64), ("job_time", ct.c_int64), ("flags", ct.c_uint32),
                ("min_ws", ct.c_size_t), ("max_ws", ct.c_size_t), ("active", ct.c_uint32),
                ("affinity", ct.c_size_t), ("priority", ct.c_uint32), ("scheduling", ct.c_uint32)]


class _Extended(ct.Structure):
    _fields_ = [("basic", _Basic), ("io", ct.c_uint64 * 6),
                ("process_memory", ct.c_size_t), ("job_memory", ct.c_size_t),
                ("peak_process_memory", ct.c_size_t), ("peak_job_memory", ct.c_size_t)]


class _CpuRate(ct.Structure):
    _fields_ = [("flags", ct.c_uint32), ("rate", ct.c_uint32)]


class WindowsJobLimits:
    """자식은 stdin 승인 신호를 기다려야 한다. 실패하면 측정을 시작하지 않는다."""

    def __init__(self, limits):
        if os.name != "nt":
            raise RuntimeError("CPU·메모리 제한 프로필은 Windows 전용이다.")
        self.limits = limits
        self.job = self.process = None
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        handle, pointer, dword = ct.c_void_p, ct.c_void_p, ct.c_uint32
        signatures = {
            "CreateJobObjectW": (handle, [pointer, ct.c_wchar_p]),
            "OpenProcess": (handle, [dword, ct.c_int, dword]),
            "GetCurrentProcess": (handle, []),
            "SetInformationJobObject": (ct.c_int, [handle, ct.c_int, pointer, dword]),
            "QueryInformationJobObject": (ct.c_int, [handle, ct.c_int, pointer, dword, pointer]),
            "AssignProcessToJobObject": (ct.c_int, [handle, handle]),
            "IsProcessInJob": (ct.c_int, [handle, handle, pointer]),
            "GetProcessAffinityMask": (ct.c_int, [handle, pointer, pointer]),
            "SetProcessAffinityMask": (ct.c_int, [handle, ct.c_size_t]),
            "CloseHandle": (ct.c_int, [handle]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel, name)
            function.restype, function.argtypes = result, arguments

    def _check(self, result):
        if not result:
            raise ct.WinError(ct.get_last_error())
        return result

    def _set(self, kind, value):
        self._check(self.kernel.SetInformationJobObject(self.job, kind, ct.byref(value), ct.sizeof(value)))

    def _query(self, kind, structure):
        value = structure()
        self._check(self.kernel.QueryInformationJobObject(self.job, kind, ct.byref(value), ct.sizeof(value), None))
        return value

    def attach(self, pid):
        if self.job or pid == os.getpid():
            raise ValueError("자기 자신이나 이미 연결된 Job에는 적용할 수 없다.")
        self.job = self._check(self.kernel.CreateJobObjectW(None, None))
        try:
            self.process = self._check(self.kernel.OpenProcess(0x0100 | 0x0200 | 0x0400 | 0x0001, False, pid))
            allowed, system = ct.c_size_t(), ct.c_size_t()
            self._check(self.kernel.GetProcessAffinityMask(self.process, ct.byref(allowed), ct.byref(system)))
            cpus = [i for i in range(ct.sizeof(allowed) * 8) if allowed.value & (1 << i)]
            if self.limits.logical_cpus > len(cpus):
                raise RuntimeError(f"요청 논리 CPU {self.limits.logical_cpus}개, 허용된 CPU {len(cpus)}개")
            mask = sum(1 << i for i in cpus[:self.limits.logical_cpus])
            extended = _Extended()
            # KILL_ON_JOB_CLOSE | PROCESS_MEMORY | JOB_MEMORY | AFFINITY
            extended.basic.flags = 0x2000 | 0x0100 | 0x0200 | 0x0010
            extended.basic.affinity = mask
            extended.process_memory = extended.job_memory = self.limits.memory_mib * 1024**2
            self._set(9, extended)
            self._set(15, _CpuRate(0x1 | 0x4, round(self.limits.cpu_percent * 100)))
            self._check(self.kernel.AssignProcessToJobObject(self.job, self.process))
            self._check(self.kernel.SetProcessAffinityMask(self.process, mask))
            report = self.snapshot()
            if (report["cpu_rate_units"] != round(self.limits.cpu_percent * 100)
                    or report["cpu_flags"] != 5 or report["job_flags"] != extended.basic.flags
                    or report["process_memory_limit_bytes"] != extended.process_memory
                    or report["job_memory_limit_bytes"] != extended.job_memory
                    or report["affinity_mask"] != mask or not report["in_job"]):
                raise RuntimeError("요청한 제한과 Windows 조회 결과가 다르다.")
            return report
        except BaseException:
            self.close()
            raise

    def snapshot(self):
        extended, cpu = self._query(9, _Extended), self._query(15, _CpuRate)
        allowed, system, member = ct.c_size_t(), ct.c_size_t(), ct.c_int()
        self._check(self.kernel.GetProcessAffinityMask(self.process, ct.byref(allowed), ct.byref(system)))
        self._check(self.kernel.IsProcessInJob(self.process, self.job, ct.byref(member)))
        return {"verified": True, "in_job": bool(member.value), "cpu_flags": cpu.flags,
                "cpu_rate_units": cpu.rate, "cpu_percent": cpu.rate / 100,
                "job_flags": extended.basic.flags, "affinity_mask": allowed.value,
                "logical_cpu_ids": [i for i in range(ct.sizeof(allowed) * 8) if allowed.value & (1 << i)],
                "process_memory_limit_bytes": extended.process_memory,
                "job_memory_limit_bytes": extended.job_memory,
                "peak_process_commit_bytes": extended.peak_process_memory,
                "peak_job_commit_bytes": extended.peak_job_memory,
                "semantics": "Windows Job CPU 시간 상한과 커밋 상한. 물리 CPU/RAM 성능 에뮬레이션이 아니다."}

    def close(self):
        for name in ("process", "job"):
            value = getattr(self, name)
            if value:
                self.kernel.CloseHandle(value)
                setattr(self, name, None)


def run_gated_child(command, *, cwd, limits=None, timeout_seconds=300):
    """wait_for_limits()를 첫 작업으로 호출하는 자식에만 사용한다."""
    job, child = None, None
    try:
        if limits is not None:
            job = WindowsJobLimits(limits)
        child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, text=True, encoding="utf-8",
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        applied = job.attach(child.pid) if job else {"verified": True, "enabled": False}
        child.stdin.write(json.dumps(applied) + "\n")
        child.stdin.flush()
        child.stdin.close()
        code = child.wait(timeout=timeout_seconds)
        return code, job.snapshot() if job else applied
    finally:
        try:
            if child and child.stdin and not child.stdin.closed:
                child.stdin.close()
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
        finally:
            if job:
                job.close()


def wait_for_limits():
    """창·게임 에셋을 import하기 전에 부모의 적용 확인을 기다린다."""
    import sys

    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("제한 적용 신호를 받지 못했다.")
    result = json.loads(line)
    if result.get("verified") is not True:
        raise RuntimeError("검증되지 않은 제한이다.")
    return result
