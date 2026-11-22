"""기존 이동 훈련장에 다수 적 교전과 실제 HP를 연결한다."""

from contextlib import contextmanager
from dataclasses import replace
import json
from math import isfinite
from pathlib import Path

from .enemy_encounter import EnemyEncounter, crowd_spawns
from .enemy_sprites import load_enemy_part_sprites, load_enemy_sprites
from .encounter_view import EncounterView
from .geometry import Vec2
from .movement_application import MovementApplication
from .sword_effects import SwordTarget
from ferrial_drive.rendering.enemy_crowd_atlas import EnemyCrowdAtlas
from ferrial_drive.ui.state import Health


ENEMY_BODY_EXTENTS = {"small": (27, 27), "medium": (30, 19), "humanoid": (38, 47)}


class EncounterApplication(MovementApplication):
    def __init__(self, config_path, *, encounter_path, enemy_count=None, enemy_spacing_m=12,
                 crowd_atlas_enabled=True, player_hp=None, **options):
        self.initial_player_health = Health(player_hp, player_hp) if player_hp is not None else None
        super().__init__(config_path, **options)
        self.config.get("sword_effects", {})["targets"] = []
        self.encounter_path = Path(encounter_path).resolve()
        settings = json.loads(self.encounter_path.read_text(encoding="utf-8-sig"))
        if enemy_count is not None:
            settings["spawns"] = crowd_spawns(settings["spawns"], enemy_count, enemy_spacing_m,
                                               self.controller.position_m, self.controller.settings.map_size_m)
        shared_radius = settings.get("rendering", {}).get("shared_frame_distance_m")
        if shared_radius is not None and (type(shared_radius) not in (int, float)
                                          or not isfinite(shared_radius) or shared_radius <= 0):
            raise ValueError("적 공유 프레임 거리는 양수 유한 미터 값이어야 한다.")
        self.enemy_sprite_scale = settings.get("rendering", {}).get("sprite_scale", 1)
        if (type(self.enemy_sprite_scale) not in (int, float) or not isfinite(self.enemy_sprite_scale)
                or self.enemy_sprite_scale <= 0):
            raise ValueError("적 표시 배율은 양수여야 한다.")
        self.encounter = EnemyEncounter(settings, map_size_m=self.controller.settings.map_size_m,
                                        player_radius_m=self.controller.settings.radius_m, registry=self.entities,
                                        projectiles=self.projectile_storage)
        self.encounter_view = None
        self.enemy_sprite_bounds = {}
        self.crowd_atlas_enabled = crowd_atlas_enabled
        self.encounter_trace = []
        self.targets_by_id = {}

    def _enter_resources(self):
        super()._enter_resources()
        if self.hud is None:
            raise ValueError("교전 테스트에는 HP·록온을 연결할 HUD 설정이 필요하다.")
        if self.initial_player_health is not None:
            self.hud.preset["player_health"] = {"current": self.initial_player_health.current,
                                                "maximum": self.initial_player_health.maximum}
            self.hud.set_hud(player_health=self.initial_player_health)
        self.hud.resolve_enemy_damage = self.encounter.damage_enemy
        self.encounter_view = EncounterView(self.renderer, self.camera, self.projection,
            backend=self.encounter.settings.get("rendering", {}).get("backend", "auto"))
        self._install_enemy_sprites(self._load_enemy_sprites(self.game_settings))

    def _load_enemy_sprites(self, settings):
        if self.demo:
            return {}
        rendering = self.encounter.settings.get("rendering", {})
        folder = self.encounter_path.parent
        sprites = self._enemy_parts(settings)
        legacy_path = rendering.get("enemy_sprites")
        if not sprites and legacy_path:
            sprites = load_enemy_sprites(folder / legacy_path)
        supplemental_path = rendering.get("supplemental_enemy_sprites")
        if not supplemental_path:
            return sprites
        try:
            supplemental = load_enemy_sprites(folder / supplemental_path)
        except BaseException:
            for sprite in sprites.values():
                sprite.close()
            raise
        for kind in sprites.keys() & supplemental.keys():
            sprites[kind].close()
        sprites.update(supplemental)
        return sprites

    def _enemy_parts(self, settings):
        if not self.pbr_enabled:
            return {}
        rendering = self.encounter.settings.get("rendering", {})
        folder = self.encounter_path.parent
        candidates = ("enemy_repacked_sprites", "enemy_sparse_sprites", "enemy_part_sprites")
        path = next((folder / rendering[key] for key in candidates
                    if rendering.get(key) and (folder / rendering[key]).is_file()), None)
        if path is None:
            return {}
        atlas_path = path.with_name("crowd_atlas.json")
        atlas = self.encounter_view.crowd_atlas
        if atlas is None and self.crowd_atlas_enabled and atlas_path.is_file():
            atlas = self.encounter_view.crowd_atlas = EnemyCrowdAtlas(self.pico, atlas_path)
        lighting = self.relative_path(self.config["upper_lower"]["pbr_lighting"])
        return load_enemy_part_sprites(path, self.pico, lighting, settings, self.timings,
                                       self.part_stream_budget, preload=atlas is None)

    def _install_enemy_sprites(self, sprites):
        for sprite in sprites.values():
            sprite.scale *= self.enemy_sprite_scale
        self.encounter_view.sprites = sprites
        self.enemy_sprite_bounds = {kind: sprite.reference_body_bounds() for kind, sprite in sprites.items()
                                    if not sprite.part_counts}
        self.encounter.sprite_death_seconds = {kind: sprite.death_seconds for kind, sprite in sprites.items()}

    @contextmanager
    def prepare_settings(self, settings):
        with super().prepare_settings(settings) as commit_player:
            current = self.encounter_view.sprites if self.encounter_view else {}
            reload_parts = (any(sprite.part_counts for sprite in current.values())
                            and (settings.texture_quality, settings.upscale_aa)
                            != (self.game_settings.texture_quality, self.game_settings.upscale_aa))
            candidate = self._load_enemy_sprites(settings) if reload_parts else {}
            installed = False

            def commit():
                nonlocal installed
                commit_player()
                if candidate:
                    self._install_enemy_sprites(candidate)
                    installed = True

            try:
                yield commit
            finally:
                for sprite in (current if installed else candidate).values():
                    sprite.close()

    def reset(self):
        self.encounter.reset()
        super().reset()

    def encounter_finished(self):
        return self.encounter.result != "running"

    def bind_hud_world(self):
        if self.hud:
            self.bind_hud_player()
        sprites = self.encounter_view.sprites if self.encounter_view else {}
        targets = {}
        for enemy_id, enemy in self.encounter.enemies.items():
            self.target_hits.setdefault(enemy_id, 0)
            if not enemy.alive:
                continue
            profile = enemy.profile
            position = enemy.position_xy
            x, foot = self.projection.project(position)
            center_y = foot - profile.height_pixels
            target = self.targets_by_id.get(enemy_id)
            if (target is None or target.eid != enemy.eid or target.position_m != position
                    or target.radius_pixels != profile.hit_radius_pixels or target.center.y != center_y):
                target = SwordTarget(enemy_id, Vec2(x, center_y), profile.hit_radius_pixels, "metal", position, enemy.eid)
            targets[enemy_id] = target
            if self.hud:
                if enemy_id not in self.hud.enemies:
                    name = f"{profile.name} {enemy_id}" if self.debug_controls else profile.name
                    self.hud.enemies[enemy_id] = {"name": name,
                                                   "health": Health(enemy.health, profile.health)}
                entry = self.hud.enemies[enemy_id]
                entry["position"], entry["position_m"] = (x, center_y), position
                bounds = self.enemy_sprite_bounds.get(profile.kind)
                if bounds is not None:
                    left, top, width, height = bounds
                    entry["world_bounds"] = (x + left, foot + top, width, height)
                    entry["body_position"] = (x, foot + top + height / 2)
                    continue
                entry.pop("body_position", None)
                half_width, head = ENEMY_BODY_EXTENTS[profile.kind]
                scale = self.enemy_sprite_scale if profile.kind in sprites else 1
                height = profile.height_pixels + head
                entry["world_bounds"] = (x - half_width * scale, foot - height * scale,
                                         half_width * 2 * scale, (height + 8) * scale)
        self.targets_by_id = targets
        self.sword_targets = list(targets.values())

    def find_sword_target(self, target_id):
        return self.targets_by_id.get(target_id)

    def sync_encounter_health(self):
        if self.hud:
            for enemy_id in self.encounter.changed_health_ids:
                entry = self.hud.enemies.get(enemy_id)
                enemy = self.encounter.enemies[enemy_id]
                if entry is not None and entry["health"].current != enemy.health:
                    health = entry["health"] = Health(enemy.health, enemy.profile.health)
                    if enemy_id == self.hud.selected_target_id:
                        self.hud.set_hud(target=replace(self.hud.state.hud.target, health=health))
                        self.hud.target_health.set_ratio(health.ratio)
            self.encounter.changed_health_ids.clear()
            self.encounter.update_result(self.controller.health.current)

    def advance_encounter(self, seconds, previous_position_m):
        self.sync_encounter_health()
        self.encounter.advance(seconds, previous_position_m, self.controller.position_m)
        for hit in self.encounter.hit_events:
            self.on_enemy_hit(hit)
        self.bind_hud_world()

    def on_enemy_hit(self, hit):
        self.hud.perform("damage_player", damage_amount=hit.damage)

    def on_sword_hit(self, strike_id, target_id):
        super().on_sword_hit(strike_id, target_id)
        if self.hud.enemies[target_id]["health"].current <= 0:
            return
        enemy = self.encounter.enemies[target_id]
        target = self.targets_by_id[target_id]
        sections = [section for section in self.sword_effects.sections if section.strike_id == strike_id]
        direction = Vec2(*self.combat.strike_direction)
        if sections:
            section = min(sections, key=lambda item: ((item.tip_a + item.tip_b) * .5 - target.center).length)
            movement = section.tip_b - section.tip_a
            if movement.length > 1e-6:
                direction = Vec2(*self.projection.unproject((movement.x, movement.y)))
        self.encounter.knock_back(enemy.enemy_id, direction)

    def on_gun_hit(self, target_id, impact):
        direction = Vec2(*self.projection.unproject((impact.direction.x, impact.direction.y)))
        self.encounter.knock_back(target_id, direction, source="gun")

    def update(self, delta_seconds):
        was_finished = self.encounter_finished()
        super().update(delta_seconds)
        if was_finished and self.encounter_finished() and not self.paused and not (self.hud and self.hud.blocking):
            seconds = 1 / 60 if self.script else min(delta_seconds, .1)
            self.encounter.advance_reactions(seconds)
            self.gun_contact.update(seconds)
        self.sync_encounter_health()
        if self.encounter_finished():
            self.keys.clear()
            self.release_attack()
            if self.combat:
                self.combat.combo.reset()
            if self.sword_effects:
                self.sword_effects.reset()
            for gun in self.guns:
                gun.projectiles.clear()
        if self.report_path:
            self.encounter_trace.append({"frame": self.frame, "seconds": self.encounter.elapsed_seconds,
                "result": self.encounter.result, "player_health": self.hud.state.hud.player_health.current,
                "enemy_projectiles": len(self.encounter.projectiles), "shots_fired": self.encounter.shots_fired,
                "hits": self.encounter.hits[:], "enemies": {key: {"health": enemy.health,
                    "position_m": [enemy.position_m.x, enemy.position_m.y], "phase": enemy.phase,
                    "attack_kind": enemy.attack_kind, "knockback_remaining_seconds": enemy.knockback_remaining_seconds,
                    "death_remaining_seconds": enemy.death_remaining_seconds}
                    for key, enemy in self.encounter.enemies.items()}})

    def handle_event(self, event):
        if self.encounter_finished() and not (self.hud and self.hud.blocking) and not self.paused:
            p = self.pico
            if event.type in (p.SDL_MOUSEBUTTONDOWN, p.SDL_MOUSEBUTTONUP):
                return
            if event.type in (p.SDL_KEYDOWN, p.SDL_KEYUP) and event.key not in (p.SDLK_F5, p.SDLK_ESCAPE, p.SDLK_F10, p.SDLK_q):
                return
        super().handle_event(event)

    def draw_targets(self):
        if self.encounter_view:
            with self.timings.scope("combat.enemies.draw"):
                self.encounter_view.draw(
                    self.encounter, self.target_flash, self.window_size,
                    player_position_m=self.controller.position_m, locked_id=self.hud.selected_target_id,
                    shadow_opacity=self.style["shadow_opacity"] if self.show_shadow else 0,
                    shadow_softness_pixels=self.style.get("shadow_softness_pixels", 5))

    def exit(self):
        try:
            try:
                if self.encounter_view:
                    self.encounter_view.close()
            finally:
                super().exit()
        finally:
            if self.report_path:
                path = self.report_path.with_name(self.report_path.stem + "_encounter.json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"version": "1.5", "trace": self.encounter_trace,
                    "enemy_rendering": self.encounter_view.primitives.stats if self.encounter_view else None},
                                           ensure_ascii=False, indent=2), encoding="utf-8")
