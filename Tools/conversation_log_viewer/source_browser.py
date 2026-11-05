"""기존 기록 화면 위에서 Codex 원문 후보를 검색·선택한다."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json

from .codex_source import CodexSource, KST, export_messages
from .text_input import TextInput
from .readable import search_context


def inside(rect, x, y):
    left, top, width, height = rect
    return left <= x < left + width and top <= y < top + height


class SourceBrowser:
    FIELDS = {"source_query": (64, 258, 560, 34), "source_thread": (672, 212, 402, 34)}
    THREAD_RECT = (64, 338, 280, 324)
    RESULT_RECT = (360, 310, 850, 120)

    def __init__(self, owner, source=None, project_name="Ferrial Drive"):
        self.owner = owner
        self.source = source or CodexSource()
        self.project_name = project_name
        self.editors = {name: TextInput() for name in self.FIELDS}
        self.visible = False
        self.projects, self.threads, self.messages = [], [], []
        self.project_index, self.thread_index, self.message_index = 0, 0, 0
        self.thread_offset = self.result_offset = self.preview_offset = 0
        self.preview_max = 0
        self.context = None
        self.context_offset = self.context_max = 0
        self.actor = "전체"
        self.extra_ids = []
        self.extra_by_project = {}
        self.anchor = None
        self.future = self.executor = None
        self.status, self.error = "검색 구절을 입력한다. 빈 검색은 선택한 채팅 전체다.", False

    @property
    def selected(self):
        return self.messages[self.message_index] if self.messages else None

    def open(self):
        self.visible = True
        self.owner.focus = "source_query"
        context = search_context(self.owner.record, self.owner.gap)
        if context != self.context:
            editor = self.editors["source_query"]
            editor.text = context.suggestions[0] if context and context.suggestions else ""
            editor.cursor, editor.anchor = len(editor.text), None
        self.context = context
        self.context_offset = 0
        try:
            settings = self.settings_path
            saved = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
            if not isinstance(saved, dict):
                raise ValueError("추가 채팅 설정의 형식이 잘못됐다.")
            self.extra_by_project = saved.get("extra_by_project", {})
            if not isinstance(self.extra_by_project, dict):
                raise ValueError("추가 채팅 목록의 형식이 잘못됐다.")
            self.projects = self.source.projects()
            self.project_index = next((i for i, project in enumerate(self.projects)
                                       if project.id == saved.get("project_id")),
                                      next((i for i, project in enumerate(self.projects)
                                            if project.name == self.project_name), 0))
            self.extra_ids = self.project_extras()
            self.load_threads()
        except (OSError, ValueError) as error:
            self.projects = []
            self.threads, self.messages = [], []
            self.status, self.error = str(error), True
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="codex-source")

    @property
    def settings_path(self):
        identity = sha256(str(self.source.home).encode("utf-8")).hexdigest()[:12]
        return self.owner.workspace / f"codex_sources_{identity}.json"

    def project_extras(self):
        identity = self.projects[self.project_index].id if self.projects else "manual"
        result = self.extra_by_project.get(identity, [])
        if not isinstance(result, list) or not all(isinstance(value, str) for value in result):
            raise ValueError("추가 채팅 목록의 형식이 잘못됐다.")
        return result.copy()

    def load_threads(self):
        ids = list(self.projects[self.project_index].thread_ids) if self.projects else []
        self.threads = self.source.threads([*ids, *self.extra_ids])
        self.thread_index = self.thread_offset = 0
        self.messages = []
        self.anchor = None
        self.status, self.error = f"채팅 {len(self.threads)}개. 원문을 검색한다.", False
        self.save_settings()

    def save_settings(self):
        from .store import _atomic_write
        self.owner.workspace.mkdir(parents=True, exist_ok=True)
        identity = self.projects[self.project_index].id if self.projects else "manual"
        self.extra_by_project[identity] = self.extra_ids.copy()
        value = {"project_id": self.projects[self.project_index].id if self.projects else None,
                 "extra_by_project": self.extra_by_project}
        _atomic_write(self.settings_path,
                      json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))

    def add_thread(self):
        identity = self.editors["source_thread"].text.strip().lower()
        try:
            threads = self.source.threads([identity])
            if not threads[0].paths:
                raise ValueError("그 채팅의 로컬 원문이 없다. 채팅 ID를 확인한다.")
            if identity in self.extra_ids:
                self.extra_ids.remove(identity)
                self.load_threads()
                self.search()
                return
            self.extra_ids.append(identity)
            self.load_threads()
            self.thread_index = next(i + 1 for i, thread in enumerate(self.threads) if thread.id == identity)
            self.search()
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def search(self):
        if not self.threads:
            self.status, self.error = "프로젝트를 선택하거나 채팅 ID를 추가한다.", True
            return
        ids = [self.threads[self.thread_index - 1].id] if self.thread_index else [thread.id for thread in self.threads]
        if self.future:
            self.future.cancel()
        self.future = self.executor.submit(self.source.search, ids, self.editors["source_query"].text, self.actor)
        self.messages = []
        self.message_index = self.result_offset = self.preview_offset = 0
        self.status, self.error = "원문 기록을 읽는 중…", False

    def poll(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            self.messages, errors = future.result()
            self.message_index = self.result_offset = self.preview_offset = 0
            self.status = f"검색 결과 {len(self.messages)}개. 연결할 발언을 직접 확인한다."
            if errors:
                self.status += " " + errors[0]
            self.error = bool(errors)
        except Exception as error:
            self.status, self.error = f"원문 검색 실패: {error}", True

    def dismiss(self):
        self.visible = False
        self.owner.focus = None
        if self.future:
            self.future.cancel()
            self.future = None

    def import_selection(self):
        if not self.selected:
            return
        try:
            messages = [self.selected] + ([self.anchor] if self.anchor else [])
            for message in messages:
                self.source.verify(message)
            self.owner.use_codex_messages(messages)
            self.dismiss()
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def export(self):
        try:
            name = datetime.now(KST).strftime("codex_messages_%Y%m%d_%H%M%S_%f.json")
            target = export_messages(self.messages, self.owner.workspace / "exports" / name)
            self.status, self.error = f"검색 결과 {len(self.messages)}개 저장: exports/{target.name}", False
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def click(self, x, y):
        self.owner.focus = None
        for name, rect in self.FIELDS.items():
            if inside(rect, x, y):
                self.owner.focus = name
                editor = self.editors[name]
                editor.cursor, editor.anchor = len(editor.text), None
                return
        try:
            if inside((1120, 48, 96, 30), x, y) or inside((1000, 714, 210, 32), x, y):
                self.dismiss()
            elif inside((64, 212, 32, 30), x, y) or inside((620, 212, 32, 30), x, y):
                if self.projects:
                    self.project_index = (self.project_index + (1 if x > 600 else -1)) % len(self.projects)
                    self.extra_ids = self.project_extras()
                    if self.future:
                        self.future.cancel()
                        self.future = None
                    self.load_threads()
            elif inside((1084, 212, 130, 34), x, y):
                self.add_thread()
            elif inside((636, 258, 100, 34), x, y):
                self.search()
            elif inside((748, 258, 100, 34), x, y):
                actors = ("전체", "사용자", "AI")
                self.actor = actors[(actors.index(self.actor) + 1) % len(actors)]
                self.search()
            elif inside((860, 258, 160, 34), x, y) and self.messages:
                self.export()
            elif inside(self.THREAD_RECT, x, y):
                index = self.thread_offset + (y - self.THREAD_RECT[1]) // 36
                if index <= len(self.threads):
                    self.thread_index = index
                    self.search()
            elif inside(self.RESULT_RECT, x, y):
                index = self.result_offset + (y - self.RESULT_RECT[1]) // 30
                if index < len(self.messages):
                    self.message_index, self.preview_offset = index, 0
            elif inside((620, 714, 154, 32), x, y) and self.selected:
                self.anchor = None if self.anchor == self.selected else self.selected
            elif inside((786, 714, 200, 32), x, y):
                self.import_selection()
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def wheel(self, amount):
        x, y = self.owner.mouse
        if 80 <= y < 200:
            self.context_offset = max(0, min(self.context_max, self.context_offset - amount * 2))
        elif x < 350:
            self.thread_offset = max(0, min(max(0, len(self.threads) + 1 - 9), self.thread_offset - amount * 3))
        elif y < 442:
            self.result_offset = max(0, min(max(0, len(self.messages) - 4), self.result_offset - amount * 3))
        else:
            self.preview_offset = max(0, min(self.preview_max, self.preview_offset - amount * 3))

    def draw(self, canvas):
        self.poll()
        button = self.owner.button
        canvas.panel((48, 36, 1184, 728), "panel_surface")
        canvas.text("Codex 원문 찾기", 64, 52, "title", "accent", 680)
        button(canvas, (1120, 48, 96, 30), "닫기")
        canvas.panel((64, 82, 1150, 116))
        label = "보완할 내용: " + self.context.label if self.context else "원문 검색 · 연결할 누락 항목 없음"
        canvas.text(label, 76, 90, "body", "accent", 920)
        canvas.text("휠: 대상 설명 이동", 1000, 92, "small", "muted", 202)
        detail = self.context.detail if self.context else "채팅의 원문을 검색하거나 결과를 내보낼 수 있다. 누락 보완은 원래 화면에서 항목을 선택한다."
        lines = canvas.gap_lines(detail, 1120, "small")
        self.context_max = max(0, len(lines) - 3)
        self.context_offset = min(self.context_offset, self.context_max)
        with canvas.clip((74, 116, 1130, 74)):
            for row, line in enumerate(lines[self.context_offset:self.context_offset + 3]):
                canvas.gap_line(line, 76, 118 + row * 22)
        button(canvas, (64, 212, 32, 30), "<")
        project = self.projects[self.project_index].name if self.projects else "프로젝트 정보 없음 · 채팅 ID로 추가"
        canvas.text("프로젝트: " + project, 108, 218, "body", max_width=500)
        button(canvas, (620, 212, 32, 30), ">")
        for name in self.FIELDS:
            self.owner.input_box(canvas, name, self.FIELDS[name])
        if not self.editors["source_thread"].text and self.owner.focus != "source_thread":
            canvas.text("추가할 채팅 ID", 680, 220, "small", "disabled", 380)
        extra = self.editors["source_thread"].text.strip().lower() in self.extra_ids
        button(canvas, (1084, 212, 130, 34), "추가 해제" if extra else "채팅 추가")
        button(canvas, (636, 258, 100, 34), "검색")
        button(canvas, (748, 258, 100, 34), self.actor)
        button(canvas, (860, 258, 160, 34), "결과 JSON 저장", enabled=bool(self.messages))
        canvas.text("프로젝트·추가 채팅 · 휠 이동", 72, 310, "small", "muted", 260)
        with canvas.clip(self.THREAD_RECT):
            entries = ["선택 범위 전체"] + [thread.title for thread in self.threads]
            for row, title in enumerate(entries[self.thread_offset:self.thread_offset + 9]):
                y = self.THREAD_RECT[1] + row * 36
                if self.thread_index == self.thread_offset + row:
                    canvas.fill((64, y, 280, 36), "selected")
                canvas.text(title, 72, y + 8, "small", max_width=264)
        with canvas.clip(self.RESULT_RECT):
            for row, message in enumerate(self.messages[self.result_offset:self.result_offset + 4]):
                y = self.RESULT_RECT[1] + row * 30
                if self.message_index == self.result_offset + row:
                    canvas.fill((360, y, 850, 30), "selected")
                label = f"{message.kst or '시각 미상'} · {message.actor} · " + " ".join(message.text.split())
                canvas.text(label, 370, y + 5, "small", max_width=830)
        canvas.panel((360, 442, 850, 230))
        if self.selected:
            message = self.selected
            canvas.text(message.thread_title + " · " + message.actor, 374, 452, "body", "accent", 820)
            canvas.text("기록 시각: " + (message.kst + " KST" if message.kst else "미상"),
                        374, 479, "small", "muted", 820)
            lines = canvas.wrap(message.text, 810, "small")
            self.preview_max = max(0, len(lines) - 8)
            self.preview_offset = min(self.preview_offset, self.preview_max)
            with canvas.clip((370, 506, 830, 160)):
                for row, line in enumerate(lines[self.preview_offset:self.preview_offset + 8]):
                    canvas.text(line, 374, 506 + row * 20, "small")
        canvas.text(self.status, 64, 681, "small", "error" if self.error else "muted", 1140)
        label = "범위 시작: " + (self.anchor.kst or "시각 미상") if self.anchor else "선택은 초안만 채운다. 저장은 기존 적용 버튼이다."
        canvas.text(label, 64, 721, "small", "muted", 540)
        button(canvas, (620, 714, 154, 32), "범위 시작 해제" if self.anchor else "범위 시작 선택", bool(self.anchor), bool(self.selected))
        button(canvas, (786, 714, 200, 32), "선택 근거 가져오기", enabled=bool(self.selected and self.owner.gap))
        button(canvas, (1000, 714, 210, 32), "취소")

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
