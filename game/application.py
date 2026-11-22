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

    def __init__(self, **options):
        super().__init__(TRAINING_MOVEMENT_CONFIG,
                         encounter_path=GAME_DIRECTORY / "training_encounter.json", **options)
        self.config["hud"]["preset"] = str(GAME_DIRECTORY / "player_hud.json")
        self.grid = False

    def _enter_resources(self):
        super()._enter_resources()
        self.encounter_view.show_test_status = False

    def perform_hud_action(self, action):
        if action != "new_game":
            return super().perform_hud_action(action)
        self.reset()
        self.paused = False
        self.hud.scene = "combat"

    def draw_scene(self, *, preview_due=False):
        if self.hud.scene == "menu" and not self.hud.transition.active:
            self.hud.view.background()
            self.hud.draw(self.mouse, None)
            return 0, 0, None
        return super().draw_scene(preview_due=preview_due)
