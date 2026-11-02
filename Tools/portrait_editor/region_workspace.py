"""AI hint painting workspace embedded in Portrait Studio's existing window."""
from __future__ import annotations

import math
from pathlib import Path

import pygame

from region_document import RegionDocument, overlay, read_image
from ui_primitives import Painter, BG, PANEL, PANEL2, BORDER, TEXT, MUTED, ACCENT, PINK, AMBER


class RegionWorkspace:
    def __init__(self, work, on_close):
        self.work = Path(work)
        self.on_close = on_close
        self.document = None
        self.ui = Painter()
        self.size = (1600, 940)
        self.viewport = pygame.Rect(280, 100, 1000, 780)
        self.image_rect = pygame.Rect(0, 0, 1, 1)
        self.scale = 1.
        self.zoom = 1.
        self.pan = [0., 0.]
        self.radius = 24
        self.erase = False
        self.drag = None
        self.editing = False
        self.text = ''
        self.composition = ''
        self.pending = None
        self.scroll = 0
        self.message = '원본 이미지를 열고 추출할 영역을 대략 칠해 줘.'
        self.error = False

    def notify(self, message, error=False):
        self.message, self.error = str(message), error

    def dialog(self, kind):
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            if kind == 'image':
                return filedialog.askopenfilename(parent=root, title='영역을 지정할 원본 이미지',
                    filetypes=[('이미지', '*.png *.jpg *.jpeg *.webp'), ('모든 파일', '*.*')])
            if kind == 'open':
                return filedialog.askopenfilename(parent=root, title='영역 작업 열기',
                    filetypes=[('영역 작업', '*.regions.zip')])
            if kind == 'save':
                return filedialog.asksaveasfilename(parent=root, title='영역 작업 저장',
                    initialdir=str(self.work), initialfile='image.regions.zip',
                    defaultextension='.regions.zip', filetypes=[('영역 작업', '*.regions.zip')])
            return filedialog.askdirectory(parent=root, title='AI 전달 묶음을 저장할 폴더', initialdir=str(self.work))
        finally:
            root.destroy()

    def finish_name(self, cancel=False):
        if not self.editing:
            return
        if not cancel:
            self.document.rename(self.text)
        self.editing = False
        self.composition = ''
        pygame.key.stop_text_input()

    def guard(self, callback):
        self.finish_name()
        self.drag = None
        if self.document and self.document.dirty:
            self.pending = callback
        else:
            callback()

    def replace(self, document):
        self.document = document
        self.fit()
        self.scroll = 0
        self.notify('영역 이름을 지정하고 브러시로 칠해 줘. 흰색 마스크가 추출 대상이야.')

    def open_image(self, path):
        if Path(path).stat().st_size > 64 * 1024 * 1024:
            raise ValueError('이미지 파일은 최대 64MB까지 열 수 있어.')
        candidate = RegionDocument(read_image(str(path)), Path(path).name)
        self.replace(candidate)

    def save(self, path=None, save_as=False):
        self.finish_name()
        if not self.document:
            return False
        path = path or (None if save_as else self.document.path) or self.dialog('save')
        if not path:
            return False
        self.document.save(path)
        self.notify('영역 작업 저장 완료 · ' + str(path))
        return True

    def fit(self):
        self.zoom = 1.
        self.pan = [0., 0.]
        self.drag = None

    def geometry(self, size):
        self.size = size
        self.viewport = pygame.Rect(280, 104, size[0] - 296, size[1] - 154)
        if self.document:
            w, h = self.document.image.get_size()
            self.scale = min(self.viewport.w / w, self.viewport.h / h) * self.zoom
            self.image_rect = pygame.Rect(0, 0, max(1, round(w * self.scale)), max(1, round(h * self.scale)))
            self.image_rect.center = (round(self.viewport.centerx + self.pan[0]), round(self.viewport.centery + self.pan[1]))

    def point(self, position):
        if not self.document or not self.viewport.collidepoint(position) or not self.image_rect.collidepoint(position):
            return None
        w, h = self.document.image.get_size()
        return (min(w - 1, max(0, int((position[0] - self.image_rect.x) / self.scale))),
                min(h - 1, max(0, int((position[1] - self.image_rect.y) / self.scale))))

    def action(self, name, value=None):
        if name == 'cancel':
            self.pending = None
            return
        if name in ('discard', 'save_continue'):
            callback = self.pending
            if name == 'save_continue' and not self.save():
                return
            self.pending = None
            if callback:
                callback()
            return
        self.finish_name()
        if name == 'back':
            self.guard(self.on_close)
        elif name == 'image':
            path = self.dialog('image')
            if path:
                self.guard(lambda: self.open_image(path))
        elif name == 'open':
            path = self.dialog('open')
            if path:
                self.guard(lambda: self.replace(RegionDocument.load(path)))
        elif name == 'fit':
            self.fit()
        elif self.document:
            if name == 'save':
                self.save()
            elif name == 'export':
                parent = self.dialog('export')
                if parent:
                    self.notify('AI 전달 묶음 저장 완료 · ' + str(self.document.export(parent)))
            elif name == 'select':
                self.document.selected = value
            elif name == 'add':
                self.document.add()
                self.scroll = max(0, len(self.document.regions) - 8)
            elif name == 'remove':
                self.document.remove()
            elif name == 'clear':
                self.document.clear()
            elif name == 'undo':
                self.document.undo()
            elif name == 'redo':
                self.document.undo(redo=True)
            elif name == 'brush':
                self.erase = False
            elif name == 'eraser':
                self.erase = True
            elif name == 'smaller':
                self.radius = max(2, self.radius - 4)
            elif name == 'larger':
                self.radius = min(160, self.radius + 4)
            elif name == 'rename':
                self.editing = True
                self.text = self.document.current['name']
                pygame.key.start_text_input()
                pygame.key.set_text_input_rect(pygame.Rect(16, 172, 248, 34))

    def handle(self, event):
        if event.type == pygame.WINDOWFOCUSLOST:
            self.drag = None
            return
        if event.type == pygame.DROPFILE:
            path = event.file
            if path.lower().endswith('.regions.zip'):
                self.guard(lambda: self.replace(RegionDocument.load(path)))
            else:
                self.guard(lambda: self.open_image(path))
            return
        if self.editing:
            if event.type == pygame.TEXTINPUT:
                self.text = (self.text + event.text)[:80]
                self.composition = ''
                return
            if event.type == pygame.TEXTEDITING:
                self.composition = event.text
                return
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.finish_name()
                elif event.key == pygame.K_ESCAPE:
                    self.finish_name(cancel=True)
                elif event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                    self.text = ''
                return
            if event.type == pygame.MOUSEBUTTONDOWN:
                self.finish_name()
        if event.type == pygame.KEYDOWN:
            if self.pending:
                if event.key == pygame.K_ESCAPE:
                    self.pending = None
                return
            control = event.mod & pygame.KMOD_CTRL
            if control and event.key == pygame.K_s:
                self.save(save_as=bool(event.mod & pygame.KMOD_SHIFT))
            elif control and event.key == pygame.K_o:
                self.action('open')
            elif control and event.key in (pygame.K_z, pygame.K_y):
                self.action('redo' if event.key == pygame.K_y or event.mod & pygame.KMOD_SHIFT else 'undo')
            elif event.key == pygame.K_ESCAPE:
                self.action('back')
            elif event.key == pygame.K_b:
                self.action('brush')
            elif event.key == pygame.K_e:
                self.action('eraser')
            elif event.key == pygame.K_LEFTBRACKET:
                self.action('smaller')
            elif event.key == pygame.K_RIGHTBRACKET:
                self.action('larger')
            return
        if self.pending:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for name, rect, value in reversed(self.ui.hits):
                    if name in ('cancel', 'discard', 'save_continue') and rect.collidepoint(event.pos):
                        self.action(name)
                        break
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                for name, rect, value in reversed(self.ui.hits):
                    if rect.collidepoint(event.pos):
                        self.action(name, value)
                        return
                point = self.point(event.pos)
                if point is not None:
                    radius = max(1, min(8192, round(self.radius / self.scale)))
                    self.document.start_stroke(point, radius, self.erase)
                    self.drag = ('paint',)
            elif event.button == 2 and self.viewport.collidepoint(event.pos):
                self.drag = ('pan', event.pos, self.pan[:])
        elif event.type == pygame.MOUSEMOTION and self.drag:
            if self.drag[0] == 'paint':
                self.document.extend_stroke(self.point(event.pos))
            else:
                _, start, old = self.drag
                self.pan = [old[0] + event.pos[0] - start[0], old[1] + event.pos[1] - start[1]]
                self.geometry(self.size)
        elif event.type == pygame.MOUSEBUTTONUP:
            if self.drag and ((self.drag[0] == 'paint' and event.button == 1) or (self.drag[0] == 'pan' and event.button == 2)):
                if self.drag[0] == 'paint':
                    self.document.extend_stroke(self.point(event.pos))
                self.drag = None
        elif event.type == pygame.MOUSEWHEEL and not self.drag:
            position = pygame.mouse.get_pos()
            if position[0] < 280:
                self.scroll = max(0, self.scroll - event.y)
            elif self.document:
                old = self.zoom
                self.zoom = min(8., max(1., self.zoom * 1.2 ** event.y))
                ratio = self.zoom / old
                self.pan = [position[i] - self.viewport.center[i] -
                            (position[i] - self.viewport.center[i] - self.pan[i]) * ratio for i in (0, 1)]
                self.geometry(self.size)

    def draw_image(self):
        # Only scale the visible crop, keeping zoom independent of source resolution.
        visible = self.image_rect.clip(self.viewport)
        if visible.w <= 0 or visible.h <= 0:
            return
        w, h = self.document.image.get_size()
        x0 = max(0, math.floor((visible.left - self.image_rect.left) / self.scale))
        y0 = max(0, math.floor((visible.top - self.image_rect.top) / self.scale))
        x1 = min(w, math.ceil((visible.right - self.image_rect.left) / self.scale))
        y1 = min(h, math.ceil((visible.bottom - self.image_rect.top) / self.scale))
        crop = pygame.Rect(x0, y0, x1 - x0, y1 - y0)
        size = (max(1, round(crop.w * self.scale)), max(1, round(crop.h * self.scale)))
        image = pygame.transform.smoothscale(self.document.image.subsurface(crop).convert_alpha(), size)
        mask = pygame.transform.scale(self.document.mask().subsurface(crop), size)
        tinted = overlay(image, mask)
        self.ui.surface.set_clip(self.viewport)
        self.ui.surface.blit(tinted, (self.image_rect.x + round(x0 * self.scale), self.image_rect.y + round(y0 * self.scale)))
        position = pygame.mouse.get_pos()
        if self.point(position) is not None:
            pygame.draw.circle(self.ui.surface, ACCENT if self.erase else PINK, position, self.radius, 1)
        self.ui.surface.set_clip(None)

    def render(self, size):
        self.geometry(size)
        ui = self.ui
        ui.surface = pygame.Surface(size, pygame.SRCALPHA)
        ui.surface.fill((*BG, 255))
        ui.hits = []
        ui.box((0, 0, size[0], 88), PANEL)
        ui.text('AI 영역 지정', 16, 14, 20, TEXT, True)
        ui.text('대략 칠한 영역으로 추출 대상을 알려줘', 180, 19, 13, MUTED)
        buttons = [('back', '리깅으로 돌아가기', 160), ('image', '원본 이미지 열기', 148),
                   ('open', '영역 작업 열기', 134), ('save', '작업 저장', 108), ('export', 'AI 전달 묶음 저장', 160)]
        x = 16
        for name, label, width in buttons:
            ui.button(name, (x, 46, width, 32), label, enabled=name in ('back', 'image', 'open') or bool(self.document), primary=name == 'export')
            x += width + 8
        ui.box((0, 88, 272, size[1] - 122), PANEL)
        ui.box(self.viewport, (35, 40, 49), BORDER)
        if self.document:
            doc = self.document
            ui.text('추출할 영역', 16, 108, 15, TEXT, True)
            ui.text('영역 이름 · 클릭해서 수정', 16, 148, 12, MUTED)
            ui.box((16, 172, 240, 34), BG, ACCENT if self.editing else BORDER, 4)
            label = self.text + self.composition + '|' if self.editing else doc.current['name']
            ui.text(label, 24, 179, 14, TEXT, width=224)
            ui.hit('rename', (16, 172, 240, 34))
            ui.button('brush', (16, 220, 116, 34), '브러시 · B', active=not self.erase)
            ui.button('eraser', (140, 220, 116, 34), '지우개 · E', active=self.erase)
            ui.text(f'브러시 크기  {self.radius}', 16, 270, 13, MUTED)
            ui.button('smaller', (164, 264, 42, 30), '-')
            ui.button('larger', (214, 264, 42, 30), '+')
            ui.button('fit', (16, 306, 116, 32), '화면에 맞춤')
            ui.button('clear', (140, 306, 116, 32), '선택 영역 비우기')
            ui.button('undo', (16, 346, 116, 32), '되돌리기', enabled=bool(doc.undo_stack))
            ui.button('redo', (140, 346, 116, 32), '다시 적용', enabled=bool(doc.redo_stack))
            ui.button('add', (16, 394, 116, 32), '영역 추가')
            ui.button('remove', (140, 394, 116, 32), '영역 삭제', enabled=len(doc.regions) > 1)
            rows = max(1, (size[1] - 560) // 34)
            self.scroll = min(self.scroll, max(0, len(doc.regions) - rows))
            for row, index in enumerate(range(self.scroll, min(len(doc.regions), self.scroll + rows))):
                ui.button('select', (16, 438 + row * 34, 240, 30), f'{index + 1}. {doc.regions[index]["name"][:18]}', active=index == doc.selected, data=index)
            ui.text(f'{len(doc.regions)}개 영역 · 목록은 휠로 이동', 16, size[1] - 105, 12, MUTED)
            state = '● 수정됨' if doc.dirty else '저장됨'
            ui.text(state + ' · ' + doc.source_name, 292, 90, 11, AMBER if doc.dirty else MUTED, width=size[0] - 310)
            self.draw_image()
        else:
            ui.text('원본 이미지 열기', self.viewport.centerx, self.viewport.centery - 24, 22, TEXT, align='center')
            ui.text('이미지나 .regions.zip 파일을 끌어 놓아도 돼', self.viewport.centerx, self.viewport.centery + 20, 14, MUTED, align='center')
        ui.text('휠: 확대  ·  가운데 드래그: 이동  ·  Ctrl+S: 저장', 292, size[1] - 43, 12, MUTED)
        ui.text(self.message, 16, size[1] - 23, 12, AMBER if self.error else MUTED, width=size[0] - 32)
        if self.pending:
            shade = pygame.Surface(size, pygame.SRCALPHA)
            shade.fill((5, 9, 16, 190))
            ui.surface.blit(shade, (0, 0))
            rect = pygame.Rect(0, 0, 520, 190)
            rect.center = (size[0] // 2, size[1] // 2)
            ui.box(rect, PANEL2, BORDER, 8)
            ui.text('영역 작업을 저장하고 계속할까?', rect.x + 24, rect.y + 26, 20, TEXT, True)
            ui.text('원본 이미지와 영역 표시를 함께 저장해.', rect.x + 24, rect.y + 70, 13, MUTED)
            for i, (name, label) in enumerate([('cancel', '취소'), ('discard', '저장 안 함'), ('save_continue', '저장 후 계속')]):
                ui.button(name, (rect.x + 24 + i * 160, rect.y + 126, 150, 36), label, primary=i == 2)
        return ui.surface
