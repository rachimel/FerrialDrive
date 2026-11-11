"""py-spy 수집 연결과 Speedscope 원본의 함수·호출 경로 요약. import 시 실행하지 않는다."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import shutil
import subprocess
from time import perf_counter_ns


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")


def find_py_spy(root, explicit=None):
    """명시 경로 → 프로젝트 전용 런타임 → PATH 순서로 찾는다."""
    if explicit is not None:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"py-spy 실행 파일이 없다: {path}")
        return path
    runtime = Path(root) / "automate/runtime/profiler/python/bin"
    for name in ("py-spy.exe", "py-spy"):
        if (runtime / name).is_file():
            return runtime / name
    installed = shutil.which("py-spy")
    if installed:
        return Path(installed)
    raise FileNotFoundError("py-spy가 없다. automate/requirements-profiler.txt의 설치 안내를 따른다.")


def summarize_speedscope(document):
    """샘플 수는 호출 횟수가 아니다. 재귀의 포함 비중은 샘플당 한 번만 센다."""
    frames = document["shared"]["frames"]
    summaries = []
    for profile in document["profiles"]:
        if profile["type"] != "sampled":
            raise ValueError("sampled Speedscope 프로파일만 지원한다.")
        samples, weights = profile["samples"], profile["weights"]
        if len(samples) != len(weights):
            raise ValueError("스택 샘플과 가중치 개수가 다르다.")
        inclusive, own, occurrences = Counter(), Counter(), Counter()
        paths = defaultdict(lambda: {"samples": 0, "weight": 0.0})
        for stack, weight in zip(samples, weights):
            if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                    or not isfinite(weight) or weight < 0):
                raise ValueError("샘플 가중치는 유한한 0 이상의 수여야 한다.")
            if any(isinstance(index, bool) or not isinstance(index, int)
                   or not 0 <= index < len(frames) for index in stack):
                raise ValueError("스택이 존재하지 않는 프레임을 참조한다.")
            for index in set(stack):
                inclusive[index] += weight
                occurrences[index] += 1
            if stack:
                own[stack[-1]] += weight
            entry = paths[tuple(stack)]
            entry["samples"] += 1
            entry["weight"] += weight
        total_weight = sum(weights)
        if not isfinite(total_weight):
            raise ValueError("샘플 가중치의 합이 유한하지 않다.")
        functions = [{"frame_index": index, **frames[index],
                      "inclusive_samples": occurrences[index],
                      "inclusive_weight": inclusive[index], "self_weight": own[index],
                      "inclusive_percent": 100 * inclusive[index] / total_weight if total_weight else 0.0,
                      "self_percent": 100 * own[index] / total_weight if total_weight else 0.0}
                     for index in inclusive]
        functions.sort(key=lambda row: (-row["self_weight"], -row["inclusive_weight"], row["frame_index"]))
        summaries.append({"name": profile["name"], "weight_unit": profile["unit"],
                          "sample_count": len(samples), "total_sample_weight": total_weight,
                          "functions": functions,
                          "call_paths": [{"frames": list(stack), **counts}
                                         for stack, counts in sorted(paths.items(),
                                                                     key=lambda pair: -pair[1]["weight"])]})
    return {"schema_version": 1, "tool": "FDrive Profiler", "collector": document.get("exporter"),
            "semantics": "sample_weights_not_exact_durations_or_call_counts",
            "time_axis": "py_spy_speedscope_weights_are_nominal_sampling_intervals",
            "frames": frames, "profiles": summaries,
            "total_samples": sum(profile["sample_count"] for profile in summaries)}


def record_profile(*, py_spy, output_dir, cwd, duration_seconds, rate_hz,
                   python_executable=None, target=None, target_args=(), pid=None, include_idle=False,
                   include_subprocesses=False):
    """새 폴더에만 수집한다. PID 연결은 대상을 종료하지 않으며 실행 모드는 py-spy가 소유한다."""
    for label, value in (("측정 시간(초)", duration_seconds), ("초당 샘플 수", rate_hz)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label}는 양수 정수여야 한다.")
    if (target is None) == (pid is None):
        raise ValueError("실행할 파일 또는 연결할 PID 중 하나를 지정한다.")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        raise ValueError("PID는 양수 정수여야 한다.")
    if pid is not None and target_args:
        raise ValueError("PID 연결에는 실행 인자를 전달할 수 없다.")
    cwd, py_spy = Path(cwd).resolve(), Path(py_spy).resolve()
    if not cwd.is_dir() or not py_spy.is_file():
        raise FileNotFoundError("작업 폴더 또는 py-spy 실행 파일이 없다.")
    if target is not None:
        target, python_executable = Path(target).resolve(), Path(python_executable).resolve()
        if not target.is_file() or not python_executable.is_file():
            raise FileNotFoundError("실행할 Python 파일 또는 인터프리터가 없다.")
    version = subprocess.run([str(py_spy), "--version"], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "profile.speedscope.json"
    command = [str(py_spy), "record", "--format", "speedscope", "--output", str(source),
               "--rate", str(rate_hz), "--duration", str(duration_seconds), "--threads", "--full-filenames"]
    if include_idle:
        command.append("--idle")
    # Windows venv의 python.exe는 실제 인터프리터를 자식으로 실행할 수 있다.
    follow_children = target is not None or include_subprocesses
    if follow_children:
        command.append("--subprocesses")
    if pid is not None:
        command.extend(["--pid", str(pid)])
    else:
        command.extend(["--", str(python_executable), str(target), *map(str, target_args)])
    session = {"schema_version": 1, "tool": "FDrive Profiler", "collector_version": version,
               "status": "running", "started_at_utc": _utc_now(), "cwd": str(cwd),
               "command": command, "target_pid": pid,
               "target_sha256": sha256(target.read_bytes()).hexdigest() if target else None,
               "requested_duration_seconds": duration_seconds, "sampling_rate_hz": rate_hz,
               "includes_idle_threads": include_idle,
               "includes_subprocesses": follow_children,
               "launch_process_cleanup": "py_spy_direct_child_only" if target else "not_owned",
               "target_exit_status_verified": False,
               "cpu_utilization_measured": False, "gpu_utilization_measured": False,
               "gpu_execution_time_measured": False, "overhead_measured": False,
               "overhead_correction_applied": False}
    _write_json(destination / "session.json", session)
    started_ns = perf_counter_ns()
    try:
        with (destination / "collector.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        session["collector_elapsed_ns"] = perf_counter_ns() - started_ns
        session["collector_exit_code"] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f"py-spy 수집 실패. 확인: {destination / 'collector.log'}")
        postprocess_start_ns = perf_counter_ns()
        summary = summarize_speedscope(json.loads(source.read_text(encoding="utf-8")))
        if not summary["total_samples"]:
            raise RuntimeError("스택 샘플이 없다. 측정 시간·실행 상태와 collector.log를 확인한다.")
        _write_json(destination / "summary.json", summary)
        session["postprocess_elapsed_ns"] = perf_counter_ns() - postprocess_start_ns
        session["total_samples"] = summary["total_samples"]
        session["status"] = "complete"
    except BaseException as error:
        session["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        session["error"] = str(error)
        raise
    finally:
        session["finished_at_utc"] = _utc_now()
        _write_json(destination / "session.json", session)
    return destination
