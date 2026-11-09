"""모델 매핑 프리셋과 동작 범위의 순서 일괄 적용."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .mech_plan import DIRECTIONS, ENERGY_MODES, LAYERS, default_plan
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
        set_order(plan["motions"][motion_key], target, defaults[source], frame)


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
    data = {"version": 1, "name": name, "layers": {
        key: {field: deepcopy(plan["layers"][key][field]) for field in ("objects", "anchor", "empty_hand", "energy_mask")}
        for key, _, _ in LAYERS}}
    path = Path(root) / (sha256(name.encode("utf-8")).hexdigest()[:24] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def mapping_options(root=PRESETS):
    result = [("default", "기본 부착점")]
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
            plan["layers"][key]["anchor"] = anchor
        return
    data = json.loads(Path(preset).read_text(encoding="utf-8"))
    if data["version"] != 1:
        raise ValueError("지원하지 않는 매핑 프리셋")
    candidate = deepcopy(plan["layers"])
    for key, _, _ in LAYERS:
        if key not in data["layers"]:
            continue
        row = data["layers"][key]
        if (any(not isinstance(row[field], str) for field in ("objects", "anchor", "empty_hand"))
                or not isinstance(row["energy_mask"], dict)
                or row["energy_mask"].get("mode") not in dict(ENERGY_MODES)
                or not isinstance(row["energy_mask"].get("source"), str)):
            raise ValueError("매핑 프리셋 형식 오류")
        candidate[key].update({field: deepcopy(row[field]) for field in ("objects", "anchor", "empty_hand", "energy_mask")})
    # 동작·이벤트·시트 경로는 프리셋에 의해 교체하지 않는다.
    plan["layers"] = candidate
