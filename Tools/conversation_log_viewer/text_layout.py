"""요약 표시 문자열과 누락 태그의 위치를 함께 보존한다."""

from dataclasses import dataclass
import re

from .model import GAP_NAMES, GAP_PATTERN
from .readable import REFERENCE, human_times, item_label, reference_label


@dataclass(frozen=True)
class GapMark:
    start: int
    end: int
    token: str


@dataclass(frozen=True)
class StyleMark:
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class ChatLine:
    text: str
    marks: tuple[GapMark, ...]
    styles: tuple[StyleMark, ...] = ()


INLINE = re.compile(GAP_PATTERN.pattern + r"|\*\*[^*\n]+\*\*|`[^`\n]+`|!?\[[^\]\n]*\]\([^)\n]+\)")
PLAIN = re.compile(r"FDLOG-[A-Za-z0-9_.-]+|" + REFERENCE.pattern)


def formatted_text(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\n(?:[ \t]*\n){2,}", "\n\n", text).strip("\n")
    text = human_times(text.replace("\r\n", "\n").replace("\r", "\n"))
    parts, gaps, styles = [], [], []
    length = 0

    def append(value, kind=None):
        nonlocal length
        start = length
        parts.append(value)
        length += len(value)
        if kind and value:
            styles.append(StyleMark(start, length, kind))

    def plain(value):
        value = re.sub(r"((?:사용자 제안|AI 제안|발견한 문제|확인 결과)\s*\d+)\s*\([UAIV]\d+\)", r"\1", value)
        cursor = 0
        for match in PLAIN.finditer(value):
            append(value[cursor:match.start()])
            if match[0].startswith("FDLOG-"):
                append(match[0], "record_id")
            else:
                append(reference_label(REFERENCE.fullmatch(match[0])), "reference")
            cursor = match.end()
        append(value[cursor:])

    def inline(value):
        cursor = 0
        for match in INLINE.finditer(value):
            plain(value[cursor:match.start()])
            token = match[0]
            gap = GAP_PATTERN.fullmatch(token)
            if gap:
                label = "[미확인: " + GAP_NAMES.get(gap[1], gap[1]) + " · " + item_label(gap[2].rsplit(":", 1)[-1]) + "]"
                start = length
                append(label)
                gaps.append(GapMark(start, length, token))
            elif token.startswith("**") or token.startswith("`"):
                start = length
                inline(token[2:-2] if token.startswith("**") else token[1:-1])
                styles.append(StyleMark(start, length, "strong" if token.startswith("**") else "code"))
            elif token.startswith("!["):
                append("[이미지]", "code")
            else:
                start = length
                inline(re.match(r"\[([^\]]*)\]", token)[1])
                styles.append(StyleMark(start, length, "reference"))
            cursor = match.end()
        plain(value[cursor:])

    for index, line in enumerate(text.split("\n")):
        if index:
            append("\n")
        heading = re.match(r"^\s*#{1,6}\s+(.+)", line)
        start = length
        inline(heading[1] if heading else line)
        if heading:
            styles.append(StyleMark(start, length, "heading"))
    return "".join(parts), tuple(gaps), tuple(styles)


def display_text(text):
    displayed, marks, _ = formatted_text(text)
    return displayed, marks


def wrap_gap_lines(text, width, measure):
    displayed, marks, styles = formatted_text(text)
    lines = []

    def append_line(content, start):
        end = start + len(content)
        local = tuple(GapMark(max(start, mark.start) - start, min(end, mark.end) - start, mark.token)
                      for mark in marks if mark.start < end and mark.end > start)
        local_styles = tuple(StyleMark(max(start, mark.start) - start, min(end, mark.end) - start, mark.kind)
                             for mark in styles if mark.start < end and mark.end > start)
        lines.append(ChatLine(content, local, local_styles))

    offset = 0
    for paragraph in displayed.split("\n"):
        current, start = "", offset
        for char in paragraph:
            if current and measure(current + char) > width:
                append_line(current, start)
                start += len(current)
                current = ""
            current += char
        append_line(current, start)
        offset += len(paragraph) + 1
    return lines
