"""출력 파츠의 안정적인 ID·상태와 참조를 관리한다. 게임 장비 규칙은 포함하지 않는다."""

from copy import deepcopy
from ferrial_drive.assets.mech import valid_part_id as valid_id


def state_defaults(name):
    return {"name": name, "enabled": True, "objects": "", "clip": "", "sheet": "", "energy_sheet": "",
            "energy_mask": {"mode": "unassigned", "source": ""}}


def part_defaults(name, anchor="root"):
    return {**state_defaults(name), "anchor": anchor, "empty_hand": "", "default_state": "base", "states": {}}


def all_orders(plan):
    for motion in plan["motions"].values():
        yield from motion["orders"].values()
        yield from (row["order"] for row in motion["overrides"])


def add_part(plan, key, name, *, duplicate=None, template=None):
    if not valid_id(key) or key.casefold() in {value.casefold() for value in plan["layers"]}:
        raise ValueError("파츠 ID는 중복 없이 영문·숫자·밑줄로 지정한다. 첫 글자는 영문 또는 밑줄이다.")
    if not name.strip():
        raise ValueError("파츠 이름이 필요하다.")
    row = deepcopy(plan["layers"][duplicate]) if duplicate else part_defaults(name.strip(), "root")
    row["name"] = name.strip()
    if template == "thrusters":
        row["anchor"] = "back_thruster_root"
        row["states"] = {state: state_defaults(label) for state, label in (
            ("vertical", "수직"), ("horizontal", "수평"),
            ("to_horizontal", "수직 → 수평"), ("to_vertical", "수평 → 수직"))}
        row["default_state"] = "vertical"
    plan["layers"][key] = row
    for order in all_orders(plan):
        index = order.index(duplicate) + 1 if duplicate else len(order)
        order.insert(index, key)
    if duplicate:
        for motion in plan["motions"].values():
            if duplicate in motion["part_states"]:
                motion["part_states"][key] = motion["part_states"][duplicate]
    return key


def remove_part(plan, key):
    if key == "body":
        raise ValueError("본체는 공통 프레임 기준 파츠여서 삭제할 수 없다. 표시 이름과 시트는 변경할 수 있다.")
    del plan["layers"][key]
    for order in all_orders(plan):
        order.remove(key)
    for motion in plan["motions"].values():
        motion["part_states"].pop(key, None)


def add_state(plan, part, key, name):
    row = plan["layers"][part]
    if not valid_id(key) or key.casefold() == "base" or key.casefold() in {value.casefold() for value in row["states"]}:
        raise ValueError("상태 ID는 base를 제외한 중복 없는 영문·숫자·밑줄이어야 한다.")
    if not name.strip():
        raise ValueError("상태 이름이 필요하다.")
    row["states"][key] = state_defaults(name.strip())


def remove_state(plan, part, key):
    if key == "base":
        raise ValueError("기본 상태는 삭제할 수 없다.")
    row = plan["layers"][part]
    del row["states"][key]
    if row["default_state"] == key:
        row["default_state"] = "base"
    for motion in plan["motions"].values():
        if motion["part_states"].get(part) == key:
            motion["part_states"].pop(part)


def replace_parts(plan, rows):
    """구성 프리셋의 ID 집합에 맞춰 순서와 상태 참조를 갱신한다."""
    plan["layers"] = deepcopy(rows)
    for order in all_orders(plan):
        order[:] = [key for key in order if key in rows] + [key for key in rows if key not in order]
    for motion in plan["motions"].values():
        motion["part_states"] = {key: state for key, state in motion["part_states"].items()
                                 if key in rows and (state == "base" or state in rows[key]["states"])}
