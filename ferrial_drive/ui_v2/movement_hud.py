"""훈련장 좌표·명중과 HUD 시연 기능을 연결한다. 창·게임 입력은 실행부가 소유한다."""

from dataclasses import replace
import json
from math import hypot, isfinite
from pathlib import Path

from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.energy import EnergyCharge
from ferrial_drive.ui.state import Health
from ferrial_drive.combat.mouse_targeting import MouseAutoTargeting
from .preview import HudPreview
from .state import DialogueInfo
from .radar import RadarMotion


class MovementHud(HudPreview):
    def __init__(self, config_path, preset_path, *, camera_motion_blur=None, settings_store=None, theme_file=None, overdrive_settings=None, energy_settings=None, targeting=None):
        if (targeting or {}).get("acquisition", "visible") != "visible":
            raise ValueError("훈련장 록온 획득은 화면 가시성을 사용한다.")
        self.distance_switch = {"enabled": False, "far_ratio": .7, "near_ratio": .55,
            "closer_ratio": .75, "switch_delay_seconds": .25, "manual_hold_seconds": 1,
            **(targeting or {}).get("screen_distance_switch", {})}
        settings = self.distance_switch
        if (type(settings["enabled"]) is not bool
                or any(not isfinite(settings[key]) for key in settings if key != "enabled")
                or not 0 < settings["near_ratio"] < settings["far_ratio"]
                or not 0 < settings["closer_ratio"] < 1
                or min(settings["switch_delay_seconds"], settings["manual_hold_seconds"]) < 0):
            raise ValueError("화면 거리 교체 비율·대기 시간이 유효하지 않다.")
        super().__init__(config_path, initial_scene="combat", preset_path=preset_path, theme_file=theme_file,
                         overdrive_settings=overdrive_settings, energy_settings=energy_settings)
        if settings_store is not None:
            self.graphics_settings.store = settings_store
            self.graphics_settings.saved = self.graphics_settings.draft = settings_store.load()
        if camera_motion_blur is not None:
            self.config.data["v2"]["camera_motion_blur"].update(camera_motion_blur)
        self.config.data["v2"]["map_walls"] = []
        self.config.buttons["menu"] = tuple(replace(button, label="훈련장 진입") if button.action == "show_hud"
                                            else button for button in self.config.buttons["menu"])
        self.world_camera = None
        self.map_position = (0.5, 0.5)
        self.reset_training()

    def reset_training(self):
        """훈련장 시연 상태만 초기화한다. 외부 이동 카메라는 보존한다."""
        super().reset()
        self.auto_target = MouseAutoTargeting(retain_outside_range=True,
                                             **self.config.data["v2"]["auto_targeting"])
        self.visibility_released_ids = set()
        self.distance_switch_active = False
        self.manual_lock_remaining_seconds = 0
        self.player_world_bounds = None
        if getattr(self, "world_camera", None) is not None:
            self.camera = self.world_camera
        self.enemies = {}
        self.auto_target.reset()
        self.apply_target(None)
        self.defeated_targets.tracks.clear()
        self.lock_motion.reset(None, None)
        self.set_hud(player_health=Health(self.state.hud.player_health.maximum, self.state.hud.player_health.maximum),
                     combo_count=0, total_damage_dealt=0, active_weapon_kind="melee", radar_contacts=())
        self.player_health.reset(1)
        self.hit_counter.set_value(0)
        self.damage_counter.set_value(0)
        self.counter_motion.reset(0)
        self.weapon_swap.reset("melee")
        self.set_energy_charge(EnergyCharge(0))
        self.state = replace(self.state, counter=False)
        self.dash_override = None
        self.radar_motion = RadarMotion(self.config.data["radar"]["motion"])
        self.map_facing = None

    def load_icon_manifest(self, path):
        """로컬 제작 아이콘을 연결하고 초기화 뒤에도 같은 원본을 사용한다."""
        path = Path(path).resolve()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("version") != 1:
            raise ValueError("HUD 아이콘 명세 버전은 1이어야 한다.")
        resolved = {}
        for category in ("slot_images", "weapon_images"):
            resolved[category] = {}
            for key, value in manifest.get(category, {}).items():
                image = (path.parent / value).resolve()
                if not image.is_file():
                    raise FileNotFoundError(f"HUD 아이콘 파일이 없다: {image}")
                resolved[category][key] = str(image)
        self.config.data["v2"]["style"]["shared_swap_slot"]["images"].update(resolved["slot_images"])
        self.config.data["v2"]["style"]["shared_swap_slot"]["glyph_kinds"] = manifest.get("slot_glyph_kinds", [])
        for loadout in self.preset["loadouts"]:
            for kind in ("melee", "ranged"):
                weapon = loadout[kind]
                if weapon["name"] in resolved["weapon_images"]:
                    weapon["image_path"] = resolved["weapon_images"][weapon["name"]]
        self.reset_training()

    @property
    def scene(self):
        return self.transition.target

    @scene.setter
    def scene(self, value):
        if value == "menu":
            self.refresh_continue()
        self.transition.request(value)
        self.inputs.reset()
        self.aiming = False

    @property
    def blocking(self):
        return (self.scene != "combat" or self.transition.active or self.pause.blocking
                or self.graphics_settings.opened)

    def enter(self):
        import pico2d.pico2d as pico
        from ferrial_drive.rendering.bicubic import renderer_name

        if renderer_name(pico) != "opengl":
            self.particle_system = None
        super().enter(load_actor_assets=False)

    def pointer(self, event, pico, paused):
        if event.type == pico.SDL_MOUSEMOTION:
            kind = "move"
            self.mouse = (event.x, event.y)
        elif event.type in (pico.SDL_MOUSEBUTTONDOWN, pico.SDL_MOUSEBUTTONUP):
            if event.button == pico.SDL_BUTTON_RIGHT:
                self.aiming = event.type == pico.SDL_MOUSEBUTTONDOWN and not self.blocking
                return None
            if event.button != pico.SDL_BUTTON_LEFT:
                return None
            kind = "down" if event.type == pico.SDL_MOUSEBUTTONDOWN else "up"
        else:
            return None
        if self.graphics_settings.opened:
            return self.graphics_settings.pointer(kind, event.x, event.y, self.config)
        if self.transition.active or self.pause.transitioning:
            return None
        scene = "pause" if paused else self.scene
        action = self.inputs.handle(kind, event.x, event.y, self.config.buttons.get(scene, ())).action
        if action == "toggle_start":
            self.perform(action)
            return "menu_changed"
        if action == "settings":
            self.inputs.reset()
            self.graphics_settings.open()
            return "settings_opened"
        return action

    def perform(self, action, *, damage_amount=None):
        if action == "reset":
            self.reset_training()
        elif action == "dash":
            self.dash_override = not self.state.dash_ready
            self.state = replace(self.state, dash_ready=self.dash_override)
        else:
            super().perform(action, damage_amount=damage_amount)

    def bind_world(self, camera, projection, controller, targets, mouse, *, player_bounds=None):
        self.bind_player(camera, projection, controller, mouse, player_bounds=player_bounds)
        for target in targets:
            self.bind_target(target, projection)

    def bind_player(self, camera, projection, controller, mouse, *, player_bounds=None):
        self.world_camera = self.camera = camera
        self.world_projection = projection
        self.player_position_m = controller.position_m
        self.player_world = projection.project(controller.position_m)
        self.player_world_bounds = player_bounds
        self.mouse = mouse

    def bind_target(self, target, projection):
        position = (target.center.x, target.center.y)
        if target.target_id not in self.enemies:
            maximum = self.preset["enemies"][0]["health"]["maximum"]
            self.enemies[target.target_id] = {"name": f"훈련 표적 {target.target_id}",
                "position": position, "health": Health(maximum, maximum)}
        entry = self.enemies[target.target_id]
        entry["position"] = position
        radius = target.radius_pixels
        entry["world_bounds"] = (position[0] - radius, position[1] - radius, radius * 2, radius * 2)
        # 지면 위치가 없는 기존 공개 도형은 중심을 지면 위 좌표로 취급한다.
        entry["position_m"] = target.position_m if target.position_m is not None else projection.unproject(position)

    def bounds_intersect_view(self, bounds, camera_position=None):
        """표시 사각형과 화면의 교차. 피격 흔들림은 제외한다."""
        left, top, width, height = bounds
        cx, cy = self.camera.position if camera_position is None else camera_position
        half_width, half_height = self.camera.screen_center
        zoom = self.camera.zoom
        x, y = (left - cx) * zoom + half_width, (top - cy) * zoom + half_height
        return x < half_width * 2 and y < half_height * 2 and x + width * zoom > 0 and y + height * zoom > 0

    def player_intersects_view(self, camera_position=None):
        return self.bounds_intersect_view(self.player_world_bounds or (*self.player_world, 1, 1), camera_position)

    def visible_candidate_ids(self):
        return {target_id for target_id, entry in self.enemies.items()
                if entry["health"].current > 0
                and self.bounds_intersect_view(entry.get("world_bounds", (*entry["position"], 1, 1)))
                and self.bounds_intersect_view(entry.get("world_bounds", (*entry["position"], 1, 1)), self.player_world)}

    def screen_distance_ratio(self, target_id):
        # 화면 중심 위치·피격 흔들림과 무관한 두 기체 사이의 화면상 간격이다.
        half_width, half_height = self.camera.screen_center
        dx, dy = (a - b for a, b in zip(self.enemies[target_id]["position"], self.player_world))
        return hypot(dx * self.camera.zoom / half_width, dy * self.camera.zoom / half_height)

    def select_mouse_target(self):
        """Q 입력의 즉시 선택. 후보가 없으면 기존 표적을 유지한다."""
        self.update_world_view(0)
        if self.mouse is None or not self.targets_enabled or not self.player_intersects_view():
            return None
        candidates = self.visible_candidate_ids() - self.visibility_released_ids
        if not candidates:
            return None
        mouse = self.camera.screen_to_world(self.mouse, include_feedback=False)
        target_id = min(candidates, key=lambda key: (hypot(*(a - b for a, b in zip(
            self.enemies[key]["position"], mouse))), key))
        self.auto_target.reset(target_id)
        self.apply_target(target_id)
        self.set_target_size(self.target_scale)
        self.distance_switch_active = False
        self.manual_lock_remaining_seconds = self.distance_switch["manual_hold_seconds"]
        return target_id

    def distance_switch_preference(self, visible, delta_seconds):
        """현재 표적·후보 집합·대기 시간만 고른다. 실제 선택은 공통 선택기가 수행한다."""
        selected = self.selected_target_id
        self.manual_lock_remaining_seconds = max(0, self.manual_lock_remaining_seconds - delta_seconds)
        if self.manual_lock_remaining_seconds < 1e-9:
            self.manual_lock_remaining_seconds = 0
        if selected is None or selected not in self.enemies or self.enemies[selected]["health"].current <= 0:
            self.distance_switch_active = False
            self.manual_lock_remaining_seconds = 0
            return None, visible, None
        if self.manual_lock_remaining_seconds > 0:
            return selected, visible, None
        settings = self.distance_switch
        if not settings["enabled"]:
            return None, visible, None
        distance = self.screen_distance_ratio(selected)
        if distance >= settings["far_ratio"]:
            self.distance_switch_active = True
        elif distance <= settings["near_ratio"]:
            self.distance_switch_active = False
        if self.distance_switch_active:
            closer = [(self.screen_distance_ratio(key), key) for key in visible - {selected}
                      if self.screen_distance_ratio(key) <= distance * settings["closer_ratio"]]
            preferred = min(closer)[1] if closer else selected
            return preferred, visible, settings["switch_delay_seconds"]
        # 가까운 표적을 고른 직후 커서가 먼 이전 표적을 다시 잡아 반복하지 않게 한다.
        local = {key for key in visible if self.screen_distance_ratio(key) < settings["far_ratio"]}
        return None, local, None

    def update_world_view(self, delta_seconds, *, update_markers=True):
        # 카메라는 훈련장에서 한 번만 갱신한다. HUD는 같은 투영을 읽는다.
        if self.world_camera is None:
            return
        visible = self.visible_candidate_ids()
        if not self.player_intersects_view():
            if self.selected_target_id is not None:
                self.visibility_released_ids.add(self.selected_target_id)
            excluded = set(self.enemies)
        else:
            # 복귀 중인 록온 카메라와 기체 포즈 변화로 같은 먼 적이 반복 획득되지 않게 한다.
            # 해제 표적은 플레이어 중심 화면에서도 보일 때만 다시 허용한다.
            self.visibility_released_ids = {target_id for target_id in self.visibility_released_ids
                if target_id in self.enemies and not self.bounds_intersect_view(
                    self.enemies[target_id].get("world_bounds", (*self.enemies[target_id]["position"], 1, 1)),
                    self.player_world)}
            excluded = self.visibility_released_ids
        preferred, visible, delay = self.distance_switch_preference(visible - excluded, delta_seconds)
        super().update_world_view(delta_seconds, update_camera=False, acquisition_ids=visible,
                                  excluded_target_ids=excluded, preferred_id=preferred, switch_delay_seconds=delay,
                                  update_markers=update_markers)
        if not update_markers:
            return
        for track in self.lock_motion.tracks:
            x, y = self.camera.world_to_screen(self.enemies[track.target_id]["position"])
            track.body = Rect(x - track.body.width / 2, y - track.body.height / 2,
                              track.body.width, track.body.height)

    def set_target_size(self, amount):
        super().set_target_size(amount)
        if self.selected_target_id is not None:
            x, y = self.camera.world_to_screen(self.enemies[self.selected_target_id]["position"])
            size = 52 * amount
            self.state = replace(self.state, target_body=Rect(x - size / 2, y - size / 2, size, size))

    def update(self, controller, delta_seconds, *, paused, interpolation, attack=None, energy_level=None, training_hits=0):
        self.pause.request(paused)
        if not self.blocking:
            speed = self.overdrive_controller.settings.animation_speed if self.state.overdrive else 1
            self.radar_motion.update(controller.state, delta_seconds * speed)
            self.map_facing = controller.facing
            self.state = replace(self.state, radar_scale=self.radar_motion.scale.value,
                                 radar_solid_ratio=self.radar_motion.solid_ratio.value)
        x, y = controller.position_m
        self.map_position = x / controller.settings.map_size_m, y / controller.settings.map_size_m
        if energy_level is not None and energy_level != self.state.energy_level:
            self.set_energy_charge(EnergyCharge(energy_level - 1))
        ready = controller.boost_remaining_seconds == 0 and not controller.boost_preparing
        self.state = replace(self.state, dash_ready=ready if self.dash_override is None else self.dash_override)
        if self.dialogue_motion.opened:
            name = "공격" if attack is not None else {"idle": "대기", "run": "달리기", "dash": "대시", "boost": "부스트"}[controller.state]
            self.state = replace(self.state, dialogue=DialogueInfo("이동·UI 훈련장", (
                "**WASD** 이동 · **Shift** 대시 · **Space** 부스트 · **좌클릭** 검 공격 · **Q** 커서 최근접 록온",
                "**F1** 표적 피해 · **F2** 피격 · **F3/F4** 에너지 · **R** Overdrive · **F6** 강제 발동 · **F7** 크기 · **F8** 흡수",
                f"{name} · {controller.speed_mps:.1f}m/s · 명중 {training_hits} · **E/F** 무장/로드아웃 · **C/T/V/B** UI · **F5** 초기화")))
        super().update(delta_seconds)

    def draw(self, mouse, player_screen):
        self.mouse = mouse
        self.view.prepare_panel_effects(lambda: self.draw_layers(actors=False))
        self.draw_layers(actors=False)

    def close(self):
        self.exit()
