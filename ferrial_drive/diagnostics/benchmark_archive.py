"""직접 조작 보고서 보관 위치와 탐색 목록을 관리한다."""

from pathlib import Path

from ferrial_drive.json_io import read_json


def default_benchmark_output(root, stamp, *, interactive):
    folder = root / "report" / "interactive" if interactive else root / "output" / "performance" / "hardware_profile"
    return folder / stamp


def write_interactive_index(root):
    reports = Path(root) / "report"
    sources = (*reports.glob("*/report.json"), *(reports / "interactive").glob("*/report.json"))
    entries = []
    for source in sources:
        try:
            result = read_json(source)
        except (OSError, ValueError):
            continue
        if not isinstance(result, dict) or result.get("input_mode") != "interactive":
            continue
        stamp = result.get("measured_at") or source.parent.name
        summaries = sorted(source.parent.glob("*.md"), reverse=True)
        entries.append((stamp, result.get("scenario", "미기록"), result.get("status", "미기록"),
                        (summaries[0] if summaries else source).relative_to(reports).as_posix(),
                        source.relative_to(reports).as_posix()))

    lines = ["# 직접 조작 벤치마크", "", "새 결과는 `interactive/`에 저장한다. 앞서 실행한 직접 조작 결과도 여기서 열 수 있다.",
             "", "| 실행 시각 | 장면 | 상태 | 보고서 | 원자료 |", "| --- | --- | --- | --- | --- |"]
    for stamp, scenario, status, summary, source in sorted(entries, reverse=True):
        lines.append(f"| {stamp} | {scenario} | {status} | [열기](<{summary}>) | [JSON](<{source}>) |")
    reports.mkdir(parents=True, exist_ok=True)
    destination = reports / "직접조작.md"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
