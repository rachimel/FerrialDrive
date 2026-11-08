"""공통 로더를 사용하는 이미지·시트·번들 미리보기 화면."""

from math import isfinite
from pathlib import Path
import re

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager, detect_kind
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer
from Tools.theme_reference import load_theme


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "samples/asset_loader/bundle.json"
DEFAULT_CATALOG = Path(__file__).with_name("workspace") / "catalog.json"
WINDOW = {"width": 1280, "height": 800, "title": "FDrive | Asset Loader"}
VIEW = Rect(24, 154, 820, 530)


def dialog(kind, **options):
    import tkinter as tk
    from tkinter import filedialog, simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        if kind == "id":
            return simpledialog.askstring("에셋 ID", "영문·숫자·밑줄·점·하이픈", parent=root, **options)
        return filedialog.askopenfilename(parent=root, **options)
    finally:
        root.destroy()


class AssetLoaderApp:
    def __init__(self, *, source=None, catalog=DEFAULT_CATALOG, debug=False, timings=None, capture=None):
        self.running = True
        self.initial_source = Path(source).resolve() if source else SAMPLE
        self.catalog_path = Path(catalog).resolve()
        self.debug = debug
        self.timings = timings
        self.capture = Path(capture).resolve() if capture else None
        self.renderer = self.manager = self.handle = None
        self.catalog = AssetCatalog(path=self.catalog_path)
        self.source = None
        self.asset_id = ""
        self.clip_name = ""
        self.elapsed = 0.0
        self.paused = False
        self.show_body = self.show_shadow = True
        self.zoom = 1.0
        self.message = "에셋을 선택한다."
        self.error = False
        self.list_offset = 0
        self.first_draw = True
        self.buttons = [
            ("불러오기 O", "open", Rect(24, 80, 150, 44)),
            ("ID 변경 I", "id", Rect(184, 80, 138, 44)),
            ("등록 S", "register", Rect(332, 80, 130, 44)),
            ("핫 로드 D", "debug", Rect(472, 80, 150, 44)),
            ("새로고침 R", "reload", Rect(632, 80, 152, 44)),
            ("카탈로그", "catalog", Rect(794, 80, 138, 44)),
            ("맞춤 F", "fit", Rect(942, 80, 126, 44)),
            ("1:1", "actual", Rect(1078, 80, 88, 44)),
        ]

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.theme = load_theme()
        paths = {role: ROOT / "data/fonts" / entry["path"] for role, entry in self.theme["fonts"].items()}
        sizes = {role: entry["size"] for role, entry in self.theme["fonts"].items()}
        self.renderer = PicoRenderer(paths, sizes)
        if self.catalog_path.exists():
            try:
                self.catalog = AssetCatalog.load(self.catalog_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.report(error)
                return
        self.open_source(self.initial_source)

    def report(self, error):
        self.message, self.error = str(error), True

    def open_source(self, source, *, kind=None, asset_id=None):
        candidate = None
        try:
            source = Path(source).resolve()
            definition = AssetDefinition("preview", kind or detect_kind(source), source)
            candidate = AssetManager(AssetCatalog([definition]), PicoAssetBackend(),
                                     debug=self.debug, timings=self.timings)
            handle = candidate.acquire("preview")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            if candidate is not None:
                candidate.close()
            self.report(error)
            return False
        if self.manager is not None:
            self.manager.close()
        self.manager, self.handle, self.source = candidate, handle, source
        hint = handle.resource.suggested_id
        self.asset_id = asset_id or re.sub(r"[^A-Za-z0-9_.-]", "_", str(hint)).strip("_.-") or "asset"
        self.clip_name = next(iter(handle.resource.clips))
        self.elapsed = 0.0
        self.fit()
        self.message, self.error = "", False
        return True

    @property
    def clip(self):
        if self.handle is None:
            return None
        clips = self.handle.resource.clips
        if self.clip_name not in clips:
            self.clip_name = next(iter(clips))
        return clips[self.clip_name]

    @property
    def frame_index(self):
        return int(self.elapsed * self.clip.fps + 1e-9) % len(self.clip.frames) if self.clip else 0

    def fit(self):
        if self.clip:
            maximum_width = max(frame.rect[2] for frame in self.clip.frames)
            maximum_height = max(frame.rect[3] for frame in self.clip.frames)
            self.zoom = min(4.0, (VIEW.width - 60) / maximum_width, (VIEW.height - 60) / maximum_height)

    def change_clip(self, offset):
        if self.handle:
            names = list(self.handle.resource.clips)
            self.clip_name = names[(names.index(self.clip_name) + offset) % len(names)]
            self.elapsed = 0.0

    def register(self):
        if self.handle is None:
            raise ValueError("먼저 정상 로딩된 에셋을 선택한다.")
        if ROOT / "samples" in self.catalog_path.parents:
            raise ValueError("샘플 카탈로그는 읽기 전용이다. --catalog로 작업용 경로를 지정한다.")
        # 외부에서 바뀐 등록 내용을 덮어쓰지 않도록 저장 직전에 다시 읽는다.
        catalog = AssetCatalog.load(self.catalog_path) if self.catalog_path.exists() else AssetCatalog(path=self.catalog_path)
        definition = AssetDefinition(self.asset_id, self.handle.resource.definition.kind, self.source)
        catalog.add(definition)
        verification = AssetManager(AssetCatalog([definition]), PicoAssetBackend(), timings=self.timings)
        try:
            with verification.acquire(definition.asset_id):
                pass
        finally:
            verification.close()
        catalog.save()
        self.catalog = catalog
        self.message, self.error = f"등록 완료: {self.asset_id}", False

    def action(self, action):
        try:
            if action == "open":
                path = dialog("open", title="이미지·시트·번들 열기", filetypes=[
                    ("이미지·메타데이터", "*.png *.jpg *.jpeg *.bmp *.json"), ("모든 파일", "*.*")])
                if path:
                    self.open_source(path)
            elif action == "id":
                value = dialog("id", initialvalue=self.asset_id)
                if value is not None:
                    AssetDefinition(value, "image", self.source or SAMPLE)
                    self.asset_id = value
            elif action == "register":
                self.register()
            elif action == "debug":
                self.debug = not self.debug
                if self.manager:
                    self.manager.debug = self.debug
                self.message, self.error = f"디버그 핫 로드 {'ON' if self.debug else 'OFF'}", False
            elif action == "reload":
                if self.debug and self.manager:
                    self.apply_reload(self.manager.poll_reload(force=True))
                elif self.source:
                    self.open_source(self.source, asset_id=self.asset_id)
            elif action == "catalog":
                path = dialog("open", title="등록 카탈로그 열기", filetypes=[("JSON", "*.json")])
                if path:
                    candidate = AssetCatalog.load(path)
                    self.catalog, self.catalog_path = candidate, candidate.path
                    self.list_offset = 0
                    self.message, self.error = "카탈로그 열기 완료", False
            elif action == "fit":
                self.fit()
            elif action == "actual":
                self.zoom = 1.0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.report(error)

    def handle_event(self, event):
        pico = self.pico
        if event.type == pico.SDL_KEYDOWN:
            key = event.key
            actions = {pico.SDLK_o: "open", pico.SDLK_i: "id", pico.SDLK_s: "register",
                       pico.SDLK_d: "debug", pico.SDLK_r: "reload", pico.SDLK_f: "fit"}
            if key in actions:
                self.action(actions[key])
            elif key == pico.SDLK_ESCAPE:
                self.running = False
            elif key == pico.SDLK_SPACE:
                self.paused = not self.paused
            elif key in (pico.SDLK_LEFT, pico.SDLK_RIGHT):
                self.change_clip(-1 if key == pico.SDLK_LEFT else 1)
            elif key == pico.SDLK_PERIOD and self.clip:
                self.paused = True
                self.elapsed = (self.frame_index + 1) / self.clip.fps
            elif key == pico.SDLK_b:
                self.show_body = not self.show_body
            elif key == pico.SDLK_h:
                self.show_shadow = not self.show_shadow
            elif key in (pico.SDLK_PAGEUP, pico.SDLK_PAGEDOWN):
                count = len(self.catalog.definitions)
                self.list_offset = max(0, min(max(0, count - 8), self.list_offset + (-8 if key == pico.SDLK_PAGEUP else 8)))
        elif event.type == pico.SDL_MOUSEBUTTONDOWN and event.button == pico.SDL_BUTTON_LEFT:
            for _, action, rect in self.buttons:
                if rect.contains(event.x, event.y):
                    self.action(action)
                    return
            if 870 <= event.x < 1254 and 430 <= event.y < 686:
                index = self.list_offset + int((event.y - 430) // 32)
                definitions = list(self.catalog.definitions.values())
                if index < len(definitions):
                    definition = definitions[index]
                    self.open_source(definition.source, kind=definition.kind, asset_id=definition.asset_id)
        elif event.type == pico.SDL_MOUSEWHEEL:
            self.zoom = max(0.01, min(16.0, self.zoom * 1.2 ** event.y))

    def apply_reload(self, events):
        for event in events:
            self.message = ("핫 로드 완료" if event.success else "핫 로드 실패 · 이전 정상 자원 유지") + ": " + event.message
            self.error = not event.success
        self.clip

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위다.")
        if self.manager:
            self.apply_reload(self.manager.poll_reload())
        if not self.paused:
            self.elapsed += delta_seconds

    def draw(self):
        r, c = self.renderer, self.theme["colors"]
        r.clear(c["background"])
        r.text("FDrive · 에셋 로더", 24, 20, "title", c["text"])
        for label, action, rect in self.buttons:
            active = action == "debug" and self.debug
            r.rect(rect, c["selected"] if active else c["button"])
            if action == "debug":
                label = f"핫 로드 {'ON' if self.debug else 'OFF'} D"
            r.text(label, rect.x + 10, rect.y + 10, "small", c["text"] if active else c["button_text"])
        with r.clip(VIEW):
            for row in range(9):
                for column in range(13):
                    r.rect(Rect(VIEW.x + column * 64, VIEW.y + row * 64, 64, 64),
                           c["panel"] if (row + column) % 2 else c["panel_surface"])
            if self.clip:
                frame = self.clip.frames[self.frame_index]
                x = VIEW.x + VIEW.width / 2 + (frame.pivot[0] - frame.rect[2] / 2) * self.zoom
                y = WINDOW["height"] - (VIEW.y + VIEW.height / 2) + (frame.pivot[1] - frame.rect[3] / 2) * self.zoom
                self.handle.resource.draw(self.clip_name, self.frame_index, x, y, scale=self.zoom,
                                          body=self.show_body, shadow=self.show_shadow)
                ui_y = WINDOW["height"] - y
                r.line(x - 10, ui_y, x + 10, ui_y, c["accent"])
                r.line(x, ui_y - 10, x, ui_y + 10, c["accent"])
        r.rect(Rect(866, 154, 390, 532), c["panel"])
        details = [f"ID: {self.asset_id or '-'}", f"종류: {self.handle.resource.definition.kind if self.handle else '-'}",
                   f"원본: {self.source.name if self.source else '-'}", f"동작: {self.clip_name or '-'}"]
        if self.clip:
            resource = self.handle.resource
            details.extend([f"프레임: {self.frame_index + 1}/{len(self.clip.frames)} · {self.clip.fps:g} FPS",
                            f"배율: {self.zoom:.2f} · 세대: {self.handle.generation}",
                            f"RGBA8 추정: {resource.estimated_bytes / 1048576:.2f} MiB",
                            f"본체 {'ON' if self.show_body else 'OFF'} / 그림자 {'ON' if self.show_shadow else 'OFF'}"])
        for index, line in enumerate(details):
            r.text(line, 882, 170 + index * 29, "small", c["text"], max_width=358)
        r.text(f"등록 목록 ({len(self.catalog.definitions)}) · PgUp/PgDn", 882, 405, "small", c["muted"])
        for index, definition in enumerate(list(self.catalog.definitions.values())[self.list_offset:self.list_offset + 8]):
            y = 430 + index * 32
            r.rect(Rect(878, y, 366, 30), c["selected"] if definition.asset_id == self.asset_id else c["background"])
            r.text(definition.asset_id, 888, y + 5, "small", c["text"], max_width=346)
        r.text(self.message, 24, 700, "small", c["error"] if self.error else c["accent"], max_width=1230)
        r.text(f"카탈로그: {self.catalog_path.as_posix()}", 24, 730, "small", c["muted"], max_width=1230)
        r.text("← → 동작/방향 · Space 재생/정지 · . 다음 프레임 · 휠 확대 · B 본체 · H 그림자 · Esc 종료", 24, 763, "small", c["muted"])
        if self.capture and self.first_draw:
            self.save_capture()
        self.first_draw = False

    def save_capture(self):
        pico = self.pico
        surface = pico.SDL_CreateRGBSurfaceWithFormat(0, WINDOW["width"], WINDOW["height"], 32, pico.SDL_PIXELFORMAT_RGBA32)
        if not surface:
            raise RuntimeError("화면 검증 이미지 버퍼 생성 실패")
        try:
            if pico.SDL_RenderReadPixels(pico.renderer, None, pico.SDL_PIXELFORMAT_RGBA32,
                                         surface.contents.pixels, surface.contents.pitch) != 0:
                raise RuntimeError("화면 검증 이미지 읽기 실패")
            self.capture.parent.mkdir(parents=True, exist_ok=True)
            if pico.IMG_SavePNG(surface, str(self.capture).encode("utf-8")) != 0:
                raise OSError("화면 검증 이미지 저장 실패")
        finally:
            pico.SDL_FreeSurface(surface)

    def exit(self):
        try:
            if self.manager:
                self.manager.close()
        finally:
            if self.renderer:
                self.renderer.close()
