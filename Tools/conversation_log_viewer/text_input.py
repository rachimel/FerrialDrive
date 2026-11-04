"""SDL 텍스트 입력용 편집 상태. 한글 조합 중 문자열과 확정 입력을 구분한다."""

from dataclasses import dataclass


@dataclass
class TextInput:
    text: str = ""
    cursor: int = 0
    anchor: int | None = None
    composition: str = ""
    multiline: bool = False

    @property
    def selection(self):
        return (min(self.cursor, self.anchor), max(self.cursor, self.anchor)) if self.anchor is not None else (self.cursor, self.cursor)

    def insert(self, value):
        if not self.multiline:
            value = value.replace("\r", " ").replace("\n", " ")
        else:
            value = value.replace("\r\n", "\n").replace("\r", "\n")
        start, end = self.selection
        self.text = self.text[:start] + value + self.text[end:]
        self.cursor = start + len(value)
        self.anchor = None
        self.composition = ""

    def move(self, amount, select=False):
        if select and self.anchor is None:
            self.anchor = self.cursor
        if not select:
            self.anchor = None
        self.cursor = max(0, min(len(self.text), self.cursor + amount))

    def erase(self, backwards=True):
        if self.composition:
            return
        start, end = self.selection
        if start == end:
            if backwards:
                start = max(0, start - 1)
            else:
                end = min(len(self.text), end + 1)
        self.text = self.text[:start] + self.text[end:]
        self.cursor, self.anchor = start, None

    def selected_text(self):
        start, end = self.selection
        return self.text[start:end]

    def move_line(self, direction, select=False):
        lines = self.text.split("\n")
        row = self.text[:self.cursor].count("\n")
        column = self.cursor - (self.text.rfind("\n", 0, self.cursor) + 1)
        target_row = max(0, min(len(lines)-1, row+direction))
        target = sum(len(line)+1 for line in lines[:target_row]) + min(column, len(lines[target_row]))
        self.move(target-self.cursor, select)
