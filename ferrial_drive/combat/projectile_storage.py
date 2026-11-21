"""같은 연속 저장소를 쓰는 투영 총탄과 월드 좌표 적 탄환."""

from collections.abc import Sequence
from ctypes import Structure, c_double, c_int64
from dataclasses import dataclass, field, fields
from itertools import islice

from .entity_storage import DenseStorage, integer_field, scalar_field, vector_field
from .geometry import Vec2


class ProjectileRecord(Structure):
    _fields_ = [(name, c_double) for name in (
        "x", "y", "previous_x", "previous_y", "dx", "dy", "remaining", "speed", "traveled", "blast_radius",
    )] + [(name, c_int64) for name in ("damage", "penetration", "blast_damage")]


@dataclass
class EnemyProjectile:
    owner: str
    position_m: Vec2
    previous_m: Vec2
    direction: Vec2
    remaining_m: float
    speed_mps: float
    damage: int


@dataclass
class GunProjectile:
    shot_id: int
    position: Vec2
    direction: Vec2
    remaining_pixels: float
    previous: Vec2
    traveled_pixels: float = 0
    damage: int = 9
    penetrations_remaining: int = 0
    hit_target_ids: set = field(default_factory=set)
    explosion_radius_m: float = 0
    explosion_damage: int = 0


class ProjectileView:
    direction = vector_field("dx", "dy")
    damage = integer_field("damage")

    def __init__(self, eid=None, owner_eid=None, projectile=None, **values):
        self.eid, self.owner_eid = eid, owner_eid
        self._record = ProjectileRecord()
        if projectile is not None:
            values = {name: getattr(projectile, name) for name in self._fields}
        for name, value in values.items():
            setattr(self, name, value)

    def __eq__(self, other):
        if not isinstance(other, self._public_type):
            return NotImplemented
        return all(getattr(self, name) == getattr(other, name) for name in self._fields)


class EnemyProjectileView(ProjectileView, EnemyProjectile):
    _public_type = EnemyProjectile
    _fields = tuple(field.name for field in fields(EnemyProjectile))
    position_m = vector_field("x", "y")
    previous_m = vector_field("previous_x", "previous_y")
    remaining_m = scalar_field("remaining")
    speed_mps = scalar_field("speed")


class GunProjectileView(ProjectileView, GunProjectile):
    _public_type = GunProjectile
    _fields = tuple(field.name for field in fields(GunProjectile))
    position = vector_field("x", "y")
    previous = vector_field("previous_x", "previous_y")
    remaining_pixels = scalar_field("remaining")
    traveled_pixels = scalar_field("traveled")
    penetrations_remaining = integer_field("penetration")
    explosion_radius_m = scalar_field("blast_radius")
    explosion_damage = integer_field("blast_damage")


class ProjectileGroup(Sequence):
    """발사 순서와 갱신 주기를 소유한다. 물리 상태는 공통 저장소에 있다."""

    def __init__(self, storage, view_type):
        self.storage, self.view_type = storage, view_type
        self._active = {}

    def __len__(self):
        return len(self._active)

    def __iter__(self):
        return iter(self._active.values())

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self._active.values())[index]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return next(islice(self._active.values(), index, None))

    def __eq__(self, other):
        if isinstance(other, (ProjectileGroup, list)):
            return list(self) == list(other)
        return NotImplemented

    def spawn(self, owner_eid=None, **values):
        return self._add(owner_eid, None, values)

    def append(self, projectile, *, owner_eid=None):
        self._add(owner_eid, projectile, {})

    def _add(self, owner_eid, projectile, values):
        registry = self.storage.registry
        eid = registry.create()
        try:
            bullet = self.view_type(eid, owner_eid, projectile, **values)
            bullet._group = self
            self.storage.append(eid, bullet, bullet._record)
        except BaseException:
            registry.release(eid)
            raise
        self._active[eid] = bullet
        return bullet

    def discard(self, projectile):
        self.storage.registry.release(projectile.eid)

    def clear(self):
        while self._active:
            self.storage.registry.release(next(reversed(self._active)))


def _remove_projectile(projectile):
    del projectile._group._active[projectile.eid]
    projectile._group = None


def projectile_storage(registry):
    return DenseStorage(registry, ProjectileRecord, on_remove=_remove_projectile)
