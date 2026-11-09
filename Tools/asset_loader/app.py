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
from .frame_strip import ANIMATION_VIEW, FRAME_STRIP, FrameStrip


ROOT = Path(__file__).resolve().parents[2]
WINDOW = {"width": 1280, "height": 800, "title": "FDrive | Asset Loader"}
VIEW = Rect(276, 88, 696, 616)
PRODUCTION_MENU = Rect(1152, 10, 112, 30)
PRODUCTION_ITEMS = [("ID 변경", "id"), ("카탈로그 열기", "catalog"),
                    ("핫 로드 전환", "debug"), ("새로고침", "reload"), ("렌더 취소", "cancel_render")]
FILTER_RECT = Rect(992, 664, 264, 28)
CATALOG_RECT = Rect(24, 132, 232, 442)
ANIMATION_RECT = Rect(992, 132, 264, 476)
CATALOG_PAGE = 13
ANIMATION_PAGE = 17
FILTER_OPTIONS_Y = 696
FILTERS = ('nearest', 'linear', 'bicubic')


class AssetLoaderApp:
    accept_text = True

    def __init__(self, *, source=None, catalog=DEFAULT_CATALOG, debug=False, timings=None, capture=None,
                 pose=False, pose_sample=False):
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
        self.clip_offset = 0
        self.frame_strip = FrameStrip()
        self.first_draw = True
        self.startup_pose, self.pose_sample = pose or pose_sample, pose_sample
        self.build = None
        self.menu_open = False
        self.panel = None
        self.pose_editor = None
        self.mech_drafts = {}
        self.show_details = False
        self.mouse = (0, 0)
        self.filtering, self.filter_popup = 'bicubic', False
        self.buttons = [
            ("불러오기", "open", Rect(184, 10, 112, 30)),
            ("등록", "register", Rect(304, 10, 80, 30)),
            ("메카 설정", "mech", Rect(412, 10, 120, 30)),
            ("애니메이션 조립", "compose", Rect(540, 10, 152, 30)),
            ("3D 렌더", "render", Rect(700, 10, 112, 30)),
            ("맵 작업", "map", Rect(820, 10, 112, 30)),
            ("포즈 편집", "pose", Rect(940, 10, 112, 30)),
            ("맞춤", "fit", Rect(276, 716, 88, 30)),
            ("1:1", "actual", Rect(372, 716, 56, 30)),
            ("재생 / 정지", "play", Rect(456, 716, 112, 30)),
            ("◀", "previous", Rect(576, 716, 40, 30)),
            ("▶", "next", Rect(624, 716, 40, 30)),
            ("본체", "body", Rect(992, 624, 124, 28)),
            ("그림자", "shadow", Rect(1128, 624, 128, 28)),
            ("상세 정보", "details", Rect(24, 584, 232, 28)),
        ]

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.theme = load_theme()
        paths = {role: ROOT / "data/fonts" / entry["path"] for role, entry in self.theme["fonts"].items()}
        sizes = {role: entry["size"] for role, entry in self.theme["fonts"].items()}
        paths["section"] = ROOT / "data/fonts/s_core_dream/SCDream6.otf"
        sizes["section"] = sizes["small"]
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
        if self.startup_pose:
            self.configure_pose()
            if self.pose_sample or self.initial_source.suffix.lower() == ".blend":
                self.pose_editor.attempt(lambda: self.pose_editor.open_model(sample=self.pose_sample))

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
        self.frame_strip.reset()
        self.clip_offset = 0
        self.ensure_clip_visible()
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
        return self.clip.frame_at(self.elapsed) if self.clip else 0

    @property
    def show_frame_strip(self):
        return self.handle is not None and self.handle.resource.definition.kind != 'map'

    @property
    def preview_rect(self):
        return ANIMATION_VIEW if self.show_frame_strip else VIEW

    def seek_frame(self, index):
        if self.clip:
            index %= len(self.clip.frames)
            self.paused = True
            self.elapsed = self.clip.frame_start_seconds(index)
            self.frame_strip.follow_playback = True
            self.frame_strip.reveal(index, len(self.clip.frames))

    def fit(self):
        if self.clip:
            maximum_width = max(frame.rect[2] for frame in self.clip.frames)
            maximum_height = max(frame.rect[3] for frame in self.clip.frames)
            view = self.preview_rect
            self.zoom = min(4.0, (view.width - 60) / maximum_width, (view.height - 60) / maximum_height)

    def change_clip(self, offset):
        if self.handle:
            names = list(self.handle.resource.clips)
            self.select_clip(names[(names.index(self.clip_name) + offset) % len(names)])

    def select_clip(self, name):
        if self.handle and name in self.handle.resource.clips:
            self.clip_name, self.elapsed = name, 0.0
            self.frame_strip.reset()
            self.ensure_clip_visible()

    def ensure_clip_visible(self):
        if self.handle:
            names = list(self.handle.resource.clips)
            if self.clip_name in names:
                index = names.index(self.clip_name)
                self.clip_offset = min(max(self.clip_offset, index - ANIMATION_PAGE + 1), index)
            self.clip_offset = max(0, min(max(0, len(names) - ANIMATION_PAGE), self.clip_offset))

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

    def configure_pose(self, source=None):
        from .pose_panel import PosePanel
        if self.pose_editor is None:
            incoming = source or (self.initial_source if self.initial_source.suffix.lower() == ".blend" else None)
            self.pose_editor = PosePanel(self, incoming)
        elif source and self.pose_editor.session is None:
            self.pose_editor.fields["source"].text = str(source)
        self.set_panel(self.pose_editor)

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
        if self.handle.resource.definition.kind == "map":
            raise ValueError("맵은 맵 작업에서 레이어·이동 구역을 편집한다.")
        if self.handle.resource.definition.kind == "mech":
            raise ValueError("분리 메카는 메카 설정에서 순서·조립 미리보기를 편집한다.")
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
            elif action == "pose":
                self.configure_pose()
            elif action == "map":
                from .map_panel import MapPanel
                self.set_panel(MapPanel(self))
            elif action == "compose":
                self.compose()
            elif action == "mech":
                from .mech_panel import MechPanel
                if self.handle is None:
                    raise ValueError("먼저 에셋을 선택한다.")
                if self.handle.resource.definition.kind == 'map':
                    raise ValueError('맵 작업에서 레이어와 이동 구역을 편집한다.')
                self.set_panel(MechPanel(self))
            elif action == "play":
                self.paused = not self.paused
                self.frame_strip.follow_playback = True
            elif action in ("previous", "next") and self.clip:
                self.seek_frame(self.frame_index + (-1 if action == "previous" else 1))
            elif action == "body":
                self.show_body = not self.show_body
            elif action == "shadow":
                self.show_shadow = not self.show_shadow
            elif action == "details":
                self.show_details = not self.show_details
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
            if key == pico.SDLK_ESCAPE:
                if self.filter_popup:
                    self.filter_popup = False
                elif self.menu_open:
                    self.menu_open = False
                else:
                    self.running = False
            elif key == pico.SDLK_SPACE:
                self.action('play')
            elif key in (pico.SDLK_LEFT, pico.SDLK_RIGHT):
                self.change_clip(-1 if key == pico.SDLK_LEFT else 1)
            elif key == pico.SDLK_PERIOD and self.clip:
                self.seek_frame(self.frame_index + 1)
            elif key in (pico.SDLK_PAGEUP, pico.SDLK_PAGEDOWN):
                count = len(self.catalog.definitions)
                self.list_offset = max(0, min(max(0, count - CATALOG_PAGE), self.list_offset + (-CATALOG_PAGE if key == pico.SDLK_PAGEUP else CATALOG_PAGE)))
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
            if self.show_frame_strip and FRAME_STRIP.contains(event.x, event.y):
                index = self.frame_strip.hit(event.x, event.y, len(self.clip.frames))
                if index is not None:
                    self.seek_frame(index)
                return
            if CATALOG_RECT.contains(event.x, event.y):
                index = self.list_offset + int((event.y - CATALOG_RECT.y) // 34)
                definitions = list(self.catalog.definitions.values())
                if index < len(definitions):
                    definition = definitions[index]
                    self.open_source(definition.source, kind=definition.kind, asset_id=definition.asset_id)
            elif ANIMATION_RECT.contains(event.x, event.y) and self.handle:
                index = self.clip_offset + int((event.y - ANIMATION_RECT.y) // 28)
                names = list(self.handle.resource.clips)
                if index < len(names):
                    self.select_clip(names[index])
        elif event.type == pico.SDL_MOUSEWHEEL:
            if CATALOG_RECT.contains(*self.mouse):
                self.list_offset = max(0, min(max(0, len(self.catalog.definitions) - CATALOG_PAGE), self.list_offset - event.y))
            elif ANIMATION_RECT.contains(*self.mouse) and self.handle:
                self.clip_offset = max(0, min(max(0, len(self.handle.resource.clips) - ANIMATION_PAGE), self.clip_offset - event.y * 3))
            elif self.show_frame_strip and FRAME_STRIP.contains(*self.mouse):
                self.frame_strip.scroll(event.y, len(self.clip.frames))
            elif self.preview_rect.contains(*self.mouse):
                self.zoom = max(0.01, min(16.0, self.zoom * 1.2 ** event.y))

    def apply_reload(self, events):
        for event in events:
            self.message = ("핫 로드 완료" if event.success else "핫 로드 실패 · 이전 정상 자원 유지") + ": " + event.message
            self.error = not event.success
        self.clip
        if events:
            self.ensure_clip_visible()

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
        if self.pose_editor is not None and self.panel is not self.pose_editor:
            self.pose_editor.update(delta_seconds)

    def draw(self):
        r, c = self.renderer, self.theme["colors"]
        r.clear(c["background"])
        r.rect(Rect(16, 88, 248, 658), c["panel"])
        r.rect(Rect(984, 88, 280, 658), c["panel"])
        # 공통 본문 글꼴로 영문과 한글의 시각적 간격을 맞춘다.
        r.text("FDrive 에셋 로더", 16, 16, "body", c["text"])
        r.line(398, 14, 398, 36, c["line"])
        r.rect(Rect(16, 50, 1248, 28), c["panel"])
        resource = self.handle.resource if self.handle else None
        details = [(f"ID  {self.asset_id or '-'}", 28, 300),
                   (f"원본  {self.source.name if self.source else '-'}", 350, 360),
                   (f"동작  {self.clip_name or '-'}", 734, 250),
                   (f"{self.frame_index + 1}/{len(self.clip.frames)} · {self.clip.durations_ms[self.frame_index]:g} ms" if self.clip else "프레임 -", 1010, 242)]
        for text, x, width in details:
            r.text(text, x, 57, "small", c["text"], max_width=width)
        r.rect(PRODUCTION_MENU, c["input"])
        r.text("관리", PRODUCTION_MENU.x + 12, PRODUCTION_MENU.y + 7, "small", c["text"])
        r.line(1240, 22, 1244, 26, c["muted"])
        r.line(1244, 26, 1248, 22, c["muted"])
        for label, action, rect in self.buttons:
            active = ((action == "debug" and self.debug) or (action == "body" and self.show_body)
                      or (action == "shadow" and self.show_shadow))
            r.rect(rect, c["selected"] if active else c["input"])
            if action == "play":
                label = "재생" if self.paused else "정지"
            elif action == "details":
                label = "상세 정보"
            if resource and resource.definition.kind == 'map':
                label = {'body': '배경', 'shadow': '바닥'}.get(action, label)
            r.text(label, rect.x + 10, rect.y + 7, "small", c["text"])
            if action == "details":
                x, y = rect.x + rect.width - 18, rect.y + 14
                points = ((x - 4, y - 2, x, y + 2), (x, y + 2, x + 4, y - 2)) if self.show_details else (
                    (x - 2, y - 4, x + 2, y), (x + 2, y, x - 2, y + 4))
                for x1, y1, x2, y2 in points:
                    r.line(x1, y1, x2, y2, c["muted"])
        view = self.preview_rect
        with r.clip(view):
            for row in range(int(view.height // 64) + 1):
                for column in range(int(view.width // 64) + 1):
                    r.rect(Rect(view.x + column * 64, view.y + row * 64, 64, 64),
                           c["panel"] if (row + column) % 2 else c["panel_surface"])
            if self.clip:
                frame = self.clip.frames[self.frame_index]
                x = view.x + view.width / 2 + (frame.pivot[0] - frame.rect[2] / 2) * self.zoom
                y = WINDOW["height"] - (view.y + view.height / 2) + (frame.pivot[1] - frame.rect[3] / 2) * self.zoom
                self.handle.resource.draw(self.clip_name, self.frame_index, x, y, scale=self.zoom,
                                          body=self.show_body, shadow=self.show_shadow)
                ui_y = WINDOW["height"] - y
                r.line(x - 10, ui_y, x + 10, ui_y, c["accent"])
                r.line(x, ui_y - 10, x, ui_y + 10, c["accent"])
        if self.show_frame_strip:
            self.frame_strip.draw(self)
        r.text("시트·번들 탐색기", 28, 102, "section", c["text"])
        r.text("맵 레이어" if resource and resource.definition.kind == 'map' else "애니메이션 탐색기", 1000, 102, "section", c["text"])
        r.rect(FILTER_RECT, c["input"])
        current_filter = self.handle.resource.filtering.title() if self.handle else '-'
        r.text(f"필터: {current_filter}", FILTER_RECT.x + 10, FILTER_RECT.y + 6, "small", c["text"])
        r.line(1230, 675, 1234, 679, c["muted"])
        r.line(1234, 679, 1238, 675, c["muted"])
        for index, definition in enumerate(list(self.catalog.definitions.values())[self.list_offset:self.list_offset + CATALOG_PAGE]):
            y = CATALOG_RECT.y + index * 34
            r.rect(Rect(CATALOG_RECT.x, y, CATALOG_RECT.width, 32), c["selected"] if definition.asset_id == self.asset_id else c["background"])
            r.text(definition.asset_id, CATALOG_RECT.x + 8, y + 8, "small", c["text"], max_width=216)
        if resource:
            names = list(resource.clips)
            for index, name in enumerate(names[self.clip_offset:self.clip_offset + ANIMATION_PAGE]):
                y = ANIMATION_RECT.y + index * 28
                r.rect(Rect(ANIMATION_RECT.x, y, ANIMATION_RECT.width, 26), c["selected"] if name == self.clip_name else c["background"])
                label = name
                if resource.definition.kind == 'map':
                    from .map_panel import VIEWS
                    label = dict(VIEWS).get(name, name)
                r.text(label, ANIMATION_RECT.x + 8, y + 6, "small", c["text"], max_width=248)
        else:
            r.text("시트·번들을 선택한다.", 1000, 144, "small", c["muted"])
        r.text(f"배율 {self.zoom:.2f}×", 688, 724, "small", c["muted"])
        r.text("휠 확대", 836, 724, "small", c["muted"])
        if self.show_details:
            lines = [f"종류: {resource.definition.kind if resource else '-'}",
                     f"RGBA8 추정: {resource.estimated_bytes / 1048576:.2f} MiB" if resource else "RGBA8 추정: -",
                     f"핫 로드: {'ON' if self.debug else 'OFF'}", "카탈로그:", self.catalog_path.as_posix()]
            for index, line in enumerate(lines):
                r.text(line, 28, 624 + index * 22, "small", c["muted"], max_width=224)
        r.line(16, 756, 1264, 756, c["line"])
        r.text(self.message or "에셋을 열고 미리보기하거나 상단에서 작업을 선택한다.", 16, 768, "small",
               c["error"] if self.error else c["muted"], max_width=1248)
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
            current = self.panel
            while current is not None:
                if hasattr(current, "close_resources"):
                    current.close_resources()
                current = getattr(current, "parent", None)
            self.set_panel(None)
            if self.pose_editor is not None:
                self.pose_editor.close_resources()
            if self.build:
                self.build.close()
            if self.manager:
                self.manager.close()
        finally:
            if self.renderer:
                self.renderer.close()
