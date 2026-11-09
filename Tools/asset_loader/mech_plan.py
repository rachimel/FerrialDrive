"""메카 분리 출력 작업본. 실제 렌더·게임 실행 상태와 분리한다."""

from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from .production import WORKSPACE, frame_numbers
from .part_model import part_defaults, state_defaults, valid_id


LAYERS = (
    ("body", "메카 본체 · 손목까지", "root"),
    ("left_hand", "왼손 + 무기", "wrist_l"),
    ("right_hand", "오른손 + 무기", "wrist_r"),
    ("stowed_sword", "수납 검", "sword_mount"),
    ("stowed_gun", "수납 총", "waist_mount"),
    ("sheath", "칼집 + 부착부", "sword_mount"),
    ("side_slot_l", "왼쪽 사이드 슬롯", "side_mount_l"),
    ("side_slot_r", "오른쪽 사이드 슬롯", "side_mount_r"),
    ("detached_sword", "분리된 검", "world"),
    ("detached_gun", "분리된 총", "world"),
)
DIRECTIONS = ("s", "sw", "w", "nw", "n", "ne", "e", "se")
MOTIONS = (
    ("stowed_idle", "수납 대기"), ("stowed_move", "수납 이동"),
    ("draw", "무기 꺼내기"), ("equipped_idle", "장착 대기"),
    ("equipped_move", "장착 이동"), ("slash", "검 공격"),
    ("aim", "총 조준"), ("fire", "총 사격"),
    ("stow", "무기 넣기"), ("eject", "사출 연계"), ("preview", "장비 선택 미리보기"),
)
EVENTS = (
    ("grip", "손잡이 파지"), ("attach_hand", "수납 → 손 부착"),
    ("clear_mount", "칼집·장착부 이탈"), ("attach_mount", "수납 위치 고정"),
    ("release", "손 놓기"), ("detach", "사출 · 독립 이동"),
)
ENERGY_CHECKS = (
    ("energy_base", "색상 출력에 발광 미포함 · 에너지 마스크 별도 출력"),
    ("energy_alignment", "마스크의 프레임·기준점·가림이 소유 레이어와 일치"),
)
ENERGY_MODES = (("unassigned", "미지정"), ("material", "재질 EnergyMask"),
                ("objects", "별도 마스크 오브젝트"), ("none", "에너지 없음"))
CHECKS = (
    ("grip_overlap", "손가락 안쪽 경미 겹침만 허용 · 손등 관통/돌출 수정"),
    ("continuity", "부착 전후 위치·회전 연속 · 무기 중복/누락 없음"),
    ("sword_path", "검 인출 시 도신이 칼집을 통과하는 경로"),
    ("sword_reset", "수납 완료 시 검 기본 길이 복귀"),
    ("stowed_safety", "사출 버튼·안전장치는 수납 상태에서만 작동"),
    ("sheath_energy", "칼집 에너지는 검 표시와 독립적으로 유지"),
    ("gun_alignment", "기관단총 파지·팔 결합부 위치 동시 정렬"),
    ("gun_occlusion", "손목을 넘는 팔 결합부와 팔 장갑 가림 확인"),
) + ENERGY_CHECKS
STATUSES = ("미확인", "확인", "해당 없음")
OCCLUSION = ("미정", "순서만 사용", "추가 분할 필요", "가림 처리 필요")


def default_energy_mask():
    return {"mode": "unassigned", "source": ""}


def with_energy_defaults(data):
    """v1을 동적 파츠 v2로 보완한다. 원본 파일은 변경하지 않는다."""
    data = deepcopy(data)
    if data["version"] == 1:
        for key, _, anchor in LAYERS:
            if key in ("side_slot_l", "side_slot_r") and key not in data["layers"]:
                data["layers"][key] = part_defaults(key, anchor)
                for motion in data["motions"].values():
                    for order in [*motion["orders"].values(), *(row["order"] for row in motion["overrides"])]:
                        order.insert(order.index("body"), key)
        data["version"] = 2
    labels = {key: name for key, name, _ in LAYERS}
    for key, row in data["layers"].items():
        defaults = part_defaults(labels.get(key, key))
        for field, value in defaults.items():
            row.setdefault(field, value)
        for state_key, state in row["states"].items():
            for field, value in state_defaults(state_key).items():
                state.setdefault(field, value)
    for motion in data["motions"].values():
        motion.setdefault("part_states", {})
    for key, _ in ENERGY_CHECKS:
        data["checks"].setdefault(key, "미확인")
    return data


def default_plan(asset_id, source):
    orders = {}
    for direction in DIRECTIONS:
        hands = ["left_hand", "right_hand"]
        orders[direction] = (["sheath", "side_slot_l", "side_slot_r", "stowed_sword", "stowed_gun"]
                             + (hands + ["body"] if direction in ("n", "ne", "nw") else ["body"] + hands)
                             + ["detached_sword", "detached_gun"])
    return {
        "version": 2, "asset_id": asset_id, "source": str(Path(source).resolve()),
        "render": {"camera": "", "frames": "1,3,5,7", "fps": "8", "width": "240",
                   "height": "240", "scale": "4.5", "pivot": "120,0", "purpose": "combat"},
        "layers": {key: part_defaults(name, anchor) for key, name, anchor in LAYERS},
        "motions": {key: {"clip": key, "frames": "", "reuse": "", "notes": "",
                          "events": [], "orders": deepcopy(orders), "overrides": [], "part_states": {},
                          "occlusion": {direction: "미정" for direction in DIRECTIONS}}
                    for key, _ in MOTIONS},
        "checks": {key: "미확인" for key, _ in CHECKS},
        "sword_reset_frame": "", "gun_storage": "허리 수납",
        "deferred": "손·팔 수납, 에임 보정기 접기", "notes": "",
    }


def plan_path(asset_id, source):
    identity = f"{asset_id}\n{Path(source).resolve()}".encode("utf-8")
    return WORKSPACE / "mech_plans" / (sha256(identity).hexdigest()[:24] + ".json")


def validate_plan(data, *, asset_id, source):
    if (data["version"] not in (1, 2) or data["asset_id"] != asset_id
            or Path(data["source"]).resolve() != Path(source).resolve()):
        raise ValueError("다른 에셋 또는 지원하지 않는 메카 작업본이다.")
    render = data["render"]
    frame_numbers(render["frames"])
    for key in ("fps", "width", "height", "scale"):
        value = float(render[key])
        if not isfinite(value) or value <= 0:
            raise ValueError("공통 FPS·크기·배율은 유한한 양수여야 한다.")
        if key != "scale" and not value.is_integer():
            raise ValueError("공통 FPS·크기는 정수여야 한다.")
    if not 1 <= float(render["fps"]) <= 240 or any(not 16 <= float(render[k]) <= 2048 for k in ("width", "height")):
        raise ValueError("FPS는 1~240, 이미지 크기는 16~2048px 범위다.")
    pivot = [float(v) for v in render["pivot"].split(",")]
    if len(pivot) != 2 or any(not isfinite(v) or not 0 <= v <= float(render[k])
                              for v, k in zip(pivot, ("width", "height"))):
        raise ValueError("공통 기준점은 이미지 안의 X,Y 값이어야 한다.")
    if render["purpose"] not in ("combat", "preview"):
        raise ValueError("출력 용도 오류")
    keys = set(data["layers"])
    if "body" not in keys or any(not valid_id(key) for key in keys) or len({key.casefold() for key in keys}) != len(keys):
        raise ValueError("본체 파츠와 유효한 파츠 ID가 필요하다.")
    for key in keys:
        row = data["layers"][key]
        if data["version"] == 2:
            if (not isinstance(row["name"], str) or not row["name"].strip() or type(row["enabled"]) is not bool
                    or row["default_state"] != "base" and row["default_state"] not in row["states"]):
                raise ValueError("파츠 이름·표시 여부·기본 상태 오류")
            for state_key, state in row["states"].items():
                if not valid_id(state_key) or state_key.casefold() == "base":
                    raise ValueError("파츠 상태 ID 오류")
                if not isinstance(state["name"], str) or not state["name"].strip() or type(state["enabled"]) is not bool:
                    raise ValueError("파츠 상태 이름·표시 여부 오류")
            if len({state.casefold() for state in row["states"]}) != len(row["states"]):
                raise ValueError("대소문자만 다른 상태 ID는 사용할 수 없다.")
            for value in [row, *row["states"].values()]:
                for field in ("objects", "clip", "sheet", "energy_sheet"):
                    if not isinstance(value[field], str):
                        raise ValueError("파츠 상태의 입력·시트 경로 오류")
                mask = value["energy_mask"]
                if not isinstance(mask, dict) or mask.get("mode") not in dict(ENERGY_MODES) or not isinstance(mask.get("source"), str):
                    raise ValueError("에너지 마스크의 분리 방식·입력 이름 오류")
        for field in ("objects", "anchor", "empty_hand"):
            if not isinstance(data["layers"][key][field], str):
                raise ValueError("레이어 오브젝트·부착점은 문자열이어야 한다.")
        for field in ("sheet", "energy_sheet"):
            if not isinstance(data["layers"][key].get(field, ""), str):
                raise ValueError("분리 시트 경로는 문자열이어야 한다.")
        mask = data["layers"][key].get("energy_mask", default_energy_mask())
        if (not isinstance(mask, dict) or mask.get("mode") not in dict(ENERGY_MODES)
                or not isinstance(mask.get("source"), str)):
            raise ValueError("에너지 마스크의 분리 방식·입력 이름 오류")
    for key, _ in MOTIONS:
        motion = data["motions"][key]
        for owner, state in motion.get("part_states", {}).items():
            if owner not in keys or state != "base" and state not in data["layers"][owner].get("states", {}):
                raise ValueError("동작의 파츠 상태 참조 오류")
        frames = frame_numbers(motion["frames"] or render["frames"])
        for field in ("clip", "reuse", "notes"):
            if not isinstance(motion[field], str):
                raise ValueError("동작 정보 형식 오류")
        for direction in DIRECTIONS:
            order = motion["orders"][direction]
            if len(order) != len(keys) or set(order) != keys:
                raise ValueError("그리기 순서는 각 출력 단위를 한 번씩 포함해야 한다.")
            if motion["occlusion"][direction] not in OCCLUSION:
                raise ValueError("가림 처리 상태 오류")
        unique_events = set()
        for event in motion["events"]:
            identity = (event["kind"], event["side"], event["weapon"])
            if (event["kind"] not in dict(EVENTS) or event["side"] not in ("left", "right")
                    or event["weapon"] not in ("sword", "gun") or identity in unique_events
                    or type(event["frame"]) is not int or event["frame"] not in frames):
                raise ValueError("전환 시점은 선택 동작의 Blender 프레임이며 종류·손·무기별로 한 번 지정한다.")
            unique_events.add(identity)
        unique_overrides = set()
        for row in motion["overrides"]:
            identity = (row["direction"], row["frame"])
            if (row["direction"] not in DIRECTIONS or type(row["frame"]) is not int or row["frame"] not in frames
                    or identity in unique_overrides or len(row["order"]) != len(keys) or set(row["order"]) != keys):
                raise ValueError("프레임별 순서의 방향·프레임·출력 단위 오류")
            unique_overrides.add(identity)
    if data["sword_reset_frame"] and int(data["sword_reset_frame"]) not in frame_numbers(data["motions"]["stow"]["frames"] or render["frames"]):
        raise ValueError("검 길이 복귀 시작은 수납 동작 프레임에서 지정한다.")
    for key, _ in CHECKS:
        status = data["checks"].get(key, "미확인") if key in dict(ENERGY_CHECKS) else data["checks"][key]
        if status not in STATUSES:
            raise ValueError("확인 상태 오류")


def load_plan(path, *, asset_id, source):
    try:
        data = with_energy_defaults(json.loads(Path(path).read_text(encoding="utf-8")))
        validate_plan(data, asset_id=asset_id, source=source)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("메카 작업본의 필수 항목·자료형 오류") from error
    return data


def save_plan(path, data):
    data = with_energy_defaults(data)
    validate_plan(data, asset_id=data["asset_id"], source=data["source"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
