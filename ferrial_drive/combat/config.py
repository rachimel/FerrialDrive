"""전투 수치와 공개 도형 훈련장. 거리 단위는 월드 단위, 시간은 초다."""

from dataclasses import dataclass, fields
import json
from math import isfinite
from pathlib import Path


@dataclass(frozen=True)
class Wall:
    x: float
    y: float
    width: float
    height: float

    def expanded(self, margin):
        return Wall(self.x - margin, self.y - margin,
                    self.width + margin * 2, self.height + margin * 2)


@dataclass(frozen=True)
class Arena:
    width_units: float = 1600
    height_units: float = 1200
    player_spawn: tuple[float, float] = (560, 460)
    enemy_spawn: tuple[float, float] = (980, 600)
    walls: tuple[Wall, ...] = ()

    def __post_init__(self):
        if not all(isfinite(v) and v > 0 for v in (self.width_units, self.height_units)):
            raise ValueError("훈련장 크기는 양수여야 한다.")
        for point in (self.player_spawn, self.enemy_spawn):
            if (len(point) != 2 or not all(isfinite(v) for v in point)
                    or not 0 <= point[0] <= self.width_units
                    or not 0 <= point[1] <= self.height_units):
                raise ValueError("출현 위치는 훈련장 안의 유한한 2차원 좌표여야 한다.")
        for wall in self.walls:
            if (not all(isfinite(v) for v in (wall.x, wall.y, wall.width, wall.height))
                    or wall.width <= 0 or wall.height <= 0
                    or wall.x < 0 or wall.y < 0
                    or wall.x + wall.width > self.width_units
                    or wall.y + wall.height > self.height_units):
                raise ValueError("장애물은 훈련장 안의 양수 크기 사각형이어야 한다.")


@dataclass(frozen=True)
class CombatConfig:
    fixed_step_seconds: float = 1 / 120
    max_frame_seconds: float = 0.25
    actor_radius_units: float = 20
    player_health: int = 240
    enemy_health: int = 480
    walk_speed_units_per_second: float = 360
    sprint_speed_units_per_second: float = 576
    enemy_speed_units_per_second: float = 220
    dash_distance_units: float = 300
    dash_duration_seconds: float = 0.20
    dash_attack_window_seconds: float = 0.08
    sword_windup_seconds: float = 0.07
    sword_active_seconds: float = 0.08
    sword_recovery_seconds: float = 0.13
    sword_reach_units: float = 125
    sword_half_angle_degrees: float = 55
    sword_step_units: float = 24
    sword_damage: int = 40
    combo_buffer_seconds: float = 0.12
    combo_reset_seconds: float = 0.80
    swap_cooldown_seconds: float = 0.28
    enemy_windup_seconds: float = 0.30
    enemy_active_seconds: float = 0.14
    enemy_recovery_seconds: float = 0.50
    enemy_reach_units: float = 100
    enemy_half_angle_degrees: float = 48
    enemy_step_units: float = 46
    enemy_damage: int = 32
    enemy_path_refresh_seconds: float = 0.30
    magazine_rounds: int = 45
    shot_interval_seconds: float = 0.085
    ammo_recovery_delay_seconds: float = 1.0
    ammo_recovery_initial_rounds_per_second: float = 2.0
    ammo_recovery_growth_per_second: float = 1.6
    bullet_speed_units_per_second: float = 1100
    bullet_range_units: float = 900
    bullet_radius_units: float = 3
    bullet_damage: int = 9
    hip_spread_degrees: float = 5
    aim_spread_degrees: float = 0.6

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"{field.name}: 양수인 유한한 수치가 필요하다.")
        for key in ("player_health", "enemy_health", "sword_damage", "enemy_damage",
                    "bullet_damage", "magazine_rounds"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key}: 양수인 정수가 필요하다.")
        if not self.fixed_step_seconds <= self.max_frame_seconds <= 1:
            raise ValueError("고정 갱신 간격 ≤ 최대 프레임 시간 ≤ 1초여야 한다.")
        if self.dash_attack_window_seconds > self.dash_duration_seconds:
            raise ValueError("대시 공격 입력 구간은 대시 시간 이하여야 한다.")
        if max(self.sword_half_angle_degrees, self.enemy_half_angle_degrees) >= 90:
            raise ValueError("근접 공격 반각은 90도 미만이어야 한다.")


def load_scenario(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    scene = dict(data["arena"])
    scene["walls"] = tuple(Wall(**entry) for entry in scene.get("walls", ()))
    for key in ("player_spawn", "enemy_spawn"):
        scene[key] = tuple(scene[key])
    return CombatConfig(**data["combat"]), Arena(**scene), data["presentation"]
