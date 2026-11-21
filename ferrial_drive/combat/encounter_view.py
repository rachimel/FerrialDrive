"""교전용 스프라이트·기본 도형·공격 표현. 판정은 EnemyEncounter가 소유한다."""

from collections import Counter
from itertools import groupby
from math import sin

from ferrial_drive.ui.components import Rect
from ferrial_drive.rendering.enemy_part_batch import EnemyUpscaleScratch
from ferrial_drive.rendering.primitive_batch import PrimitiveBatch
from .geometry import Vec2


ENEMY_VIEW_MARGIN_PIXELS = 200
BODY_RUN_WINDOW = 16
CROWD_ATLAS = "crowd_atlas"


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
        self.crowd_atlas = None
        self.upscale_scratch = None
        self.batch_enemy_parts = True
        self.batch_enemy_shadows = True
        self.deferred_enemy_enabled = False
        self.deferred_enemy_screen_depth = False
        self.deferred_enemy_batch_upload = True
        self.deferred_enemy_cache_keypose_samples = False
        self.deferred_pbr = self.deferred_box_shadows = None
        self.show_enemy_labels = False

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
            self.primitives.stats["crowd_atlas_draws"] = 0
            self.primitives.stats["pbr_pose_requests"] = 0
            self.primitives.stats["batched_bodies"] = 0
            self.primitives.stats["body_batch_submits"] = 0
            self.primitives.stats.update(deferred_bodies=0, deferred_surface_submits=0, deferred_light_submits=0,
                                         deferred_shadow_submits=0, deferred_gpu_bytes=0)
            if self.deferred_enemy_screen_depth:
                self.primitives.stats.update(deferred_depth_submits=0, deferred_depth_bodies=0,
                                             deferred_depth_tested_tiles=0, deferred_depth_bytes=0,
                                             deferred_instance_uploads=0, deferred_instance_upload_bytes=0,
                                             deferred_keypose_cached_tiles=0, deferred_keypose_buffer_bytes=0)
            else:
                for key in ("submits", "bodies", "tested_tiles", "bytes"):
                    self.primitives.stats.pop("deferred_depth_" + key, None)
                for key in ("deferred_instance_uploads", "deferred_instance_upload_bytes",
                            "deferred_keypose_cached_tiles", "deferred_keypose_buffer_bytes"):
                    self.primitives.stats.pop(key, None)
            self.primitives.stats["enemy_motions"] = {}
            self._draw(encounter, flashes, window_size, shadow_opacity, shadow_softness_pixels,
                       player_position_m, locked_id)

    def close(self):
        try:
            for sprite in self.sprites.values():
                sprite.close()
            self.sprites.clear()
        finally:
            if self.crowd_atlas is not None:
                self.crowd_atlas.close()
                self.crowd_atlas = None
            if self.deferred_pbr is not None:
                self.deferred_pbr.close()
                self.deferred_pbr = None
            if self.deferred_box_shadows is not None:
                self.deferred_box_shadows.close()
                self.deferred_box_shadows = None
            if self.upscale_scratch is not None:
                self.upscale_scratch.close()
                self.upscale_scratch = None
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
            playback = sprite.playback(enemy) if sprite else None
            shared = bool(sprite and sprite.part_counts and
                          use_shared_frame(enemy, player_position_m, locked_id, shared_radius))
            if shared and self.crowd_atlas and self.crowd_atlas.supports(enemy.profile.kind, playback):
                shared = CROWD_ATLAS
            placed.append((foot, x, enemy, sprite, playback, shared))
        placed.sort(key=lambda row: row[0])
        r.stats["placed_enemies"] = len(placed)
        requests = {}
        for _, _, enemy, sprite, playback, shared in placed:
            if sprite is not None and sprite.part_counts and shared != CROWD_ATLAS:
                priorities = requests.setdefault(enemy.profile.kind, ([], [], []))
                priority = 0 if enemy.enemy_id == locked_id else 2 if shared else 1
                priorities[priority].append(playback)
        for kind, (locked, near, far) in requests.items():
            r.stats["pbr_pose_requests"] += len(locked) + len(near) + len(far)
            self.sprites[kind].prepare_frame(locked + near + far)
        for index, (foot, x, enemy, sprite, playback, shared) in enumerate(placed):
            if sprite is not None and sprite.part_counts and shared != CROWD_ATLAS:
                has_atlas = self.crowd_atlas is not None and self.crowd_atlas.supports(enemy.profile.kind, playback)
                display = sprite.display_playback(playback, allow_fallback=not has_atlas)
                r.stats["fallback_poses"] += display != playback
                if display is None and has_atlas:
                    placed[index] = foot, x, enemy, sprite, playback, CROWD_ATLAS
                else:
                    placed[index] = foot, x, enemy, sprite if display is not None else None, display, shared
        if shadow_opacity > 0:
            shadow_groups = {}
            crowd_shadows = []
            for foot, x, enemy, sprite, playback, shared in placed:
                if shared == CROWD_ATLAS:
                    if enemy.alive:
                        crowd_shadows.append((enemy.profile.kind, playback[1], x, foot, sprite.scale * zoom,
                                              max(4, enemy.profile.hit_radius_pixels * .45 * zoom)))
                elif sprite is not None and sprite.part_counts:
                    pose = sprite.ground_shadow_pose(playback)
                    kind = enemy.profile.kind
                    shadow_groups.setdefault((kind, pose, shared), []).append((x, foot))
                elif enemy.alive:
                    r.circle(x, foot, max(4, enemy.profile.hit_radius_pixels * .45 * zoom),
                             "#0A1015", shadow_opacity * .55)
            if r.count:
                r.flush()
            if crowd_shadows:
                r.stats["shadow_draws"] += self.crowd_atlas.draw_shadows(crowd_shadows, shadow_opacity)
            near_shadows = {}
            for (kind, pose, shared), placements in shadow_groups.items():
                if not shared and self.batch_enemy_shadows:
                    near_shadows.setdefault(kind, []).append((pose, placements))
                    continue
                sprite = self.sprites[kind]
                r.stats["shadow_draws"] += sprite.draw_ground_shadows(
                    pose, placements, zoom, shadow_opacity, shadow_softness_pixels, shared_frame=shared)
            if self.deferred_enemy_enabled and near_shadows:
                if self.deferred_box_shadows is None:
                    from ferrial_drive.rendering.enemy_shadow_batch import EnemyBoxMask
                    self.deferred_box_shadows = EnemyBoxMask(self.renderer.pico)
                mask = self.deferred_box_shadows
                r.stats["shadow_draws"] += mask.draw(near_shadows, self.sprites, zoom, shadow_opacity, window_size)
                r.stats["deferred_shadow_submits"] = mask.submits
                r.stats["deferred_gpu_bytes"] += mask.storage_bytes
            else:
                for kind, groups in near_shadows.items():
                    count, submits = self.sprites[kind].draw_near_shadows(groups, zoom, shadow_opacity, shadow_softness_pixels)
                    r.stats["shadow_draws"] += count
                    r.stats["near_shadow_batch_submits"] += submits
            r.stats["shadow_groups"] = len(shadow_groups)
        self._select_shared_bodies(placed)
        body_requests = {}
        for foot, x, enemy, sprite, playback, shared in placed:
            if self.batch_enemy_parts and sprite is not None and sprite.part_counts and not shared:
                motion, direction, seconds = playback
                bank = sprite.part_clip(motion, direction)[-1]
                body_requests.setdefault(enemy.profile.kind, []).append((enemy.enemy_id, motion, bank, seconds, x, foot))
        prepared = {}
        deferred = {}
        if self.deferred_enemy_enabled and body_requests:
            screen_depth = self.deferred_enemy_screen_depth
            batch_upload = screen_depth and self.deferred_enemy_batch_upload
            cache_samples = batch_upload and self.deferred_enemy_cache_keypose_samples
            current = self.deferred_pbr
            if current is not None and ((current.depth is not None, current.instance_buffer is not None,
                                         current.keypose_buffer is not None) != (screen_depth, batch_upload, cache_samples)):
                self.deferred_pbr.close()
                self.deferred_pbr = None
            if self.deferred_pbr is None:
                from ferrial_drive.rendering.enemy_deferred_pbr import EnemyDeferredPbr
                self.deferred_pbr = EnemyDeferredPbr(self.renderer.pico, screen_depth=screen_depth,
                    batch_upload=batch_upload, cache_keypose_samples=cache_samples)
            ranks = {row[2].enemy_id: len(placed) - index for index, row in enumerate(placed)} if screen_depth else None
            deferred = self.deferred_pbr.prepare(body_requests, self.sprites, zoom, body_depth_ranks=ranks)
            r.stats["deferred_bodies"] = len(deferred)
            r.stats["deferred_surface_submits"] = self.deferred_pbr.surface_submits
            r.stats["deferred_light_submits"] = self.deferred_pbr.light_submits
            r.stats["deferred_gpu_bytes"] += self.deferred_pbr.storage_bytes
            if screen_depth:
                r.stats.update(deferred_depth_submits=self.deferred_pbr.depth_submits,
                               deferred_depth_bodies=self.deferred_pbr.depth_bodies,
                               deferred_depth_tested_tiles=self.deferred_pbr.depth_tested_tiles,
                               deferred_depth_bytes=self.deferred_pbr.depth.storage_bytes,
                               deferred_instance_uploads=self.deferred_pbr.instance_uploads,
                               deferred_instance_upload_bytes=self.deferred_pbr.instance_upload_bytes,
                               deferred_keypose_cached_tiles=self.deferred_pbr.keypose_cached_tiles,
                               deferred_keypose_buffer_bytes=(self.deferred_pbr.keypose_buffer.storage_bytes
                                                             if cache_samples else 0))
        for kind, requests in body_requests.items():
            if deferred:
                requests = [request for request in requests if request[0] not in deferred]
            sprite = self.sprites[kind]
            if len(requests) >= 2:
                if self.upscale_scratch is None:
                    self.upscale_scratch = EnemyUpscaleScratch(sprite.resource.pico)
                prepared.update(sprite.prepare_bodies(requests, zoom, scratch=self.upscale_scratch))
                r.stats["body_batch_submits"] += sprite.body_batch.submits
        r.stats["batched_bodies"] = len(prepared)
        self._draw_bodies(placed, encounter, flashes, zoom, prepared, labels, break_labels, deferred)
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

    def _draw_bodies(self, placed, encounter, flashes, zoom, prepared, labels, break_labels, deferred):
        r = self.primitives
        for pose, items, _ in self._body_runs(placed, zoom):
            if pose is None:
                for row in items:
                    self._draw_enemy(row, encounter, flashes, zoom, prepared, labels, break_labels, deferred)
                continue
            sprite, kind, motion, direction, index = pose
            if r.count:
                r.flush()
            sprite.shared_frames().draw_bodies(sprite.part_clip(motion, direction), index, items, sprite.scale * zoom)
            count = len(items)
            r.stats["shared_frame_draws"] += count
            r.stats["sprite_draws"] += count
            r.stats["part_draws"] += count
            motions = r.stats["enemy_motions"]
            key = f"{kind}/{motion}"
            motions[key] = motions.get(key, 0) + count

    def _body_runs(self, placed, zoom):
        pending = []
        for pose, rows in groupby(placed, self._shared_body_key):
            if pose is None:
                yield from pending
                pending.clear()
                yield None, rows, None
                continue
            sprite, _, motion, direction, index = pose
            points = [(row[1], row[0]) for row in rows]
            clip = sprite.part_clip(motion, direction)
            span = sprite.shared_frames().body_horizontal_span(clip, index, points, sprite.scale * zoom)
            if span is None or len(pending) == BODY_RUN_WINDOW:
                yield from pending
                pending.clear()
            if span is None:
                yield pose, points, None
                continue
            left, right = span
            # 그 사이의 다른 텍스처가 덮는 픽셀을 건너뛸 수 있을 때만 앞으로 당긴다.
            for i in range(len(pending) - 1, -1, -1):
                previous, positions, (xmin, xmax) = pending[i]
                if previous == pose:
                    positions.extend(points)
                    pending[i] = previous, positions, (min(xmin, left), max(xmax, right))
                    break
                if left < xmax and xmin < right:
                    pending.append((pose, points, span))
                    break
            else:
                pending.append((pose, points, span))
        yield from pending

    def _shared_body_key(self, row):
        _, _, enemy, sprite, playback, shared = row
        # 공격 효과·디버그 표시·개별 기체를 경계로 원래의 가림 순서를 보존한다.
        if self.show_enemy_labels or shared is not True or sprite is None or enemy.phase == "active":
            return None
        motion, direction, seconds = playback
        return sprite, enemy.profile.kind, motion, direction, sprite.shared_frame_index(motion, direction, seconds)

    def _select_shared_bodies(self, placed):
        """실제 중복이 있는 중간 자세만 개별 포즈 텍스처에 저장한다."""
        candidates = {}
        for index, row in enumerate(placed):
            if row[-1] is True and row[3] is not None and row[3].shared_pose_fps is not None:
                pose = self._shared_body_key(row)
                candidates[index] = None if pose is None else pose[1:]
        counts = Counter(candidates.values())
        for index, pose in candidates.items():
            if pose is None or counts[pose] == 1:
                placed[index] = (*placed[index][:-1], False)

    def _draw_enemy(self, row, encounter, flashes, zoom, prepared, labels, break_labels, deferred):
        foot, x, enemy, sprite, playback, shared = row
        r = self.primitives
        profile = enemy.profile
        y = foot - profile.height_pixels * zoom
        facing = Vec2(*self.projection.project((enemy.facing.x, enemy.facing.y))).normalized(Vec2(-1, 0))
        sprite_top = None
        muzzles = ()
        motion = None
        if sprite is not None:
            if r.count:
                r.flush()
            if shared == CROWD_ATLAS:
                motion, direction, seconds = playback
                sprite_top = self.crowd_atlas.draw(profile.kind, playback, x, foot, sprite.scale * zoom)
                if enemy.phase == "active" and enemy.attack_kind != "melee":
                    muzzles = sprite.muzzles(f"{motion}/{direction}", sprite.frame_index(motion, direction, seconds),
                                             x, foot, sprite.scale * zoom * sprite.resource.data["pixel_scale"])
                r.stats["crowd_atlas_draws"] += 1
            else:
                record = deferred.get(enemy.enemy_id)
                sprite_top, muzzles, motion = sprite.draw(enemy, x, foot, zoom, playback=playback, shared_frame=shared,
                    prepared=prepared.get(enemy.enemy_id), resolved=(self.deferred_pbr.copy, record) if record else None)
                r.stats["shared_frame_draws"] += shared
                r.stats["part_draws"] += bool(sprite.part_counts)
            r.stats["sprite_draws"] += 1
            key = f"{profile.kind}/{motion}"
            motions = r.stats["enemy_motions"]
            motions[key] = motions.get(key, 0) + 1
            if not enemy.alive:
                if self.show_enemy_labels and motion == "break" and enemy.death_remaining_seconds > .52 * sprite.death_seconds:
                    break_labels.append((x, sprite_top - 14 * zoom))
                return
        if not enemy.alive:
            opacity = enemy.death_remaining_seconds / encounter.death_seconds
            size = profile.hit_radius_pixels * zoom
            split = (1 - opacity) * size * .4
            for sign in (-1, 1):
                r.rect(Rect(x + (sign - 1) * size / 2 + sign * split, y - size / 2,
                            size * .85, size), profile.color, opacity)
            return
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
