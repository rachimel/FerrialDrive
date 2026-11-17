"""게임 에셋 없이 검 Trail·판정 시연에 사용할 직접 작성한 수치 궤적."""

import json
from math import cos, pi, sin
from pathlib import Path


def sample_data():
    clips = {}
    directions = ("e", "se", "s", "sw", "w", "nw", "n", "ne")
    for strike in range(1, 5):
        duration = (6 if strike < 4 else 8) / 12
        for index, direction in enumerate(directions):
            facing = index * pi / 4
            rows = []
            for sample in range(81):
                phase = sample / 80
                angle = facing + (-1 if strike % 2 else 1) * (phase - 0.5) * pi
                root = [cos(facing) * 24, -80 + sin(facing) * 8]
                rows.append({"time_seconds": phase * duration, "root": root,
                             "tip": [root[0] + cos(angle) * 140, root[1] + sin(angle) * 90]})
            clips[f"combo_{strike:02}/{direction}"] = rows
    return {"type": "sword_trail_sample", "source": "직접 작성한 기본 수치", "clips": clips}


if __name__ == "__main__":
    path = Path(__file__).with_name("trail_sample.json")
    path.write_text(json.dumps(sample_data(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
