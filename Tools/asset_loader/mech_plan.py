"""메카 분리 출력 작업본. 실제 렌더·게임 실행 상태와 분리한다."""

from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from .production import WORKSPACE, frame_numbers


LAYERS = (
    ("body", "메카 본체 · 손목까지", "root"),
    ("left_hand", "왼손 + 무기", "wrist_l"),
    ("right_hand", "오른손 + 무기", "wrist_r"),
    ("stowed_sword", "수납 검", "sword_mount"),
    ("stowed_gun", "수납 총", "waist_mount"),
    ("sheath", "칼집 + 부착부", "sword_mount"),
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
    """기존 v1 입력을 보존하며 신규 선택 항목만 채운다."""
    data = deepcopy(data)
    for key, _, _ in LAYERS:
        data["layers"][key].setdefault("energy_mask", default_energy_mask())
    for key, _ in ENERGY_CHECKS:
        data["checks"].setdefault(key, "미확인")
    return data


def default_plan(asset_id, source):
    orders = {}
    for direction in DIRECTIONS:
        hands = ["left_hand", "right_hand"]
        orders[direction] = (["sheath", "stowed_sword", "stowed_gun"]
                             + (hands + ["body"] if direction in ("n", "ne", "nw") else ["body"] + hands)
                             + ["detached_sword", "detached_gun"])
    return {
        "version": 1, "asset_id": asset_id, "source": str(Path(source).resolve()),
        "render": {"camera": "", "frames": "1,3,5,7", "fps": "8", "width": "240",
                   "height": "240", "scale": "4.5", "pivot": "120,0", "purpose": "combat"},
        "layers": {key: {"objects": "", "anchor": anchor, "empty_hand": "", "energy_mask": default_energy_mask()}
                   for key, _, anchor in LAYERS},
        "motions": {key: {"clip": key, "frames": "", "reuse": "", "notes": "",
                          "events": [], "orders": deepcopy(orders), "overrides": [],
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
    if (data["version"] != 1 or data["asset_id"] != asset_id
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
    keys = {key for key, _, _ in LAYERS}
    for key in keys:
        for field in ("objects", "anchor", "empty_hand"):
            if not isinstance(data["layers"][key][field], str):
                raise ValueError("레이어 오브젝트·부착점은 문자열이어야 한다.")
        mask = data["layers"][key].get("energy_mask", default_energy_mask())
        if (not isinstance(mask, dict) or mask.get("mode") not in dict(ENERGY_MODES)
                or not isinstance(mask.get("source"), str)):
            raise ValueError("에너지 마스크의 분리 방식·입력 이름 오류")
    for key, _ in MOTIONS:
        motion = data["motions"][key]
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
