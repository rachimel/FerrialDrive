"""교전용 스프라이트·기본 도형·공격 표현. 판정은 EnemyEncounter가 소유한다."""

from math import sin

from ferrial_drive.ui.components import Rect
from ferrial_drive.rendering.primitive_batch import PrimitiveBatch
from .geometry import Vec2


ENEMY_VIEW_MARGIN_PIXELS = 200


def use_shared_frame(enemy, player_position_m, locked_id, distance_m):
    if distance_m is None or player_position_m is None or enemy.enemy_id == locked_id:
        return False
    dx = enemy.position_m.x - player_position_m[0]
    dy = enemy.position_m.y - player_position_m[1]
    return dx * dx + dy * dy > distance_m * distance_m


class EncounterView:
    def __init__(self, renderer, camera, projection, *, backend="auto"):
        self.renderer, self.camera, self.projection = renderer, camera, projection
        self.primitives = PrimitiveBatch(renderer, backend=backend)
        self.sprites = {}
        self.batch_enemy_parts = True
        self.batch_enemy_shadows = True
        self.show_enemy_labels = True

    def point(self, position_m, height_pixels=0):
        x, y = self.projection.project((position_m.x, position_m.y))
        return self.camera.world_to_screen((x, y - height_pixels))

    def visible_enemies(self, enemies, window_size):
        width, height = window_size
        margin = ENEMY_VIEW_MARGIN_PIXELS
        # 역변환 반올림으로 경계 기체를 잃지 않도록 후보만 1px 넓게 잡는다.
        left, top = self.projection.unproject(self.camera.screen_to_world((-margin - 1, -margin - 1)))
        right, bottom = self.projection.unproject(
            self.camera.screen_to_world((width + margin + 1, height + margin + 1)))
        for enemy in enemies:
            position = enemy.position_m
            if not (left <= position.x <= right and top <= position.y <= bottom):
                continue
            if not enemy.alive and enemy.death_remaining_seconds <= 0:
                continue
            x, foot = self.point(position)
            if -margin <= x <= width + margin and -margin <= foot <= height + margin:
                yield enemy, x, foot

    def polygon(self, points, color, opacity=1):
        for first, second in zip(points, points[1:] + points[:1]):
            self.primitives.line(*first, *second, color, opacity)

    def draw(self, encounter, flashes, window_size, *, shadow_opacity=0, shadow_softness_pixels=0,
             player_position_m=None, locked_id=None):
        with self.primitives.frame():
            self.primitives.stats["sprite_draws"] = 0
            self.primitives.stats["part_draws"] = 0
            self.primitives.stats["shadow_draws"] = 0
            self.primitives.stats["shadow_groups"] = 0
            self.primitives.stats["near_shadow_batch_submits"] = 0
            self.primitives.stats["fallback_poses"] = 0
            self.primitives.stats["shared_frame_draws"] = 0
            self.primitives.stats["batched_bodies"] = 0
            self.primitives.stats["body_batch_submits"] = 0
            self.primitives.stats["enemy_motions"] = {}
            self._draw(encounter, flashes, window_size, shadow_opacity, shadow_softness_pixels,
                       player_position_m, locked_id)

    def close(self):
        try:
            for sprite in self.sprites.values():
                sprite.close()
            self.sprites.clear()
        finally:
            self.primitives.close()

    def _draw(self, encounter, flashes, window_size, shadow_opacity, shadow_softness_pixels,
              player_position_m, locked_id):
        r, zoom = self.primitives, self.camera.zoom
        width, height = window_size
        phase_names = {"move": "이동", "windup": "준비", "active": "공격", "recovery": "회수", "stagger": "피격"}
        labels = []
        break_labels = []
        placed = []
        shared_radius = encounter.settings.get("rendering", {}).get("shared_frame_distance_m")
        for enemy, x, foot in self.visible_enemies(encounter.enemies.values(), window_size):
            sprite = self.sprites.get(enemy.profile.kind)
            shared = bool(sprite and sprite.part_counts and
                          use_shared_frame(enemy, player_position_m, locked_id, shared_radius))
            placed.append((foot, x, enemy, sprite, sprite.playback(enemy) if sprite else None, shared))
        placed.sort(key=lambda row: row[0])
        r.stats["placed_enemies"] = len(placed)
        requests = {}
        for _, _, enemy, sprite, playback, shared in placed:
            if sprite is not None and sprite.part_counts:
                priorities = requests.setdefault(enemy.profile.kind, ([], [], []))
                priority = 0 if enemy.enemy_id == locked_id else 2 if shared else 1
                priorities[priority].append(playback)
        for kind, (locked, near, far) in requests.items():
            self.sprites[kind].prepare_frame(locked + near + far)
        for index, (foot, x, enemy, sprite, playback, shared) in enumerate(placed):
            if sprite is not None and sprite.part_counts:
                display = sprite.display_playback(playback)
                r.stats["fallback_poses"] += display != playback
                placed[index] = foot, x, enemy, sprite if display is not None else None, display, shared
        if shadow_opacity > 0:
            shadow_groups = {}
            for foot, x, enemy, sprite, playback, shared in placed:
                if sprite is not None and sprite.part_counts:
                    pose = sprite.ground_shadow_pose(playback)
                    kind = enemy.profile.kind
                    shadow_groups.setdefault((kind, pose, shared), []).append((x, foot))
                elif enemy.alive:
                    r.circle(x, foot, max(4, enemy.profile.hit_radius_pixels * .45 * zoom),
                             "#0A1015", shadow_opacity * .55)
            if r.count:
                r.flush()
            near_shadows = {}
            for (kind, pose, shared), placements in shadow_groups.items():
                if not shared and self.batch_enemy_shadows:
                    near_shadows.setdefault(kind, []).append((pose, placements))
                    continue
                sprite = self.sprites[kind]
                r.stats["shadow_draws"] += sprite.draw_ground_shadows(
                    pose, placements, zoom, shadow_opacity, shadow_softness_pixels, shared_frame=shared)
            for kind, groups in near_shadows.items():
                count, submits = self.sprites[kind].draw_near_shadows(groups, zoom, shadow_opacity, shadow_softness_pixels)
                r.stats["shadow_draws"] += count
                r.stats["near_shadow_batch_submits"] += submits
            r.stats["shadow_groups"] = len(shadow_groups)
        body_requests = {}
        for foot, x, enemy, sprite, playback, shared in placed:
            if self.batch_enemy_parts and sprite is not None and sprite.part_counts and not shared:
                motion, direction, seconds = playback
                bank = sprite.part_clip(motion, direction)[-1]
                body_requests.setdefault(enemy.profile.kind, []).append((enemy.enemy_id, motion, bank, seconds, x, foot))
        prepared = {}
        for kind, requests in body_requests.items():
            sprite = self.sprites[kind]
            if len(requests) >= 2:
                prepared.update(sprite.prepare_bodies(requests, zoom))
                r.stats["body_batch_submits"] += sprite.body_batch.submits
        r.stats["batched_bodies"] = len(prepared)
        for foot, x, enemy, sprite, playback, shared in placed:
            profile = enemy.profile
            y = foot - profile.height_pixels * zoom
            facing = Vec2(*self.projection.project((enemy.facing.x, enemy.facing.y))).normalized(Vec2(-1, 0))
            sprite_top = None
            muzzles = ()
            motion = None
            if sprite is not None:
                if r.count:
                    r.flush()
                sprite_top, muzzles, motion = sprite.draw(enemy, x, foot, zoom, playback=playback, shared_frame=shared,
                                                          prepared=prepared.get(enemy.enemy_id))
                r.stats["shared_frame_draws"] += shared
                r.stats["sprite_draws"] += 1
                r.stats["part_draws"] += bool(sprite.part_counts)
                key = f"{profile.kind}/{motion}"
                motions = r.stats["enemy_motions"]
                motions[key] = motions.get(key, 0) + 1
                if not enemy.alive:
                    if self.show_enemy_labels and motion == "break" and enemy.death_remaining_seconds > .52 * sprite.death_seconds:
                        break_labels.append((x, sprite_top - 14 * zoom))
                    continue
            if not enemy.alive:
                opacity = enemy.death_remaining_seconds / encounter.death_seconds
                size = profile.hit_radius_pixels * zoom
                split = (1 - opacity) * size * .4
                for sign in (-1, 1):
                    r.rect(Rect(x + (sign - 1) * size / 2 + sign * split, y - size / 2,
                                size * .85, size), profile.color, opacity)
                continue
            color = "#FFFFFF" if flashes.get(enemy.enemy_id, 0) else profile.color
            # 준비 시 무기를 뒤로 당기고 공격 시 뻗어 별도 바닥 경고 없이 읽게 한다.
            extension = -12 if enemy.phase == "windup" else 30 if enemy.phase == "active" else 8
            muzzle_x, muzzle_y = x + facing.x * (35 + extension) * zoom, y + facing.y * (35 + extension) * zoom
            if sprite is None:
                self.draw_placeholder(enemy, facing, x, foot, y, zoom, color)
                r.line(x, y, muzzle_x, muzzle_y, "#FFF0CE")
            if enemy.phase == "active":
                if enemy.attack_kind == "melee":
                    self.polygon(tuple(self.point(p, 48) for p in enemy.attack_polygon), color, .8)
                elif muzzles:
                    for muzzle in muzzles:
                        r.circle(*muzzle, 4 * zoom, "#FFF1C4")
                else:
                    if sprite is not None:
                        muzzle_x, muzzle_y = self.point(enemy.position_m + enemy.facing * (profile.radius_m + .5), 48)
                    r.circle(muzzle_x, muzzle_y, 7 * zoom, "#FFF1C4")
            if self.show_enemy_labels:
                top = y - (56 if profile.kind == "humanoid" else 38) * zoom
                phase = "move" if motion == "move" else "stagger" if motion == "hit" else enemy.phase
                labels.append((enemy, x, top if sprite_top is None else sprite_top - 7 * zoom, color, phase))
        for bullet in encounter.projectiles:
            point = self.point(bullet.position_m, 48)
            tail = self.point(bullet.position_m - bullet.direction * 2, 48)
            r.line(*tail, *point, "#FF8173")
            r.rect(Rect(point[0] - 2, point[1] - 2, 4, 4), "#FFE1B0")
        bar_width = 66 * zoom
        for enemy, x, top, color, phase in labels:
            r.rect(Rect(x - bar_width / 2, top, bar_width, 4 * zoom), "#24313D")
            r.rect(Rect(x - bar_width / 2, top, bar_width * enemy.health / enemy.profile.health, 4 * zoom), color)
            r.text(f"{enemy.profile.name} {enemy.enemy_id} · {phase_names[phase]}", x, top - 20 * zoom,
                   "small", color, align="center")
        for x, top in break_labels:
            r.text("Break", x, top, "small", "#FFE1B0", align="center")
        alive = sum(enemy.alive for enemy in encounter.enemies.values())
        r.rect(Rect(width / 2 - 270, 164, 540, 32), "#101D2B", .85)
        r.text(f"COMBAT TEST v1.5 · 남은 적 {alive}/{len(encounter.enemies)} · F5 재시작",
               width / 2, 170, "small", "#D5E3EF", align="center")
        if encounter.result != "running":
            r.rect(Rect(width / 2 - 240, 215, 480, 110), "#101D2B", .95)
            text = "훈련 완료 · 적 전멸" if encounter.result == "victory" else "기체 파괴 · 훈련 종료"
            r.text(text, width / 2, 240, "body", "#F1DBB2", align="center")
            r.text("F5 재시작 · Esc 메뉴 · F10 종료", width / 2, 282, "small", "#CADAE4", align="center")

    def draw_placeholder(self, enemy, facing, x, foot, y, zoom, color):
        r = self.primitives
        bob = sin(enemy.travel_m * 1.7) * 4 * zoom if enemy.phase == "move" else 0
        r.line(x - 15 * zoom, foot, x + 15 * zoom, foot, "#0A1015", .7)
        if enemy.profile.kind == "small":
            size = 23 * zoom
            side = Vec2(-facing.y, facing.x)
            center = Vec2(x, y)
            points = tuple((p.x, p.y) for p in (center + facing * size,
                center - facing * (size * .6) + side * size, center - facing * (size * .6) - side * size))
            self.polygon(points, color)
            for sign in (-1, 1):
                r.line(x + sign * 12 * zoom, y, x + sign * 26 * zoom, foot + bob, color)
        elif enemy.profile.kind == "medium":
            r.rect(Rect(x - 30 * zoom, y - 19 * zoom, 60 * zoom, 38 * zoom), color, .85)
            for sign in (-1, 1):
                r.rect(Rect(x + sign * 23 * zoom - 6 * zoom, y + 20 * zoom,
                            12 * zoom, max(5, foot - y - 20 * zoom)), "#5F717C")
        else:
            r.rect(Rect(x - 23 * zoom, y - 23 * zoom + bob, 46 * zoom, 46 * zoom), color, .9)
            r.rect(Rect(x - 11 * zoom, y - 43 * zoom + bob, 22 * zoom, 18 * zoom), color)
            for sign in (-1, 1):
                step = sin(enemy.travel_m * 1.7) * sign * 7 * zoom
                r.rect(Rect(x + (sign * 13 - 6) * zoom, y + 26 * zoom,
                            12 * zoom, max(6, foot - y - 26 * zoom + step)), "#6D7E8C")
                r.rect(Rect(x + (sign * 32 - 6) * zoom, y - 15 * zoom,
                            12 * zoom, 38 * zoom), color, .85)
