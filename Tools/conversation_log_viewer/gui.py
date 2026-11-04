"""Pico2D 대화형 요약 열람과 누락 보완 화면."""

from ctypes import CFUNCTYPE, byref, c_void_p, cast, string_at
import json
from pathlib import Path
from time import perf_counter, sleep

from unit_test_runner.interface import WindowSpec
from unit_test_runner.runner import PicoWindow
from .canvas import Canvas
from .model import Bubble, GAP_NAMES, LEGACY_HEADING, filter_records, list_records
from .store import LogStore, _atomic_write
from .text_input import TextInput

WINDOW = WindowSpec(1280, 800, "Ferrial Drive | 대화 기록")


def contains(rect, x, y):
    left, top, width, height = rect
    return left <= x < left + width and top <= y < top + height


class LogViewer:
    FIELDS = {"search": (28, 114, 256, 34), "body": (920, 330, 328, 158),
              "evidence": (920, 526, 328, 56), "event_time": (920, 624, 328, 34)}

    def __init__(self, directory, workspace):
        self.directory, self.workspace = Path(directory).resolve(), Path(workspace).resolve()
        self.store = LogStore(self.directory, self.workspace)
        self.editors = {key: TextInput(multiline=key in ("body", "evidence")) for key in self.FIELDS}
        self.focus = None
        self.source_kind = "recollection"
        self.only_missing, self.actor_filter, self.show_original = False, "전체", False
        self.records, self.filtered, self.record = [], [], None
        self.gap_index = self.file_offset = self.gap_offset = self.chat_offset = 0
        self.chat_max = 0
        self.pending_gap = None
        self.mouse = (0, 0)
        self.status, self.error = "누락 항목을 선택해 보완한다. Ctrl+Enter로 적용한다.", False
        self.drafts = {}
        draft_path = self.workspace / "drafts.json"
        if draft_path.exists():
            try:
                self.drafts = json.loads(draft_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.status, self.error = "임시 입력을 읽지 못했다. 저장된 Markdown은 영향을 받지 않는다.", True
        self.reload()

    @property
    def gap(self):
        return self.record.gaps[self.gap_index] if self.record and self.record.gaps else None

    def draft_key(self):
        return str(self.record.path) + "|" + self.gap.token if self.gap else None

    def stash_draft(self):
        key = self.draft_key()
        if key:
            value = {name: self.editors[name].text for name in ("body", "evidence", "event_time")}
            value["source_kind"] = self.source_kind
            if any(value[name] for name in ("body", "evidence", "event_time")):
                self.drafts[key] = value
            else:
                self.drafts.pop(key, None)

    def restore_draft(self):
        value = self.drafts.get(self.draft_key(), {})
        for name in ("body", "evidence", "event_time"):
            self.editors[name].text = value.get(name, "")
            self.editors[name].cursor = len(self.editors[name].text)
            self.editors[name].anchor = None
            self.editors[name].composition = ""
        self.source_kind = value.get("source_kind", "recollection")

    def select_record(self, record):
        self.stash_draft()
        self.record, self.gap_index, self.gap_offset, self.chat_offset = record, 0, 0, 0
        self.pending_gap = None
        self.restore_draft()

    def reload(self):
        self.stash_draft()
        selected_path = self.record.path if self.record else None
        self.records, errors = list_records(self.directory)
        self.refilter(selected_path)
        if errors:
            self.status, self.error = "읽기 오류: " + errors[0], True

    def refilter(self, selected_path=None):
        selected_path = selected_path or (self.record.path if self.record else None)
        self.filtered = filter_records(self.records, self.editors["search"].text, self.only_missing)
        selected = next((record for record in self.filtered if record.path == selected_path), None)
        if selected is None:
            selected = self.filtered[0] if self.filtered else None
        if not self.record or not selected or self.record.path != selected.path or self.record.fingerprint != selected.fingerprint:
            self.select_record(selected)
        self.file_offset = max(0, min(self.file_offset, max(0, len(self.filtered) - 12)))

    def select_gap(self, index):
        if self.record and 0 <= index < len(self.record.gaps):
            self.stash_draft()
            self.gap_index = index
            self.restore_draft()
            self.actor_filter, self.show_original = "전체", False
            self.pending_gap = self.gap.token

    def chat_layout(self, canvas, bubbles):
        layout, total = [], 0
        for bubble in bubbles:
            lines = canvas.gap_lines(bubble.text, 496, "small")
            height = 64 + len(lines) * 20
            layout.append((bubble, lines, total, height))
            total += height + 12
        self.chat_max = max(0, total - 568)
        if self.pending_gap:
            target = next((top + 52 + row * 20 - 48
                           for _, lines, top, _ in layout for row, line in enumerate(lines)
                           if any(mark.token == self.pending_gap for mark in line.marks)), None)
            if target is not None:
                self.chat_offset = target
            self.pending_gap = None
        self.chat_offset = max(0, min(self.chat_offset, self.chat_max))
        return layout

    def apply(self):
        if not self.gap:
            return
        try:
            key = self.draft_key()
            self.store.apply(self.record, self.gap.token, self.editors["body"].text,
                             source_kind=self.source_kind, evidence=self.editors["evidence"].text,
                             event_time=self.editors["event_time"].text)
            self.drafts.pop(key, None)
            # 저장한 입력이 다음 누락 항목의 초안으로 섞이지 않게 한다.
            for name in ("body", "evidence", "event_time"):
                self.editors[name].text = ""
            self.reload()
            self.status, self.error = "보완과 누락 인덱스를 저장했다. 사용자 보완 출처·시각도 기록했다.", False
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def undo(self):
        if self.record is None:
            return
        try:
            self.store.undo(self.record)
            self.reload()
            self.status, self.error = "이 기록의 마지막 보완을 되돌리고 누락 인덱스를 갱신했다.", False
        except (OSError, ValueError) as error:
            self.status, self.error = str(error), True

    def insert(self, value):
        editor = self.editors[self.focus]
        limit = {"search": 200, "body": 8000, "evidence": 2000, "event_time": 19}[self.focus]
        start, end = editor.selection
        editor.insert(value[:max(0, limit - len(editor.text) + end - start)])
        if self.focus == "search":
            self.refilter()

    def handle(self, event, pico):
        if event.type == pico.SDL_MOUSEMOTION:
            self.mouse = (event.x, event.y)
        elif event.type == pico.SDL_MOUSEWHEEL:
            x, _ = self.mouse
            if x < 300:
                self.file_offset = max(0, min(max(0, len(self.filtered) - 12), self.file_offset - event.y * 3))
            elif x < 900:
                self.chat_offset = max(0, min(self.chat_max, self.chat_offset - event.y * 90))
            elif self.record:
                self.gap_offset = max(0, min(max(0, len(self.record.gaps) - 4), self.gap_offset - event.y * 2))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            self.click(event.x, event.y)
        elif event.type == pico.SDL_TEXTEDITING and self.focus:
            self.editors[self.focus].composition = event.text
        elif event.type == pico.SDL_TEXTINPUT and self.focus:
            self.insert(event.text)
        elif event.type == pico.SDL_KEYDOWN:
            self.key(event, pico)

    def click(self, x, y):
        for name, rect in self.FIELDS.items():
            if contains(rect, x, y):
                if name != "search" and not self.gap:
                    return
                self.focus = name
                editor = self.editors[name]
                editor.cursor, editor.anchor = len(editor.text), None
                return
        self.focus = None
        if contains((28,154,72,30),x,y):
            self.only_missing = False
            self.refilter()
        elif contains((110,154,88,30),x,y):
            self.only_missing = True
            self.refilter()
        elif contains((208,154,76,30),x,y):
            self.reload()
        elif contains((28,210,256,528),x,y):
            index = self.file_offset + (y - 210) // 44
            if index < len(self.filtered):
                self.select_record(self.filtered[index])
        elif contains((920,134,328,112),x,y) and self.record:
            self.select_gap(self.gap_offset + (y - 134) // 28)
        elif contains((920,268,154,30),x,y) and self.gap:
            self.source_kind = "recollection"
        elif contains((1086,268,162,30),x,y) and self.gap:
            self.source_kind = "source_checked"
        elif contains((920,680,154,38),x,y):
            self.apply()
        elif contains((1086,680,162,38),x,y):
            self.undo()
        for index, actor in enumerate(("전체","사용자","AI","기록")):
            if contains((320+index*82,132,74,28),x,y):
                self.actor_filter, self.show_original, self.chat_offset = actor, False, 0
        if contains((658,132,104,28),x,y):
            self.show_original, self.chat_offset = not self.show_original, 0

    def key(self, event, pico):
        ctrl, shift = bool(event.mod & pico.KMOD_CTRL), bool(event.mod & pico.KMOD_SHIFT)
        if event.key == pico.SDLK_F5:
            self.reload()
            return
        if ctrl and event.key == pico.SDLK_RETURN and not any(editor.composition for editor in self.editors.values()):
            self.apply()
            return
        if event.key == pico.SDLK_TAB:
            names = list(self.editors)
            self.focus = names[(names.index(self.focus) + 1) % len(names)] if self.focus in names else "search"
            return
        if not self.focus:
            return
        editor = self.editors[self.focus]
        if editor.composition and not ctrl:
            if event.key == pico.SDLK_ESCAPE:
                editor.composition = ""
            return
        if ctrl and event.key == pico.SDLK_a:
            editor.anchor, editor.cursor = 0, len(editor.text)
        elif ctrl and event.key in (pico.SDLK_c, pico.SDLK_x):
            text = editor.selected_text()
            if text:
                pico.SDL_SetClipboardText(text.encode("utf-8"))
                if event.key == pico.SDLK_x:
                    editor.erase()
        elif ctrl and event.key == pico.SDLK_v:
            # PySDL2의 c_char_p 자동 변환을 피하고 SDL이 준 원래 포인터를 해제한다.
            get_text = CFUNCTYPE(c_void_p)(cast(pico.SDL_GetClipboardText, c_void_p).value)
            pointer = get_text()
            if pointer:
                try:
                    self.insert(string_at(pointer).decode("utf-8", errors="replace"))
                finally:
                    pico.SDL_free(c_void_p(pointer))
        elif event.key in (pico.SDLK_LEFT, pico.SDLK_RIGHT):
            editor.move(-1 if event.key == pico.SDLK_LEFT else 1, shift)
        elif event.key in (pico.SDLK_UP, pico.SDLK_DOWN):
            editor.move_line(-1 if event.key == pico.SDLK_UP else 1, shift)
        elif event.key == pico.SDLK_HOME:
            start = 0 if ctrl else editor.text.rfind("\n", 0, editor.cursor) + 1
            editor.move(start - editor.cursor, shift)
        elif event.key == pico.SDLK_END:
            end = editor.text.find("\n", editor.cursor) if not ctrl else -1
            editor.move((len(editor.text) if end < 0 else end) - editor.cursor, shift)
        elif event.key in (pico.SDLK_BACKSPACE, pico.SDLK_DELETE):
            editor.erase(event.key == pico.SDLK_BACKSPACE)
        elif event.key == pico.SDLK_RETURN and not editor.composition:
            if editor.multiline:
                self.insert("\n")
            else:
                self.focus = None
        elif event.key == pico.SDLK_ESCAPE:
            editor.composition = ""
            self.focus = None
        if self.focus == "search":
            self.refilter()

    def button(self, canvas, rect, label, active=False, enabled=True):
        color = "button_hover" if active or contains(rect,*self.mouse) and enabled else "button"
        canvas.fill(rect, color if enabled else "panel_surface")
        canvas.text(label,rect[0]+8,rect[1]+6,"small","button_text" if enabled else "disabled",rect[2]-16)

    def input_box(self, canvas, name):
        rect = self.FIELDS[name]
        x,y,width,height = rect
        editor = self.editors[name]
        canvas.fill(rect,"selected" if editor.anchor is not None else "input")
        canvas.border(rect,"accent" if self.focus == name else "line")
        lines = canvas.wrap(editor.text,width-16,"small")
        prefix = canvas.wrap(editor.text[:editor.cursor],width-16,"small")
        cursor_row = len(prefix)-1
        visible = max(1,(height-12)//20)
        offset = max(0,cursor_row-visible+1) if self.focus == name else 0
        with canvas.clip((x+4,y+2,width-8,height-4)):
            for row,line in enumerate(lines[offset:offset+visible]):
                canvas.text(line,x+8,y+6+row*20,"small")
            if name == "evidence" and not editor.text and self.focus != name:
                hint = "Codex 대화 ID · UTC 시각 · 발언자 · 짧은 인용"
                for row, line in enumerate(canvas.wrap(hint, width-16, "small")[:visible]):
                    canvas.text(line,x+8,y+6+row*20,"small","disabled")
            if self.focus == name:
                caret_x = x+8+canvas.size(prefix[-1],"small")[0]
                caret_y = y+6+(cursor_row-offset)*20
                canvas.fill((caret_x,caret_y,1,17),"accent")
                if editor.composition:
                    canvas.text(editor.composition,caret_x,caret_y,"small","warning")
                target = canvas.pico.SDL_Rect(round(caret_x),round(caret_y),200,24)
                canvas.pico.SDL_SetTextInputRect(byref(target))

    def draw(self, canvas):
        canvas.fill((0,0,1280,800),"background")
        canvas.panel((16,12,1248,60),"panel_surface")
        canvas.text("대화 기록",32,22,"title","accent")
        canvas.text("요약 열람 · 사용자 보완",180,25,"body")
        canvas.text(self.directory.as_posix(),32,49,"small","muted",1216)
        canvas.panel((16,84,280,700))
        canvas.panel((308,84,584,700))
        canvas.panel((904,84,360,700))
        canvas.text("검색 · 단어를 띄우면 모두 포함",28,93,"small","muted")
        self.input_box(canvas,"search")
        for rect,label,active in (((28,154,72,30),"전체",not self.only_missing),((110,154,88,30),"누락만",self.only_missing),((208,154,76,30),"새로고침",False)):
            self.button(canvas,rect,label,active)
        canvas.text(f"기록 {len(self.filtered)}개",28,190,"small","muted")
        with canvas.clip((28,210,256,528)):
            for row,record in enumerate(self.filtered[self.file_offset:self.file_offset+12]):
                y=210+row*44
                if self.record and record.path==self.record.path:
                    canvas.fill((28,y,256,44),"selected")
                    canvas.fill((28,y,3,44),"accent")
                canvas.text(record.title,38,y+3,"small",max_width=234)
                canvas.text(f"{record.path.name[:10]}  ·  누락 {len(record.gaps)}",38,y+24,"small","muted",234)
                canvas.fill((28,y+43,256,1),"line")
        canvas.text("휠: 영역별 스크롤  |  F5: 갱신",28,756,"small","muted",256)
        canvas.text(self.record.title if self.record else "검색 결과 없음",320,96,"title","accent",560)
        for index,actor in enumerate(("전체","사용자","AI","기록")):
            self.button(canvas,(320+index*82,132,74,28),actor,self.actor_filter==actor and not self.show_original)
        self.button(canvas,(658,132,104,28),"이전 기록",self.show_original)
        bubbles=[]
        if self.record:
            if self.show_original:
                legacy=self.record.text.partition(LEGACY_HEADING)[2]
                bubbles=[Bubble("기록","이전 형식 기록",legacy or "별도 이전 기록 없음","당시 요약 · 원시 채팅 아님")]
            else:
                bubbles=[bubble for bubble in self.record.bubbles if self.actor_filter=="전체" or bubble.actor==self.actor_filter or self.actor_filter=="사용자" and bubble.actor=="사용자 보완"]
        layout = self.chat_layout(canvas, bubbles)
        selected_token = self.gap.token if self.gap and not self.show_original else None
        with canvas.clip((316,172,568,568)):
            for bubble, lines, offset, height in layout:
                top=172+offset-self.chat_offset
                if top+height<172 or top>740:
                    continue
                x=344 if bubble.actor.startswith("사용자") else 320
                canvas.panel((x,top,528,height),"user_bubble" if bubble.actor.startswith("사용자") else "ai_bubble" if bubble.actor=="AI" else "panel_surface")
                canvas.text(bubble.actor+"  ·  "+bubble.origin,x+12,top+8,"small","accent",504)
                canvas.text(bubble.title,x+12,top+29,"small","muted",504)
                for row,line in enumerate(lines):
                    line_y=top+52+row*20
                    if 150<line_y<742:
                        canvas.gap_line(line,x+12,line_y,selected_token)
        canvas.text("말풍선은 요약이다. 원문 연결과 사용자 보완을 구분한다.",320,756,"small","muted",560)
        canvas.text("누락 보완",920,96,"title","accent")
        canvas.text(f"{len(self.record.gaps) if self.record else 0}개",1190,100,"small","warning")
        if self.record:
            for row,gap in enumerate(self.record.gaps[self.gap_offset:self.gap_offset+4]):
                y=134+row*28
                if self.gap_index==self.gap_offset+row:
                    canvas.fill((920,y,328,28),"selected")
                canvas.text(f"{GAP_NAMES.get(gap.kind,gap.kind)} · {gap.item}",928,y+4,"small","warning",312)
        canvas.text("누락 선택 → 가운데 위치로 이동",920,246,"small","muted",328)
        self.button(canvas,(920,268,154,30),"사용자 회고",self.source_kind=="recollection",bool(self.gap))
        self.button(canvas,(1086,268,162,30),"원문 확인",self.source_kind=="source_checked",bool(self.gap))
        for label,y in (("보완 내용",310),("근거·원문 위치 (원문 확인이면 필수)",506),("당시 시각 (시각 항목이면 필수)",602)):
            canvas.text(label,920,y,"small","muted",328)
        for name in ("body","evidence","event_time"):
            self.input_box(canvas,name)
        self.button(canvas,(920,680,154,38),"적용",enabled=bool(self.gap))
        self.button(canvas,(1086,680,162,38),"마지막 보완 취소",enabled=bool(self.record))
        for row,line in enumerate(canvas.wrap(self.status,328,"small")[:3]):
            canvas.text(line,920,732+row*16,"small","error" if self.error else "muted",328)

    def close(self):
        self.stash_draft()
        self.workspace.mkdir(parents=True,exist_ok=True)
        _atomic_write(self.workspace/"drafts.json",json.dumps(self.drafts,ensure_ascii=False,indent=2).encode("utf-8"))


def run_gui(directory, workspace, *, frame_limit=None, screenshot=None, selected_file=None):
    backend=PicoWindow(accept_text=True)
    backend.open(WINDOW)
    canvas=viewer=None
    try:
        canvas=Canvas(backend)
        viewer=LogViewer(directory,workspace)
        if selected_file:
            selected=next((record for record in viewer.records if record.path.name==selected_file),None)
            if selected:
                viewer.select_record(selected)
        frames=0
        running=True
        while running:
            started=perf_counter()
            for event in backend.events():
                if backend.is_close_event(event):
                    running=False
                    break
                viewer.handle(event,backend.pico)
            if not running:
                break
            viewer.draw(canvas)
            if screenshot:
                target=Path(screenshot)
                target.parent.mkdir(parents=True,exist_ok=True)
                pico=backend.pico
                surface=pico.SDL_CreateRGBSurfaceWithFormat(0,1280,800,32,pico.SDL_PIXELFORMAT_RGBA32)
                if not surface:
                    raise RuntimeError("화면 저장 실패")
                try:
                    if pico.SDL_RenderReadPixels(pico.renderer,None,pico.SDL_PIXELFORMAT_RGBA32,surface.contents.pixels,surface.contents.pitch)!=0 or pico.IMG_SavePNG(surface,str(target.resolve()).encode("utf-8"))!=0:
                        raise RuntimeError("화면 저장 실패")
                finally:
                    pico.SDL_FreeSurface(surface)
                screenshot=None
            backend.present()
            frames+=1
            if frame_limit and frames>=frame_limit:
                break
            remaining=1/60-(perf_counter()-started)
            if remaining>0:
                sleep(remaining)
    finally:
        try:
            if viewer:
                viewer.close()
        finally:
            try:
                if canvas:
                    canvas.close()
            finally:
                backend.close()
