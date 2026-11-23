"""계측 구간의 호출 경로를 Flamegraph SVG로 저장한다."""

from collections import Counter, defaultdict
from xml.etree import ElementTree as ET
from zlib import crc32


MIN_WIDTH = 1440
MARGIN = 20
ROW_HEIGHT = 22
NAME_COLUMNS = 3
NAME_CHAR_WIDTH = 9


def write_flamegraph(result, destination):
    """보고서 옆에 호출 경로별 누적 wall 시간을 표시한다."""
    datasets = [(f"{row['round']}회차 · {row['variant']}", row.get("draw_breakdown", {}))
                for row in result.get("comparisons", ())]
    if not datasets:
        probe = result.get("draw_breakdown", {})
        datasets = [(probe.get("variant", "측정 구간"), probe)]
    return _write_graph([(label, probe.get("flamegraph_stacks")) for label, probe in datasets], destination)


def write_frame_flamegraph(row, destination):
    """느린 프레임 하나의 전투 모션 호출 경로를 저장한다."""
    label = f"{row['frame']}프레임 · 프레임 작업 {row['work_ms']:.2f} ms"
    return _write_graph([(label, row["live_combat_stacks"])], destination)


def _write_graph(datasets, destination):
    names = sorted({name for _, stacks in datasets for entry in stacks or () for name in entry["stack"]})
    if not names:
        return False
    column_width = max((MIN_WIDTH - 2 * MARGIN) // NAME_COLUMNS,
                       max(map(len, names)) * NAME_CHAR_WIDTH + 34)
    width = max(MIN_WIDTH, 2 * MARGIN + NAME_COLUMNS * column_width)
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(width), role="img")
    ET.SubElement(svg, "title").text = "Ferrial Drive 벤치마크 Flamegraph"
    ET.SubElement(svg, "rect", width="100%", height="100%", fill="#fffaf1")
    text = ET.SubElement(svg, "g", fill="#291e19", **{"font-family": "system-ui, sans-serif"})
    ET.SubElement(text, "text", x=str(MARGIN), y="30", **{"font-size": "20"}).text = "벤치마크 Flamegraph"
    ET.SubElement(text, "text", x=str(MARGIN), y="53", **{"font-size": "13"}).text = (
        "아래에서 위로 호출 관계를 읽는다. 폭은 그래프별 누적 wall 시간 비중이며 대기와 계측 비용을 포함한다."
    )
    top = 74
    for label, stacks in datasets:
        if stacks:
            top = _draw_scopes(text, label, stacks, top, width)
    top = _draw_names(text, names, top, column_width)

    svg.set("height", str(top))
    svg.set("viewBox", f"0 0 {width} {top}")
    ET.ElementTree(svg).write(destination, encoding="utf-8", xml_declaration=True)
    return True


def _scope_color(name):
    hue = 12 + crc32(name.encode("utf-8")) % 38
    return f"hsl({hue}, 86%, 69%)"


def _draw_names(text, names, top, column_width):
    title = "전체 함수·구간 이름"
    names_group = ET.SubElement(text, "g", **{"aria-label": title})
    ET.SubElement(names_group, "text", x=str(MARGIN), y=str(top + 16), **{"font-size": "16"}).text = title
    rows = (len(names) + NAME_COLUMNS - 1) // NAME_COLUMNS
    for index, name in enumerate(names):
        column, row = divmod(index, rows)
        x = MARGIN + column * column_width
        y = top + 40 + row * ROW_HEIGHT
        ET.SubElement(names_group, "rect", x=str(x), y=str(y - 11), width="10", height="10", fill=_scope_color(name))
        ET.SubElement(names_group, "text", x=str(x + 17), y=str(y),
                      **{"font-family": "Consolas, monospace", "font-size": "14"}).text = name
    return top + 40 + rows * ROW_HEIGHT


def _draw_scopes(svg, label, stacks, top, chart_width):
    inclusive_ns = Counter()
    own_ns = {}
    for row in stacks:
        path = tuple(row["stack"])
        own_ns[path] = row["self_wall_ns"]
        for depth in range(len(path) + 1):
            inclusive_ns[path[:depth]] += row["self_wall_ns"]

    children = defaultdict(list)
    for path in sorted(inclusive_ns):
        if path:
            children[path[:-1]].append(path)
    total_ns = inclusive_ns[()]
    bottom = top + 29 + max(map(len, inclusive_ns)) * ROW_HEIGHT
    scale = (chart_width - 2 * MARGIN) / total_ns
    ET.SubElement(svg, "text", x=str(MARGIN), y=str(top + 14), **{"font-size": "14"}).text = (
        f"{label} · 계측 구간 합계 {total_ns / 1e6:,.2f} ms"
    )

    def draw_children(parent, x):
        for path in children.get(parent, ()):
            name = path[-1]
            elapsed = inclusive_ns[path]
            width = elapsed * scale
            y = bottom - len(path) * ROW_HEIGHT
            block = ET.SubElement(svg, "g")
            ET.SubElement(block, "title").text = (
                f"{' → '.join(path)}\n포함 {elapsed / 1e6:,.3f} ms ({elapsed / total_ns:.2%})"
                f"\n자체 {own_ns.get(path, 0) / 1e6:,.3f} ms"
            )
            ET.SubElement(block, "rect", x=f"{x:.3f}", y=str(y), width=f"{width:.3f}", height=str(ROW_HEIGHT - 1),
                          fill=_scope_color(name), stroke="#fffaf1", **{"stroke-width": "0.5"})
            capacity = int((width - 8) / NAME_CHAR_WIDTH)
            if capacity >= 3:
                caption = name if len(name) <= capacity else name[:capacity - 1] + "…"
                ET.SubElement(block, "text", x=f"{x + 4:.3f}", y=str(y + 15),
                              **{"font-family": "Consolas, monospace", "font-size": "13",
                                 "pointer-events": "none"}).text = caption
            draw_children(path, x)
            x += width

    draw_children((), MARGIN)
    return bottom + 20
