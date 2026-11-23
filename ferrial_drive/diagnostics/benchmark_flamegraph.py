"""계측 구간의 호출 경로를 Flamegraph SVG로 저장한다."""

from collections import Counter, defaultdict
from xml.etree import ElementTree as ET
from zlib import crc32


MIN_WIDTH = 1440
MARGIN = 20
ROW_HEIGHT = 22
NAME_CHAR_WIDTH = 9
DEPTH_INDENT = 18
TIME_COLUMNS_WIDTH = 360


def write_flamegraph(result, destination):
    """보고서 옆에 호출 경로별 누적 wall 시간을 표시한다."""
    datasets = [(f"{row['round']}회차 · {row['variant']}", row.get("draw_breakdown", {}))
                for row in result.get("comparisons", ())]
    if not datasets:
        probe = result.get("draw_breakdown", {})
        datasets = [(probe.get("variant", "측정 구간"), probe)]
    return _write_graph([(label, probe.get("flamegraph_stacks") or (), probe.get("flamegraph_order"))
                         for label, probe in datasets], destination)


def write_frame_flamegraph(row, destination):
    """느린 프레임 하나의 전투 모션 호출 경로를 저장한다."""
    label = f"{row['frame']}프레임 · 프레임 작업 {row['work_ms']:.2f} ms"
    return _write_graph([(label, row["live_combat_stacks"], row.get("flamegraph_order"))], destination)


def _write_graph(datasets, destination):
    name_width = max((len(path[-1]) * NAME_CHAR_WIDTH + (len(path) - 1) * DEPTH_INDENT
                      for _, stacks, _ in datasets for entry in stacks if (path := entry["stack"])), default=0)
    if not name_width:
        return False
    width = max(MIN_WIDTH, 2 * MARGIN + name_width + TIME_COLUMNS_WIDTH + 38)
    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(width), role="img")
    ET.SubElement(svg, "title").text = "Ferrial Drive 벤치마크 Flamegraph"
    ET.SubElement(svg, "rect", width="100%", height="100%", fill="#fffaf1")
    text = ET.SubElement(svg, "g", fill="#291e19", **{"font-family": "system-ui, sans-serif"})
    ET.SubElement(text, "text", x=str(MARGIN), y="30", **{"font-size": "20"}).text = "벤치마크 Flamegraph"
    ET.SubElement(text, "text", x=str(MARGIN), y="53", **{"font-size": "13"}).text = (
        "아래에서 위로 호출 관계를 읽는다. 블록 폭과 표의 비중은 전체 계측 시간 대비 포함 시간이다. "
        "경과 시간에는 대기와 계측 비용이 포함된다."
    )
    start_y = top = 74
    for label, stacks, order in datasets:
        if stacks:
            top = _draw_scopes(text, label, stacks, top, width, order)
    if top == start_y:
        return False

    svg.set("height", str(top))
    svg.set("viewBox", f"0 0 {width} {top}")
    ET.ElementTree(svg).write(destination, encoding="utf-8", xml_declaration=True)
    return True


def _scope_color(name):
    hue = 12 + crc32(name.encode("utf-8")) % 38
    return f"hsl({hue}, 86%, 69%)"


def _draw_call_table(svg, rows, total_ns, top, width, order):
    table = ET.SubElement(svg, "g", **{"aria-label": "호출 경로별 시간"})
    order_text = "같은 부모 아래에서 처음 호출된 순서" if order == "first_call" else "이전 기록 · 이름순"
    ET.SubElement(table, "text", x=str(MARGIN), y=str(top + 13), **{"font-size": "13"}).text = order_text
    right = width - MARGIN
    columns = (right - 240, right - 120, right)
    header_y = top + 38
    ET.SubElement(table, "text", x=str(MARGIN), y=str(header_y), **{"font-weight": "600"}).text = "함수·구간"
    for x, title in zip(columns, ("포함 시간 (ms)", "자체 시간 (ms)", "시간 비중")):
        ET.SubElement(table, "text", x=str(x), y=str(header_y),
                      **{"font-size": "13", "font-weight": "600", "text-anchor": "end"}).text = title
    for index, (path, elapsed, own) in enumerate(rows):
        group = ET.SubElement(table, "g", **{"data-depth": str(len(path) - 1)})
        y = header_y + 23 + index * ROW_HEIGHT
        if index % 2 == 0:
            ET.SubElement(group, "rect", x=str(MARGIN), y=str(y - 16), width=str(width - 2 * MARGIN),
                          height=str(ROW_HEIGHT), fill="#f6eddf")
        name = path[-1]
        x = MARGIN + 4 + (len(path) - 1) * DEPTH_INDENT
        ET.SubElement(group, "rect", x=str(x), y=str(y - 11), width="10", height="10", fill=_scope_color(name))
        ET.SubElement(group, "text", x=str(x + 17), y=str(y),
                      **{"font-family": "Consolas, monospace", "font-size": "14"}).text = name
        values = (f"{elapsed / 1e6:,.3f}", f"{own / 1e6:,.3f}", f"{elapsed / total_ns:.2%}")
        for x, value in zip(columns, values):
            ET.SubElement(group, "text", x=str(x), y=str(y),
                          **{"font-family": "Consolas, monospace", "font-size": "14", "text-anchor": "end"}).text = value
    return header_y + 31 + len(rows) * ROW_HEIGHT


def _draw_scopes(svg, label, stacks, top, chart_width, order):
    inclusive_ns = Counter()
    own_ns = {}
    for row in stacks:
        path = tuple(row["stack"])
        own_ns[path] = row["self_wall_ns"]
        for depth in range(len(path) + 1):
            inclusive_ns[path[:depth]] += row["self_wall_ns"]

    total_ns = inclusive_ns[()]
    if not total_ns:
        return top
    children = defaultdict(list)
    paths = inclusive_ns if order == "first_call" else sorted(inclusive_ns)
    for path in paths:
        if path and inclusive_ns[path]:
            children[path[:-1]].append(path)
    rows = []
    bottom = top + 29 + max(map(len, inclusive_ns)) * ROW_HEIGHT
    scale = (chart_width - 2 * MARGIN) / total_ns
    ET.SubElement(svg, "text", x=str(MARGIN), y=str(top + 14), **{"font-size": "14"}).text = (
        f"{label} · 계측 구간 합계 {total_ns / 1e6:,.2f} ms"
    )

    def draw_children(parent, x):
        for path in children.get(parent, ()):
            name = path[-1]
            elapsed = inclusive_ns[path]
            own = own_ns.get(path, 0)
            rows.append((path, elapsed, own))
            width = elapsed * scale
            y = bottom - len(path) * ROW_HEIGHT
            block = ET.SubElement(svg, "g")
            ET.SubElement(block, "title").text = (
                f"{' → '.join(path)}\n포함 {elapsed / 1e6:,.3f} ms ({elapsed / total_ns:.2%})"
                f"\n자체 {own / 1e6:,.3f} ms"
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
    return _draw_call_table(svg, rows, total_ns, bottom + 20, chart_width, order)
