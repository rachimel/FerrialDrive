"""학교안심 운동장 원본을 보존하고 HUD 숫자용 각진 OTF 사본을 생성한다."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/fonts/학교안심 운동장/HakgyoansimUndongjangOTFL.otf"
DESTINATION = ROOT / "data/fonts/ferrial_hud_square/FerrialHudSquare-Regular.otf"
SOURCE_SHA256 = "dd370e205d784fddae359199a1b5f0d3a138523a9e2db71663012e13ef7ef393"
FAMILY = "Ferrial HUD Square"
POSTSCRIPT_NAME = "FerrialHudSquare-Regular"


def outline(glyph):
    pen = RecordingPen()
    glyph.draw(pen)
    return pen.value


def simplify(points):
    """직각 변환으로 생긴 일직선의 중복·되짚는 꼭짓점을 제거한다."""
    changed = True
    while changed and len(points) > 3:
        changed = False
        for index in range(len(points)):
            previous = points[index - 1]
            current = points[index]
            following = points[(index + 1) % len(points)]
            cross = ((current[0] - previous[0]) * (following[1] - current[1])
                     - (current[1] - previous[1]) * (following[0] - current[0]))
            if cross == 0:
                points.pop(index)
                changed = True
                break
    return points


def square_contours(commands):
    contours = []
    points = []
    for operation, operands in commands:
        if operation == "moveTo":
            points = [operands[0]]
        elif operation == "lineTo":
            points.append(operands[0])
        elif operation == "curveTo":
            first, second, end = operands
            start = points[-1]
            # 원본 숫자의 둥근 모서리를 접선의 주축에 맞춘 직각으로 바꾼다.
            if abs(first[0] - start[0]) >= abs(first[1] - start[1]):
                corner = (end[0], start[1])
            else:
                corner = (start[0], end[1])
            points.extend((corner, end))
        elif operation == "closePath":
            contours.append(simplify(points))
        else:
            raise ValueError(f"지원하지 않는 원본 숫자 명령: {operation}")
    return contours


def verify_variant(source, destination):
    with TTFont(source) as original, TTFont(destination) as variant:
        if original.getBestCmap() != variant.getBestCmap():
            raise ValueError("문자 매핑이 변경됐다.")
        if original["hmtx"].metrics != variant["hmtx"].metrics:
            raise ValueError("원본 글자 폭 또는 사이드베어링이 변경됐다.")
        if original["name"].getDebugName(0) != variant["name"].getDebugName(0):
            raise ValueError("원본 저작권 고지가 변경됐다.")
        original_glyphs, variant_glyphs = original.getGlyphSet(), variant.getGlyphSet()
        expected = {original.getBestCmap()[ord(char)] for char in "0123456789"}
        changed = {name for name in original.getGlyphOrder()
                   if outline(original_glyphs[name]) != outline(variant_glyphs[name])}
        if changed != expected:
            raise ValueError(f"숫자 이외의 윤곽 변경 또는 숫자 변경 누락: {changed ^ expected}")
        for name in expected:
            if any(operation == "curveTo" for operation, _ in outline(variant_glyphs[name])):
                raise ValueError("수정 숫자에 곡선이 남았다.")
        zero = outline(variant_glyphs[variant.getBestCmap()[ord("0")]])
        if sum(operation == "moveTo" for operation, _ in zero) != 2:
            raise ValueError("0은 외곽과 단일 내부 공간으로 구성해야 한다.")
        if variant["name"].getDebugName(1) != FAMILY:
            raise ValueError("수정본 가족명이 다르다.")
        return {"changed_glyphs": sorted(changed),
                "unchanged_glyphs": len(original.getGlyphOrder()) - len(changed)}


def build(source=SOURCE, destination=DESTINATION):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError("원본 경로에 덮어쓸 수 없다.")
    if sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("기준 학교안심 운동장 OTF 원본과 일치하지 않는다.")
    with TTFont(source, recalcTimestamp=False) as font:
        glyphs = font.getGlyphSet()
        top = font["CFF "].cff.topDictIndex[0]
        for char in "0123456789":
            name = font.getBestCmap()[ord(char)]
            contours = square_contours(outline(glyphs[name]))
            if char == "0":
                # 원본의 두 삼각형 내부 공간을 하나의 직사각형으로 합쳐 사선을 없앤다.
                contours = [[(67, 686), (67, 5), (642, 5), (642, 686)],
                            [(213, 87), (213, 604), (496, 604), (496, 87)]]
            pen = T2CharStringPen(font["hmtx"].metrics[name][0], glyphs)
            for points in contours:
                pen.moveTo(points[0])
                for point in points[1:]:
                    pen.lineTo(point)
                pen.closePath()
            top.CharStrings[name] = pen.getCharString(
                private=top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
        names = {1: FAMILY, 2: "Regular", 3: f"1.000;FerrialDrive;{POSTSCRIPT_NAME}",
                 4: f"{FAMILY} Regular", 5: "Version 1.000", 6: POSTSCRIPT_NAME,
                 16: FAMILY, 17: "Regular",
                 13: "SIL Open Font License 1.1. Modified numeric outlines; original copyright retained.",
                 14: "https://openfontlicense.org/"}
        for record in list(font["name"].names):
            if record.nameID in names:
                font["name"].setName(names[record.nameID], record.nameID,
                                     record.platformID, record.platEncID, record.langID)
        for name_id, value in names.items():
            font["name"].setName(value, name_id, 3, 1, 0x409)
        font["CFF "].cff.fontNames = [POSTSCRIPT_NAME]
        top.FamilyName = FAMILY
        top.FullName = names[4]
        if "DSIG" in font:
            del font["DSIG"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        font.save(destination)
    report = verify_variant(source, destination)
    shutil.copyfile(source.parent / "LICENSE.txt", destination.parent / "LICENSE.txt")
    manifest = {"family": FAMILY, "source": source.relative_to(ROOT).as_posix(),
                "source_sha256": SOURCE_SHA256,
                "output_sha256": sha256(destination.read_bytes()).hexdigest(),
                "changes": ["Square ASCII digit contours", "Remove slash from ASCII zero"],
                "preserved": ["Other glyph outlines", "Character mapping", "Advance widths",
                              "Sidebearings", "Original copyright"], **report}
    (destination.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="기존 생성본의 윤곽·메트릭 보존 검사")
    arguments = parser.parse_args()
    result = verify_variant(SOURCE, DESTINATION) if arguments.check else build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
