"""현재 폴더만 읽는 테스트 파일 탐색 상태. 창·프로세스에 의존하지 않는다."""

from dataclasses import dataclass
from pathlib import Path

from .entrypoints import entrypoint_from_tree, read_test_header, read_test_source


@dataclass(frozen=True)
class BrowserEntry:
    path: Path
    is_directory: bool
    mode: str = ""
    reason: str = ""
    is_parent: bool = False
    title: str = ""
    description: str = ""

    @property
    def display_name(self):
        return ".." if self.is_parent else self.path.name

    @property
    def runnable(self):
        return not self.is_directory and bool(self.mode) and not self.reason


class FileBrowser:
    def __init__(self, directory: Path, visible_rows=11):
        self.directory = Path(directory).resolve()
        self.visible_rows = visible_rows
        self.entries = []
        self.selected_index = None
        self.offset = 0
        self.error = ""
        self.refresh()

    @property
    def selected(self):
        return self.entries[self.selected_index] if self.selected_index is not None else None

    def refresh(self):
        selected_path = self.selected.path if self.selected else None
        try:
            entries = []
            for path in self.directory.iterdir():
                is_directory = path.is_dir()
                if not is_directory and (path.suffix.lower() != ".py" or not path.is_file()):
                    continue
                mode, reason, title, description = "", "", "", ""
                if not is_directory:
                    try:
                        tree = read_test_source(path)
                        title, description = read_test_header(tree)
                        mode = entrypoint_from_tree(tree)
                    except SyntaxError as error:
                        reason = f"문법 오류 ({error.lineno or '?'}행): {error.msg}"
                    except (OSError, UnicodeError, ValueError) as error:
                        reason = str(error)
                entries.append(BrowserEntry(path, is_directory, mode, reason,
                                            title=title, description=description))
            entries.sort(key=lambda entry: (not entry.is_directory, entry.path.name.casefold()))
            if self.directory.parent != self.directory:
                entries.insert(0, BrowserEntry(self.directory.parent, True, is_parent=True))
        except OSError as error:
            self.error = f"폴더를 열 수 없다: {error}"
            return False
        self.entries = entries
        self.selected_index = next((i for i, entry in enumerate(entries)
                                    if entry.path == selected_path), None)
        self.scroll(0)
        self.error = ""
        return True

    def navigate(self, directory):
        previous = self.directory
        self.directory = Path(directory).resolve()
        if not self.refresh():
            self.directory = previous
            return False
        self.selected_index = None
        self.offset = 0
        return True

    def select(self, index):
        if 0 <= index < len(self.entries):
            self.selected_index = index
            if index < self.offset:
                self.offset = index
            elif index >= self.offset + self.visible_rows:
                self.offset = index - self.visible_rows + 1

    def move_selection(self, direction):
        if self.entries:
            index = self.selected_index
            if index is None:
                index = 0 if direction > 0 else len(self.entries) - 1
            else:
                index = max(0, min(len(self.entries) - 1, index + direction))
            self.select(index)

    def scroll(self, rows):
        self.offset = max(0, min(max(0, len(self.entries) - self.visible_rows), self.offset + rows))

    def activate(self):
        entry = self.selected
        if entry is None:
            return None
        if entry.is_directory:
            self.navigate(entry.path)
        elif entry.runnable:
            return entry.path
        return None
