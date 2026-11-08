"""공통 로더를 사용하는 이미지·시트·번들 미리보기 화면."""

from math import isfinite
from pathlib import Path
import json
import re
from uuid import uuid4

from ferrial_drive.assets import AssetCatalog, AssetDefinition, AssetManager, detect_kind
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer
from Tools.theme_reference import load_theme
from .library import DEFAULT_CATALOG, SAMPLE, prepare_library, store_asset


ROOT = Path(__file__).resolve().parents[2]
WINDOW = {"width": 1280, "height": 800, "title": "FDrive | Asset Loader"}
VIEW = Rect(20, 174, 844, 482)
PRODUCTION_MENU = Rect(1164, 12, 96, 34)
PRODUCTION_ITEMS = [("메카 · 무기 분리…", "mech"), ("3D 프리렌더…", "render"),
                    ("애니메이션 조립…", "compose"), ("렌더 취소", "cancel_render")]
FILTER_RECT = Rect(900, 590, 344, 28)
CATALOG_RECT = Rect(892, 216, 360, 320)
FILTER_OPTIONS_Y = 622
FILTERS = ('nearest', 'linear', 'bicubic')


class AssetLoaderApp:
    accept_text = True

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
        self.build = None
        self.menu_open = False
        self.panel = None
        self.mech_drafts = {}
        self.mouse = (0, 0)
        self.filtering, self.filter_popup = 'bicubic', False
        self.buttons = [
            ("불러오기 O", "open", Rect(226, 12, 118, 34)),
            ("ID 변경 I", "id", Rect(352, 12, 104, 34)),
            ("등록 S", "register", Rect(464, 12, 82, 34)),
            ("핫 로드 D", "debug", Rect(554, 12, 150, 34)),
            ("새로고침 R", "reload", Rect(712, 12, 126, 34)),
            ("카탈로그", "catalog", Rect(846, 12, 112, 34)),
            ("메카 분리", "mech", Rect(966, 12, 112, 34)),
            ("맞춤 F", "fit", Rect(20, 668, 104, 32)),
            ("1:1", "actual", Rect(132, 668, 64, 32)),
            ("재생 / 정지", "play", Rect(208, 668, 128, 32)),
            ("◀", "previous", Rect(348, 668, 44, 32)),
            ("▶", "next", Rect(400, 668, 44, 32)),
            ("본체 B", "body", Rect(900, 546, 156, 32)),
            ("그림자 H", "shadow", Rect(1068, 546, 176, 32)),
        ]

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.theme = load_theme()
        paths = {role: ROOT / "data/fonts" / entry["path"] for role, entry in self.theme["fonts"].items()}
        sizes = {role: entry["size"] for role, entry in self.theme["fonts"].items()}
        self.renderer = PicoRenderer(paths, sizes)
        if self.catalog_path == DEFAULT_CATALOG:
            try:
                prepare_library()
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.report(error)
                return
        if self.catalog_path.exists():
            try:
                self.catalog = AssetCatalog.load(self.catalog_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.report(error)
                return
        if self.initial_source.suffix.lower() == ".blend":
            self.configure_render(self.initial_source)
        else:
            self.open_source(self.initial_source)

    def report(self, error):
        self.message, self.error = str(error), True

    def open_source(self, source, *, kind=None, asset_id=None):
        candidate = None
        try:
            source = Path(source).resolve()
            definition = AssetDefinition("preview", kind or detect_kind(source), source)
            candidate = AssetManager(AssetCatalog([definition]), PicoAssetBackend(self.filtering),
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
        self.clip_name = handle.resource.default_clip
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
            with verification.acquire(definition.asset_id) as current:
                stored = (store_asset(definition, image_size=current.resource.sizes["body"])
                          if self.catalog_path == DEFAULT_CATALOG else definition)
        finally:
            verification.close()
        if stored != definition:
            verification = AssetManager(AssetCatalog([stored]), PicoAssetBackend(), timings=self.timings)
            try:
                with verification.acquire(stored.asset_id):
                    pass
            finally:
                verification.close()
            catalog.definitions[definition.asset_id] = stored
        catalog.save()
        self.catalog = catalog
        if stored != definition:
            self.open_source(stored.source, kind=stored.kind, asset_id=stored.asset_id)
        self.message, self.error = f"등록 완료: {self.asset_id}", False

    def configure_render(self, source=None):
        from .editors import RenderPanel
        if self.build and self.build.process is not None:
            raise ValueError("렌더 작업이 진행 중이다.")
        self.set_panel(RenderPanel(self, source))

    def set_panel(self, panel):
        self.panel, self.menu_open = panel, False
        self.filter_popup = False
        if hasattr(self, "pico"):
            if panel is not None:
                self.pico.SDL_StartTextInput()
            else:
                self.pico.SDL_StopTextInput()

    def choose_source(self, path):
        if Path(path).suffix.lower() == ".blend":
            self.configure_render(path)
        elif not self.open_source(path):
            raise ValueError(self.message)

    def choose_catalog(self, path):
        candidate = AssetCatalog.load(path)
        self.catalog, self.catalog_path, self.list_offset = candidate, candidate.path, 0
        self.message, self.error = "카탈로그 열기 완료", False

    def start_render(self, source, config, *, blender=None):
        from .production import WORKSPACE
        from Tools.blender_pipeline.asset_build import AssetBuild
        if self.build and self.build.process is not None:
            raise ValueError("렌더 작업이 진행 중이다.")
        path = WORKSPACE / "render_jobs" / (uuid4().hex + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.build:
            self.build.close()
        self.build = AssetBuild(path, source_blend=source, blender=blender,
                                output_root=ROOT / "output/asset_loader/renders")
        self.build.start()
        self.message, self.error = self.build.progress_text, False

    def compose(self):
        from .editors import AssemblyPanel
        if self.handle is None:
            raise ValueError("먼저 에셋을 선택한다.")
        if self.build and self.build.process is not None:
            raise ValueError("렌더 완료 후 조립한다.")
        self.set_panel(AssemblyPanel(self))

    def action(self, action):
        try:
            if action == "open":
                from .file_panel import FilePanel
                self.set_panel(FilePanel(self, self.choose_source,
                    extensions={".blend", ".png", ".jpg", ".jpeg", ".bmp", ".json"}, initial=self.source or ROOT))
            elif action == "id":
                from .file_panel import IdPanel
                self.set_panel(IdPanel(self))
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
                from .file_panel import FilePanel
                self.set_panel(FilePanel(self, self.choose_catalog, extensions={".json"}, initial=self.catalog_path))
            elif action == "fit":
                self.fit()
            elif action == "actual":
                self.zoom = 1.0
            elif action == "render":
                self.configure_render()
            elif action == "compose":
                self.compose()
            elif action == "mech":
                from .mech_panel import MechPanel
                if self.handle is None:
                    raise ValueError("먼저 에셋을 선택한다.")
                self.set_panel(MechPanel(self))
            elif action == "play":
                self.paused = not self.paused
            elif action in ("previous", "next") and self.clip:
                self.paused = True
                self.elapsed = ((self.frame_index + (-1 if action == "previous" else 1)) % len(self.clip.frames)) / self.clip.fps
            elif action == "body":
                self.show_body = not self.show_body
            elif action == "shadow":
                self.show_shadow = not self.show_shadow
            elif action == "cancel_render" and self.build:
                self.build.close()
                self.message, self.error = "렌더 취소", False
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.report(error)

    def handle_event(self, event):
        pico = self.pico
        if (event.type == pico.SDL_QUIT or event.type == pico.SDL_WINDOWEVENT
                and event.window_event == pico.SDL_WINDOWEVENT_CLOSE):
            self.running = False
            return
        if event.type == pico.SDL_MOUSEMOTION:
            self.mouse = (event.x, event.y)
        if self.panel is not None:
            self.panel.handle_event(event)
            return
        if event.type == pico.SDL_KEYDOWN:
            if getattr(event, "repeat", False):
                return
            key = event.key
            actions = {pico.SDLK_o: "open", pico.SDLK_i: "id", pico.SDLK_s: "register",
                       pico.SDLK_d: "debug", pico.SDLK_r: "reload", pico.SDLK_f: "fit"}
            if key in actions:
                self.action(actions[key])
            elif key == pico.SDLK_ESCAPE:
                if self.filter_popup:
                    self.filter_popup = False
                elif self.menu_open:
                    self.menu_open = False
                else:
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
            if FILTER_RECT.contains(event.x, event.y) and self.handle:
                self.filter_popup, self.menu_open = not self.filter_popup, False
                return
            if self.filter_popup:
                self.filter_popup = False
                for index, mode in enumerate(FILTERS):
                    if Rect(FILTER_RECT.x, FILTER_OPTIONS_Y + index * 32, FILTER_RECT.width, 32).contains(event.x, event.y):
                        self.handle.resource.set_filtering(mode)
                        self.filtering = mode
                        return
            if PRODUCTION_MENU.contains(event.x, event.y):
                self.menu_open = not self.menu_open
                return
            if self.menu_open:
                self.menu_open = False
                for index, (_, action) in enumerate(PRODUCTION_ITEMS):
                    if Rect(1030, 56 + index * 36, 226, 36).contains(event.x, event.y):
                        self.action(action)
                        return
            for _, action, rect in self.buttons:
                if rect.contains(event.x, event.y):
                    self.action(action)
                    return
            if CATALOG_RECT.contains(event.x, event.y):
                index = self.list_offset + int((event.y - CATALOG_RECT.y) // 40)
                definitions = list(self.catalog.definitions.values())
                if index < len(definitions):
                    definition = definitions[index]
                    self.open_source(definition.source, kind=definition.kind, asset_id=definition.asset_id)
        elif event.type == pico.SDL_MOUSEWHEEL:
            if CATALOG_RECT.contains(*self.mouse):
                self.list_offset = max(0, min(max(0, len(self.catalog.definitions) - 8), self.list_offset - event.y))
            elif VIEW.contains(*self.mouse):
                self.zoom = max(0.01, min(16.0, self.zoom * 1.2 ** event.y))

    def apply_reload(self, events):
        for event in events:
            self.message = ("핫 로드 완료" if event.success else "핫 로드 실패 · 이전 정상 자원 유지") + ": " + event.message
            self.error = not event.success
        self.clip

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위다.")
        if self.manager and self.panel is None:
            self.apply_reload(self.manager.poll_reload())
        if self.build and self.build.process is not None:
            result = self.build.poll()
            if result is True:
                if self.open_source(self.build.result):
                    self.message = self.build.progress_text
            elif result is False:
                self.report(self.build.error)
            else:
                self.message, self.error = self.build.progress_text, False
        if not self.paused:
            self.elapsed += delta_seconds
        if self.panel is not None:
            self.panel.update(delta_seconds)

    def draw(self):
        r, c = self.renderer, self.theme["colors"]
        r.clear(c["background"])
        # 공통 본문 글꼴로 영문과 한글의 시각적 간격을 맞춘다.
        r.text("FDrive 에셋 로더", 20, 19, "body", c["text"])
        r.rect(Rect(20, 60, 1240, 100), c["panel"])
        r.text("공통 정보", 36, 72, "small", c["accent"])
        resource = self.handle.resource if self.handle else None
        details = [(f"ID: {self.asset_id or '-'}", 142, 72, 310),
                   (f"종류: {resource.definition.kind if resource else '-'}", 482, 72, 180),
                   (f"원본: {self.source.name if self.source else '-'}", 690, 72, 550),
                   (f"동작: {self.clip_name or '-'}", 36, 112, 330),
                   (f"프레임: {self.frame_index + 1}/{len(self.clip.frames)} · {self.clip.fps:g} FPS" if self.clip else "프레임: -", 390, 112, 300),
                   (f"배율: {self.zoom:.2f}", 716, 112, 160),
                   (f"RGBA8 추정: {resource.estimated_bytes / 1048576:.2f} MiB" if resource else "RGBA8 추정: -", 918, 112, 322)]
        for text, x, y, width in details:
            r.text(text, x, y, "small", c["text"], max_width=width)
        r.rect(PRODUCTION_MENU, c["button"])
        r.text("제작", PRODUCTION_MENU.x + 12, PRODUCTION_MENU.y + 5, "body", c["button_text"])
        r.line(1230, 24, 1235, 29, c["button_text"])
        r.line(1235, 29, 1240, 24, c["button_text"])
        for label, action, rect in self.buttons:
            active = ((action == "debug" and self.debug) or (action == "body" and self.show_body)
                      or (action == "shadow" and self.show_shadow))
            r.rect(rect, c["selected"] if active else c["button"])
            if action == "debug":
                label = f"핫 로드 {'ON' if self.debug else 'OFF'} D"
            elif action == "play":
                label = "재생 Space" if self.paused else "정지 Space"
            r.text(label, rect.x + 10, rect.y + 10, "small", c["text"] if active else c["button_text"])
        with r.clip(VIEW):
            for row in range(int(VIEW.height // 64) + 1):
                for column in range(int(VIEW.width // 64) + 1):
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
        # 사이드바 배경은 조작 버튼 뒤를 덮지 않도록 목록 영역에만 그린다.
        r.rect(Rect(884, 174, 376, 362), c["panel"])
        r.rect(FILTER_RECT, c["input"])
        current_filter = self.handle.resource.filtering.title() if self.handle else '-'
        r.text(f"필터: {current_filter}", FILTER_RECT.x + 10, FILTER_RECT.y + 6, "small", c["text"])
        r.line(1220, 600, 1225, 605, c["text"])
        r.line(1225, 605, 1230, 600, c["text"])
        r.text(f"등록 목록 ({len(self.catalog.definitions)}) · 휠 / PgUp/PgDn", 900, 188, "small", c["muted"])
        for index, definition in enumerate(list(self.catalog.definitions.values())[self.list_offset:self.list_offset + 8]):
            y = CATALOG_RECT.y + index * 40
            r.rect(Rect(CATALOG_RECT.x, y, CATALOG_RECT.width, 38), c["selected"] if definition.asset_id == self.asset_id else c["background"])
            r.text(definition.asset_id, CATALOG_RECT.x + 10, y + 10, "small", c["text"], max_width=340)
        r.text("← → 동작/방향 · . 다음 프레임", 466, 678, "small", c["muted"])
        r.text(self.message, 20, 714, "small", c["error"] if self.error else c["accent"], max_width=1240)
        r.text(f"카탈로그: {self.catalog_path.as_posix()}", 20, 742, "small", c["muted"], max_width=1240)
        r.text("미리보기에서 휠 확대 · 메카 분리에서 출력 단위/동작/전환 시점 편집 · Esc 종료", 20, 773, "small", c["muted"])
        if self.menu_open:
            for index, (label, _) in enumerate(PRODUCTION_ITEMS):
                rect = Rect(1030, 56 + index * 36, 226, 36)
                r.rect(rect, c["panel"])
                r.text(label, rect.x + 12, rect.y + 8, "small", c["text"])
        if self.filter_popup:
            for index, mode in enumerate(FILTERS):
                r.rect(Rect(FILTER_RECT.x, FILTER_OPTIONS_Y + index * 32, FILTER_RECT.width, 32), c["selected"] if mode == self.filtering else c["input"])
                r.text(mode.title(), FILTER_RECT.x + 12, FILTER_OPTIONS_Y + 7 + index * 32, "small", c["text"])
        if self.panel is not None:
            self.panel.draw()
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
            self.set_panel(None)
            if self.build:
                self.build.close()
            if self.manager:
                self.manager.close()
        finally:
            if self.renderer:
                self.renderer.close()
