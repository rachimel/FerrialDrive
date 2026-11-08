"""메카 디자인 설정. Blender를 불러오거나 파일을 수정하지 않는다."""
from dataclasses import dataclass, field
from math import isfinite


def vector3(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f'{label}: 숫자3개 필요')
    result = tuple(float(x) for x in value)
    if not all(isfinite(x) for x in result):
        raise ValueError(f'{label}: 유한한 숫자 필요')
    return result


def known_fields(cls, data):
    unknown = set(data) - set(cls.__dataclass_fields__)
    if unknown:
        raise ValueError(f'{cls.__name__}: 알 수 없는 항목 {sorted(unknown)}')


@dataclass
class ProfileEdit:
    """부위 경계 기준0~1 위치별 축 배율/이동량. 중간 값은 선형 보간한다."""
    along_axis: str
    deform_axis: str
    knots: list

    def __post_init__(self):
        if self.along_axis not in 'XYZ' or len(self.along_axis) != 1:
            raise ValueError('along_axis는 X/Y/Z')
        if self.deform_axis not in 'XYZ' or len(self.deform_axis) != 1:
            raise ValueError('deform_axis는 X/Y/Z')
        if self.along_axis == self.deform_axis:
            raise ValueError('프로파일 기준축과 변형축은 달라야 한다')
        self.knots = [vector3(k, '프로파일 [위치, 배율, 이동]') for k in self.knots]
        if len(self.knots) < 2 or self.knots[0][0] != 0 or self.knots[-1][0] != 1:
            raise ValueError('프로파일은0에서 시작하고1에서 끝나야 한다')
        if any(a[0] >= b[0] for a, b in zip(self.knots, self.knots[1:])):
            raise ValueError('프로파일 위치는 오름차순이어야 한다')
        if any(k[1] <= 0 for k in self.knots):
            raise ValueError('프로파일 배율은 양수여야 한다')


@dataclass
class PartEdit:
    part: str
    scale: tuple = (1, 1, 1)
    offset: tuple = (0, 0, 0)
    pivot: tuple | None = None
    profiles: list = field(default_factory=list)

    def __post_init__(self):
        self.scale = vector3(self.scale, 'scale')
        self.offset = vector3(self.offset, 'offset')
        if any(x <= 0 for x in self.scale):
            raise ValueError('scale은 양수여야 한다')
        if self.pivot is not None:
            self.pivot = vector3(self.pivot, 'pivot')
        parsed = []
        for item in self.profiles:
            known_fields(ProfileEdit, item)
            parsed.append(ProfileEdit(**item))
        self.profiles = parsed


@dataclass
class BoneEdit:
    bone: str
    head_offset: tuple = (0, 0, 0)
    tail_offset: tuple = (0, 0, 0)
    roll_offset_degrees: float = 0

    def __post_init__(self):
        self.head_offset = vector3(self.head_offset, 'head_offset')
        self.tail_offset = vector3(self.tail_offset, 'tail_offset')
        self.roll_offset_degrees = float(self.roll_offset_degrees)
        if not isfinite(self.roll_offset_degrees):
            raise ValueError('본 roll은 유한해야 한다')


@dataclass
class MaterialEdit:
    material: str
    base_color: tuple | None = None
    metallic: float | None = None
    roughness: float | None = None

    def __post_init__(self):
        if self.base_color is not None:
            if len(self.base_color) != 4:
                raise ValueError('base_color는 RGBA4개')
            self.base_color = tuple(float(x) for x in self.base_color)
            if not all(isfinite(x) and 0 <= x <= 1 for x in self.base_color):
                raise ValueError('색상 범위는0~1')
        for name in ('metallic', 'roughness'):
            value = getattr(self, name)
            if value is not None:
                value = float(value)
                if not isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f'{name} 범위는0~1')
                setattr(self, name, value)


@dataclass
class MountEdit:
    """부착 계층 전체를 옮기고 기존 조절 속성을 바꾼다."""
    mount: str
    offset: tuple = (0, 0, 0)
    controls: dict = field(default_factory=dict)

    def __post_init__(self):
        self.offset = vector3(self.offset, 'mount offset')


@dataclass
class DesignConfig:
    name: str = 'v061_baseline'
    parts: list = field(default_factory=list)
    bones: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    controls: dict = field(default_factory=dict)
    mounts: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        known_fields(cls, data)
        values = dict(data)
        for key, item_cls in [('parts', PartEdit), ('bones', BoneEdit), ('materials', MaterialEdit), ('mounts', MountEdit)]:
            values[key] = []
            for item in data.get(key, []):
                known_fields(item_cls, item)
                values[key].append(item_cls(**item))
        return cls(**values)
