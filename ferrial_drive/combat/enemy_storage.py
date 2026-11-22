"""출현 순서를 유지하는 교전 적 컴포넌트 저장소."""

from collections.abc import ItemsView, MutableMapping, ValuesView
from ctypes import Structure, c_bool, c_byte, c_double, c_int64
from dataclasses import dataclass, fields

from .entity_storage import DenseStorage, integer_field, scalar_field, vector_field
from .geometry import Vec2


PHASES = ("move", "windup", "active", "recovery", "stagger", "break")
MOVE, WINDUP, ACTIVE, RECOVERY, STAGGER, BREAK = range(len(PHASES))
ATTACK_KINDS = ("melee", "ranged")
MELEE, RANGED = range(len(ATTACK_KINDS))


class EnemyRecord(Structure):
    _fields_ = [
        ("x", c_double), ("y", c_double), ("fx", c_double), ("fy", c_double),
        ("radius", c_double), ("speed", c_double), ("melee_reach", c_double),
        ("fire_distance", c_double), ("preferred", c_double),
        ("travel", c_double), ("walk", c_double), ("walk_x", c_double), ("walk_y", c_double),
        ("push_x", c_double), ("push_y", c_double), ("push_remaining", c_double), ("push_duration", c_double),
        ("death_remaining", c_double), ("remaining", c_double), ("break_duration", c_double),
        ("health", c_int64), ("interrupts", c_bool), ("hit_player", c_bool),
        ("phase", c_byte), ("attack_kind", c_byte),
    ]


@dataclass
class EncounterEnemy:
    enemy_id: str
    profile: object
    position_m: Vec2
    health: int
    facing: Vec2 = Vec2(-1, 0)
    phase: str = "move"
    attack_kind: str = "melee"
    remaining_seconds: float = 0
    hit_player: bool = False
    travel_m: float = 0
    locomotion_m: float = 0
    locomotion_step_m: Vec2 = Vec2()
    knockback_remaining_seconds: float = 0
    knockback_velocity_mps: Vec2 = Vec2()
    knockback_duration_seconds: float = .12
    knockback_interrupts: bool = False
    death_remaining_seconds: float = 0
    break_duration_seconds: float = 0

    @property
    def alive(self):
        return self.health > 0

    @property
    def attack_polygon(self):
        length = self.profile.melee_reach_m
        position, facing = self.position_m, self.facing
        side = Vec2(-facing.y, facing.x) * (length * .3)
        end = position + facing * length
        return (position - side, end - side, end + side, position + side)


ENEMY_FIELDS = tuple(field.name for field in fields(EncounterEnemy))


class EnemyView(EncounterEnemy):
    position_m = vector_field("x", "y")
    facing = vector_field("fx", "fy")
    remaining_seconds = scalar_field("remaining")
    hit_player = scalar_field("hit_player")
    travel_m = scalar_field("travel")
    locomotion_m = scalar_field("walk")
    locomotion_step_m = vector_field("walk_x", "walk_y")
    knockback_remaining_seconds = scalar_field("push_remaining")
    knockback_velocity_mps = vector_field("push_x", "push_y")
    knockback_duration_seconds = scalar_field("push_duration")
    knockback_interrupts = scalar_field("interrupts")
    death_remaining_seconds = scalar_field("death_remaining")
    break_duration_seconds = scalar_field("break_duration")
    health = integer_field("health")

    @property
    def alive(self):
        return self._record.health > 0

    def __init__(self, eid=None, enemy=None, **values):
        self.eid = eid
        self._record = EnemyRecord()
        if enemy is not None:
            values = {name: getattr(enemy, name) for name in ENEMY_FIELDS}
        for name, value in values.items():
            setattr(self, name, value)

    @property
    def position_xy(self):
        record = self._record
        return record.x, record.y

    @property
    def profile(self):
        return self._profile

    @profile.setter
    def profile(self, profile):
        self._profile = profile
        record = self._record
        record.radius, record.speed = profile.radius_m, profile.speed_mps
        record.melee_reach = profile.melee_reach_m if profile.kind != "medium" else -1.
        record.fire_distance = profile.fire_range_m if profile.kind != "small" else -1.
        record.preferred = profile.preferred_range_m

    @property
    def phase(self):
        return PHASES[self._record.phase]

    @phase.setter
    def phase(self, name):
        self._record.phase = PHASES.index(name)

    @property
    def attack_kind(self):
        return ATTACK_KINDS[self._record.attack_kind]

    @attack_kind.setter
    def attack_kind(self, name):
        self._record.attack_kind = ATTACK_KINDS.index(name)

    def __eq__(self, other):
        if not isinstance(other, EncounterEnemy):
            return NotImplemented
        return all(getattr(self, name) == getattr(other, name) for name in ENEMY_FIELDS)

    def __deepcopy__(self, memo):
        return EncounterEnemy(*(getattr(self, name) for name in ENEMY_FIELDS))


class EnemyValues(ValuesView):
    def __iter__(self):
        return iter(self._mapping.storage.views)


class EnemyItems(ItemsView):
    def __iter__(self):
        return zip(self._mapping, self._mapping.storage.views)


class EnemyActors(MutableMapping):
    def __init__(self, registry, capacity):
        self.storage = DenseStorage(registry, EnemyRecord, capacity, ordered=True, on_remove=self._removed)
        self._ids = {}

    def _removed(self, view):
        del self._ids[view._key]

    def __len__(self):
        return len(self._ids)

    def __iter__(self):
        return iter(self._ids)

    def values(self):
        return EnemyValues(self)

    def items(self):
        return EnemyItems(self)

    def __getitem__(self, key):
        return self.storage[self._ids[key]]

    def __setitem__(self, key, enemy):
        registry = self.storage.registry
        eid = registry.create()
        try:
            view = EnemyView(eid, enemy)
        except BaseException:
            registry.release(eid)
            raise
        view._key = key
        previous = self._ids.get(key)
        if previous is None:
            self.storage.append(eid, view, view._record)
        else:
            self.storage.replace(previous, eid, view, view._record)
            registry.release(previous)
        self._ids[key] = eid

    def __delitem__(self, key):
        self.storage.registry.release(self._ids[key])

    def clear(self):
        while self._ids:
            self.storage.registry.release(self._ids[next(reversed(self._ids))])
