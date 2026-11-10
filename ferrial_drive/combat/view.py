"""전투 상태를 도형과 기존 HUD로 표시한다. 판정이나 입력은 처리하지 않는다."""

from dataclasses import replace
from math import atan2, cos, pi, sin

from ..ui.components import Rect
from ..ui.state import Health, HudState, LoadoutInfo, RadarContact, TargetInfo, WeaponInfo
from ..ui.view import UiView
from .simulation import Vec2


class CombatView:
    def __init__(self, config, renderer, style):
        self.config, self.renderer, self.style = config, renderer, style
        self.hud = UiView(config, renderer)
        self.scale_y = style["projection_y_scale"]
        if not 0 < self.scale_y <= 1 or style["grid_spacing_units"] <= 0:
            raise ValueError("화면 투영 비율은 0 초과 1 이하, 격자 간격은 양수여야 한다.")

    def project(self, point, camera, height_pixels=0):
        anchor_x, anchor_y = self.config.actor_anchor("player")
        return (anchor_x + point.x - camera.x,
                anchor_y - (point.y - camera.y) * self.scale_y - height_pixels)

    def aim_direction(self, mouse):
        anchor_x, anchor_y = self.config.actor_anchor("player")
        return Vec2(mouse[0] - anchor_x, -(mouse[1] - anchor_y) / self.scale_y)

    def polygon(self, points, color, opacity=1):
        for index in range(1, len(points) - 1):
            self.renderer.filled_triangle(points[0], points[index], points[index + 1], color, opacity)

    def ellipse(self, x, y, width, height, color, opacity=1):
        self.polygon([(x + cos(i * pi / 12) * width / 2,
                       y + sin(i * pi / 12) * height / 2) for i in range(24)], color, opacity)

    def terrain(self, world):
        r, style, camera = self.renderer, self.style, world.player.position
        r.clear(style["background"])
        arena = world.arena
        left, top = self.project(Vec2(0, arena.height_units), camera)
        right, bottom = self.project(Vec2(arena.width_units, 0), camera)
        r.rect(Rect(left, top, right - left, bottom - top), style["floor"])
        spacing = style["grid_spacing_units"]
        for x in range(0, int(arena.width_units) + 1, int(spacing)):
            r.line(*self.project(Vec2(x, 0), camera),
                   *self.project(Vec2(x, arena.height_units), camera), self.config.colors["grid"])
        for y in range(0, int(arena.height_units) + 1, int(spacing)):
            r.line(*self.project(Vec2(0, y), camera),
                   *self.project(Vec2(arena.width_units, y), camera), self.config.colors["grid"])
        r.rect(Rect(left, top, right - left, bottom - top), self.config.colors["ui_accent"], 0.7, filled=False)

    def wall(self, wall, camera):
        r, style = self.renderer, self.style
        height = style["wall_height_pixels"]
        left, top = self.project(Vec2(wall.x, wall.y + wall.height), camera, height)
        right, bottom = self.project(Vec2(wall.x + wall.width, wall.y), camera, height)
        r.rect(Rect(left, bottom, right - left, height), style["wall_front"])
        r.rect(Rect(left, top, right - left, bottom - top), style["wall_top"])
        r.rect(Rect(left, top, right - left, bottom - top), self.config.colors["panel_border"], 0.65, filled=False)
        r.line(left, bottom + height, right, bottom + height, self.config.colors["line"])

    def actor(self, actor, world):
        r, camera, c = self.renderer, world.player.position, self.config.colors
        x, y = self.project(actor.position, camera)
        player = actor.owner == "player"
        color = c["ui_accent"] if player else c["enemy"]
        if not actor.alive:
            self.ellipse(x, y, 48, 16, c["background"], 0.8)
            r.rect(Rect(x - 22, y - 12, 44, 14), self.style["wall_side"])
            r.line(x - 20, y - 10, x + 20, y, c["muted"], 0.4)
            return
        if actor.hit_flash_seconds > 0:
            color = c["text"]
        facing = actor.facing
        side = Vec2(-facing.y, facing.x)
        height = self.style["mech_height_pixels"]
        width = self.style["mech_width_pixels"]

        def point(forward, lateral, z):
            return self.project(actor.position + facing * forward + side * lateral, camera, z)

        self.ellipse(x, y + 2, width * 1.5, 16, c["background"], 0.8)
        if actor.dash is not None:
            back = actor.position - actor.dash.direction * 26
            tip = self.project(back - actor.dash.direction * 38, camera, 9)
            self.polygon([self.project(back + side * 9, camera, 12), tip,
                          self.project(back - side * 9, camera, 12)], c["accent"], 0.75)
        stride = 0 if actor.dash else sin(actor.travel_units / 14) * 7
        for sign in (-1, 1):
            foot = point(stride * sign + 3, sign * width * 0.28, 3)
            knee = point(-stride * sign * 0.25, sign * width * 0.25, height * 0.28)
            hip = point(0, sign * width * 0.20, height * 0.43)
            r.line(*hip, *knee, color)
            r.line(*knee, *foot, color)
            r.rect(Rect(foot[0] - 7, foot[1] - 4, 14, 8), color)
        torso = [point(-9, -width * 0.4, height * 0.8), point(12, -width * 0.4, height * 0.8),
                 point(12, width * 0.4, height * 0.8), point(-9, width * 0.4, height * 0.8)]
        self.polygon([(px, py + 13) for px, py in torso], self.style["wall_side"])
        self.polygon(torso, color)
        for first, second in zip(torso, torso[1:] + torso[:1]):
            r.line(*first, *second, c["text"], 0.6)
        head = point(3, 0, height)
        r.rect(Rect(head[0] - 8, head[1] - 5, 16, 12), color)
        visor = point(11, 0, height - 2)
        self.ellipse(*visor, 8, 5, c["background"])
        r.line(*point(3, -width * 0.55, height * 0.65), *point(15, -width * 0.58, height * 0.5), color)
        self.weapon(actor, world, point, color)

    def weapon(self, actor, world, point, color):
        r = self.renderer
        attack = actor.attack
        ranged = actor.owner == "player" and world.weapon_kind == "ranged"
        hand = point(13, 17, 27)
        if ranged:
            end = point(48, 17, 27)
            r.line(*hand, *end, color)
            r.line(hand[0], hand[1] - 2, end[0], end[1] - 2, color)
            if world.shot_remaining_seconds > world.config.shot_interval_seconds * 0.6:
                self.ellipse(*end, 12, 9, self.config.colors["warning"])
            return
        if attack is None:
            end = point(39, 20, 10)
            r.line(*hand, *end, color)
            return
        direction = attack.direction
        base = actor.position + direction * 14
        progress = max(0, min(1, (attack.elapsed_seconds - attack.windup_seconds) / attack.active_seconds))
        angle = atan2(direction.y, direction.x)
        if attack.combo_index == 1:
            angle += -1.1 + progress * 2.2
        elif attack.combo_index == 3:
            angle += 1.1 - progress * 2.2
        elif attack.phase == "windup":
            angle -= 0.9
        blade_reach = max(0, attack.reach_units - 14)
        length = blade_reach if attack.phase == "active" else blade_reach * 0.64
        if attack.combo_index == 2:
            length = blade_reach * (0.45 + progress * 0.55)
        z = 24 + (1 - progress) * 30 if attack.combo_index == 0 else 28
        tip = base + Vec2(cos(angle), sin(angle)) * length
        start_screen = self.project(base, world.player.position, 28)
        end_screen = self.project(tip, world.player.position, z)
        r.line(*hand, *start_screen, color)
        r.line(*start_screen, *end_screen, color)
        r.line(start_screen[0] + 1, start_screen[1], end_screen[0] + 1, end_screen[1], color)
        # 타격 중의 실제 무기 잔상만 표시한다. 공격 전 범위·경고 표시는 없다.
        if attack.phase == "active":
            previous_tip = base + Vec2(cos(angle - 0.22), sin(angle - 0.22)) * length
            r.line(*start_screen, *self.project(previous_tip, world.player.position, z), color, 0.3)

    def hud_state(self, world):
        enemy = world.enemy
        screen_x, screen_y = self.project(enemy.position, world.player.position)
        relative = enemy.position - world.player.position
        contact = RadarContact(relative.x / 1400, relative.y / 1400, screen_x, screen_y)
        return HudState(
            Health(world.player.health, world.player.maximum_health),
            TargetInfo("훈련 기체", Health(enemy.health, enemy.maximum_health)) if enemy.alive else None,
            world.hit_count, world.total_damage, (contact,) if enemy.alive else (),
            -1 if world.player.facing.x < 0 else 1,
            (LoadoutInfo(WeaponInfo("카타나"), WeaponInfo("기관단총", world.ammo)),), 0, world.weapon_kind)

    def draw(self, world, mouse, damage_visuals, weapon_swap, health_trails, counters, *, paused=False, started=True):
        self.terrain(world)
        objects = [(wall.y, "wall", wall) for wall in world.arena.walls]
        objects.extend((actor.position.y, "actor", actor) for actor in (world.player, world.enemy))
        for _, kind, item in sorted(objects, key=lambda item: -item[0]):
            if kind == "wall":
                self.wall(item, world.player.position)
            else:
                self.actor(item, world)
        for bullet in world.bullets:
            start = self.project(bullet.position - bullet.direction * 12, world.player.position, 23)
            self.renderer.line(*start, *self.project(bullet.position, world.player.position, 23),
                               self.config.colors["warning"])
        anchor_x, anchor_y = self.config.actor_anchor("player")
        popup_offset_x = anchor_x - world.player.position.x
        popup_offset_y = anchor_y + world.player.position.y * self.scale_y
        popups = tuple(replace(v, x=v.x + popup_offset_x, y=v.y + popup_offset_y) for v in damage_visuals)
        damage, hits, visibility = counters
        self.hud.combat(self.hud_state(world), popups, 1, 0,
                        counter_visual=damage.visual, combo_visual=hits.visual,
                        counters_opacity=visibility.opacity, cursor_position=mouse,
                        player_trailing_ratio=health_trails[0].trailing_ratio,
                        target_trailing_ratio=health_trails[1].trailing_ratio,
                        weapon_swap_visual=weapon_swap.visual)
        self.instructions(world)
        if world.result != "running":
            self.overlay("훈련 성공" if world.result == "victory" else "기체 파괴", "R 재시작  ·  F10 종료")
        elif paused:
            self.overlay("일시정지" if started else "교전 훈련", "Enter 시작 / 계속  ·  F10 종료")

    def instructions(self, world):
        r, c = self.renderer, self.config.colors
        height = self.config.window["height"]
        r.rect(Rect(20, height - 100, 680, 82), c["background"], 0.88)
        r.text("WASD 이동  ·  Shift 달리기  ·  Space 대시  ·  E 무기 전환",
               32, height - 88, "small", c["muted"])
        r.text("좌클릭 공격  ·  우클릭 총 조준  ·  Esc 일시정지  ·  R 재시작",
               32, height - 62, "small", c["muted"])
        status = f"HP {world.player.health}/{world.player.maximum_health}  ·  F10 종료"
        if world.ammo < world.config.magazine_rounds:
            if world.ammo_recovery_wait_seconds > 1e-9:
                status += f"  ·  탄약 회복 대기 {world.ammo_recovery_wait_seconds:.1f}초"
            else:
                status += f"  ·  탄약 회복 +{world.ammo_recovery_rate_rounds_per_second:.1f}/초"
        elif world.weapon_kind == "melee" and world.player.attack:
            status += f"  ·  검 {world.player.attack.combo_index + 1}타"
        r.text(status, 32, height - 36, "small", c["text"])

    def overlay(self, title, detail):
        r, c = self.renderer, self.config.colors
        width, height = self.config.window["width"], self.config.window["height"]
        r.rect(Rect(0, 0, width, height), c["background"], 0.7)
        r.rect(Rect(width / 2 - 220, height / 2 - 76, 440, 152), c["panel_surface"], 0.96)
        r.text(title, width / 2, height / 2 - 44, "heading", c["text"], align="center")
        r.text(detail, width / 2, height / 2 + 14, "body", c["muted"], align="center")
