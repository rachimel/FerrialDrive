"""본편 타이틀과 첫 훈련 교전을 FDrive에 연결한다."""

from dataclasses import replace
from pathlib import Path
from time import perf_counter, sleep

from ferrial_drive.combat.encounter_application import EncounterApplication
from ferrial_drive.continuation import ContinueSession
from ferrial_drive.ui.components import Button, Rect
from ferrial_drive.animation import smooth_step
from ferrial_drive.runtime import poll_events
from ferrial_drive.ui.loading import LoadingCancelled
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.title_menu import submenu_buttons
from .title_background import TitleBackground
from .title_music import TitleMusic


GAME_DIRECTORY = Path(__file__).resolve().parent
TRAINING_MOVEMENT_CONFIG = GAME_DIRECTORY.parent / "samples/sword_movement/movement_config.json"
EXIT_FADE_SECONDS = 0.5


class GameHud(MovementHud):
    def __init__(self, config_path, preset_path, **options):
        super().__init__(config_path, preset_path, initial_scene="menu",
                         continuation=ContinueSession(mode="game"), **options)
        title = self.config.data["title_menu"]
        title["version_label"] = "VER. PRE_DEMO"
        title["hover_seconds"] = .10
        title["duration_seconds"] = .14
        self.credits_open = False
        self.menu_audio = None
        self.entry_sound_pending = False
        buttons = self.title_menu_motion.base_buttons
        exit_button = next(button for button in buttons if button.action == "quit")
        credit = Button("credits", "credits", "CREDIT", exit_button.rect)
        self.title_menu_motion.base_buttons = tuple(
            replace(button, rect=button.rect.translated(0, button.rect.height * 1.3))
            if button is exit_button else button for button in buttons) + (credit,)
        self.config.buttons["menu"] = self.title_menu_motion.buttons
        for row in title["submenu_buttons"]:
            if row["action"] == "new_game":
                row["enabled"] = True
        self.title_menu_motion.submenu = submenu_buttons(title)
        layout = self.config.data["graphics_settings"]
        layout["language_selection"] = True
        self.korean_settings_labels = layout["labels"].copy()
        self.apply_language(self.graphics_settings.saved.language)

    def apply_language(self, language):
        from .menu_language import ENGLISH_SETTINGS, MENU_LABELS
        text = MENU_LABELS[language]
        self.config.labels["pause_heading"] = text["pause"]
        layout = self.config.data["graphics_settings"]
        layout["labels"] = (self.korean_settings_labels | ENGLISH_SETTINGS
                            if language == "en" else self.korean_settings_labels.copy())
        self.config.buttons["pause"] = tuple(replace(b, label=text[b.action]) for b in self.config.buttons["pause"])
        motion = self.title_menu_motion
        motion.base_buttons = tuple(replace(b, label=text[b.action]) for b in motion.base_buttons)
        for row in motion.settings["submenu_buttons"]:
            row["label"] = text[row["action"]]
        motion.submenu = submenu_buttons(motion.settings)
        self.config.buttons["menu"] = motion.buttons

    def reset_training(self):
        super().reset_training()
        self.dialogue_motion.reset(opened=False)
        self.state = replace(self.state, dialogue=None)

    def pointer(self, event, pico, paused):
        if self.credits_open:
            if ((event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_ESCAPE)
                    or (event.type == pico.SDL_MOUSEBUTTONUP and event.button == pico.SDL_BUTTON_LEFT)):
                self.credits_open = False
                self.inputs.reset()
            return None
        title_input = self.scene == "menu" and not self.graphics_settings.opened
        previous_hover = self.inputs.hovered_id
        action = super().pointer(event, pico, paused)
        if action == "settings_saved":
            self.apply_language(self.graphics_settings.saved.language)
        if title_input and action:
            self.entry_sound_pending = action in ("new_game", "continue", "load")
        if title_input and self.menu_audio:
            if event.type == pico.SDL_MOUSEMOTION and self.inputs.hovered_id and self.inputs.hovered_id != previous_hover:
                self.menu_audio.play("btn_hover")
            if event.type == pico.SDL_MOUSEBUTTONUP and action:
                self.menu_audio.play("btn_click")
        if action == "credits":
            self.credits_open = True
            self.inputs.reset()
            return None
        return action


class GameApplication(EncounterApplication):
    hud_type = GameHud
    debug_controls = False
    reload_on_exit = False

    def create_loading_screen(self, pico, settings):
        if self.skip_splash:
            return None
        from .splash import GameSplash
        return GameSplash(pico, self.window_size)

    def __init__(self, **options):
        super().__init__(TRAINING_MOVEMENT_CONFIG,
                         encounter_path=GAME_DIRECTORY / "training_encounter.json", **options)
        self.config["hud"]["preset"] = str(GAME_DIRECTORY / "player_hud.json")
        self.grid = False
        self.title_background = TitleBackground()
        self.title_music = TitleMusic()
        self.exit_fade_started = False
        self.skip_splash = False

    def on_reload(self):
        self.skip_splash = True

    def _enter_resources(self):
        self._enter_ui_resources()
        if not self.mute:
            from ferrial_drive.audio.effects import SoundEffects
            self.hud.menu_audio = SoundEffects(GAME_DIRECTORY / "title_sound_bank.json",
                GAME_DIRECTORY.parent / "data/source/audio/sources/UI_SE",
                volume=self.effects_volume(self.game_settings), channels=8, warn_missing_files=False)
        self.draw_scene()

    def _fade_to_black(self, draw_frame, renderer):
        self.exit_fade_started = True
        screen = Rect(0, 0, *self.window_size)
        start = perf_counter()
        while True:
            for _ in poll_events(self.pico):
                pass
            opacity = smooth_step((perf_counter() - start) / EXIT_FADE_SECONDS)
            if opacity < 1:
                draw_frame()
                renderer.rect(screen, "#000000", opacity)
            else:
                renderer.clear("#000000")
            self.pico.SDL_RenderPresent(self.pico.renderer)
            if opacity >= 1:
                return
            sleep(1 / 60)

    def loading_progress(self, progress, label):
        try:
            super().loading_progress(progress, label)
        except LoadingCancelled:
            self._fade_to_black(self.loading.draw_last, self.loading.renderer)
            raise

    def exit(self):
        try:
            if not self.reload_on_exit:
                if self.combat_collection:
                    self.combat_collection.make_screen = None
                if not self.running and not self.exit_fade_started and self.renderer:
                    self._fade_to_black(self.draw, self.renderer)
        finally:
            try:
                self.title_music.close()
                if self.hud and self.hud.menu_audio:
                    self.hud.menu_audio.close()
                if self.title_background.shade:
                    self.title_background.close(self.pico)
            finally:
                super().exit()

    def _prepare_encounter(self):
        if self.encounter_view is not None:
            return
        self.title_music.close()
        self.loading = super().create_loading_screen(self.pico, self.config["loading"])
        try:
            self.loading_progress(0, "교전 준비")
            super()._enter_resources()
            self.encounter_view.show_test_status = False
        except LoadingCancelled:
            self.running = False
        finally:
            self.loading.close()
            self.loading = None

    def update(self, delta_seconds):
        if self.hud.menu_audio:
            self.hud.menu_audio.set_volume(self.effects_volume(self.game_settings))
            self.hud.menu_audio.update(delta_seconds)
        if self.hud.scene == "combat" and self.encounter_view is not None and self.hud.entry_sound_pending:
            if self.hud.menu_audio:
                self.hud.menu_audio.play("start")
            self.hud.entry_sound_pending = False
        if self.hud.scene == "menu":
            if self.title_background.elapsed == 0 and self.hud.menu_audio:
                self.title_music.start(self.hud.menu_audio.mixer)
            hovered = None if self.hud.graphics_settings.opened or self.hud.credits_open else self.hud.inputs.hovered_id
            button = next((b for b in self.hud.config.buttons["menu"] if b.button_id == hovered), None) if hovered else None
            self.title_background.update(min(delta_seconds, .1), button)
        if self.encounter_view is None:
            self.hud.update(self.controller, min(delta_seconds, 0.1), paused=False, interpolation=False)
            return
        super().update(delta_seconds)

    def draw(self):
        if self.encounter_view is None:
            self.draw_scene()
            return
        super().draw()

    def perform_hud_action(self, action):
        if action != "new_game":
            return super().perform_hud_action(action)
        self._prepare_encounter()
        if not self.running:
            return
        self.reset()
        self.paused = False
        self.hud.scene = "combat"
        self.hud.entry_sound_pending = True

    def handle_event(self, event):
        was_in_combat = self.hud.scene == "combat"
        super().handle_event(event)
        if self.hud.scene == "combat" and self.encounter_view is None and self.running:
            self._prepare_encounter()
        if self.combat_collection and was_in_combat and self.hud.scene == "menu":
            self.combat_collection.make_screen = None
            self.reload_on_exit = True
            self.running = False

    def draw_scene(self, *, preview_due=False):
        if self.hud.scene == "menu" and not self.hud.transition.active:
            w, h = self.window_size
            self.title_background.draw(self.hud.view, w, h)
            if self.hud.credits_open:
                self.renderer.rect(Rect(0, 0, w, h), "#121419", .87)
                self.renderer.text("CREDIT", w / 2, h * .35, "title_menu", "#FFFFFF", align="center")
                self.renderer.text("Atlas — Prismatic Tone", w / 2, h * .49, "title_menu", "#FFFFFF", align="center")
                self.renderer.text("UI Sound Effects — OtoLogic", w / 2, h * .56, "title_version", "#FFFFFF", align="center")
                back = "Click or press Esc to return" if self.game_settings.language == "en" else "클릭 또는 Esc로 돌아가기"
                self.renderer.text(back, w / 2, h * .64,
                                   "title_version", "#C4CCD0", align="center")
            else:
                self.hud.draw(self.mouse, None)
            self.title_background.draw_overlay(self.hud.view, w, h)
            return 0, 0, None
        return super().draw_scene(preview_due=preview_due)
