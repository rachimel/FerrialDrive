"""요약 표시 문자열과 누락 태그의 위치를 함께 보존한다."""

from dataclasses import dataclass
import re

from .model import GAP_NAMES, GAP_PATTERN


@dataclass(frozen=True)
class GapMark:
    start: int
    end: int
    token: str


@dataclass(frozen=True)
class ChatLine:
    text: str
    marks: tuple[GapMark, ...]


def display_text(text):
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[이미지]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "").replace("\r\n", "\n").replace("\r", "\n")
    parts, marks = [], []
    cursor = length = 0
    for match in GAP_PATTERN.finditer(text):
        prefix = text[cursor:match.start()]
        label = "[미확인: " + GAP_NAMES.get(match[1], match[1]) + " · " + match[2].rsplit(":", 1)[-1] + "]"
        parts.extend((prefix, label))
        length += len(prefix)
        marks.append(GapMark(length, length + len(label), match[0]))
        length += len(label)
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts), tuple(marks)


def wrap_gap_lines(text, width, measure):
    displayed, marks = display_text(text)
    lines = []

    def append_line(content, start):
        end = start + len(content)
        local = tuple(GapMark(max(start, mark.start) - start, min(end, mark.end) - start, mark.token)
                      for mark in marks if mark.start < end and mark.end > start)
        lines.append(ChatLine(content, local))

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
