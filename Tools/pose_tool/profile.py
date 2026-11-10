"""Blender와 분리한 리그 매핑·동작 범위 계약."""

from copy import deepcopy
import json
from pathlib import Path


def default_profile():
    return {
        "version": 1, "rig": "PlayerRigidRig", "mirror_axis": "Y",
        "body": {"pelvis": "Pelvis", "waist": "Waist", "chest": "Chest", "head": "Head",
                 "shoulder.L": "ShoulderWingUpper.L", "shoulder.R": "ShoulderWingUpper.R"},
        "limbs": {f"{part}.{side}": {"upper": upper + "." + side,
                                    "lower": lower + "." + side, "end": end + "." + side}
                  for part, upper, lower, end in (("hand", "UpperArm", "Forearm", "Hand"),
                                                ("foot", "Thigh", "Shin", "Foot"))
                  for side in ("L", "R")},
        "equipment": {"object": "BasicWeapons", "properties": ["sword_stowed", "gun_stowed"],
                      "main_hand": "R", "support_hand": "L"},
    }


def validate_profile(profile):
    data = deepcopy(profile)
    if data.get("version") != 1 or data.get("mirror_axis") not in ("X", "Y", "Z"):
        raise ValueError("리그 매핑 버전/대칭축 오류")
    if not isinstance(data.get("rig"), str) or not data["rig"]:
        raise ValueError("Armature 이름이 필요하다.")
    names = list(data.get("body", {}).values())
    for key, limb in data.get("limbs", {}).items():
        if key not in ("hand.L", "hand.R", "foot.L", "foot.R"):
            raise ValueError(f"지원하지 않는 팔다리: {key}")
        names.extend(limb[field] for field in ("upper", "lower", "end"))
    if len(set(names)) != len(names) or not names:
        raise ValueError("본 매핑 중복 또는 빈 매핑")
    return data


def load_profile(path=None):
    return validate_profile(json.loads(Path(path).read_text(encoding="utf-8")) if path else default_profile())


def clip_ranges(scene, metadata=None):
    """명시한 표본 범위를 우선하고 없으면 Timeline Marker를 사용한다."""
    if metadata:
        clips = []
        for item in metadata["clips"]:
            frames = item["frames"]
            if not frames or any(type(f) is not int for f in frames) or frames != sorted(set(frames)):
                raise ValueError("동작 프레임은 정렬한 고유 정수여야 한다.")
            events = []
            for event in item.get("events", []):
                global_frame = frames[event["clip_frame"]] if "clip_frame" in event else event["frame"]
                if global_frame not in frames:
                    raise ValueError("이벤트 프레임이 동작 범위에 없다.")
                events.append({k: v for k, v in event.items() if k not in ("frame", "clip_frame")} | {"frame": global_frame-frames[0]})
            clips.append({"name": item["name"], "label": item.get("label", item["name"]),
                          "start": frames[0], "end": frames[-1], "frames": frames,
                          "fps": item.get("fps", scene.render.fps), "events": events})
        if len({c["name"] for c in clips}) != len(clips):
            raise ValueError("중복 동작 이름")
        return clips
    markers = sorted(scene.timeline_markers, key=lambda m: m.frame)
    return [{"name": m.name, "label": m.name, "start": m.frame,
             "end": markers[i + 1].frame - 1 if i + 1 < len(markers) else scene.frame_end,
             "fps": scene.render.fps, "events": []} for i, m in enumerate(markers)] or [
        {"name": "pose", "label": "포즈", "start": scene.frame_start, "end": scene.frame_end,
         "fps": scene.render.fps, "events": []}]
