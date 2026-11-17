"""HUD 시연 상태와 표시 효과. 창과 실행 루프는 호출자가 소유한다."""

from dataclasses import replace
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from ferrial_drive.ui.components import ButtonInput, Rect
from ferrial_drive.settings import GameSettingsStore
from ferrial_drive.ui.settings import GraphicsSettingsMenu
from ferrial_drive.combat.targeting import TargetCandidate
from ferrial_drive.combat.mouse_targeting import MouseAutoTargeting
from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.assets.catalog import AssetDefinition, read_document
from ferrial_drive.assets.directional import DirectionalPlayback
from ferrial_drive.assets.combo import ComboPlayback
from ferrial_drive.ui.config import UiConfig
from ferrial_drive.ui.counter import RollingCounter
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.combat.overdrive import OverdriveController
from ferrial_drive.combat.energy import EnergyAmount, EnergyDecay, EnergySettings
from ferrial_drive.ui.theme import DEFAULT_THEME_PATH, ThemeWatcher
from ferrial_drive.ui.energy_fill import EnergyFillMotion
from ferrial_drive.ui.damage import DamageNumbers
from ferrial_drive.ui.health import HealthTrail
from ferrial_drive.ui.loadout_slide import LoadoutSlide
from ferrial_drive.ui.pause import PauseState
from ferrial_drive.ui.state import Health, HudState, LoadoutInfo, RadarContact, TargetInfo, WeaponInfo
from ferrial_drive.ui.transition import SceneTransition
from ferrial_drive.ui.weapon_swap import WeaponSwap
from ferrial_drive.ui_v2.effects import (BoundaryParticleEmitter, DefeatedTargetMotion, DialoguePanelMotion,
                                       EnergyAbsorption, EnergyRecoveryFlash, EnergyTintMotion, HealthDamageFlash, HealthHitMotion,
                                       IndicatorFade, OverdriveMotion, ScanlineMotion, UltimateReadyMotion)
from ferrial_drive.ui_v2.lock_on import LockOnMotion
from ferrial_drive.ui_v2.geometry import resource_geometry, scaled_point
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer
from ferrial_drive.ui_v2.state import DialogueInfo, HudV2State
from ferrial_drive.ui_v2.view import UiV2View
from ferrial_drive.ui_v2.counter_motion import CounterMotion
from ferrial_drive.ui_v2.pause_motion import PauseHoverMotion
from ferrial_drive.ui_v2.title_menu import TitleMenuMotion
from ferrial_drive.particles import GpuParticleSystem


SAMPLE_DIRECTORY = PROJECT_ROOT / "samples/ui_unit_test_v2"


class HudPreview:
    def __init__(self, config_path=None, *, initial_scene=None, capture_path=None, particle_backend=None, settings_file=None, preset_path=None, theme_file=None, overdrive_settings=None, energy_settings=None, continuation=None):
        from ferrial_drive.continuation import ContinueSession

        self.continuation = continuation if continuation is not None else ContinueSession(mode="test")
        self.overdrive_controller = OverdriveController(overdrive_settings)
        self.energy_settings = energy_settings or EnergySettings()
        self.energy_decay = EnergyDecay(self.energy_settings)
        self.config = UiConfig(Path(config_path) if config_path else SAMPLE_DIRECTORY / "ui_config.json")
        self.graphics_settings = GraphicsSettingsMenu(GameSettingsStore(settings_file))
        self.theme_watcher = ThemeWatcher(theme_file or DEFAULT_THEME_PATH)
        self.graphics_settings.enable_buttons(self.config)
        if particle_backend is not None:
            self.config.data['v2']['style']['absorption_trail']['renderer'] = particle_backend
        self.preset = json.loads((Path(preset_path) if preset_path else SAMPLE_DIRECTORY / "hud_sample.json").read_text(encoding="utf-8"))
        self.running = True
        self.pico = self.renderer = self.view = None
        self.player_asset = self.player_idle = None
        self.player_combo_asset = self.player_combo = None
        self.player_interpolator = None
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
        self.pause_hover_motion = PauseHoverMotion(**self.config.data["pause"]["button_style"].get("hover_motion", {}))
        self.title_menu_motion = TitleMenuMotion(self.config.buttons["menu"], self.config.data["title_menu"])
        motion = self.config.data["v2"]["style"]["dialogue_motion"]
        self.dialogue_motion = DialoguePanelMotion(**{key: value for key, value in motion.items() if key.endswith("_seconds")})
        self.lock_motion = LockOnMotion(**self.config.data["v2"]["style"]["lock_motion"])
        self.reset()

    def reset(self):
        self.overdrive_controller.reset()
        self.energy_decay.reset()
        data = self.preset
        if self.player_idle is not None:
            self.player_idle.reset()
        if self.player_combo is not None:
            self.player_combo.reset()
        self.mouse = None
        self.player_world = tuple(data["player_world_position"])
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
        px, py = self.player_world
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
                                dialogue=DialogueInfo(data["dialogue"]["speaker"], tuple(data["dialogue"]["lines"])),
                                ultimate_cooldown_duration_seconds=self.config.data['v2']['ultimate_sample']['cooldown_seconds'])
        self.target_size_index = 0
        self.overdrive_controller.observe_charge(EnergyCharge.from_state(self.state).total)
        if self.state.overdrive:
            self.overdrive_controller.activate(force=True)
        self.sync_overdrive_state()
        self.set_target_size(1)
        counter = self.config.data['damage_counter']
        counter_motion = {key: counter[key] for key in ('vertical_easing', 'elastic_strength', 'elastic_period')}
        duration = counter['duration_seconds']
        self.hit_counter = RollingCounter(duration, hud.combo_count, **counter_motion)
        self.damage_counter = RollingCounter(duration, hud.total_damage_dealt, **counter_motion)
        motion = self.config.data["v2"]["style"].get("counter_visibility", {})
        self.counter_motion = CounterMotion(**motion)
        self.counter_motion.reset(hud.combo_count)
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
        self.energy_fill = EnergyFillMotion(self.config.data['v2'].get('energy_fill_seconds', 0.12))
        self.energy_fill.reset(EnergyCharge.from_state(self.state).total)
        self.energy_flash = EnergyRecoveryFlash(absorption['flash_seconds'])
        self.energy_tint = EnergyTintMotion(self.config.data['v2']['style']['energy_tint_seconds'])
        self.energy_tint.reset(EnergyCharge.from_state(self.state).overdrive_ratio)
        self.boundary_emitter = BoundaryParticleEmitter(self.config.data['v2']['style']['energy_boundary']['rate_per_second'])
        self.overdrive_motion = OverdriveMotion(**self.config.data['v2']['style']['overdrive_motion'])
        self.overdrive_motion.reset(self.state.overdrive)
        self.ultimate_motion = UltimateReadyMotion(self.config.data['v2']['ultimate_sample']['flash_seconds'])
        self.ultimate_motion.reset(self.state.ultimate_ready)
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
        self.pause_hover_motion.reset()
        self.title_menu_motion.reset()
        self.refresh_continue()
        self.dialogue_motion.reset(opened=True, animate=True)
        self.lock_motion.reset(self.selected_target_id, self.state.target_body)
        self.counter_message = IndicatorFade(**self.config.data["v2"]["style"]["counter_message_motion"])
        self.counter_message.reset(self.state.counter, animate=True)
        self.loadout_slide = LoadoutSlide(hud.active_loadout_index,
                                         self.config.data["loadout_slide"]["duration_seconds"])
        self.weapon_swap = WeaponSwap(hud.active_weapon_kind,
                                      self.config.data["weapon_swap"]["duration_seconds"])
        self.sync_energy_target()

    def refresh_continue(self):
        """타이틀 진입·저장 목록 변경 시 재개 가능 여부와 입력 영역을 갱신한다."""
        self.title_menu_motion.set_continue_available(self.continuation.available)
        self.config.buttons["menu"] = self.title_menu_motion.buttons

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

    def update_world_view(self, delta_seconds, *, update_camera=True, range_distances=None, excluded_target_ids=(),
                          acquisition_ids=None, preferred_id=None, switch_delay_seconds=None):
        if update_camera:
            self.camera.update(self.player_world, self.mouse, delta_seconds)
        candidates = tuple(TargetCandidate(key, entry["position"]) for key, entry in self.enemies.items()
                           if self.targets_enabled and entry["health"].current > 0 and key not in excluded_target_ids)
        current = self.enemies.get(self.selected_target_id)
        mouse_world = (self.camera.screen_to_world(self.mouse, include_feedback=False) if self.mouse is not None else
                       current["position"] if current is not None else self.player_world)
        target_id = self.auto_target.update(candidates, self.player_world, mouse_world, delta_seconds,
                                           aiming=self.aiming, range_distances=range_distances,
                                           acquisition_ids=acquisition_ids, preferred_id=preferred_id,
                                           switch_delay_seconds=switch_delay_seconds)
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

    def enter(self, *, load_actor_assets=True):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering.canvas import apply_output_resolution

        self.pico = pico
        if load_actor_assets:
            apply_output_resolution(self.graphics_settings.saved.screen_resolution,
                                    (self.config.window["width"], self.config.window["height"]))
        self.renderer = PicoV2Renderer(self.config.font_paths, self.config.font_sizes)
        self.view = UiV2View(self.config, self.renderer)
        if self.particle_system is not None:
            self.renderer.prepare_compute_particles(self.particle_system)
        if not load_actor_assets:
            return
        settings = self.config.data["v2"].get("player_asset", {})
        interpolation = settings.get("interpolation", {})
        if interpolation.get("enabled", False) and interpolation.get("source"):
            source = (self.config.path.parent / interpolation["source"]).resolve()
            from ferrial_drive.rendering.bicubic import renderer_name

            if source.is_file() and renderer_name(pico) == "opengl":
                from ferrial_drive.rendering.pico_motion_sprite import PicoMotionSprite

                expected_sources = tuple((self.config.path.parent / settings[key]).resolve()
                                         for key in ("source", "combo_source") if settings.get(key))
                self.player_interpolator = PicoMotionSprite(pico, source, expected_sources=expected_sources, **{
                    key: interpolation[key] for key in
                    ("easing", "shutter_seconds", "blur_direction", "blur_strength") if key in interpolation})
                self.player_idle = DirectionalPlayback(self.player_interpolator.clips,
                                                       direction=settings.get("direction", "se"))
                self.player_combo = ComboPlayback(self.player_interpolator.clips)
                return
        if settings.get("source"):
            source = (self.config.path.parent / settings["source"]).resolve()
            if source.is_file():
                from ferrial_drive.assets.pico_assets import PicoAssetResource

                document = read_document(AssetDefinition("ui_v2_player_idle", "mech", source))
                self.player_asset = PicoAssetResource(document)
                self.player_idle = DirectionalPlayback(self.player_asset.clips,
                                                       direction=settings.get("direction", "se"))
        if settings.get("combo_source"):
            source = (self.config.path.parent / settings["combo_source"]).resolve()
            if source.is_file() and self.player_idle is not None:
                from ferrial_drive.assets.pico_assets import PicoAssetResource

                document = read_document(AssetDefinition("ui_v2_player_combo", "mech", source))
                self.player_combo_asset = PicoAssetResource(document)
                self.player_combo = ComboPlayback(self.player_combo_asset.clips)

    def start_attack(self):
        if self.player_combo is None:
            return False
        if (not self.player_combo.active or self.player_combo.waiting_for_input) and self.mouse is not None:
            x, y = self.camera.world_to_screen(self.player_world)
            self.player_idle.face(self.mouse[0] - x, self.mouse[1] - y)
        if self.player_combo.waiting_for_input:
            self.player_combo.direction = self.player_idle.direction
        return self.player_combo.request(self.player_idle.direction)

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
            ratio = self.state.overdrive_charge_ratio if self.state.overdrive else charge.arrival_ratio
            self.particle_system.set_energy_target(left, right, ratio, charge_total=charge.total)

    @property
    def energy_amount(self):
        return EnergyAmount.from_ratios(self.state.energy_level, self.state.energy_ratio,
                                        self.state.overdrive_charge_ratio, self.energy_settings)

    def set_energy_charge(self, charge):
        """기존 시연·입력의 0~4 표시 값을 실제 에너지량으로 변환한다."""
        self.set_energy_amount(EnergyAmount.from_display(charge.total, self.energy_settings))

    def set_energy_amount(self, energy):
        before = self.energy_amount
        if energy.amount + energy.overdrive_amount > before.amount + before.overdrive_amount:
            self.energy_decay.reset()
        if self.overdrive_controller.active and energy.level == 1:
            self.overdrive_controller.cancel()
        readiness = 3 + energy.overdrive_ratio if energy.overdrive_amount else energy.display_total
        self.overdrive_controller.observe_charge(readiness)
        self.state = replace(self.state, energy_level=energy.level, energy_ratio=energy.ratio,
                             overdrive_charge_ratio=energy.overdrive_ratio, overdrive=self.overdrive_controller.active)
        self.sync_overdrive_state()
        self.energy_fill.request(3 + self.state.overdrive_charge_ratio if self.state.overdrive else energy.display_total)
        self.level_counter.set_value(energy.level)
        self.energy_tint.request(1 if self.state.overdrive else energy.overdrive_ratio)
        self.overdrive_motion.request(self.state.overdrive)
        self.ultimate_motion.request(self.state.ultimate_ready)
        self.sync_energy_target()

    def recover_energy_ratio(self, ratio):
        before = self.energy_amount
        recovered = before.recover_ratio(ratio)
        if recovered.amount + recovered.overdrive_amount > before.amount + before.overdrive_amount:
            self.energy_flash.trigger()
        self.set_energy_amount(recovered)

    def sync_overdrive_state(self):
        controller = self.overdrive_controller
        self.state = replace(self.state, overdrive=controller.active,
                             overdrive_standby_seconds=controller.standby_remaining_seconds,
                             overdrive_remaining_seconds=controller.active_remaining_seconds,
                             overdrive_cooldown_seconds=controller.cooldown_remaining_seconds)
        if controller.active:
            self.state = replace(self.state, overdrive_charge_ratio=controller.active_remaining_seconds / controller.settings.duration_seconds)

    def emit_boundary_particles(self, delta_seconds):
        ratio = self.state.overdrive_charge_ratio if self.state.overdrive else EnergyCharge.from_state(self.state).arrival_ratio
        settings = self.config.data['v2']['style']['energy_boundary']
        overdrive = self.state.overdrive
        level = self.state.energy_level - 1
        self.boundary_emitter.rate_per_second = settings['overdrive_rate_per_second'] if overdrive else settings['level_rates_per_second'][level]
        enabled = (self.particle_system is not None and (0 < ratio < 1 or overdrive)
                   and self.transition.target == 'combat' and not self.transition.active)
        count = self.boundary_emitter.update(delta_seconds, enabled)
        if count:
            channel, _, _ = self.energy_geometry()
            display_ratio = self.energy_fill.visual.arrival_ratio
            top = tuple(a + (b - a) * display_ratio for a, b in zip(channel[0], channel[1]))
            bottom = tuple(a + (b - a) * display_ratio for a, b in zip(channel[3], channel[2]))
            self.particle_system.emit_sparks(top, bottom, count=count,
                duration_seconds=settings['overdrive_duration_seconds'] if overdrive else settings['duration_seconds'],
                spread_pixels=settings['spread_pixels'],
                intensity=settings['overdrive_intensity'] if overdrive else settings['level_intensities'][level])

    def absorb(self, *, target_id=None):
        settings = self.config.data['v2']['energy_absorption']
        channel, left, right = self.energy_geometry()
        ratio = EnergyCharge.from_state(self.state).arrival_ratio
        destination = tuple(a + (b - a) * ratio for a, b in zip(left, right))
        enemy = self.enemies.get(self.selected_target_id if target_id is None else target_id)
        start = self.camera.world_to_screen(enemy["position"]) if enemy else self.config.actor_anchor("target")
        side = 1 if start[0] > self.camera.world_to_screen(self.player_world)[0] else -1
        bend_x = max(left[0] + 18, min(right[0] - 18, destination[0] + side * settings['approach_offset_pixels']))
        below = min(self.config.window['height'] - 12,
                    max(point[1] for point in channel) + settings['under_bar_gap_pixels'])
        waypoint = bend_x, below
        if self.particle_system is not None:
            self.sync_energy_target()
            self.particle_system.emit(start, waypoint, destination, count=settings['count'], side=side, spread_pixels=6,
                                      gain_ratio=settings['gain_ratio'], arrival_spacing_seconds=settings['arrival_spacing_seconds'],
                                      duration_variation=settings['duration_variation'])
        else:
            for offset in (-15, 0, 15):
                self.absorption.add((start[0] + offset, start[1] - offset), waypoint, destination, approach_side=side)

    def damage_target(self, target_id, amount=None):
        """록온을 변경하지 않고 실제 피격 대상에 피해를 적용한다."""
        if target_id not in self.enemies or self.enemies[target_id]["health"].current <= 0:
            return
        if target_id == self.selected_target_id:
            self.perform("damage_target", damage_amount=amount)
            return
        amount = self.config.data["sample_actions"]["damage_target"] if amount is None else amount
        if type(amount) is not int or amount < 0:
            raise ValueError("피해량은 0 이상의 정수여야 한다.")
        enemy = self.enemies[target_id]
        applied = min(amount, enemy["health"].current)
        if applied <= 0:
            return
        enemy["health"] = replace(enemy["health"], current=enemy["health"].current - applied)
        hud = self.state.hud
        self.set_hud(combo_count=hud.combo_count + 1, total_damage_dealt=hud.total_damage_dealt + applied)
        self.hit_counter.set_value(self.state.hud.combo_count)
        self.damage_counter.set_value(self.state.hud.total_damage_dealt)
        self.absorb(target_id=target_id)
        position = enemy["position"]
        direction = tuple(a - b for a, b in zip(position, self.player_world))
        self.damage_numbers.add(target_id, applied, *position, direction=direction)

    def perform(self, action, *, damage_amount=None):
        if action == "continue":
            if self.transition.active or self.transition.target != "menu":
                return
            if not self.continuation.resume():
                self.refresh_continue()
                return
            self.aiming = False
            self.pause.reset()
            self.inputs.reset()
            self.transition.request("combat")
            return
        if action == "toggle_start":
            self.inputs.pressed_id = None
            self.title_menu_motion.toggle()
            self.config.buttons["menu"] = self.title_menu_motion.buttons
            return
        if action == "settings":
            self.inputs.reset()
            self.graphics_settings.open()
            return
        hud = self.state.hud
        if action == "quit":
            self.running = False
        elif action in ("show_hud", "show_menu"):
            if action == "show_hud" and self.player_combo is not None:
                self.player_combo.reset()
            if action == "show_menu":
                self.refresh_continue()
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
            amount = self.config.data["sample_actions"][action] if damage_amount is None else damage_amount
            if type(amount) is not int or amount < 0:
                raise ValueError("피해량은 0 이상의 정수여야 한다.")
            applied = min(amount, health.current)
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
            if self.state.overdrive:
                self.overdrive_controller.cancel()
                self.set_energy_charge(EnergyCharge(3))
            else:
                self.overdrive_controller.activate(force=True)
                self.set_energy_charge(EnergyCharge(4))
        elif action == "activate_overdrive":
            if self.overdrive_controller.activate():
                self.set_energy_charge(EnergyCharge(4))
        elif action == 'ultimate':
            if self.state.ultimate_ready:
                duration = self.config.data['v2']['ultimate_sample']['cooldown_seconds']
                self.state = replace(self.state, ultimate_cooldown_seconds=duration, ultimate_cooldown_duration_seconds=duration)
                self.ultimate_motion.request(False)
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
        if self.graphics_settings.opened:
            if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_ESCAPE:
                self.graphics_settings.cancel()
            elif event.type == p.SDL_MOUSEMOTION:
                self.mouse = (event.x, event.y)
                self.graphics_settings.pointer("move", *self.mouse, self.config)
            elif event.type in (p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP) and event.button == p.SDL_BUTTON_LEFT:
                self.mouse = (event.x, event.y)
                self.graphics_settings.pointer("down" if event.type == p.SDL_MOUSEBUTTONDOWN else "up", *self.mouse, self.config)
            elif event.type == p.SDL_WINDOWEVENT:
                self.graphics_settings.inputs.reset()
            return
        if event.type == p.SDL_WINDOWEVENT:
            if event.window_event in (p.SDL_WINDOWEVENT_LEAVE, p.SDL_WINDOWEVENT_FOCUS_LOST):
                self.mouse = None
                self.auto_target.reset(self.selected_target_id)
                self.aiming = False
                self.inputs.reset()
                if self.player_combo is not None:
                    self.player_combo.clear_buffer()
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
                       p.SDLK_r: "activate_overdrive", p.SDLK_e: "swap", p.SDLK_f: "loadout", p.SDLK_F5: "reset",
                       p.SDLK_g: "absorb", p.SDLK_SPACE: "dash", p.SDLK_d: "dialogue", p.SDLK_v: 'ultimate'}
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
        if scene == "combat" and event.type == p.SDL_MOUSEBUTTONDOWN and event.button == p.SDL_BUTTON_LEFT:
            self.start_attack()
            return
        if scene == "combat" or (event.type != p.SDL_MOUSEMOTION and event.button != p.SDL_BUTTON_LEFT):
            return
        kind = "move" if event.type == p.SDL_MOUSEMOTION else (
            "down" if event.type == p.SDL_MOUSEBUTTONDOWN else "up")
        result = self.inputs.handle(kind, *self.mouse, self.config.buttons[scene])
        if result.action:
            self.perform(result.action)

    def update(self, delta_seconds):
        wall_seconds = delta_seconds
        self.graphics_settings.update(wall_seconds)
        if self.transition.target == "menu" and not self.graphics_settings.opened:
            self.title_menu_motion.update(wall_seconds, self.inputs.hovered_id)
        self.config.buttons["menu"] = self.title_menu_motion.buttons
        self.pause_hover_motion.update(wall_seconds, self.inputs.hovered_id, self.config.buttons["pause"],
                                       active=self.pause.blocking and not self.graphics_settings.opened)
        was_active = self.state.overdrive
        delta_seconds *= self.overdrive_controller.settings.animation_speed if was_active else 1
        if self.graphics_settings.opened:
            self.scanline_motion.update(delta_seconds)
            self.pause.update(delta_seconds)
            return
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
        if self.transition.target != "combat" or self.transition.active:
            return
        if self.transition.target == "combat" and not self.transition.active:
            consumed = self.energy_decay.update(wall_seconds, suspended=was_active or self.state.overdrive_ready)
            if consumed > 0 and self.energy_amount.amount > 0:
                self.set_energy_amount(self.energy_amount.consume(consumed))
        reset_total = self.overdrive_controller.update(wall_seconds)
        if reset_total is not None:
            self.set_energy_charge(EnergyCharge(reset_total))
            self.energy_decay.reset()
        self.sync_overdrive_state()
        cooldown_seconds = wall_seconds * (self.overdrive_controller.settings.cooldown_speed if was_active else 1)
        self.ultimate_motion.update(delta_seconds)
        self.state = replace(self.state,
            ultimate_cooldown_seconds=max(0, self.state.ultimate_cooldown_seconds - cooldown_seconds),
            skill_cooldown_seconds=max(0, self.state.skill_cooldown_seconds - cooldown_seconds),
            back_weapon_cooldown_seconds=max(0, self.state.back_weapon_cooldown_seconds - cooldown_seconds))
        self.ultimate_motion.request(self.state.ultimate_ready)
        self.overdrive_motion.request(self.state.overdrive)
        self.overdrive_motion.update(delta_seconds)
        self.energy_tint.request(1 if self.state.overdrive else self.state.overdrive_charge_ratio)
        self.energy_tint.update(delta_seconds)
        self.energy_fill.request(3 + self.state.overdrive_charge_ratio if self.state.overdrive else EnergyCharge.from_state(self.state).total)
        self.energy_fill.update(delta_seconds)
        self.loadout_slide.request(self.state.hud.active_loadout_index)
        self.loadout_slide.update(delta_seconds)
        self.weapon_swap.request(self.state.hud.active_weapon_kind)
        self.weapon_swap.update(delta_seconds)
        if self.transition.target == "combat" and not self.transition.active:
            # 표적 교체·수동 선택 보호 시간은 Overdrive 애니메이션 배율과 분리한다.
            self.update_world_view(wall_seconds)
            if self.player_idle is not None:
                if self.player_combo is not None and self.player_combo.active:
                    direction = self.player_combo.direction
                    speed = self.config.data["v2"].get("player_asset", {}).get("combo_playback_speed", 1.0)
                    if self.mouse is not None:
                        x, y = self.camera.world_to_screen(self.player_world)
                        self.player_idle.face(self.mouse[0]-x, self.mouse[1]-y)
                    self.player_combo.update(delta_seconds * speed, next_direction=self.player_idle.direction)
                    if not self.player_combo.active:
                        self.player_idle.reset()
                        self.player_idle.direction = direction
                else:
                    self.player_idle.update(delta_seconds)
                if (self.player_combo is None or not self.player_combo.active) and self.mouse is not None:
                    x, y = self.camera.world_to_screen(self.player_world)
                    self.player_idle.face(self.mouse[0] - x, self.mouse[1] - y)
        self.hit_counter.update(delta_seconds)
        if self.transition.target == "combat":
            self.counter_motion.update(self.state.hud.combo_count, delta_seconds)
        self.damage_counter.update(delta_seconds)
        self.level_counter.update(delta_seconds)
        self.player_health.update(delta_seconds)
        self.target_health.update(delta_seconds)
        self.player_flash.update(wall_seconds)
        self.target_flash.update(wall_seconds)
        self.player_hit.update(delta_seconds)
        self.target_hit.update(delta_seconds)
        self.defeated_targets.update(wall_seconds)
        self.energy_flash.update(wall_seconds)
        self.damage_numbers.update(delta_seconds, accumulation_delta_seconds=wall_seconds)
        if self.particle_system is not None:
            if self.renderer is not None and self.renderer.compute_particles is not None:
                self.renderer.compute_particles.poll_arrivals()
            gain, _ = self.particle_system.take_arrivals()
            if gain > 0:
                self.recover_energy_ratio(gain * self.energy_settings.absorption_gain_multiplier)
            self.sync_energy_target()
            # HUD 전환 속도와 입자 발생·이동·수명 시계를 분리한다.
            self.emit_boundary_particles(wall_seconds)
            self.particle_system.update(wall_seconds)
        else:
            arrived = sum(trail.progress < 1 <= trail.progress + wall_seconds / trail.duration_seconds
                          for trail in self.absorption.trails)
            self.absorption.update(wall_seconds)
            if arrived:
                gain = self.config.data["v2"]["energy_absorption"]["gain_ratio"] * arrived / 3
                self.recover_energy_ratio(gain * self.energy_settings.absorption_gain_multiplier)

    def actor(self, owner, opacity):
        r, c = self.renderer, self.config.colors
        x, y = self.camera.world_to_screen(self.player_world if owner == "player" else self.enemies[owner]["position"])
        if owner == "player" and self.player_interpolator is not None:
            playback = self.player_combo if self.player_combo.active else self.player_idle
            settings = self.config.data["v2"]["player_asset"]
            options = ({"easing": settings.get("combo_easing", "accelerate"),
                        "playback_speed": settings.get("combo_playback_speed", 1.0)}
                       if self.player_combo.active else {})
            self.player_interpolator.draw(playback.clip_name, playback.elapsed_seconds, x, y,
                                          scale=settings["scale"], opacity=opacity, **options)
            return
        if owner == "player" and self.player_asset is not None:
            scale = self.config.data["v2"]["player_asset"]["scale"]
            attacking = self.player_combo is not None and self.player_combo.active
            asset = self.player_combo_asset if attacking else self.player_asset
            playback = self.player_combo if attacking else self.player_idle
            frame_index = playback.frame_index
            if attacking:
                from ferrial_drive.rendering.motion_vectors import target_phase
                clip = playback.clips[playback.clip_name]
                phase = playback.elapsed_seconds/(clip.duration_ms/1000)
                easing = self.config.data["v2"]["player_asset"].get("combo_easing", "accelerate")
                frame_index = min(int(target_phase(phase, easing=easing)*len(clip.frames)), len(clip.frames)-1)
            with asset.opacity(opacity):
                asset.draw(playback.clip_name, frame_index,
                           x, self.config.window["height"] - y, scale=scale)
            return
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
        self.view.overdrive_palette = self.state.overdrive
        if self.theme_watcher.poll():
            self.view.hud_theme = self.theme_watcher.document
        self.view.show_key_hints = self.graphics_settings.saved.show_key_hints
        for scene in ("menu", "combat"):
            pose = self.transition.pose(scene)
            if pose.opacity <= 0:
                continue
            if scene == "menu":
                self.view.menu(pose.opacity, 0, self.inputs,
                               scanline_visual=self.scanline_motion.visual,
                               expansion=self.title_menu_motion.expansion,
                               hover_amounts=self.title_menu_motion.hover_amounts)
            else:
                if actors:
                    with self.view.world_motion_blur(
                            self.camera.velocity_pixels_per_second,
                            enabled=not self.pause.blocking and not self.transition.active):
                        self.actor("player", pose.opacity)
                        for enemy_id in self.enemies:
                            self.actor(enemy_id, pose.opacity)
                damage_visuals = tuple(replace(visual, x=self.camera.world_to_screen((visual.x, visual.y))[0],
                                               y=self.camera.world_to_screen((visual.x, visual.y))[1])
                                       for visual in self.damage_numbers.visuals)
                self.view.combat(self.state, damage_visuals, pose.opacity,
                                 counter_visual=self.damage_counter.visual,
                                 counter_motion_visual=self.counter_motion.visual,
                                 combo_visual=self.hit_counter.visual, cursor_position=self.mouse,
                                 player_trailing_ratio=self.player_health.trailing_ratio,
                                 target_trailing_ratio=self.target_health.trailing_ratio,
                                 absorption_trails=self.absorption.trails,
                                 particle_system=self.particle_system,
                                 defeated_targets=self.defeated_targets.visuals,
                                 energy_flash=self.energy_flash.opacity,
                                 level_visual=self.level_counter.visual,
                                 overdrive_visual=self.overdrive_motion.visual,
                                 ultimate_visual=self.ultimate_motion.visual,
                                 energy_tint_ratio=self.energy_tint.ratio,
                                 energy_visual=self.energy_fill.visual,
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
                                 player_screen=self.camera.world_to_screen(self.player_world, include_feedback=False),
                                 minimap_player_position=getattr(self, "map_position", (0.5, 0.5)))
        if self.pause.opacity > 0 and not self.graphics_settings.opened:
            self.view.pause(self.pause.opacity, self.inputs,
                            scanline_visual=self.scanline_motion.visual,
                            button_visuals=self.pause_hover_motion.visuals)
        if self.graphics_settings.opened:
            self.view.graphics_settings(self.graphics_settings)

    def exit(self):
        if self.player_interpolator is not None:
            self.player_interpolator.close()
            self.player_interpolator = self.player_idle = self.player_combo = None
        if self.player_combo_asset is not None:
            self.player_combo_asset.close()
            self.player_combo_asset = self.player_combo = None
        if self.player_asset is not None:
            self.player_asset.close()
            self.player_asset = self.player_idle = None
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.view = None


def create_preview(**kwargs):
    return HudPreview(**kwargs)
