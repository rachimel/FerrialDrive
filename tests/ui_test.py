"""메뉴·전투 HUD를 직접 확인하는 테스트. 공통 실행기의 GUI 창에 드롭한다."""

from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "Tools"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from ferrial_drive.ui.components import ButtonInput, InputResult
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.damage import DamageNumbers
from ferrial_drive.ui.pico_renderer import PicoRenderer
from ferrial_drive.ui.state import Health, HudState, RadarContact, TargetInfo
from ferrial_drive.ui.transition import SceneTransition
from ferrial_drive.ui.view import UiView
from unit_test_runner import Stop, TestProgram, WindowSpec


CONFIG_PATH = PROJECT_ROOT / "samples/ui_unit_test/ui_config.json"
SAMPLE_PATH = PROJECT_ROOT / "samples/ui_unit_test/hud_sample.json"
_WINDOW = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["window"]
WINDOW = WindowSpec(_WINDOW["width"], _WINDOW["height"], "Ferrial Drive | UI Unit Test")


class SampleHud:
    """버튼으로 바꾸는 가짜 상태. 실제 게임의 피해·콤보 규칙이 아니다."""

    def __init__(self, path):
        self.preset = json.loads(path.read_text(encoding="utf-8"))
        self.reset()

    def reset(self):
        data = self.preset
        target = data["target"]
        self.saved_target = (TargetInfo(target["name"], Health(**target["health"]))
                             if target is not None else None)
        self.state = HudState(Health(**data["player_health"]), self.saved_target,
                              data["combo_count"], data["total_damage_dealt"],
                              tuple(RadarContact(**entry) for entry in data["radar_contacts"]))

    def damage_player(self, amount):
        applied = min(amount, self.state.player_health.current)
        health = replace(self.state.player_health, current=self.state.player_health.current - applied)
        self.state = replace(self.state, player_health=health)
        return int(applied)

    def damage_target(self, amount):
        target = self.state.target
        if target is None:
            return 0
        applied = min(amount, target.health.current)
        if applied <= 0:
            return 0
        target = replace(target, health=replace(target.health, current=target.health.current - applied))
        self.saved_target = target
        self.state = replace(self.state, target=target, combo_count=self.state.combo_count + 1,
                              total_damage_dealt=self.state.total_damage_dealt + int(applied))
        return int(applied)

    def toggle_target(self):
        if self.state.target is not None:
            self.saved_target = self.state.target
            self.state = replace(self.state, target=None)
        else:
            self.state = replace(self.state, target=self.saved_target)


class UiTest(TestProgram):
    def __init__(self):
        self.config = UiConfig(CONFIG_PATH)
        self.sample = SampleHud(SAMPLE_PATH)
        animation = self.config.data["animation"]
        if animation["transition_input_policy"] != "consume_until_finished":
            raise ValueError("현재 UI 테스트의 전환 입력 정책은 consume_until_finished다.")
        self.transition = SceneTransition("menu", "combat", self.config.window["initial_scene"],
                                          animation["duration_seconds"], animation["slide_pixels"])
        self.damage_numbers = DamageNumbers(animation["damage_duration_seconds"],
                                            animation["damage_rise_pixels"])
        self.inputs = ButtonInput()
        self.last_input = InputResult()
        self.mouse = (-1, -1)
        self.renderer = None
        self.view = None
        self.pico = None

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.renderer = PicoRenderer(self.config.font_paths, self.config.font_sizes)
        self.view = UiView(self.config, self.renderer)

    def current_buttons(self, scene):
        buttons = self.config.buttons[scene]
        if scene != "combat":
            return buttons
        state = self.sample.state
        enabled = {
            "damage_target": state.target is not None and state.target.health.current > 0,
            "damage_player": state.player_health.current > 0,
        }
        return tuple(replace(button, enabled=enabled.get(button.action, True)) for button in buttons)

    def change_scene(self, scene):
        self.inputs.reset()
        self.transition.request(scene)

    def handle_event(self, event):
        pico = self.pico
        self.last_input = InputResult()
        pointer = event.type in (pico.SDL_MOUSEMOTION, pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP)
        if pointer:
            self.mouse = (event.x, event.y)
        escape = event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_ESCAPE
        left_click = (event.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP)
                      and event.button == pico.SDL_BUTTON_LEFT)
        if self.transition.active:
            if escape or left_click:
                self.last_input = InputResult(consumed=True)
            return None
        if escape:
            scene = "combat" if self.transition.target == "menu" else "menu"
            self.change_scene(scene)
            self.last_input = InputResult(consumed=True, action="change_scene")
            return None
        if not (event.type == pico.SDL_MOUSEMOTION or left_click):
            return None
        kind = "move" if event.type == pico.SDL_MOUSEMOTION else (
            "down" if event.type == pico.SDL_MOUSEBUTTONDOWN else "up")
        scene = self.transition.target
        pose = self.transition.pose(scene)
        self.last_input = self.inputs.handle(kind, *self.mouse, self.current_buttons(scene), pose.offset_x)
        if self.last_input.action is not None:
            return self.perform(self.last_input.action)
        return None

    def perform(self, action):
        if action == "quit":
            return Stop()
        if action == "show_hud":
            self.change_scene("combat")
        elif action == "reset":
            self.sample.reset()
            self.damage_numbers.clear()
        elif action == "toggle_target":
            self.sample.toggle_target()
            self.damage_numbers.clear("target")
        elif action in ("damage_target", "damage_player"):
            amount = self.config.data["sample_actions"][action]
            if not isinstance(amount, int) or amount < 0:
                raise ValueError("샘플 피해량은 0 이상의 정수여야 한다.")
            owner = "target" if action == "damage_target" else "player"
            applied = self.sample.damage_target(amount) if owner == "target" else self.sample.damage_player(amount)
            x, y = self.config.layout[f"{owner}_anchor"]
            self.damage_numbers.add(owner, applied, x, y + self.config.layout["popup_offset_y"])
        else:
            raise ValueError(f"UI 동작 없음: {action}")
        return None

    def update(self, delta_seconds):
        self.transition.update(delta_seconds)
        self.damage_numbers.update(delta_seconds)
        if not self.transition.active:
            scene = self.transition.target
            pose = self.transition.pose(scene)
            self.inputs.handle("move", *self.mouse, self.current_buttons(scene), pose.offset_x)

    def draw(self):
        self.view.background()
        self.view.header()
        for scene in ("menu", "combat"):
            pose = self.transition.pose(scene)
            if pose.opacity <= 0:
                continue
            if scene == "menu":
                self.view.menu(pose.opacity, pose.offset_x, self.inputs)
            else:
                self.view.combat(self.sample.state, self.damage_numbers.visuals,
                                 pose.opacity, pose.offset_x, self.inputs,
                                 self.current_buttons("combat"))
        self.view.footer(self.transition.target, self.transition.active)

    def exit(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.view = None


def create_test():
    return UiTest()


if __name__ == "__main__":
    from unit_test_runner import run

    run(create_test(), WINDOW)
