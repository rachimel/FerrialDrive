"""장치 입력·전투 규칙·공통 UI를 연결하는 재사용 전투 장면."""

from pathlib import Path

from ..diagnostics import TimingRecorder
from ..ui.config import UiConfig
from ..ui.counter import CounterVisibility, RollingCounter
from ..ui.damage import DamageNumbers
from ..ui.health import HealthTrail
from ..ui.pico_renderer import PicoRenderer
from ..ui.weapon_swap import WeaponSwap
from .config import load_scenario
from .simulation import CombatInput, CombatWorld, Vec2
from .view import CombatView


class CombatApplication:
    def __init__(self, scenario_path, ui_config_path, *, profile_path=None):
        config, arena, self.style = load_scenario(scenario_path)
        self.world = CombatWorld(config, arena)
        self.ui_config_path = Path(ui_config_path)
        self.profile_path = Path(profile_path) if profile_path else None
        self.timings = TimingRecorder(enabled=self.profile_path is not None, session="combat_prototype")
        self.running = True
        self.paused = True
        self.started = False
        self.renderer = self.view = self.pico = None
        self.keys, self.buttons = set(), set()
        self.attack_pressed = self.dash_pressed = self.swap_pressed = False
        self.mouse = (800, 360)
        if self.timings.enabled:
            self.world.advance = self.timings.wrap(self.world.advance, name="combat.simulation")
            self.draw = self.timings.wrap(self.draw, name="combat.draw")

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.ui_config = UiConfig(self.ui_config_path)
        self.ui_config.labels["combat_heading"] = "교전 훈련"
        self.renderer = PicoRenderer(self.ui_config.font_paths, self.ui_config.font_sizes)
        self.view = CombatView(self.ui_config, self.renderer, self.style)
        self.mouse = self.view.project(self.world.enemy.position, self.world.player.position)
        animation = self.ui_config.data["animation"]
        self.damage_numbers = DamageNumbers(
            animation["damage_duration_seconds"], animation["damage_scatter_x_pixels"],
            animation["damage_scatter_y_pixels"],
            measure_text=lambda text: self.renderer.text_size(text, "damage_number"),
            **self.ui_config.data["damage_popup"],
            width_expand_seconds=animation["damage_width_expand_seconds"],
            height_expand_seconds=animation["damage_height_expand_seconds"])
        self.weapon_swap = WeaponSwap(self.world.weapon_kind, self.ui_config.data["weapon_swap"]["duration_seconds"])
        duration = self.ui_config.data["health_trail"]["duration_seconds"]
        self.health_trails = (HealthTrail(duration, 1), HealthTrail(duration, 1))
        counter = self.ui_config.data["damage_counter"]
        options = {key: counter[key] for key in ("vertical_easing", "elastic_strength", "elastic_period")}
        self.damage_counter = RollingCounter(counter["duration_seconds"], **options)
        self.hit_counter = RollingCounter(counter["duration_seconds"], **options)
        self.counter_visibility = CounterVisibility(**self.ui_config.data["counter_visibility"])
        pico.SDL_ShowCursor(pico.SDL_DISABLE)

    def clear_input(self):
        self.keys.clear()
        self.buttons.clear()
        self.attack_pressed = self.dash_pressed = self.swap_pressed = False
        self.world.pending_attack = self.world.pending_dash = self.world.pending_swap = False

    def handle_event(self, event):
        p = self.pico
        if event.type == p.SDL_WINDOWEVENT:
            if event.window_event == p.SDL_WINDOWEVENT_CLOSE:
                self.running = False
            elif event.window_event == p.SDL_WINDOWEVENT_FOCUS_LOST:
                self.paused = True
                self.clear_input()
        elif event.type in (p.SDL_KEYDOWN, p.SDL_KEYUP):
            if event.type == p.SDL_KEYUP:
                self.keys.discard(event.key)
                return
            if getattr(event, "repeat", False) or event.key in self.keys:
                return
            self.keys.add(event.key)
            if event.key == p.SDLK_F10:
                self.running = False
            elif event.key == p.SDLK_r:
                self.restart()
            elif event.key in (p.SDLK_ESCAPE, p.SDLK_RETURN):
                self.paused = not self.paused
                self.started = True
                self.clear_input()
            elif not self.paused and self.world.result == "running":
                self.dash_pressed |= event.key == p.SDLK_SPACE
                self.swap_pressed |= event.key == p.SDLK_e
        elif event.type in (p.SDL_MOUSEMOTION, p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP):
            self.mouse = (event.x, event.y)
            if event.type == p.SDL_MOUSEBUTTONUP:
                self.buttons.discard(event.button)
            elif event.type == p.SDL_MOUSEBUTTONDOWN and not self.paused:
                self.buttons.add(event.button)
                self.attack_pressed |= event.button == p.SDL_BUTTON_LEFT

    def update(self, delta_seconds):
        if self.paused:
            return
        p = self.pico
        direction = Vec2(int(p.SDLK_d in self.keys) - int(p.SDLK_a in self.keys),
                         int(p.SDLK_w in self.keys) - int(p.SDLK_s in self.keys))
        command = CombatInput(direction, self.view.aim_direction(self.mouse),
                              bool({p.SDLK_LSHIFT, p.SDLK_RSHIFT} & self.keys),
                              p.SDL_BUTTON_LEFT in self.buttons, p.SDL_BUTTON_RIGHT in self.buttons,
                              self.attack_pressed, self.dash_pressed, self.swap_pressed)
        events = self.world.advance(delta_seconds, command)
        self.attack_pressed = self.dash_pressed = self.swap_pressed = False
        for event in events:
            self.damage_numbers.add(event.owner, event.amount, event.position.x,
                                    -event.position.y * self.view.scale_y - self.style["mech_height_pixels"],
                                    direction=(event.direction.x, -event.direction.y * self.view.scale_y))
            if event.owner == "enemy":
                self.counter_visibility.show()
        self.weapon_swap.request(self.world.weapon_kind)
        self.weapon_swap.update(delta_seconds)
        for actor, trail in zip((self.world.player, self.world.enemy), self.health_trails):
            trail.set_ratio(actor.health / actor.maximum_health)
            trail.update(delta_seconds)
        self.damage_counter.set_value(self.world.total_damage)
        self.hit_counter.set_value(self.world.hit_count)
        self.damage_counter.update(delta_seconds)
        self.hit_counter.update(delta_seconds)
        self.damage_numbers.update(delta_seconds)
        if self.counter_visibility.update(delta_seconds):
            self.world.reset_counters()
            self.damage_counter.reset()
            self.hit_counter.reset()

    def draw(self):
        self.view.draw(self.world, self.mouse, self.damage_numbers.visuals, self.weapon_swap,
                       self.health_trails, (self.damage_counter, self.hit_counter, self.counter_visibility),
                       paused=self.paused, started=self.started)

    def restart(self):
        self.world.reset()
        self.clear_input()
        self.weapon_swap.reset(self.world.weapon_kind)
        self.damage_numbers.clear()
        self.damage_counter.reset()
        self.hit_counter.reset()
        self.counter_visibility.hide()
        for trail in self.health_trails:
            trail.reset(1)
        self.started, self.paused = True, False

    def exit(self):
        if self.pico is not None:
            self.pico.SDL_ShowCursor(self.pico.SDL_ENABLE)
        if self.renderer is not None:
            self.renderer.close()
        if self.profile_path is not None:
            self.timings.write_json(self.profile_path)
