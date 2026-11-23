"""저장된 벤치마크 JSON으로 Markdown과 Flamegraph를 생성한다. 창을 열지 않는다."""

import argparse
from collections import Counter
import json
from pathlib import Path

from .benchmark_flamegraph import write_flamegraph, write_frame_flamegraph


def number(value, digits=2):
    return "미측정" if value is None else f"{value:.{digits}f}"


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def slow_frame_details(benchmark):
    if "function_timing_columns" not in benchmark:
        return []
    rows = sorted((row for row in benchmark.get("frames", ()) if "combat_events" in row),
                  key=lambda row: (-row["work_ms"], row["frame"]))
    lines = ["", "## 느린 프레임과 전투 이벤트", "",
             f"보존한 표본에서 작업 예산 {number(benchmark.get('budget_ms'))}ms를 넘긴 {len(rows)}프레임이다. "
             "시간은 첫 측정 프레임 기준이며, 함수별 wall 시간에는 대기와 하위 호출이 포함된다. "
             "자체 시간은 계측된 하위 호출을 뺀 값이다."]
    if not rows:
        return lines
    lines += ["", "| 프레임 / 시간 | 작업 ms | 전투 이벤트 / 상태 | 함수별 시간 (포함 / 자체 ms · 호출 수) |",
              "| --- | ---: | --- | --- |"]
    labels = benchmark.get("function_scopes", {})
    for row in rows:
        event_lines, relevant = [], set()
        for event in row["combat_events"]:
            kind = event["type"]
            if kind == "gun_fire":
                followup = " · 후속" if event["followup"] else ""
                event_lines.append(f"총격 {event['count']}회 · 총기 슬롯 {event['gun_slot']}{followup}")
                relevant.add("RangedCombat.fire_followup" if event["followup"] else "RangedCombat.update")
            elif kind == "back_weapon_fire":
                event_lines.append(f"백웨폰 미사일 {event['count']}발")
                relevant.add("SwapActions.launch")
            elif kind == "loadout_transition_start":
                event_lines.append("로드아웃 전환 시작")
                relevant.add("MovementApplication.perform_hud_action")
            elif kind == "loadout_changed":
                event_lines.append(f"로드아웃 {event['from']} → {event['to']}")
                relevant.add("MovementHud.perform(loadout)")
        state = row["combat_state"]
        weapon = {"ranged": "원거리", "melee": "근접"}.get(state["weapon_kind"], state["weapon_kind"])
        transition = " · 전환 중" if state["loadout_transition"] else ""
        event_lines.append(f"로드아웃 {state['loadout']} · {weapon}{transition}")
        timings = sorted(row["function_timings_ns"].items(), key=lambda item: -item[1][2])
        functions = [f"`{labels.get(scope, scope)}` {number(wall / 1e6)} / {number(own / 1e6)} · {calls}회"
                     for index, (scope, (calls, wall, own)) in enumerate(timings) if index < 5 or scope in relevant]
        lines.append(f"| {row['frame']} / {number(row['session_ms'] / 1000)}초 | {number(row['work_ms'])} | "
                     f"{cell('<br>'.join(event_lines))} | {cell('<br>'.join(functions))} |")
    lines += ["", "표에 자체 시간 상위 5개와 이벤트에 해당하는 함수를 표시한다. 해당 프레임의 전체 함수는 원자료에 있다."]
    return lines


def live_combat_frames(benchmark):
    return sorted((row for row in benchmark.get("frames", ()) if row.get("live_combat_stacks")),
                  key=lambda row: (-row["work_ms"], row["frame"]))


def frame_flamegraph_path(row):
    return f"flamegraphs/frame-{row['frame']:06d}.svg"


def live_combat_frame_details(rows):
    if not rows:
        return []
    lines = ["", "## 느린 프레임의 전투 모션", "",
             "`draw_live_combat_motion`을 실행한 예산 초과 프레임이다. 각 호출 경로의 자체 시간을 "
             "가장 가까운 계측 구간에 한 번만 집계했다. 그림자 준비에는 캐스터 표면 생성이 포함된다.", "",
             "| 프레임 / 시간 | 작업 ms | 모션 합계 ms | 포즈 준비 | 그림자 준비 | 그림자 제출 | 파츠 합성 | 기타 | Flamegraph |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    phase_order = ("pose_prepare", "shadow_prepare", "shadow_submit", "parts_compose", "other")
    for row in rows:
        phase_ns = Counter()
        for entry in row["live_combat_stacks"]:
            phase = next((scope.split(".", 2)[1] for scope in reversed(entry["stack"])
                          if scope.startswith("live_combat.")), "other")
            phase_ns[phase] += entry["self_wall_ns"]
        phases = " | ".join(number(phase_ns[key] / 1e6) if key in phase_ns else "—" for key in phase_order)
        lines.append(f"| {row['frame']} / {number(row['session_ms'] / 1000)}초 | {number(row['work_ms'])} | "
                     f"{number(sum(phase_ns.values()) / 1e6)} | {phases} | [열기]({frame_flamegraph_path(row)}) |")
    return lines


def render_report(result, limits=None, *, flamegraph=False):
    """누락·실패 결과는 미측정으로 표시하고 실제 측정값만 표로 만든다."""
    lines = ["# 전투 성능 측정 보고서", "", "## 실행 조건", "",
             "| 항목 | 값 |", "| --- | --- |"]
    profile = result.get("profile", {})
    settings = result.get("settings", {})
    for name, value in (
        ("상태", result.get("status", "미확인")), ("측정 시각", result.get("measured_at", "미확인")),
        ("장면 / 입력", f"{result.get('scenario', '미확인')} / {result.get('input_mode', '미확인')}"),
        ("도형 시연", result.get("demo", "미확인")),
        ("해상도", result.get("resolution", "미확인")),
        ("텍스처 품질 / 실제 divisor", f"{settings.get('texture_quality', '미확인')} / {result.get('atlas_divisor_after_load', '미확인')}"),
        ("이동 배율", result.get("movement_speed_multiplier", 1)),
        ("GPU", result.get("actual_gl", {}).get("renderer", "미확인")),
        ("CPU", result.get("host", {}).get("processor_name", result.get("host", {}).get("processor", "미확인"))),
        ("자원 제한 사용", profile.get("resource_limits_enabled", "미확인")),
        ("자원 제한 요청", profile.get("resource_limits", "미확인")),
        ("GPU 기능 가드", profile.get("gpu_profile", "미확인")),
        ("기능 위반", result.get("gpu_profile", {}).get("violations", "미확인 / 가드 비활성")),
        ("계측 옵션", result.get("instrumentation", "미확인")),
        ("로딩 시간(초)", number(result.get("load_seconds"))),
    ):
        lines.append(f"| {name} | {cell(value)} |")
    if result.get("auto_input"):
        lines += ["", "자동 입력: `" + cell(json.dumps(result["auto_input"], ensure_ascii=False)) + "`.",
                  "2초 주기 초기화·무장 전환·조준 비용을 포함한다. 실제 교전 전체의 대표값으로 간주하지 않는다."]
    if result.get("error"):
        lines += ["", "실행 오류: " + cell(result["error"])]

    if stop := result.get("memory_stop"):
        lines += ["", f"커밋 메모리 상한에 가까워 {stop['frame']}번째 프레임을 시작하기 전에 종료했다. "
                  f"사용량 {mib(stop['commit_bytes'])} MiB / 상한 {mib(stop['limit_bytes'])} MiB. "
                  f"종료 여유 {mib(stop['reserve_bytes'])} MiB."]

    benchmark = result.get("benchmark")
    if benchmark is not None:
        lines += ["", "## 프레임 측정", "",
                  f"목표 {number(benchmark.get('target_fps'))} FPS / 예산 {number(benchmark.get('budget_ms'))}ms. "
                  f"완료: {benchmark.get('completed')}. 목표 충족: {benchmark.get('target_met')}.",
                  f"실측 {number(benchmark.get('observed_fps'))} FPS. "
                  f"예산 초과 {benchmark.get('deadline_miss_count', '미측정')}회 "
                  f"({number(benchmark.get('deadline_miss_percent'))}%).",
                  f"준비 {benchmark.get('warmup_frames')}프레임 / 측정 전체 {benchmark.get('total_measured_frames')}프레임 / "
                  f"분포 표본 {benchmark.get('measured_frames')}프레임. "
                  f"프레임 대기: {benchmark.get('paced')}. VSync: {benchmark.get('vsync')}.", "",
                  "| 구간(ms) | 평균 | p50 | p95 | p99 | 최대 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        rows = [("프레임 작업", benchmark.get("work_ms"))]
        rows += list(benchmark.get("cpu_ms", {}).items())
        rows.append(("GPU draw elapsed", benchmark.get("gpu_draw_elapsed_ms")))
        for label, values in rows:
            values = values or {}
            lines.append("| " + label + " | " + " | ".join(number(values.get(key)) for key in ("mean", "p50", "p95", "p99", "max")) + " |")
        lines += slow_frame_details(benchmark)
        lines += live_combat_frame_details(live_combat_frames(benchmark))
    else:
        lines += ["", "프레임 측정값 없음. 실행 실패를 성능 통과로 판정하지 않는다."]

    probe = result.get("draw_breakdown", {})
    if flamegraph:
        lines += ["", "## Flamegraph", "",
                  "[Flamegraph 열기](flamegraph.svg). 계측 구간의 호출 경로와 누적 wall 시간을 표시한다. "
                  "블록에 마우스를 올리면 경로 전체와 포함·자체 시간을 볼 수 있다."]
    combat = probe.get("combat_activity")
    if combat:
        lines += ["", "## 교전 부하", "",
                  f"초기 적 {combat['initial_enemies']}기. 실행 상태가 running인 표본 "
                  f"{combat['running_frames']} / {combat['sampled_frames']}프레임. "
                  f"Overdrive {combat['overdrive_frames']}프레임. "
                  f"일시정지·메뉴 {combat.get('paused_frames', '미측정')}프레임. "
                  f"원거리 무장 {combat.get('ranged_frames', '미측정')}프레임.", "",
                  "| 항목 | 평균 | 최대 |", "| --- | ---: | ---: |"]
        for key in ("alive_enemies", "enemy_projectiles", "player_projectiles"):
            lines.append(f"| {key} | {number(combat['mean'].get(key))} | {combat['peak'].get(key, '미측정')} |")
        lines += ["", f"생존 적 최소 {combat['alive_min']}기. 마지막 교전 상태: {combat['final_result']}.",
                  "적 수·투사체 수는 각 측정 update 직후 표본이다. 종료·일시정지 구간이 포함되면 별도 조작 구간으로 재측정한다.",
                  "마지막 적 렌더링 통계(전체 평균 아님): `" + cell(json.dumps(combat.get("enemy_rendering_last"), ensure_ascii=False)) + "`."]

    frames = probe.get("frames", 0)
    if probe.get("ground_effects_backend"):
        stats = probe.get("ground_effects_per_frame", {})
        lines += ["", "## 지면 효과 배치", "",
                  f"경로: {probe['ground_effects_backend']}. 앞·뒤 레이어 합산 프레임 평균: "
                  f"입자 제출 {number(stats.get('particles'))}개, 드로우 {number(stats.get('submits'))}회, "
                  f"업로드 {number(stats.get('upload_bytes'))}bytes, 버퍼 재할당 {number(stats.get('buffer_allocations'))}회."]
    measurements = probe.get("timings", {}).get("measurements", [])
    if frames and measurements:
        lines += ["", "## 처리 구간", "", "부모와 자식의 inclusive wall 시간은 중복된다. "
                  "큰 값은 조사 후보이며 GPU 병목이나 제거 가능한 비용으로 확정하지 않는다.", "",
                  "| 구간 | 호출/프레임 | 포함 ms/프레임 | 자체 ms/프레임 |",
                  "| --- | ---: | ---: | ---: |"]
        for row in measurements[:25]:
            label = row["name"]
            lines.append(f"| {label} | {number(row['calls']/frames)} | {number(row['total_ns']/frames/1e6)} | "
                         f"{number(probe.get('self_ms_per_frame', {}).get(label))} |")
    if result.get("comparisons"):
        lines += ["", "## 조건별 측정", "", "각 회차의 측정값을 개별 표시한다. 상단 프레임 표는 마지막 조건이다.", "",
                  "| 회차 | 조건 | FPS | work p95(ms) | 예산 초과(%) | 완료 | 생존 적 평균 | 진행 프레임 |",
                  "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |"]
        for row in result["comparisons"]:
            values = row["benchmark"]
            activity = row.get("draw_breakdown", {}).get("combat_activity") or {}
            lines.append(f"| {row['round']} | {row['variant']} | {number(values.get('observed_fps'))} | "
                         f"{number((values.get('work_ms') or {}).get('p95'))} | "
                         f"{number(values.get('deadline_miss_percent'))} | {values.get('completed')} | "
                         f"{number(activity.get('mean', {}).get('alive_enemies'))} | {activity.get('running_frames', '미측정')} |")

    limits = limits or {}
    ground_rows = [row for row in result.get("comparisons", [])
                   if row.get("draw_breakdown", {}).get("ground_effects_per_frame")]
    if ground_rows:
        lines += ["", "## 지면 효과 조건별 측정", "",
                  "| 회차 | 조건 | 지면 효과 ms/프레임 | 입자 제출/프레임 | 드로우/프레임 |",
                  "| --- | --- | ---: | ---: | ---: |"]
        for row in ground_rows:
            breakdown = row["draw_breakdown"]
            measurement = next((item for item in breakdown["timings"]["measurements"]
                                if item["name"] == "world.ground_effects"), None)
            milliseconds = measurement["total_ns"] / max(1, breakdown["frames"]) / 1e6 if measurement else None
            stats = breakdown["ground_effects_per_frame"]
            lines.append(f"| {row['round']} | {row['variant']} | {number(milliseconds)} | "
                         f"{number(stats.get('particles'))} | {number(stats.get('submits'))} |")
    verified = "비활성" if limits.get("enabled") is False else limits.get("verified", "미확인")
    lines += ["", "## 자원과 해석 범위", "",
              f"최대 프로세스 커밋: {number(limits.get('peak_process_commit_bytes') / 1024**2 if limits.get('peak_process_commit_bytes') is not None else None)}MiB. "
              f"Windows 제한 검증: {verified}.",
              "GPU 메모리 표본: `" + cell(json.dumps(result.get("gpu_memory"), ensure_ascii=False)) + "`.",
              "- CPU 시간 상한·커밋 상한·GPU 기능 가드는 기준 하드웨어의 처리량을 재현하지 않는다.",
              "- wall 시간에는 선점·드라이버 대기가 포함된다. GPU elapsed는 draw+SDL flush 제출 간격을 포함할 수 있다.",
              "- 직접 조작의 프레임 분포는 최근 최대 3,600개, 처리 구간·교전 부하는 전체 측정 구간이다.",
              "- 상세 계측·cProfile의 오버헤드는 보정하지 않는다. 동일 조건으로 비교하고 FPS 판정은 가벼운 별도 실행으로 확인한다.",
              "- 기능 위반·실행 오류·측정 미완료는 목표 충족으로 해석하지 않는다.",
              "", "원자료: [report.json](report.json), [timings.json](timings.json), [limits_final.json](limits_final.json).", ""]
    return "\n".join(lines)


def write_report(source, *, destination=None):
    source = Path(source)
    limits_path = source.with_name("limits_final.json")
    limits = json.loads(limits_path.read_text(encoding="utf-8")) if limits_path.is_file() else None
    destination = Path(destination) if destination is not None else source.with_suffix(".md")
    result = json.loads(source.read_text(encoding="utf-8"))
    flamegraph = write_flamegraph(result, destination.with_name("flamegraph.svg"))
    for row in live_combat_frames(result.get("benchmark") or {}):
        graph = destination.parent / frame_flamegraph_path(row)
        graph.parent.mkdir(exist_ok=True)
        write_frame_flamegraph(row, graph)
    destination.write_text(render_report(result, limits, flamegraph=flamegraph), encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="측정된 report.json 경로")
    args = parser.parse_args()
    print(write_report(args.report))


if __name__ == "__main__":
    main()
