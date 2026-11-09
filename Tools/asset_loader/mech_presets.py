"""모델 매핑 프리셋과 동작 범위의 순서 일괄 적용."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .mech_plan import DIRECTIONS, LAYERS, default_plan, validate_plan, with_energy_defaults
from .part_model import part_defaults, replace_parts
from .production import WORKSPACE


PRESETS = WORKSPACE / "mech_presets"
ORDER_PRESETS = (("front", "정면 · 손+무기 앞"), ("back", "후면 · 본체 앞"), ("directional", "기본 8방향 순서"))


def set_order(motion, direction, order, frame=None):
    if frame is None:
        motion["orders"][direction] = list(order)
        return
    rows = motion["overrides"]
    previous = next((row for row in rows if (row["direction"], row["frame"]) == (direction, frame)), None)
    if previous is None:
        rows.append({"direction": direction, "frame": frame, "order": list(order)})
    else:
        previous["order"] = list(order)


def apply_order_preset(plan, motion_key, direction, preset, frame=None):
    if preset not in dict(ORDER_PRESETS):
        raise ValueError("지원하지 않는 순서 프리셋")
    defaults = default_plan(plan["asset_id"], plan["source"])["motions"][motion_key]["orders"]
    for target in DIRECTIONS if preset == "directional" else (direction,):
        source = target if preset == "directional" else ("n" if preset == "back" else "s")
        current = plan["motions"][motion_key]["orders"][target]
        if frame is not None:
            current = next((row["order"] for row in plan["motions"][motion_key]["overrides"]
                            if (row["direction"], row["frame"]) == (target, frame)), current)
        standard = [key for key in defaults[source] if key in plan["layers"]]
        # 사용자 파츠의 상대 순서는 유지하고 기본 파츠의 위치만 프리셋대로 바꾼다.
        order = iter(standard)
        result = [next(order) if key in standard else key for key in current]
        set_order(plan["motions"][motion_key], target, result, frame)


def apply_all_directions(plan, motion_key, direction, frame=None):
    motion = plan["motions"][motion_key]
    source = motion["orders"][direction] if frame is None else next(
        row["order"] for row in motion["overrides"] if (row["direction"], row["frame"]) == (direction, frame))
    for target in DIRECTIONS:
        set_order(motion, target, source, frame)


def save_mapping(name, plan, *, root=PRESETS):
    name = name.strip()
    if not name or len(name) > 64:
        raise ValueError("프리셋 이름은 1~64자로 작성한다.")
    rows = deepcopy(plan["layers"])
    for row in rows.values():
        for value in [row, *row["states"].values()]:
            value["sheet"], value["energy_sheet"] = "", ""
    data = {"version": 2, "name": name, "layers": rows}
    path = Path(root) / (sha256(name.encode("utf-8")).hexdigest()[:24] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def mapping_options(root=PRESETS):
    result = [("default", "기본 부착점"), ("mech", "메카 기본 구성"), ("npc", "NPC 기본 구성")]
    for path in sorted(Path(root).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append((str(path), str(data["name"])))
        except (OSError, ValueError, KeyError, TypeError):
            result.append((str(path), path.stem + " (읽기 오류)"))
    return result


def apply_mapping(plan, preset):
    if preset == "default":
        for key, _, anchor in LAYERS:
            if key in plan["layers"]:
                plan["layers"][key]["anchor"] = anchor
        return
    if preset in ("mech", "npc"):
        rows = default_plan(plan["asset_id"], plan["source"])["layers"] if preset == "mech" else {"body": part_defaults("본체")}
        data = {"version": 2, "layers": rows}
    else:
        data = json.loads(Path(preset).read_text(encoding="utf-8"))
    if data["version"] not in (1, 2):
        raise ValueError("지원하지 않는 매핑 프리셋")
    candidate = deepcopy(plan)
    if data["version"] == 1:
        for key, row in data["layers"].items():
            if key in candidate["layers"]:
                for field in ("objects", "anchor", "empty_hand", "energy_mask"):
                    candidate["layers"][key][field] = deepcopy(row[field])
    else:
        rows = deepcopy(data["layers"])
        for key, row in rows.items():
            old = plan["layers"].get(key, {})
            for field in ("sheet", "energy_sheet"):
                row[field] = old.get(field, "")
            for state, value in row.get("states", {}).items():
                previous = old.get("states", {}).get(state, {})
                for field in ("sheet", "energy_sheet"):
                    value[field] = previous.get(field, "")
        replace_parts(candidate, rows)
    candidate = with_energy_defaults(candidate)
    validate_plan(candidate, asset_id=plan["asset_id"], source=plan["source"])
    plan.update(candidate)
