"""ui-unit-test-v2

사용자 도안의 전투 배치·게이지·흡수 Trail을 샘플 상태로 확인한다.
샘플 상태와 타이틀·일시정지 흐름을 확인한다.
"""

from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ferrial_drive.ui.components import ButtonInput, Rect
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.counter import RollingCounter
from ferrial_drive.ui.damage import DamageNumbers
from ferrial_drive.ui.health import HealthTrail
from ferrial_drive.ui.pause import PauseState
from ferrial_drive.ui.state import Health, HudState, LoadoutInfo, RadarContact, TargetInfo, WeaponInfo
from ferrial_drive.ui.transition import SceneTransition
from ferrial_drive.ui_v2.effects import EnergyAbsorption
from ferrial_drive.ui_v2.geometry import resource_geometry, scaled_point
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
from ferrial_drive.ui_v2.state import HudV2State
from ferrial_drive.ui_v2.view import UiV2View


UNIT_TEST_ENTRYPOINT = "standalone"
SAMPLE_DIRECTORY = PROJECT_ROOT / "samples/ui_unit_test_v2"


class UiUnitTestV2:
    def __init__(self, config_path=None, *, initial_scene=None, capture_path=None):
        self.config = UiConfig(Path(config_path) if config_path else SAMPLE_DIRECTORY / "ui_config.json")
        self.preset = json.loads((SAMPLE_DIRECTORY / "hud_sample.json").read_text(encoding="utf-8"))
        self.running = True
        self.pico = self.renderer = self.view = None
        self.inputs = ButtonInput()
        self.mouse = None
        self.capture_path = Path(capture_path) if capture_path else None
        self.help_visible = False
        self.transition = SceneTransition("menu", "combat", initial_scene or self.config.window["initial_scene"],
                                          self.config.data["animation"]["duration_seconds"], 0)
        self.pause = PauseState(self.config.data["pause"]["duration_seconds"])
        self.absorption = EnergyAbsorption(self.config.data["v2"]["absorption_duration_seconds"])
        self.reset()

    def reset(self):
        data = self.preset
        self.saved_target = TargetInfo(data["target"]["name"], Health(**data["target"]["health"]))
        loadouts = tuple(LoadoutInfo(WeaponInfo(**entry["melee"]), WeaponInfo(**entry["ranged"]))
                         for entry in data["loadouts"])
        hud = HudState(Health(**data["player_health"]), self.saved_target, data["combo_count"],
                       data["total_damage_dealt"], tuple(RadarContact(**entry) for entry in data["radar_contacts"]),
                       loadouts=loadouts, active_loadout_index=data["active_loadout_index"],
                       active_weapon_kind=data["active_weapon_kind"])
        self.state = HudV2State(hud, data["energy_ratio"], data["energy_level"],
                                data["overdrive"], data["counter"], data["dash_ready"])
        self.target_size_index = 0
        self.set_target_size(1)
        duration = self.config.data["damage_counter"]["duration_seconds"]
        self.hit_counter = RollingCounter(duration, hud.combo_count)
        self.damage_counter = RollingCounter(duration, hud.total_damage_dealt)
        duration = self.config.data["health_trail"]["duration_seconds"]
        self.player_health = HealthTrail(duration, hud.player_health.ratio)
        self.target_health = HealthTrail(duration, hud.target.health.ratio)
        animation = self.config.data["animation"]
        self.damage_numbers = DamageNumbers(animation["damage_duration_seconds"],
                                            animation["damage_scatter_x_pixels"],
                                            animation["damage_scatter_y_pixels"],
                                            measure_text=self.damage_text_size,
                                            **self.config.data["damage_popup"])
        self.absorption.clear()

    def damage_text_size(self, text):
        if self.renderer is not None:
            return self.renderer.text_size(text, "damage_number")
        size = self.config.font_sizes["damage_number"]
        return len(text) * size, size

    def set_target_size(self, amount):
        width, height = self.preset["target_body_size_pixels"]
        width, height = width * amount, height * amount
        x, y = self.config.actor_anchor("target")
        body = Rect(x - width / 2, y - 12 * amount, width, height)
        self.state = replace(self.state, target_body=body)

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.renderer = PicoV2Renderer(self.config.font_paths, self.config.font_sizes)
        self.view = UiV2View(self.config, self.renderer)

    def set_hud(self, **changes):
        self.state = replace(self.state, hud=replace(self.state.hud, **changes))

    def absorb(self):
        layout = self.config.data["v2"]["layout"]
        geometry = resource_geometry(layout, self.config.data["v2"]["style"]["level_curve_radius_pixels"])
        icon, destination = geometry.icon_center, geometry.energy_tip(self.state.energy_ratio)
        scale = self.config.data["v2"]["style"]["hud_scale"]
        anchor = (self.config.window["width"] / 2, self.config.window["height"])
        icon = scaled_point(icon, anchor, scale)
        destination = scaled_point(destination, anchor, scale)
        start = self.config.actor_anchor("target")
        for offset in (-15, 0, 15):
            self.absorption.add((start[0] + offset, start[1] - offset), icon, destination)

    def perform(self, action):
        hud = self.state.hud
        if action == "quit":
            self.running = False
        elif action in ("show_hud", "show_menu"):
            self.pause.reset()
            self.inputs.reset()
            self.transition.request("combat" if action == "show_hud" else "menu")
        elif action == "resume":
            self.inputs.reset()
            self.pause.request(False)
        elif action == "reset":
            self.reset()
        elif action in ("damage_target", "damage_player"):
            target = action == "damage_target"
            if target and hud.target is None:
                return
            health = hud.target.health if target else hud.player_health
            applied = min(self.config.data["sample_actions"][action], health.current)
            if applied <= 0:
                return
            health = replace(health, current=health.current - applied)
            if target:
                self.saved_target = replace(hud.target, health=health)
                self.set_hud(target=self.saved_target, combo_count=hud.combo_count + 1,
                             total_damage_dealt=hud.total_damage_dealt + int(applied))
                self.target_health.set_ratio(health.ratio)
                self.hit_counter.set_value(self.state.hud.combo_count)
                self.damage_counter.set_value(self.state.hud.total_damage_dealt)
            else:
                self.set_hud(player_health=health)
                self.player_health.set_ratio(health.ratio)
            owner = "target" if target else "player"
            self.damage_numbers.add(owner, int(applied), *self.config.actor_anchor(owner),
                                    direction=(1, 0) if target else None)
        elif action == "toggle_target":
            target = self.saved_target if hud.target is None else None
            self.set_hud(target=target)
            self.target_health.reset(target.health.ratio if target else 0)
            self.damage_numbers.clear("target")
        elif action == "next_target":
            # 표시 확인용 고정 표적 교체다. 본편의 거리·각도 획득 규칙과 구분한다.
            names = self.preset["target_names"]
            current = hud.target.name if hud.target else self.saved_target.name
            name = names[(names.index(current) + 1) % len(names)]
            self.saved_target = replace(self.saved_target, name=name)
            self.set_hud(target=self.saved_target)
            self.target_health.reset(self.saved_target.health.ratio)
            self.damage_numbers.clear("target")
        elif action in ("energy_up", "energy_down"):
            change = 0.1 if action == "energy_up" else -0.1
            self.state = replace(self.state, energy_ratio=round(max(0, min(1, self.state.energy_ratio + change)), 3))
            if change > 0:
                self.absorb()
        elif action == "absorb":
            self.absorb()
        elif action == "level":
            self.state = replace(self.state, energy_level=self.state.energy_level % 3 + 1)
        elif action == "target_size":
            sizes = (1, 1.5, 0.75)
            self.target_size_index = (self.target_size_index + 1) % len(sizes)
            self.set_target_size(sizes[self.target_size_index])
        elif action in ("overdrive", "counter", "dash"):
            field = {"overdrive": "overdrive", "counter": "counter", "dash": "dash_ready"}[action]
            self.state = replace(self.state, **{field: not getattr(self.state, field)})
        elif action == "swap":
            self.set_hud(active_weapon_kind="melee" if hud.active_weapon_kind == "ranged" else "ranged")
        elif action == "loadout":
            self.set_hud(active_loadout_index=(hud.active_loadout_index + 1) % len(hud.loadouts))
        else:
            raise ValueError(f"v2 샘플 동작 없음: {action}")

    def handle_event(self, event):
        p = self.pico
        if event.type == p.SDL_WINDOWEVENT:
            if event.window_event in (p.SDL_WINDOWEVENT_LEAVE, p.SDL_WINDOWEVENT_FOCUS_LOST):
                self.mouse = None
                self.inputs.reset()
            return
        if event.type == p.SDL_KEYDOWN and not getattr(event, "repeat", False):
            if event.key == p.SDLK_F1:
                self.help_visible = not self.help_visible
                return
            if self.transition.active or self.pause.transitioning:
                return
            if event.key == p.SDLK_ESCAPE:
                if self.transition.target == "combat":
                    self.inputs.reset()
                    self.pause.request(not self.pause.opened)
                return
            if self.pause.blocking or self.transition.target != "combat":
                return
            actions = {p.SDLK_1: "damage_target", p.SDLK_2: "damage_player",
                       p.SDLK_3: "energy_down", p.SDLK_4: "energy_up", p.SDLK_5: "level",
                       p.SDLK_6: "overdrive", p.SDLK_7: "target_size", p.SDLK_c: "counter", p.SDLK_t: "toggle_target",
                       p.SDLK_e: "swap", p.SDLK_f: "loadout", p.SDLK_r: "next_target", p.SDLK_F5: "reset",
                       p.SDLK_g: "absorb", p.SDLK_SPACE: "dash"}
            if event.key in actions:
                self.perform(actions[event.key])
            return
        pointer = event.type in (p.SDL_MOUSEMOTION, p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP)
        if not pointer:
            return
        self.mouse = (event.x, event.y)
        if self.transition.active or self.pause.transitioning:
            return
        scene = "pause" if self.pause.opened else self.transition.target
        if scene == "combat" or (event.type != p.SDL_MOUSEMOTION and event.button != p.SDL_BUTTON_LEFT):
            return
        kind = "move" if event.type == p.SDL_MOUSEMOTION else (
            "down" if event.type == p.SDL_MOUSEBUTTONDOWN else "up")
        result = self.inputs.handle(kind, *self.mouse, self.config.buttons[scene])
        if result.action:
            self.perform(result.action)

    def update(self, delta_seconds):
        if self.pause.blocking:
            self.pause.update(delta_seconds)
            return
        self.transition.update(delta_seconds)
        self.hit_counter.update(delta_seconds)
        self.damage_counter.update(delta_seconds)
        self.player_health.update(delta_seconds)
        self.target_health.update(delta_seconds)
        self.damage_numbers.update(delta_seconds)
        self.absorption.update(delta_seconds)

    def actor(self, owner, opacity):
        r, c = self.renderer, self.config.colors
        x, y = self.config.actor_anchor(owner)
        sx = sy = 1
        if owner == "target" and self.state.target_body is not None:
            body = self.state.target_body
            sx, sy = body.width / 30, body.height / 27
            x, y = body.x + body.width / 2, body.y + 12 * sy
        color = c["accent" if owner == "player" else "enemy"]
        for dx, dy, width, height in ((-8, -27, 16, 13), (-15, -12, 30, 27),
                                       (-26, -8, 8, 24), (18, -8, 8, 24),
                                       (-13, 18, 9, 19), (4, 18, 9, 19)):
            r.rect(Rect(x + dx * sx, y + dy * sy, width * sx, height * sy), color, opacity * 0.7)

    def draw(self):
        self.view.background()
        for scene in ("menu", "combat"):
            pose = self.transition.pose(scene)
            if pose.opacity <= 0:
                continue
            if scene == "menu":
                self.view.menu(pose.opacity, 0, self.inputs)
            else:
                self.actor("player", pose.opacity)
                if self.state.hud.target is not None:
                    self.actor("target", pose.opacity)
                self.view.combat(self.state, self.damage_numbers.visuals, pose.opacity,
                                 counter_visual=self.damage_counter.visual,
                                 combo_visual=self.hit_counter.visual, cursor_position=self.mouse,
                                 player_trailing_ratio=self.player_health.trailing_ratio,
                                 target_trailing_ratio=self.target_health.trailing_ratio,
                                 absorption_trails=self.absorption.trails)
        if self.pause.opacity > 0:
            self.view.pause(self.pause.opacity, self.inputs)
        if self.help_visible:
            self.draw_help()
        if self.capture_path:
            self.renderer.save_frame(self.capture_path, self.config.window["width"], self.config.window["height"])
            self.capture_path = None

    def draw_help(self):
        self.view.panel((262, 32, 655, 134), 1, fill_opacity=0.98)
        for index, text in enumerate(("1 / 2 적·플레이어 피해   3 / 4 에너지   5 레벨   6 Overdrive   7 표적 크기",
                                      "E 무기 교체   F 로드아웃   T 타겟   C COUNTER   SPACE 대시 표시",
                                      "G 흡수 Trail   R 샘플 표적 교체   F5 초기화   Esc 일시정지   F1 도움말 닫기")):
            self.renderer.text(text, 290, 48 + index * 36, "small", self.config.colors["text"])

    def exit(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.view = None


def create_test(**kwargs):
    return UiUnitTestV2(**kwargs)


if __name__ == "__main__":
    import argparse
    from ferrial_drive.runtime import run_application

    parser = argparse.ArgumentParser(description="ui-concept-v2 기반 독립 UI 테스트")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--scene", choices=("menu", "combat"))
    parser.add_argument("--frames", type=int)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    program = create_test(config_path=args.config, initial_scene=args.scene, capture_path=args.capture)
    run_application(program, width=program.config.window["width"], height=program.config.window["height"],
                    title="Ferrial Drive | ui-unit-test-v2", frame_limit=args.frames)
