"""교전용 기본 도형과 공격 동작. 판정은 EnemyEncounter가 소유한다."""

from math import sin

from ferrial_drive.ui.components import Rect
from ferrial_drive.rendering.primitive_batch import PrimitiveBatch
from .geometry import Vec2


class EncounterView:
    def __init__(self, renderer, camera, projection, *, backend="auto"):
        self.renderer, self.camera, self.projection = renderer, camera, projection
        self.primitives = PrimitiveBatch(renderer, backend=backend)

    def point(self, position_m, height_pixels=0):
        x, y = self.projection.project((position_m.x, position_m.y))
        return self.camera.world_to_screen((x, y - height_pixels))

    def polygon(self, points, color, opacity=1):
        for first, second in zip(points, points[1:] + points[:1]):
            self.primitives.line(*first, *second, color, opacity)

    def draw(self, encounter, flashes, window_size):
        with self.primitives.frame():
            self._draw(encounter, flashes, window_size)

    def close(self):
        self.primitives.close()

    def _draw(self, encounter, flashes, window_size):
        r, zoom = self.primitives, self.camera.zoom
        width, height = window_size
        phase_names = {"move": "이동", "windup": "준비", "active": "공격", "recovery": "회수", "stagger": "피격"}
        for enemy in sorted(encounter.enemies.values(), key=lambda item: item.position_m.y):
            if not enemy.alive and enemy.death_remaining_seconds <= 0:
                continue
            profile = enemy.profile
            x, foot = self.point(enemy.position_m)
            y = foot - profile.height_pixels * zoom
            if not (-200 <= x <= width + 200 and -200 <= foot <= height + 200):
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
            facing = Vec2(*self.projection.project((enemy.facing.x, enemy.facing.y))).normalized(Vec2(-1, 0))
            bob = sin(enemy.travel_m * 1.7) * 4 * zoom if enemy.phase == "move" else 0
            r.line(x - 15 * zoom, foot, x + 15 * zoom, foot, "#0A1015", .7)
            if profile.kind == "small":
                size = 23 * zoom
                side = Vec2(-facing.y, facing.x)
                center = Vec2(x, y)
                points = tuple((p.x, p.y) for p in (center + facing * size,
                    center - facing * (size * .6) + side * size, center - facing * (size * .6) - side * size))
                self.polygon(points, color)
                for sign in (-1, 1):
                    r.line(x + sign * 12 * zoom, y, x + sign * 26 * zoom, foot + bob, color)
            elif profile.kind == "medium":
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
            muzzle_x, muzzle_y = x + facing.x * (35 + extension) * zoom, y + facing.y * (35 + extension) * zoom
            r.line(x, y, muzzle_x, muzzle_y, "#FFF0CE")
            if enemy.phase == "active":
                if enemy.attack_kind == "melee":
                    self.polygon(tuple(self.point(p, 48) for p in enemy.attack_polygon), color, .8)
                else:
                    r.circle(muzzle_x, muzzle_y, 7 * zoom, "#FFF1C4")
            bar_width = 66 * zoom
            top = y - (56 if profile.kind == "humanoid" else 38) * zoom
            r.rect(Rect(x - bar_width / 2, top, bar_width, 4 * zoom), "#24313D")
            r.rect(Rect(x - bar_width / 2, top, bar_width * enemy.health / profile.health, 4 * zoom), color)
            r.text(f"{profile.name} {enemy.enemy_id} · {phase_names[enemy.phase]}", x, top - 20 * zoom,
                   "small", color, align="center")
        for bullet in encounter.projectiles:
            point = self.point(bullet.position_m, 48)
            tail = self.point(bullet.position_m - bullet.direction * 2, 48)
            r.line(*tail, *point, "#FF8173")
            r.rect(Rect(point[0] - 2, point[1] - 2, 4, 4), "#FFE1B0")
        alive = sum(enemy.alive for enemy in encounter.enemies.values())
        r.rect(Rect(width / 2 - 270, 164, 540, 32), "#101D2B", .85)
        r.text(f"COMBAT TEST v1.5 · 남은 적 {alive}/{len(encounter.enemies)} · F5 재시작",
               width / 2, 170, "small", "#D5E3EF", align="center")
        if encounter.result != "running":
            r.rect(Rect(width / 2 - 240, 215, 480, 110), "#101D2B", .95)
            text = "훈련 완료 · 적 전멸" if encounter.result == "victory" else "기체 파괴 · 훈련 종료"
            r.text(text, width / 2, 240, "body", "#F1DBB2", align="center")
            r.text("F5 재시작 · Esc 메뉴 · F10 종료", width / 2, 282, "small", "#CADAE4", align="center")
