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
from ferrial_drive.combat.targeting import TargetCandidate
from ferrial_drive.combat.mouse_targeting import MouseAutoTargeting
from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.counter import RollingCounter
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui.damage import DamageNumbers
from ferrial_drive.ui.health import HealthTrail
from ferrial_drive.ui.loadout_slide import LoadoutSlide
from ferrial_drive.ui.pause import PauseState
from ferrial_drive.ui.state import Health, HudState, LoadoutInfo, RadarContact, TargetInfo, WeaponInfo
from ferrial_drive.ui.transition import SceneTransition
from ferrial_drive.ui.weapon_swap import WeaponSwap
from ferrial_drive.ui_v2.effects import (DefeatedTargetMotion, DialoguePanelMotion, EnergyAbsorption, EnergyRecoveryFlash, HealthDamageFlash,
                                       HealthHitMotion, IndicatorFade, ScanlineMotion)
from ferrial_drive.ui_v2.lock_on import LockOnMotion
from ferrial_drive.ui_v2.geometry import resource_geometry, scaled_point
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
from ferrial_drive.ui_v2.state import DialogueInfo, HudV2State
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.particles import GpuParticleSystem


UNIT_TEST_ENTRYPOINT = "standalone"
SAMPLE_DIRECTORY = PROJECT_ROOT / "samples/ui_unit_test_v2"


class UiUnitTestV2:
    def __init__(self, config_path=None, *, initial_scene=None, capture_path=None, particle_backend=None):
        self.config = UiConfig(Path(config_path) if config_path else SAMPLE_DIRECTORY / "ui_config.json")
        if particle_backend is not None:
            self.config.data['v2']['style']['absorption_trail']['renderer'] = particle_backend
        self.preset = json.loads((SAMPLE_DIRECTORY / "hud_sample.json").read_text(encoding="utf-8"))
        self.running = True
        self.pico = self.renderer = self.view = None
        self.inputs = ButtonInput()
        self.mouse = None
        self.capture_path = Path(capture_path) if capture_path else None
        self.transition = SceneTransition("menu", "combat", initial_scene or self.config.window["initial_scene"],
                                          self.config.data["animation"]["duration_seconds"], 0)
        self.pause = PauseState(self.config.data["pause"]["duration_seconds"])
        self.particle_system = (GpuParticleSystem(self.config.data['v2']['absorption_duration_seconds'],
                                 capacity=self.config.data['v2']['energy_absorption']['capacity'],
                                 tail_fraction=self.config.data['v2']['style']['absorption_trail']['tail_fraction'],
                                 **self.config.data['v2']['absorption_routes'])
                                if self.config.data['v2']['style']['absorption_trail']['renderer'] == 'compute' else None)
        self.absorption = EnergyAbsorption(self.config.data["v2"]["absorption_duration_seconds"],
                                           tail_fraction=self.config.data["v2"]["style"]["absorption_trail"]["tail_fraction"],
                                           **self.config.data["v2"]["absorption_routes"])
        scanline = self.config.data["v2"]["style"]["panel_scanlines"]
        scanline_speeds = (scanline["spacing_pixels"], scanline["motion"]["slow_speed_pixels_per_second"],
                           scanline["motion"]["fast_speed_pixels_per_second"])
        self.scanline_motion = ScanlineMotion(*scanline_speeds)
        motion = self.config.data["v2"]["style"]["dialogue_motion"]
        self.dialogue_motion = DialoguePanelMotion(**{key: value for key, value in motion.items() if key.endswith("_seconds")})
        self.lock_motion = LockOnMotion(**self.config.data["v2"]["style"]["lock_motion"])
        self.reset()

    def reset(self):
        data = self.preset
        self.mouse = None
        self.player_world = self.config.actor_anchor("player")
        self.camera = LookAheadCamera(self.config.window["width"], self.config.window["height"],
                                      **self.config.data["v2"]["camera"])
        self.camera.reset(self.player_world)
        self.enemies = {entry["id"]: {**entry, "position": tuple(entry["position_pixels"]),
                                       "health": Health(**entry["health"])} for entry in data["enemies"]}
        settings = self.config.data["v2"]["targeting_sample"]
        self.auto_target = MouseAutoTargeting(settings["range_pixels"], settings["aim_range_pixels"],
                                               **self.config.data["v2"]["auto_targeting"])
        self.targets_enabled, self.aiming = True, False
        self.selected_target_id = data["initial_target_id"]
        self.auto_target.reset(self.selected_target_id)
        enemy = self.enemies[self.selected_target_id]
        target = TargetInfo(enemy["name"], enemy["health"])
        px, py = self.config.actor_anchor("player")
        contacts = tuple(RadarContact((entry["position"][0] - px) / settings["aim_range_pixels"],
                                      (py - entry["position"][1]) / settings["aim_range_pixels"],
                                      *entry["position"]) for entry in self.enemies.values())
        loadouts = tuple(LoadoutInfo(WeaponInfo(**entry["melee"]), WeaponInfo(**entry["ranged"]))
                         for entry in data["loadouts"])
        hud = HudState(Health(**data["player_health"]), target, data["combo_count"],
                       data["total_damage_dealt"], contacts,
                       loadouts=loadouts, active_loadout_index=data["active_loadout_index"],
                       active_weapon_kind=data["active_weapon_kind"])
        self.state = HudV2State(hud, data["energy_ratio"], data["energy_level"],
                                data["overdrive"], data["counter"], data["dash_ready"],
                                dialogue=DialogueInfo(data["dialogue"]["speaker"], tuple(data["dialogue"]["lines"])))
        self.target_size_index = 0
        self.set_target_size(1)
        counter = self.config.data['damage_counter']
        counter_motion = {key: counter[key] for key in ('vertical_easing', 'elastic_strength', 'elastic_period')}
        duration = counter['duration_seconds']
        self.hit_counter = RollingCounter(duration, hud.combo_count, **counter_motion)
        self.damage_counter = RollingCounter(duration, hud.total_damage_dealt, **counter_motion)
        self.level_counter = RollingCounter(duration, self.state.energy_level, **counter_motion)
        duration = self.config.data["health_trail"]["duration_seconds"]
        self.player_health = HealthTrail(duration, hud.player_health.ratio)
        self.target_health = HealthTrail(duration, hud.target.health.ratio)
        flash = self.config.data["v2"]["style"]["health_damage_flash"]
        self.player_flash = HealthDamageFlash(flash["hold_seconds"], flash["fade_seconds"], attack_seconds=flash["attack_seconds"])
        self.target_flash = HealthDamageFlash(flash["hold_seconds"], flash["fade_seconds"], attack_seconds=flash["attack_seconds"])
        hit_settings = self.config.data["v2"]["style"]["health_hit_motion"]
        self.player_hit = HealthHitMotion(**hit_settings["player"])
        self.target_hit = HealthHitMotion(**hit_settings["target"])
        absorption = self.config.data['v2']['energy_absorption']
        self.energy_flash = EnergyRecoveryFlash(absorption['flash_seconds'])
        self.defeated_targets = DefeatedTargetMotion(absorption['target_fade_seconds'])
        animation = self.config.data["animation"]
        self.damage_numbers = DamageNumbers(animation["damage_duration_seconds"],
                                            animation["damage_scatter_x_pixels"],
                                            animation["damage_scatter_y_pixels"],
                                            measure_text=self.damage_text_size,
                                            **self.config.data["damage_popup"])
        self.absorption.clear()
        if self.particle_system is not None:
            self.particle_system.clear()
        self.scanline_motion.reset()
        self.dialogue_motion.reset(opened=True, animate=True)
        self.lock_motion.reset(self.selected_target_id, self.state.target_body)
        self.counter_message = IndicatorFade(**self.config.data["v2"]["style"]["counter_message_motion"])
        self.counter_message.reset(self.state.counter, animate=True)
        self.loadout_slide = LoadoutSlide(hud.active_loadout_index,
                                         self.config.data["loadout_slide"]["duration_seconds"])
        self.weapon_swap = WeaponSwap(hud.active_weapon_kind,
                                      self.config.data["weapon_swap"]["duration_seconds"])
        self.sync_energy_target()

    def damage_text_size(self, text):
        if self.renderer is not None:
            return self.renderer.text_size(text, "damage_number")
        size = self.config.font_sizes["damage_number"]
        return len(text) * size, size

    def set_target_size(self, amount):
        self.target_scale = amount
        if self.selected_target_id is None:
            self.state = replace(self.state, target_body=None)
            return
        width, height = self.preset["target_body_size_pixels"]
        width, height = width * amount, height * amount
        x, y = self.camera.world_to_screen(self.enemies[self.selected_target_id]["position"])
        body = Rect(x - width / 2, y - 12 * amount, width, height)
        self.state = replace(self.state, target_body=body)

    def apply_target(self, target_id):
        if target_id == self.selected_target_id:
            return
        if self.state.hud.target and not any(v.target_id == self.selected_target_id for v in self.defeated_targets.visuals):
            self.defeated_targets.trigger(self.selected_target_id, self.state.target_body,
                                         self.target_health.trailing_ratio, self.state.hud.target.health.ratio)
        self.defeated_targets.tracks = [track for track in self.defeated_targets.tracks if track['target_id'] != target_id]
        self.selected_target_id = target_id
        if self.auto_target.selected_id != target_id:
            self.auto_target.reset(target_id)
        enemy = self.enemies.get(self.selected_target_id)
        self.set_hud(target=TargetInfo(enemy["name"], enemy["health"]) if enemy else None)
        self.set_target_size(self.target_scale)
        self.target_health.reset(enemy["health"].ratio if enemy else 0)
        self.target_flash.clear()
        self.target_hit.clear()
        self.lock_motion.select(self.selected_target_id, self.state.target_body)

    def update_world_view(self, delta_seconds):
        self.camera.update(self.player_world, self.mouse, delta_seconds)
        candidates = tuple(TargetCandidate(key, entry["position"]) for key, entry in self.enemies.items()
                           if self.targets_enabled and entry["health"].current > 0)
        current = self.enemies.get(self.selected_target_id)
        mouse_world = (self.camera.screen_to_world(self.mouse) if self.mouse is not None else
                       current["position"] if current is not None else self.player_world)
        target_id = self.auto_target.update(candidates, self.player_world, mouse_world, delta_seconds, aiming=self.aiming)
        self.apply_target(target_id)
        self.set_target_size(self.target_scale)
        limit = self.config.data["v2"]["targeting_sample"]["aim_range_pixels"]
        px, py = self.player_world
        contacts = tuple(RadarContact((entry["position"][0] - px) / limit, (py - entry["position"][1]) / limit,
                                      *self.camera.world_to_screen(entry["position"])) for entry in self.enemies.values())
        self.set_hud(radar_contacts=contacts)
        for track in self.lock_motion.tracks:
            if track.target_id in self.enemies:
                x, y = self.camera.world_to_screen(self.enemies[track.target_id]["position"])
                width, height = track.body.width, track.body.height
                track.body = Rect(x - width / 2, y - 12 * width / self.preset["target_body_size_pixels"][0], width, height)
        for track in self.defeated_targets.tracks:
            x, y = self.camera.world_to_screen(self.enemies[track['target_id']]['position'])
            body = track['body']
            track['body'] = Rect(x - body.width / 2, y - 12 * body.width / self.preset['target_body_size_pixels'][0],
                                 body.width, body.height)

    def enter(self):
        import pico2d.pico2d as pico

        self.pico = pico
        self.renderer = PicoV2Renderer(self.config.font_paths, self.config.font_sizes)
        self.view = UiV2View(self.config, self.renderer)
        if self.particle_system is not None:
            self.renderer.prepare_compute_particles(self.particle_system)

    def set_hud(self, **changes):
        self.state = replace(self.state, hud=replace(self.state.hud, **changes))

    def energy_geometry(self):
        layout = self.config.data["v2"]["layout"]
        geometry = resource_geometry(layout, self.config.data["v2"]["style"]["level_bevel_pixels"])
        scale = self.config.data["v2"]["style"]["hud_scale"]
        anchor = (self.config.window["width"] / 2, self.config.window["height"])
        offset = self.player_hit.visual.offset_pixels
        screen = lambda point: tuple(value + shift for value, shift in zip(scaled_point(point, anchor, scale), offset))
        channel = tuple(screen(point) for point in geometry.energy_channel)
        left = tuple((a + b) / 2 for a, b in zip(channel[0], channel[3]))
        right = tuple((a + b) / 2 for a, b in zip(channel[1], channel[2]))
        return channel, left, right

    def sync_energy_target(self):
        if self.particle_system is not None:
            _, left, right = self.energy_geometry()
            charge = EnergyCharge.from_state(self.state)
            self.particle_system.set_energy_target(left, right, charge.arrival_ratio, charge_total=charge.total)

    def set_energy_charge(self, charge):
        self.state = replace(self.state, energy_level=charge.level, energy_ratio=charge.ratio,
                             overdrive_charge_ratio=charge.overdrive_ratio, overdrive=charge.active)
        self.level_counter.set_value(charge.level)
        self.sync_energy_target()

    def absorb(self):
        settings = self.config.data['v2']['energy_absorption']
        channel, left, right = self.energy_geometry()
        ratio = EnergyCharge.from_state(self.state).arrival_ratio
        destination = tuple(a + (b - a) * ratio for a, b in zip(left, right))
        enemy = self.enemies.get(self.selected_target_id)
        start = self.camera.world_to_screen(enemy["position"]) if enemy else self.config.actor_anchor("target")
        side = 1 if start[0] > self.camera.world_to_screen(self.player_world)[0] else -1
        bend_x = max(left[0] + 18, min(right[0] - 18, destination[0] + side * settings['approach_offset_pixels']))
        below = min(self.config.window['height'] - 12,
                    max(point[1] for point in channel) + settings['under_bar_gap_pixels'])
        waypoint = bend_x, below
        if self.particle_system is not None:
            self.sync_energy_target()
            self.particle_system.emit(start, waypoint, destination, count=settings['count'], side=side, spread_pixels=6,
                                      gain_ratio=settings['gain_ratio'], arrival_spacing_seconds=settings['arrival_spacing_seconds'])
        else:
            for offset in (-15, 0, 15):
                self.absorption.add((start[0] + offset, start[1] - offset), waypoint, destination, approach_side=side)

    def perform(self, action):
        hud = self.state.hud
        if action == "quit":
            self.running = False
        elif action in ("show_hud", "show_menu"):
            self.aiming = False
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
            previous_ratio = health.ratio
            health = replace(health, current=health.current - applied)
            if target:
                self.enemies[self.selected_target_id]["health"] = health
                self.set_hud(target=replace(hud.target, health=health), combo_count=hud.combo_count + 1,
                             total_damage_dealt=hud.total_damage_dealt + int(applied))
                self.target_health.set_ratio(health.ratio)
                self.target_flash.trigger(previous_ratio, health.ratio)
                self.target_hit.trigger()
                self.absorb()
                if health.current == 0:
                    self.defeated_targets.trigger(self.selected_target_id, self.state.target_body, self.target_health.trailing_ratio)
                    self.lock_motion.select(None, None)
                else:
                    self.lock_motion.hit(self.selected_target_id)
                self.hit_counter.set_value(self.state.hud.combo_count)
                self.damage_counter.set_value(self.state.hud.total_damage_dealt)
            else:
                self.set_hud(player_health=health)
                self.player_health.set_ratio(health.ratio)
                self.player_flash.trigger(previous_ratio, health.ratio)
                self.player_hit.trigger()
            owner = self.selected_target_id if target else "player"
            origin = self.player_world
            position = self.enemies[owner]["position"] if target else origin
            direction = (position[0] - origin[0], position[1] - origin[1]) if target else None
            self.damage_numbers.add(owner, int(applied), *position, direction=direction)
        elif action == "toggle_target":
            self.targets_enabled = not self.targets_enabled
            self.auto_target.reset()
            self.apply_target(None)
        elif action == "dialogue":
            if not self.dialogue_motion.opened and self.state.dialogue is None:
                data = self.preset["dialogue"]
                self.state = replace(self.state, dialogue=DialogueInfo(data["speaker"], tuple(data["lines"])))
            self.dialogue_motion.request(not self.dialogue_motion.opened)
        elif action in ("energy_up", "energy_down"):
            change = 0.1 if action == "energy_up" else -0.1
            if change > 0:
                self.absorb()
            else:
                self.set_energy_charge(EnergyCharge.from_state(self.state).add(change))
        elif action == "absorb":
            self.absorb()
        elif action == "level":
            self.set_energy_charge(EnergyCharge(self.state.energy_level % 3))
        elif action == "target_size":
            sizes = (1, 1.5, 0.75)
            self.target_size_index = (self.target_size_index + 1) % len(sizes)
            self.set_target_size(sizes[self.target_size_index])
        elif action == 'overdrive':
            self.set_energy_charge(EnergyCharge(3 if self.state.overdrive else 4))
        elif action in ("counter", "dash"):
            field = {"counter": "counter", "dash": "dash_ready"}[action]
            self.state = replace(self.state, **{field: not getattr(self.state, field)})
        elif action == "swap":
            self.set_hud(active_weapon_kind="melee" if hud.active_weapon_kind == "ranged" else "ranged")
            self.weapon_swap.request(self.state.hud.active_weapon_kind)
        elif action == "loadout":
            self.set_hud(active_loadout_index=(hud.active_loadout_index + 1) % len(hud.loadouts))
            self.loadout_slide.request(self.state.hud.active_loadout_index)
        else:
            raise ValueError(f"v2 샘플 동작 없음: {action}")

    def handle_event(self, event):
        p = self.pico
        if event.type == p.SDL_WINDOWEVENT:
            if event.window_event in (p.SDL_WINDOWEVENT_LEAVE, p.SDL_WINDOWEVENT_FOCUS_LOST):
                self.mouse = None
                self.auto_target.reset(self.selected_target_id)
                self.aiming = False
                self.inputs.reset()
            return
        if event.type == p.SDL_KEYDOWN and not getattr(event, "repeat", False):
            if self.transition.active or self.pause.transitioning:
                return
            if event.key == p.SDLK_ESCAPE:
                if self.transition.target == "combat":
                    self.aiming = False
                    self.inputs.reset()
                    self.pause.request(not self.pause.opened)
                return
            if self.pause.blocking or self.transition.target != "combat":
                return
            actions = {p.SDLK_1: "damage_target", p.SDLK_2: "damage_player",
                       p.SDLK_3: "energy_down", p.SDLK_4: "energy_up", p.SDLK_5: "level",
                       p.SDLK_6: "overdrive", p.SDLK_7: "target_size", p.SDLK_c: "counter", p.SDLK_t: "toggle_target",
                       p.SDLK_e: "swap", p.SDLK_f: "loadout", p.SDLK_F5: "reset",
                       p.SDLK_g: "absorb", p.SDLK_SPACE: "dash", p.SDLK_d: "dialogue"}
            if event.key in actions:
                self.perform(actions[event.key])
            return
        pointer = event.type in (p.SDL_MOUSEMOTION, p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP)
        if not pointer:
            return
        self.mouse = (event.x, event.y)
        if event.type != p.SDL_MOUSEMOTION and event.button == p.SDL_BUTTON_RIGHT:
            self.aiming = (event.type == p.SDL_MOUSEBUTTONDOWN and not self.pause.blocking
                           and not self.transition.active and self.transition.target == "combat")
            return
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
        self.counter_message.request(self.state.counter)
        self.counter_message.update(delta_seconds)
        self.scanline_motion.update(delta_seconds)
        self.dialogue_motion.update(delta_seconds)
        self.lock_motion.update_body(self.state.target_body)
        self.lock_motion.update(delta_seconds, freeze_hits=self.pause.blocking)
        if self.dialogue_motion.phase == "closed" and self.state.dialogue is not None:
            self.state = replace(self.state, dialogue=None)
        if self.pause.blocking:
            self.pause.update(delta_seconds)
            return
        self.transition.update(delta_seconds)
        self.loadout_slide.request(self.state.hud.active_loadout_index)
        self.loadout_slide.update(delta_seconds)
        self.weapon_swap.request(self.state.hud.active_weapon_kind)
        self.weapon_swap.update(delta_seconds)
        if self.transition.target == "combat" and not self.transition.active:
            self.update_world_view(delta_seconds)
        self.hit_counter.update(delta_seconds)
        self.damage_counter.update(delta_seconds)
        self.level_counter.update(delta_seconds)
        self.player_health.update(delta_seconds)
        self.target_health.update(delta_seconds)
        self.player_flash.update(delta_seconds)
        self.target_flash.update(delta_seconds)
        self.player_hit.update(delta_seconds)
        self.target_hit.update(delta_seconds)
        self.defeated_targets.update(delta_seconds)
        self.energy_flash.update(delta_seconds)
        self.damage_numbers.update(delta_seconds)
        if self.particle_system is not None:
            if self.renderer is not None and self.renderer.compute_particles is not None:
                self.renderer.compute_particles.poll_arrivals()
            gain, _ = self.particle_system.take_arrivals()
            if gain > 0:
                charge = EnergyCharge.from_state(self.state)
                recovered = charge.add(gain)
                if recovered.total > charge.total:
                    self.energy_flash.trigger()
                self.set_energy_charge(recovered)
            self.sync_energy_target()
            self.particle_system.update(delta_seconds)
        else:
            self.absorption.update(delta_seconds)

    def actor(self, owner, opacity):
        r, c = self.renderer, self.config.colors
        x, y = self.camera.world_to_screen(self.player_world if owner == "player" else self.enemies[owner]["position"])
        sx = sy = self.target_scale if owner == self.selected_target_id else 1
        color = c["accent" if owner == "player" else "enemy"]
        for dx, dy, width, height in ((-8, -27, 16, 13), (-15, -12, 30, 27),
                                       (-26, -8, 8, 24), (18, -8, 8, 24),
                                       (-13, 18, 9, 19), (4, 18, 9, 19)):
            r.rect(Rect(x + dx * sx, y + dy * sy, width * sx, height * sy), color, opacity * 0.7)

    def draw(self):
        self.view.prepare_panel_effects(lambda: self.draw_layers(actors=False))
        self.view.background()
        self.draw_layers()
        if self.capture_path:
            self.renderer.save_frame(self.capture_path, self.config.window["width"], self.config.window["height"])
            self.capture_path = None

    def draw_layers(self, *, actors=True):
        for scene in ("menu", "combat"):
            pose = self.transition.pose(scene)
            if pose.opacity <= 0:
                continue
            if scene == "menu":
                self.view.menu(pose.opacity, 0, self.inputs,
                               scanline_visual=self.scanline_motion.visual)
            else:
                if actors:
                    self.actor("player", pose.opacity)
                    for enemy_id in self.enemies:
                        self.actor(enemy_id, pose.opacity)
                damage_visuals = tuple(replace(visual, x=self.camera.world_to_screen((visual.x, visual.y))[0],
                                               y=self.camera.world_to_screen((visual.x, visual.y))[1])
                                       for visual in self.damage_numbers.visuals)
                self.view.combat(self.state, damage_visuals, pose.opacity,
                                 counter_visual=self.damage_counter.visual,
                                 combo_visual=self.hit_counter.visual, cursor_position=self.mouse,
                                 player_trailing_ratio=self.player_health.trailing_ratio,
                                 target_trailing_ratio=self.target_health.trailing_ratio,
                                 absorption_trails=self.absorption.trails,
                                 particle_system=self.particle_system,
                                 defeated_targets=self.defeated_targets.visuals,
                                 energy_flash=self.energy_flash.opacity,
                                 level_visual=self.level_counter.visual,
                                 scanline_visual=self.scanline_motion.visual,
                                 dialogue_visual=self.dialogue_motion.visual,
                                 lock_visuals=self.lock_motion.visuals,
                                 player_damage_flashes=self.player_flash.visuals,
                                 target_damage_flashes=self.target_flash.visuals,
                                 player_hit_visual=self.player_hit.visual,
                                 target_hit_visual=self.target_hit.visual,
                                 counter_message_opacity=self.counter_message.opacity,
                                 loadout_visual=self.loadout_slide.visual,
                                 weapon_swap_visual=self.weapon_swap.visual,
                                 player_screen=self.camera.world_to_screen(self.player_world))
        if self.pause.opacity > 0:
            self.view.pause(self.pause.opacity, self.inputs,
                            scanline_visual=self.scanline_motion.visual)

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
