"""기존 이동 훈련장에 다수 적 교전과 실제 HP를 연결한다."""

import json
from pathlib import Path

from .enemy_encounter import EnemyEncounter
from .encounter_view import EncounterView
from .geometry import Vec2
from .movement_application import MovementApplication
from .sword_effects import SwordTarget
from ferrial_drive.ui.state import Health


class EncounterApplication(MovementApplication):
    def __init__(self, config_path, *, encounter_path, **options):
        super().__init__(config_path, **options)
        self.config.get("sword_effects", {})["targets"] = []
        settings = json.loads(Path(encounter_path).read_text(encoding="utf-8-sig"))
        self.encounter = EnemyEncounter(settings, map_size_m=self.controller.settings.map_size_m,
                                        player_radius_m=self.controller.settings.radius_m)
        self.encounter_view = None
        self.encounter_trace = []

    def _enter_resources(self):
        super()._enter_resources()
        if self.hud is None:
            raise ValueError("교전 테스트에는 HP·록온을 연결할 HUD 설정이 필요하다.")
        self.encounter_view = EncounterView(self.renderer, self.camera, self.projection,
            backend=self.encounter.settings.get("rendering", {}).get("backend", "auto"))

    def reset(self):
        self.encounter.reset()
        super().reset()

    def encounter_finished(self):
        return self.encounter.result != "running"

    def bind_hud_world(self):
        self.sword_targets = [SwordTarget(enemy.enemy_id,
            Vec2(*self.projection.project((enemy.position_m.x, enemy.position_m.y))) - Vec2(0, enemy.profile.height_pixels),
            enemy.profile.hit_radius_pixels, "metal", (enemy.position_m.x, enemy.position_m.y))
            for enemy in self.encounter.enemies.values() if enemy.alive]
        for enemy_id in self.encounter.enemies:
            self.target_hits.setdefault(enemy_id, 0)
        created = set(self.encounter.enemies) - set(self.hud.enemies) if self.hud else set()
        super().bind_hud_world()
        if self.hud:
            for target in self.sword_targets:
                enemy = self.encounter.enemies[target.target_id]
                # 살아 있는 적 본체·다리의 보수적 영역. 이름·HP·무기/VFX는 제외한다.
                half_width, head = {"small": (27, 27), "medium": (30, 19), "humanoid": (38, 47)}[enemy.profile.kind]
                self.hud.enemies[target.target_id]["world_bounds"] = (
                    target.center.x - half_width, target.center.y - head,
                    half_width * 2, enemy.profile.height_pixels + head + 8)
            for enemy_id in created:
                enemy = self.encounter.enemies[enemy_id]
                entry = self.hud.enemies[enemy_id]
                entry["name"] = f"{enemy.profile.name} {enemy_id}"
                entry["health"] = Health(enemy.health, enemy.profile.health)

    def sync_encounter_health(self):
        if self.hud:
            self.encounter.sync_health({key: row["health"].current for key, row in self.hud.enemies.items()
                                        if key in self.encounter.enemies}, self.hud.state.hud.player_health.current)

    def advance_encounter(self, seconds, previous_position_m):
        self.sync_encounter_health()
        hits = self.encounter.advance(seconds, previous_position_m, self.controller.position_m)
        for _, amount in hits:
            self.hud.perform("damage_player", damage_amount=amount)
        self.bind_hud_world()

    def on_sword_hit(self, strike_id, target_id):
        super().on_sword_hit(strike_id, target_id)
        if self.hud.enemies[target_id]["health"].current <= 0:
            return
        enemy = self.encounter.enemies[target_id]
        target = next(target for target in self.sword_targets if target.target_id == target_id)
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
                self.encounter_view.draw(self.encounter, self.target_flash, self.window_size)

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
