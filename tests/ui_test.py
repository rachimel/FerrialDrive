"""Runner 없이 직접 실행하는 메뉴·전투 HUD 미리보기."""

from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ferrial_drive.ui.components import ButtonInput, InputResult, Rect
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.counter import CounterVisibility, RollingCounter
from ferrial_drive.ui.damage import DamageNumbers
from ferrial_drive.ui.health import HealthTrail
from ferrial_drive.ui.pause import PauseState
from ferrial_drive.ui.pico_renderer import PicoRenderer
from ferrial_drive.ui.state import Health, HudState, RadarContact, TargetInfo
from ferrial_drive.ui.transition import SceneTransition
from ferrial_drive.ui.view import UiView


CONFIG_PATH = PROJECT_ROOT / "samples/ui_unit_test/ui_config.json"
SAMPLE_PATH = PROJECT_ROOT / "samples/ui_unit_test/hud_sample.json"
_WINDOW = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["window"]
UNIT_TEST_ENTRYPOINT = "standalone"
WINDOW = {"width": _WINDOW["width"], "height": _WINDOW["height"],
          "title": "Ferrial Drive | UI Unit Test"}


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
                              tuple(RadarContact(**entry) for entry in data["radar_contacts"]),
                              data["attack_direction_x"])

    def reset_counters(self):
        self.state = replace(self.state, combo_count=0, total_damage_dealt=0)

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


class UiTest:
    def __init__(self):
        self.running = True
        self.config = UiConfig(CONFIG_PATH)
        self.sample = SampleHud(SAMPLE_PATH)
        animation = self.config.data["animation"]
        if animation["transition_input_policy"] != "consume_until_finished":
            raise ValueError("현재 UI 테스트의 전환 입력 정책은 consume_until_finished다.")
        self.transition = SceneTransition("menu", "combat", self.config.window["initial_scene"],
                                          animation["duration_seconds"], animation["slide_pixels"])
        self.pause = PauseState(self.config.data["pause"]["duration_seconds"])
        self.damage_numbers = DamageNumbers(animation["damage_duration_seconds"],
                                            animation["damage_scatter_x_pixels"],
                                            animation["damage_scatter_y_pixels"],
                                            width_expand_seconds=animation["damage_width_expand_seconds"],
                                            height_expand_seconds=animation["damage_height_expand_seconds"])
        counter_config = self.config.data["damage_counter"]
        counter_motion = {key: counter_config[key] for key in
                          ("vertical_easing", "elastic_strength", "elastic_period")}
        self.damage_counter = RollingCounter(counter_config["duration_seconds"],
                                             self.sample.state.total_damage_dealt, **counter_motion)
        self.combo_counter = RollingCounter(counter_config["duration_seconds"],
                                            self.sample.state.combo_count, **counter_motion)
        self.counter_visibility = CounterVisibility(**self.config.data["counter_visibility"])
        health_duration = self.config.data["health_trail"]["duration_seconds"]
        self.player_health_trail = HealthTrail(health_duration, self.sample.state.player_health.ratio)
        self.target_health_trail = HealthTrail(health_duration, self.target_health_ratio())
        self.inputs = ButtonInput()
        self.last_input = InputResult()
        self.mouse = (-1, -1)
        self.crosshair_position = self.config.actor_anchor("player")
        self.renderer = None
        self.view = None
        self.pico = None

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.renderer = PicoRenderer(self.config.font_paths, self.config.font_sizes)
        self.view = UiView(self.config, self.renderer)

    def target_health_ratio(self):
        target = self.sample.state.target
        return target.health.ratio if target is not None else 0.0

    def sync_health_trails(self):
        self.player_health_trail.set_ratio(self.sample.state.player_health.ratio)
        if self.sample.state.target is None:
            self.target_health_trail.reset(0.0)
        else:
            self.target_health_trail.set_ratio(self.target_health_ratio())

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

    def set_paused(self, opened):
        self.inputs.reset()
        self.pause.request(opened)

    def handle_event(self, event):
        pico = self.pico
        self.last_input = InputResult()
        pointer = event.type in (pico.SDL_MOUSEMOTION, pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP)
        if pointer:
            self.mouse = (event.x, event.y)
            if (0 <= event.x < self.config.window["width"]
                    and 0 <= event.y < self.config.window["height"]):
                self.crosshair_position = self.mouse
        escape = event.type == pico.SDL_KEYDOWN and event.key == pico.SDLK_ESCAPE
        left_click = (event.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP)
                      and event.button == pico.SDL_BUTTON_LEFT)
        if self.transition.active or self.pause.transitioning:
            if escape or left_click:
                self.last_input = InputResult(consumed=True)
            return None
        if escape:
            if not getattr(event, "repeat", False):
                if self.pause.opened:
                    self.set_paused(False)
                elif self.transition.target == "combat":
                    self.set_paused(True)
                else:
                    self.change_scene("combat")
            self.last_input = InputResult(consumed=True)
            return None
        if not (event.type == pico.SDL_MOUSEMOTION or left_click):
            return None
        kind = "move" if event.type == pico.SDL_MOUSEMOTION else (
            "down" if event.type == pico.SDL_MOUSEBUTTONDOWN else "up")
        scene = "pause" if self.pause.opened else self.transition.target
        offset_x = 0 if scene == "pause" else self.transition.pose(scene).offset_x
        result = self.inputs.handle(kind, *self.mouse, self.current_buttons(scene), offset_x)
        self.last_input = InputResult(consumed=True, action=result.action) if scene == "pause" else result
        if self.last_input.action is not None:
            return self.perform(self.last_input.action)
        return None

    def perform(self, action):
        if action == "quit":
            self.running = False
            return None
        if action == "show_hud":
            self.change_scene("combat")
        elif action == "resume":
            self.set_paused(False)
        elif action == "show_menu":
            self.pause.reset()
            self.change_scene("menu")
        elif action == "reset":
            self.sample.reset()
            self.damage_numbers.clear()
            self.damage_counter.reset(self.sample.state.total_damage_dealt)
            self.combo_counter.reset(self.sample.state.combo_count)
            self.counter_visibility.hide()
            self.player_health_trail.reset(self.sample.state.player_health.ratio)
            self.target_health_trail.reset(self.target_health_ratio())
        elif action == "toggle_target":
            self.sample.toggle_target()
            self.damage_numbers.clear("target")
            self.target_health_trail.reset(self.target_health_ratio())
        elif action in ("damage_target", "damage_player"):
            amount = self.config.data["sample_actions"][action]
            if not isinstance(amount, int) or amount < 0:
                raise ValueError("샘플 피해량은 0 이상의 정수여야 한다.")
            owner = "target" if action == "damage_target" else "player"
            applied = self.sample.damage_target(amount) if owner == "target" else self.sample.damage_player(amount)
            self.sync_health_trails()
            self.damage_counter.set_value(self.sample.state.total_damage_dealt)
            self.combo_counter.set_value(self.sample.state.combo_count)
            if owner == "target" and applied > 0:
                self.counter_visibility.show()
            x, y = self.config.actor_anchor(owner)
            self.damage_numbers.add(owner, applied, x, y)
        else:
            raise ValueError(f"UI 동작 없음: {action}")
        return None

    def update(self, delta_seconds):
        if self.pause.blocking:
            self.pause.update(delta_seconds)
            if self.pause.opened and not self.pause.transitioning:
                self.inputs.handle("move", *self.mouse, self.current_buttons("pause"))
            # 닫힘이 끝나는 프레임도 전투 시간에 더하지 않는다.
            return
        self.transition.update(delta_seconds)
        self.damage_numbers.update(delta_seconds)
        self.damage_counter.set_value(self.sample.state.total_damage_dealt)
        self.damage_counter.update(delta_seconds)
        self.combo_counter.set_value(self.sample.state.combo_count)
        self.combo_counter.update(delta_seconds)
        if self.counter_visibility.update(delta_seconds):
            self.sample.reset_counters()
            self.damage_counter.reset()
            self.combo_counter.reset()
        self.sync_health_trails()
        self.player_health_trail.update(delta_seconds)
        self.target_health_trail.update(delta_seconds)
        if not self.transition.active:
            scene = self.transition.target
            pose = self.transition.pose(scene)
            self.inputs.handle("move", *self.mouse, self.current_buttons(scene), pose.offset_x)
            mouse_x, mouse_y = self.mouse
            width, height = self.config.window["width"], self.config.window["height"]
            over_button = any(button.rect.translated(pose.offset_x).contains(
                mouse_x, mouse_y, button.hit_padding) for button in self.current_buttons(scene))
            if (scene == "combat" and not over_button
                    and 0 <= mouse_x < width and 0 <= mouse_y < height and mouse_x != width / 2):
                direction = -1 if mouse_x < width / 2 else 1
                self.sample.state = replace(self.sample.state, attack_direction_x=direction)

    def draw_sample_actor(self, anchor, label, color, opacity, offset_x=0):
        """테스트용 기체 도형·이름표는 재사용 HUD에 포함하지 않는다."""
        r, c = self.renderer, self.config.colors
        x, y = anchor
        x += offset_x
        for rect in (Rect(x - 13, y - 46, 26, 17), Rect(x - 22, y - 25, 44, 44),
                     Rect(x - 38, y - 19, 12, 35), Rect(x + 26, y - 19, 12, 35),
                     Rect(x - 20, y + 23, 15, 24), Rect(x + 5, y + 23, 15, 24)):
            r.rect(rect, c["panel"], opacity)
            r.rect(rect, c[color], opacity * 0.8, filled=False)
        r.text(label, x, y + 58, "hud_small", c["muted"], opacity, max_width=180, align="center")

    def draw(self):
        self.view.background()
        for scene in ("menu", "combat"):
            pose = self.transition.pose(scene)
            if pose.opacity <= 0:
                continue
            if scene == "menu":
                self.view.menu(pose.opacity, pose.offset_x, self.inputs)
            else:
                self.draw_sample_actor(self.config.actor_anchor("player"),
                                       self.sample.preset["player_name"], "accent", pose.opacity)
                if self.sample.state.target is not None:
                    self.draw_sample_actor(self.config.actor_anchor("target"), self.sample.state.target.name,
                                           "enemy", pose.opacity, pose.offset_x)
                self.view.combat(self.sample.state, self.damage_numbers.visuals,
                                 pose.opacity, pose.offset_x,
                                 counter_visual=self.damage_counter.visual,
                                 combo_visual=self.combo_counter.visual,
                                 counters_opacity=self.counter_visibility.opacity,
                                 cursor_position=self.crosshair_position,
                                 player_trailing_ratio=self.player_health_trail.trailing_ratio,
                                 target_trailing_ratio=self.target_health_trail.trailing_ratio)
                self.view.buttons("combat", self.inputs, pose.opacity, pose.offset_x,
                                  self.current_buttons("combat"))
        if self.pause.opacity > 0:
            self.view.pause(self.pause.opacity, self.inputs)

    def exit(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.view = None


def create_test():
    return UiTest()


if __name__ == "__main__":
    import argparse
    from ferrial_drive.ui.standalone import run_preview

    parser = argparse.ArgumentParser(description="메뉴·전투 HUD 독립 미리보기")
    parser.add_argument("--frames", type=int, default=None)
    arguments = parser.parse_args()
    run_preview(create_test(), **WINDOW, frame_limit=arguments.frames)
