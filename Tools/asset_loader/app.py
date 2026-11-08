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
VIEW = Rect(24, 116, 820, 568)
PRODUCTION_MENU = Rect(1136, 18, 120, 34)
PRODUCTION_ITEMS = [("3D 프리렌더…", "render"), ("애니메이션 조립…", "compose"), ("렌더 취소", "cancel_render")]
FILTER_RECT = Rect(882, 371, 358, 28)
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
        self.mouse = (0, 0)
        self.filtering, self.filter_popup = 'bicubic', False
        self.buttons = [
            ("불러오기 O", "open", Rect(24, 64, 150, 36)),
            ("ID 변경 I", "id", Rect(184, 64, 138, 36)),
            ("등록 S", "register", Rect(332, 64, 130, 36)),
            ("핫 로드 D", "debug", Rect(472, 64, 150, 36)),
            ("새로고침 R", "reload", Rect(632, 64, 152, 36)),
            ("카탈로그", "catalog", Rect(794, 64, 138, 36)),
            ("맞춤 F", "fit", Rect(942, 64, 126, 36)),
            ("1:1", "actual", Rect(1078, 64, 88, 36)),
        ]

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.theme = load_theme()
        paths = {role: ROOT / "data/fonts" / entry["path"] for role, entry in self.theme["fonts"].items()}
        sizes = {role: entry["size"] for role, entry in self.theme["fonts"].items()}
        sizes["title"] = 28
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
                    if Rect(882, 405 + index * 32, 358, 32).contains(event.x, event.y):
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
        r.text("FDrive · 에셋 로더", 24, 20, "title", c["text"])
        r.text("제작", PRODUCTION_MENU.x + 12, PRODUCTION_MENU.y + 5, "body", c["text"])
        r.line(1204, 32, 1209, 37, c["text"])
        r.line(1209, 37, 1214, 32, c["text"])
        for label, action, rect in self.buttons:
            active = action == "debug" and self.debug
            r.rect(rect, c["selected"] if active else c["button"])
            if action == "debug":
                label = f"핫 로드 {'ON' if self.debug else 'OFF'} D"
            r.text(label, rect.x + 10, rect.y + 10, "small", c["text"] if active else c["button_text"])
        with r.clip(VIEW):
            for row in range(10):
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
        r.rect(Rect(866, 116, 390, 570), c["panel"])
        details = [f"ID: {self.asset_id or '-'}", f"종류: {self.handle.resource.definition.kind if self.handle else '-'}",
                   f"원본: {self.source.name if self.source else '-'}", f"동작: {self.clip_name or '-'}"]
        if self.clip:
            resource = self.handle.resource
            details.extend([f"프레임: {self.frame_index + 1}/{len(self.clip.frames)} · {self.clip.fps:g} FPS",
                            f"배율: {self.zoom:.2f} · 세대: {self.handle.generation}",
                            f"RGBA8 추정: {resource.estimated_bytes / 1048576:.2f} MiB",
                            f"본체 {'ON' if self.show_body else 'OFF'} / 그림자 {'ON' if self.show_shadow else 'OFF'}"])
        for index, line in enumerate(details):
            r.text(line, 882, 132 + index * 29, "small", c["text"], max_width=358)
        r.rect(FILTER_RECT, c["input"])
        current_filter = self.handle.resource.filtering.title() if self.handle else '-'
        r.text(f"필터: {current_filter}", 892, 377, "small", c["text"])
        r.line(1220, 382, 1225, 387, c["text"])
        r.line(1225, 387, 1230, 382, c["text"])
        r.text(f"등록 목록 ({len(self.catalog.definitions)}) · PgUp/PgDn", 882, 405, "small", c["muted"])
        for index, definition in enumerate(list(self.catalog.definitions.values())[self.list_offset:self.list_offset + 8]):
            y = 430 + index * 32
            r.rect(Rect(878, y, 366, 30), c["selected"] if definition.asset_id == self.asset_id else c["background"])
            r.text(definition.asset_id, 888, y + 5, "small", c["text"], max_width=346)
        r.text(self.message, 24, 700, "small", c["error"] if self.error else c["accent"], max_width=1230)
        r.text(f"카탈로그: {self.catalog_path.as_posix()}", 24, 730, "small", c["muted"], max_width=1230)
        r.text("← → 동작/방향 · Space 재생/정지 · . 다음 프레임 · 휠 확대 · B 본체 · H 그림자 · Esc 종료", 24, 763, "small", c["muted"])
        if self.menu_open:
            for index, (label, _) in enumerate(PRODUCTION_ITEMS):
                rect = Rect(1030, 56 + index * 36, 226, 36)
                r.rect(rect, c["panel"])
                r.text(label, rect.x + 12, rect.y + 8, "small", c["text"])
        if self.filter_popup:
            for index, mode in enumerate(FILTERS):
                r.rect(Rect(882, 405 + index * 32, 358, 32), c["selected"] if mode == self.filtering else c["input"])
                r.text(mode.title(), 894, 412 + index * 32, "small", c["text"])
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
