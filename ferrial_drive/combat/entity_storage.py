"""교전의 세대 핸들과 연속 레코드 저장소."""

from ctypes import addressof, memmove, sizeof

from .geometry import Vec2


SLOT_BITS = 32
SLOT_MASK = (1 << SLOT_BITS) - 1


class EntityRegistry:
    def __init__(self):
        self._generations = []
        self._alive = []
        self._free = []
        self._stores = []

    def create(self):
        if self._free:
            slot = self._free.pop()
            self._alive[slot] = True
        else:
            slot = len(self._generations)
            if slot > SLOT_MASK:
                raise OverflowError("엔티티 슬롯 한도 초과")
            self._generations.append(1)
            self._alive.append(True)
        return self._generations[slot] << SLOT_BITS | slot

    def valid(self, eid):
        slot = eid & SLOT_MASK
        return (slot < len(self._generations) and self._alive[slot]
                and self._generations[slot] == eid >> SLOT_BITS)

    def release(self, eid):
        if not self.valid(eid):
            raise KeyError(eid)
        for store in self._stores:
            store._remove(eid)
        slot = eid & SLOT_MASK
        self._alive[slot] = False
        self._generations[slot] += 1
        self._free.append(slot)


class DenseStorage:
    """슬롯으로 행을 찾는다. ordered 저장소는 삭제 뒤에도 순회 순서를 유지한다."""

    def __init__(self, registry, record_type, capacity=0, *, ordered=False, on_remove=None):
        self.registry, self.record_type, self.ordered = registry, record_type, ordered
        self.records = (record_type * capacity)()
        self.eids, self.views = [], []
        self._sparse = []
        self.on_remove = on_remove
        registry._stores.append(self)

    def index(self, eid):
        slot = eid & SLOT_MASK
        if slot < len(self._sparse):
            row = self._sparse[slot]
            if row >= 0 and self.eids[row] == eid:
                return row
        raise KeyError(eid)

    def __getitem__(self, eid):
        return self.views[self.index(eid)]

    def _grow(self):
        records = (self.record_type * max(8, 2 * len(self.records)))()
        memmove(records, self.records, sizeof(self.records))
        self.records = records
        for row, view in enumerate(self.views):
            view._record = records[row]

    def _reserve_slot(self, eid):
        if not self.registry.valid(eid):
            raise KeyError(eid)
        slot = eid & SLOT_MASK
        if slot >= len(self._sparse):
            self._sparse.extend([-1] * (slot + 1 - len(self._sparse)))
        if self._sparse[slot] >= 0:
            raise ValueError("이미 등록된 컴포넌트")
        return slot

    def append(self, eid, view, record):
        slot = self._reserve_slot(eid)
        row = len(self.views)
        if row == len(self.records):
            self._grow()
        self.records[row] = record
        view._record = self.records[row]
        self.eids.append(eid)
        self.views.append(view)
        self._sparse[slot] = row

    def replace(self, previous_eid, eid, view, record):
        row = self.index(previous_eid)
        slot = self._reserve_slot(eid)
        self.views[row]._record = self.record_type.from_buffer_copy(self.records[row])
        self._sparse[previous_eid & SLOT_MASK] = -1
        self.records[row] = record
        self.eids[row], self.views[row] = eid, view
        view._record = self.records[row]
        self._sparse[slot] = row

    def _remove(self, eid):
        try:
            row = self.index(eid)
        except KeyError:
            return
        last = len(self.views) - 1
        # 보관 중인 공개 뷰는 삭제 시점의 값을 읽을 수 있다.
        view = self.views[row]
        view._record = self.record_type.from_buffer_copy(self.records[row])
        if self.on_remove is not None:
            self.on_remove(view)
        self._sparse[eid & SLOT_MASK] = -1
        if row != last and self.ordered:
            memmove(addressof(self.records[row]), addressof(self.records[row + 1]),
                    (last - row) * sizeof(self.record_type))
            del self.views[row], self.eids[row]
            for index in range(row, last):
                self._bind_moved_row(index)
            return
        if row != last:
            self.records[row] = self.records[last]
            self.views[row] = self.views[last]
            self.eids[row] = self.eids[last]
            self._bind_moved_row(row)
        self.views.pop()
        self.eids.pop()

    def _bind_moved_row(self, row):
        self._sparse[self.eids[row] & SLOT_MASK] = row
        self.views[row]._record = self.records[row]


def scalar_field(field):
    def read(view):
        return getattr(view._record, field)

    def write(view, value):
        setattr(view._record, field, value)

    return property(read, write)


def vector_field(x, y, vector_type=Vec2):
    def read(view):
        row = view._record
        return vector_type(getattr(row, x), getattr(row, y))

    def write(view, value):
        row = view._record
        first, second = (value.x, value.y) if isinstance(value, Vec2) else value
        setattr(row, x, first)
        setattr(row, y, second)

    return property(read, write)


def integer_field(field):
    """64비트 행을 사용하면서 기존 Python 수치 범위도 보존한다."""
    overflow = f"_overflow_{field}"

    def read(view):
        if overflow in view.__dict__:
            return view.__dict__[overflow]
        return getattr(view._record, field)

    def write(view, value):
        if type(value) is int and -(1 << 63) <= value < (1 << 63):
            view.__dict__.pop(overflow, None)
            setattr(view._record, field, value)
        else:
            view.__dict__[overflow] = value
            setattr(view._record, field, int(value > 0))

    return property(read, write)
