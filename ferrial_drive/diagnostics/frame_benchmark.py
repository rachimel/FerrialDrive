"""공통 실행 규약의 프로그램에 연결하는 자동·직접 조작 프레임 벤치마크."""

from collections import deque
from itertools import count
from math import ceil, isfinite
from statistics import mean
from time import perf_counter, sleep

from .texture_metrics import GpuFrameTimer, bind_gl, process_memory


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"count": len(values), "mean": mean(values), "min": ordered[0],
            **{f"p{p}": ordered[ceil(len(values)*p/100)-1] for p in (50, 95, 99)}, "max": ordered[-1]}


def summarize_frames(rows, *, target_fps, expected_frames, elapsed_seconds):
    budget = 1000 / target_fps
    work = [r["work_ms"] for r in rows]
    missed = sum(value > budget for value in work)
    complete = bool(rows) if expected_frames is None else len(rows) == expected_frames
    observed_fps = len(rows) / elapsed_seconds if elapsed_seconds > 0 else 0
    return {"completed": complete, "target_fps": target_fps, "budget_ms": budget,
            "observed_fps": observed_fps,
            "target_met": complete and bool(rows) and missed == 0 and observed_fps >= target_fps * .99,
            "target_criterion": "측정 전부 완료·work 예산 초과 0회·실측 FPS가 목표의 99% 이상",
            "deadline_miss_count": missed, "deadline_miss_percent": missed / len(rows)*100 if rows else None,
            "all_work_within_budget": complete and bool(rows) and missed == 0,
            "work_ms": distribution(work),
            "cpu_ms": {key: distribution([r[key] for r in rows]) for key in
                       ("events_ms", "update_ms", "draw_submit_ms", "present_ms", "interval_ms")},
            "semantics": "wall 시간은 OS 선점·드라이버 대기를 포함한다. interval은 프레임 제한 대기 포함."}


def benchmark_program(program, canvas, *, target_fps=165, frames=600, warmup=120, paced=True,
                      before_step=None, interactive=False, sample_capacity=3600, on_status=None,
                      should_continue=None, frame_trace=None):
    """직접 조작은 실제 경과 시간·전체 입력을 사용한다. 창·enter/exit는 호출자가 소유한다."""
    from ferrial_drive.runtime import poll_events

    if not isfinite(target_fps) or target_fps <= 0:
        raise ValueError("목표 FPS는 양수 유한값이어야 한다.")
    if ((frames is None and not interactive) or (frames is not None and (type(frames) is not int or frames < 1))
            or type(warmup) is not int or warmup < 0 or type(sample_capacity) is not int or sample_capacity < 1):
        raise ValueError("측정은 1프레임 이상, 준비는 0프레임 이상이어야 한다.")
    pico = canvas.pico
    finish = bind_gl(pico, "glFinish", None, [])
    timer = GpuFrameTimer(pico)
    rows = deque(maxlen=sample_capacity) if interactive else []
    total_measured = 0
    peak_private = 0
    measured_start = None
    budget_ms = 1000 / target_fps
    finish()
    previous_start = perf_counter()
    status_start, status_frames = previous_start, 0
    try:
        for index in count():
            if frames is not None and index >= warmup + frames:
                break
            if should_continue is not None and not should_continue(index):
                break
            if index == warmup:
                finish()
                measured_start = perf_counter()
            started = perf_counter()
            measured = index >= warmup
            if measured and frame_trace is not None:
                frame_trace.begin()
            delta_seconds = started - previous_start
            previous_start = started
            for event in poll_events(pico, accept_text=getattr(program, "accept_text", False)):
                if event.type == pico.SDL_QUIT:
                    program.running = False
                elif interactive:
                    program.handle_event(event)
                if not program.running:
                    break
            if not program.running:
                break
            if before_step is not None:
                before_step(program, index, index == warmup)
            events_done = perf_counter()
            program.update(delta_seconds if interactive else 1 / target_fps)
            if not program.running:
                break
            updated = perf_counter()
            if measured:
                timer.begin()
            program.draw()
            pico.SDL_RenderFlush(pico.renderer)
            if measured:
                timer.end()
            drawn = perf_counter()
            canvas.present()
            if getattr(program, "after_present", None) is not None:
                program.after_present()
            presented = perf_counter()
            if paced:
                remaining = 1 / target_fps - (perf_counter() - started)
                if remaining > 0:
                    sleep(remaining)
            ended = perf_counter()
            if measured:
                total_measured += 1
                row = {"events_ms": (events_done-started)*1000, "update_ms": (updated-events_done)*1000,
                       "draw_submit_ms": (drawn-updated)*1000, "present_ms": (presented-drawn)*1000,
                       "work_ms": (presented-started)*1000, "interval_ms": (ended-started)*1000}
                if frame_trace is not None:
                    row.update(frame=total_measured, session_ms=(started - measured_start)*1000)
                    frame_trace.finish(row, budget_ms)
                rows.append(row)
            if index % 30 == 0:
                peak_private = max(peak_private, process_memory().get("private_bytes", 0))
            if interactive:
                # 장시간 직접 조작에서 GPU 표본을 무제한 보관하지 않는다.
                del timer.samples_ms[:-sample_capacity]
            if on_status is not None:
                status_frames += 1
                if ended-status_start >= 1:
                    on_status({"fps": status_frames/(ended-status_start), "warming_up": not measured})
                    status_start, status_frames = ended, 0
        ended = perf_counter()
        elapsed = ended - measured_start if measured_start is not None else 0
        finish()
        timer.collect()
        sample_elapsed = sum(row["interval_ms"] for row in rows) / 1000
        expected = min(frames, sample_capacity) if interactive and frames is not None else frames
        result = summarize_frames(rows, target_fps=target_fps, expected_frames=expected,
                                  elapsed_seconds=sample_elapsed if interactive else elapsed)
        if frames is not None and total_measured != frames:
            result.update(completed=False, target_met=False, all_work_within_budget=False)
        result.update({"warmup_frames": warmup, "measured_frames": len(rows), "paced": paced, "vsync": False,
                       "interactive": interactive, "total_measured_frames": total_measured,
                       "sample_capacity": sample_capacity if interactive else None,
                       "sample_window_seconds": sample_elapsed, "session_observed_fps": total_measured / elapsed if elapsed else 0,
                       "fixed_update_seconds": None if interactive else 1 / target_fps, "elapsed_seconds": elapsed,
                       "gpu_draw_elapsed_ms": distribution(timer.samples_ms),
                       "gpu_timer_available": timer.available,
                       "gpu_semantics": "draw+SDL flush의 GL_TIME_ELAPSED. GPU 전용 실행 시간과 다르며 제출 간격을 포함한다.",
                       "process_memory_after": process_memory(), "sampled_peak_private_bytes": peak_private,
                       "frames": list(rows)})
        if frame_trace is not None:
            result["function_scopes"] = dict(frame_trace.probe.scope_functions)
            result["function_timing_columns"] = ["calls", "wall_ns", "self_wall_ns"]
        return result
    finally:
        if frame_trace is not None:
            frame_trace.stop()
        timer.close()
