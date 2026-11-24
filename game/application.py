"""본편 타이틀과 첫 훈련 교전을 FDrive에 연결한다."""

from dataclasses import replace
from pathlib import Path

from ferrial_drive.combat.encounter_application import EncounterApplication
from ferrial_drive.continuation import ContinueSession
from ferrial_drive.ui_v2.movement_hud import MovementHud
from ferrial_drive.ui_v2.title_menu import submenu_buttons


GAME_DIRECTORY = Path(__file__).resolve().parent
TRAINING_MOVEMENT_CONFIG = GAME_DIRECTORY.parent / "samples/sword_movement/movement_config.json"


class GameHud(MovementHud):
    def __init__(self, config_path, preset_path, **options):
        super().__init__(config_path, preset_path, initial_scene="menu",
                         continuation=ContinueSession(mode="game"), **options)
        title = self.config.data["title_menu"]
        for row in title["submenu_buttons"]:
            if row["action"] == "new_game":
                row["enabled"] = True
        self.title_menu_motion.submenu = submenu_buttons(title)
        self.config.buttons["pause"] = tuple(
            replace(button, label="게임 종료") if button.action == "quit" else button
            for button in self.config.buttons["pause"])

    def reset_training(self):
        super().reset_training()
        self.dialogue_motion.reset(opened=False)
        self.state = replace(self.state, dialogue=None)


class GameApplication(EncounterApplication):
    hud_type = GameHud
    debug_controls = False
    reload_on_exit = False

    def create_loading_screen(self, pico, settings):
        from .splash import GameSplash
        return GameSplash(pico, self.window_size)

    def __init__(self, **options):
        super().__init__(TRAINING_MOVEMENT_CONFIG,
                         encounter_path=GAME_DIRECTORY / "training_encounter.json", **options)
        self.config["hud"]["preset"] = str(GAME_DIRECTORY / "player_hud.json")
        self.grid = False

    def _enter_resources(self):
        self._enter_ui_resources()
        self.draw_scene()

    def _prepare_encounter(self):
        if self.encounter_view is not None:
            return
        from ferrial_drive.ui.loading import LoadingCancelled
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

    def handle_event(self, event):
        was_in_combat = self.hud.scene == "combat"
        super().handle_event(event)
        if self.hud.scene == "combat" and self.encounter_view is None and self.running:
            self._prepare_encounter()
        if self.combat_collection and was_in_combat and self.hud.scene == "menu":
            self.reload_on_exit = True
            self.running = False

    def draw_scene(self, *, preview_due=False):
        if self.hud.scene == "menu" and not self.hud.transition.active:
            self.hud.view.background()
            self.hud.draw(self.mouse, None)
            return 0, 0, None
        return super().draw_scene(preview_due=preview_due)
