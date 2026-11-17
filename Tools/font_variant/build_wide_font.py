"""Ferrial HUD Square 전체 윤곽을 각지게 만들고 가로 비율만 확장한다."""

import argparse
from hashlib import sha256
import json
from math import ceil, floor, hypot, isfinite
from pathlib import Path
import shutil

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/fonts/ferrial_hud_square/FerrialHudSquare-Regular.otf"
DESTINATION = ROOT / "data/fonts/ferrial_hud_square_wide/FerrialHudSquareWide-Regular.otf"
SOURCE_SHA256 = "d8ba3003147963ffec9f782e50c629aa6871da5767b10521b832743bc0feb5dc"
FAMILY = "Ferrial HUD Square Wide"
POSTSCRIPT_NAME = "FerrialHudSquareWide-Regular"
DEFAULT_WIDTH_SCALE = 1.20
DEFAULT_BEVEL = 0.35
FLATNESS_UNITS = 12.0
# 고밀도 기호는 원본 곡선을 더 촘촘한 직선으로 바꿔 획/속공간의 합쳐짐을 피한다.
# 기준 원본의 128/256px 전체 문자 검사에서 찾은 항목이며 일반 글자에는 적용하지 않는다.
PRESERVE_SHAPE_GLYPHS = {
    "uni246E", "uni2606", "uni3049", "uni3065", "uni3182", "uni3380", "uni3389", "uni33D8",
    "uniE02C", "uniE034", "uniE038", "uniE04E", "uniE052", "uniE117", "uniE118",
    "uniE13A", "uniE141",
}


def outline(glyph):
    pen = RecordingPen()
    glyph.draw(pen)
    return pen.value


def contour_areas(commands):
    areas = []
    pen = None
    for operation, operands in commands:
        if operation == "moveTo":
            pen = AreaPen()
        getattr(pen, operation)(*operands)
        if operation == "closePath":
            areas.append(pen.value)
    return areas


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def signed_area(points):
    return sum(a[0] * b[1] - b[0] * a[1]
               for a, b in zip(points, points[1:] + points[:1])) / 2


def clean_points(points):
    cleaned = []
    for point in points:
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    changed = True
    while changed and len(cleaned) > 3:
        changed = False
        for index in range(len(cleaned)):
            a, b, c = cleaned[index - 1], cleaned[index], cleaned[(index + 1) % len(cleaned)]
            if cross(a, b, c) == 0:
                cleaned.pop(index)
                changed = True
                break
    return cleaned


def has_crossing(points):
    """끝점 접촉·공선은 제외하고, 비인접 변이 가로지르는지 검사한다."""
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 2, count):
            if first == 0 and second == count - 1:
                continue
            c, d = points[second], points[(second + 1) % count]
            if (max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0])
                    or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1])):
                continue
            if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
                return True
    return False


def cubic_point(start, first, second, end, amount):
    other = 1 - amount
    return tuple(other ** 3 * start[axis] + 3 * other ** 2 * amount * first[axis]
                 + 3 * other * amount ** 2 * second[axis] + amount ** 3 * end[axis]
                 for axis in (0, 1))


def linearized_curve(start, first, second, end, tolerance=FLATNESS_UNITS):
    """복잡한 곡선은 형상을 따라 직선으로 분할한다. S자·루프의 끝점도 보존한다."""
    result = []

    def subdivide(a, b, depth):
        p, q = cubic_point(start, first, second, end, a), cubic_point(start, first, second, end, b)
        length = hypot(q[0] - p[0], q[1] - p[1])
        deviations = []
        for fraction in (0.25, 0.5, 0.75):
            probe = cubic_point(start, first, second, end, a + (b - a) * fraction)
            if length:
                # 수직 거리뿐 아니라 매개변수상의 진행도 비교해 되감기는 곡선도 분할한다.
                chord = (p[0] + (q[0] - p[0]) * fraction,
                         p[1] + (q[1] - p[1]) * fraction)
                deviations.append(hypot(probe[0] - chord[0], probe[1] - chord[1]))
            else:
                deviations.append(hypot(probe[0] - p[0], probe[1] - p[1]))
        if max(deviations) <= tolerance or depth >= 12:
            result.append(q)
        else:
            middle = (a + b) / 2
            subdivide(a, middle, depth + 1)
            subdivide(middle, b, depth + 1)

    subdivide(0, 1, 0)
    return result


def beveled_curve(start, first, second, end, bevel):
    initial = (first[0] - start[0], first[1] - start[1])
    final = (end[0] - second[0], end[1] - second[1])

    def axis(vector):
        major = 0 if abs(vector[0]) >= abs(vector[1]) else 1
        return major if abs(vector[1 - major]) <= max(1, abs(vector[major]) * 0.06) else None

    first_axis, last_axis = axis(initial), axis(final)
    inside = all(min(start[dimension], end[dimension]) - 1 <= control[dimension]
                 <= max(start[dimension], end[dimension]) + 1
                 for control in (first, second) for dimension in (0, 1))
    if first_axis is None or last_axis is None or first_axis == last_axis or not inside:
        return linearized_curve(start, first, second, end)
    corner = (end[0], start[1]) if first_axis == 0 else (start[0], end[1])
    before = tuple(corner[axis] + (start[axis] - corner[axis]) * bevel for axis in (0, 1))
    after = tuple(corner[axis] + (end[axis] - corner[axis]) * bevel for axis in (0, 1))
    return [before, after, end]


def contours_from_commands(commands, *, bevel, preserve_shape=False):
    contours, segments = [], []
    for operation, operands in commands:
        if operation == "moveTo":
            segments = [(operation, operands)]
        elif operation in ("lineTo", "curveTo"):
            segments.append((operation, operands))
        elif operation == "closePath":
            contours.append(segments)
        else:
            raise ValueError(f"지원하지 않는 CFF 명령: {operation}")
    result, fallback_count = [], 0
    for segments in contours:
        source_points, candidate = [], []
        current = None
        for operation, operands in segments:
            if operation == "moveTo":
                current = operands[0]
                source_points.append(current)
                candidate.append(current)
            elif operation == "lineTo":
                current = operands[0]
                source_points.append(current)
                candidate.append(current)
            else:
                first, second, end = operands
                precision = 0.01 if preserve_shape else 2
                source_points.extend(linearized_curve(
                    current, first, second, end, tolerance=precision))
                candidate.extend(beveled_curve(current, first, second, end, bevel))
                current = end
        source_points = clean_points(source_points)
        candidate = clean_points(candidate)
        # 각진 변환 때문에 획이 뒤집히거나 교차하면 원래 곡선을 따라 분할한 직선 윤곽을 쓴다.
        if preserve_shape or abs(signed_area(source_points)) < 0.5:
            candidate = source_points
        elif (len(candidate) < 3 or signed_area(candidate) * signed_area(source_points) <= 0
                or (has_crossing(candidate) and not has_crossing(source_points))):
            candidate = source_points
            fallback_count += 1
        result.append(candidate)
    return result, fallback_count


def verify_variant(source, destination, width_scale):
    with TTFont(source) as original, TTFont(destination) as variant:
        if original.getGlyphOrder() != variant.getGlyphOrder() or original.getBestCmap() != variant.getBestCmap():
            raise ValueError("글리프 순서 또는 문자 매핑이 변경됐다.")
        for field in ("ascent", "descent", "lineGap"):
            if getattr(original["hhea"], field) != getattr(variant["hhea"], field):
                raise ValueError(f"세로 메트릭이 변경됐다: {field}")
        if original["name"].getDebugName(0) != variant["name"].getDebugName(0):
            raise ValueError("원본 저작권 고지가 변경됐다.")
        drawn = empty = contours = 0
        originals, variants = original.getGlyphSet(), variant.getGlyphSet()
        for name in original.getGlyphOrder():
            before, after = outline(originals[name]), outline(variants[name])
            if bool(before) != bool(after):
                raise ValueError(f"빈 글리프 상태가 변경됐다: {name}")
            if sum(op == "closePath" for op, _ in before) != sum(op == "closePath" for op, _ in after):
                raise ValueError(f"글리프 외곽/내부 공간 수가 변경됐다: {name}")
            if any(abs(first) > 1 and first * second <= 0
                   for first, second in zip(contour_areas(before), contour_areas(after))):
                raise ValueError(f"외곽 또는 내부 공간의 감기는 방향이 뒤집혔다: {name}")
            if any(op not in ("moveTo", "lineTo", "closePath") for op, _ in after):
                raise ValueError(f"곡선 또는 지원하지 않는 명령이 남았다: {name}")
            expected = tuple(round(value * width_scale) for value in original["hmtx"].metrics[name])
            if variant["hmtx"].metrics[name] != expected:
                raise ValueError(f"가로 메트릭 비율이 다르다: {name}")
            for _, operands in after:
                if any(not all(isfinite(value) for value in point) for point in operands):
                    raise ValueError(f"유한하지 않은 윤곽 좌표: {name}")
            drawn += bool(before)
            empty += not before
            contours += sum(op == "closePath" for op, _ in after)
        zero = outline(variants[variant.getBestCmap()[ord("0")]])
        if sum(op == "moveTo" for op, _ in zero) != 2:
            raise ValueError("0의 사선 제거 상태가 유지되지 않았다.")
        if variant["name"].getDebugName(1) != FAMILY:
            raise ValueError("새 수정본 가족명이 다르다.")
        return {"glyphs": len(original.getGlyphOrder()), "drawn_glyphs": drawn,
                "preserved_empty_glyphs": empty, "preserved_contours": contours,
                "remaining_curves": 0}


def build(*, width_scale=DEFAULT_WIDTH_SCALE, bevel=DEFAULT_BEVEL):
    if not isfinite(width_scale) or not 1 < width_scale <= 1.5:
        raise ValueError("가로 배율은 1 초과 1.5 이하여야 한다.")
    if not isfinite(bevel) or not 0.15 <= bevel <= 0.65:
        raise ValueError("사선 모서리 비율은 0.15~0.65여야 한다.")
    if sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("기준 숫자 수정본의 해시와 일치하지 않는다.")
    all_points, fallback_count, converted_curves = [], 0, 0
    with TTFont(SOURCE, recalcTimestamp=False) as font:
        glyphs = font.getGlyphSet()
        # CFF 글리프는 같은 테이블을 참조하므로 변환 전 윤곽을 먼저 모두 기록한다.
        recordings = {name: outline(glyphs[name]) for name in font.getGlyphOrder()}
        top = font["CFF "].cff.topDictIndex[0]
        extents = []
        for name, commands in recordings.items():
            paths, fallbacks = contours_from_commands(
                commands, bevel=bevel, preserve_shape=name in PRESERVE_SHAPE_GLYPHS)
            fallback_count += fallbacks
            converted_curves += sum(operation == "curveTo" for operation, _ in commands)
            width, bearing = font["hmtx"].metrics[name]
            width, bearing = round(width * width_scale), round(bearing * width_scale)
            font["hmtx"].metrics[name] = (width, bearing)
            pen = T2CharStringPen(width, glyphs, roundTolerance=0)
            glyph_points = []
            for path in paths:
                points = clean_points([(round(x * width_scale, 4), round(y, 4)) for x, y in path])
                if not points or (len(points) < 3 and signed_area(path) != 0):
                    raise ValueError(f"확장 후 윤곽이 소실됐다: {name}")
                pen.moveTo(points[0])
                if len(points) == 1:
                    # 원본 일부 PUA 글리프에 있는 면적 0의 표시를 그대로 보존한다.
                    pen.lineTo(points[0])
                for point in points[1:]:
                    pen.lineTo(point)
                pen.closePath()
                glyph_points.extend(points)
            top.CharStrings[name] = pen.getCharString(private=top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
            if glyph_points:
                all_points.extend(glyph_points)
                span = max(x for x, _ in glyph_points) - min(x for x, _ in glyph_points)
                extents.append((bearing, width - bearing - span, bearing + span))
        minimum_x = floor(min(x for x, _ in all_points))
        maximum_x = ceil(max(x for x, _ in all_points))
        minimum_y = floor(min(y for _, y in all_points))
        maximum_y = ceil(max(y for _, y in all_points))
        top.FontBBox = [minimum_x, minimum_y, maximum_x, maximum_y]
        font["head"].xMin, font["head"].yMin = minimum_x, minimum_y
        font["head"].xMax, font["head"].yMax = maximum_x, maximum_y
        font["head"].fontRevision = 1.1
        font["hhea"].advanceWidthMax = max(value[0] for value in font["hmtx"].metrics.values())
        font["hhea"].minLeftSideBearing = min(row[0] for row in extents)
        font["hhea"].minRightSideBearing = min(row[1] for row in extents)
        font["hhea"].xMaxExtent = max(row[2] for row in extents)
        font["OS/2"].xAvgCharWidth = round(font["OS/2"].xAvgCharWidth * width_scale)
        names = {1: FAMILY, 2: "Regular", 3: f"1.100;FerrialDrive;{POSTSCRIPT_NAME}",
                 4: f"{FAMILY} Regular", 5: "Version 1.100", 6: POSTSCRIPT_NAME,
                 16: FAMILY, 17: "Regular",
                 13: "SIL Open Font License 1.1. Angular wide derivative; original copyright retained.",
                 14: "https://openfontlicense.org/"}
        for record in list(font["name"].names):
            if record.nameID in names:
                font["name"].setName(names[record.nameID], record.nameID,
                                     record.platformID, record.platEncID, record.langID)
        for name_id, value in names.items():
            font["name"].setName(value, name_id, 3, 1, 0x409)
        font["CFF "].cff.fontNames = [POSTSCRIPT_NAME]
        top.FamilyName, top.FullName = FAMILY, names[4]
        if "DSIG" in font:
            del font["DSIG"]
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        font.save(DESTINATION)
    report = verify_variant(SOURCE, DESTINATION, width_scale)
    shutil.copyfile(SOURCE.parent / "LICENSE.txt", DESTINATION.parent / "LICENSE.txt")
    manifest = {"family": FAMILY, "source": SOURCE.relative_to(ROOT).as_posix(),
                "source_sha256": SOURCE_SHA256, "width_scale": width_scale, "height_scale": 1,
                "bevel_ratio": bevel, "irregular_curve_flatness_units": FLATNESS_UNITS,
                "converted_cubic_segments": converted_curves, "fallback_contours": fallback_count,
                "conservative_glyphs": sorted(PRESERVE_SHAPE_GLYPHS),
                "output_sha256": sha256(DESTINATION.read_bytes()).hexdigest(), **report}
    (DESTINATION.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width-scale", type=float, default=DEFAULT_WIDTH_SCALE)
    parser.add_argument("--bevel", type=float, default=DEFAULT_BEVEL)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        manifest = json.loads((DESTINATION.parent / "manifest.json").read_text(encoding="utf-8"))
        result = verify_variant(SOURCE, DESTINATION, manifest["width_scale"])
    else:
        result = build(width_scale=arguments.width_scale, bevel=arguments.bevel)
    print(json.dumps(result, ensure_ascii=False, indent=2))
