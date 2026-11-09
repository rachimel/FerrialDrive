"""Asset Tool 내부 포즈 편집

비표시 Blender 작업자의 손바닥 이동·키·저장·출력·재개를 확인한다.
"""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Tools.pose_tool.session import PoseSession


def ready(session, timeout=90):
    until = time.monotonic()+timeout
    while session.busy and time.monotonic() < until:
        session.poll()
        time.sleep(.05)
    if session.busy:
        raise TimeoutError(f"포즈 작업자 응답 대기 초과: {session.directory / 'worker.log'}")
    if session.error:
        raise RuntimeError(session.error)
    return session.state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    start = time.monotonic()
    session = PoseSession(args.source, sample=args.source is None)
    try:
        data = ready(session)
        initial_seconds = time.monotonic()-start
        source_state = data
        point = data["points"]["hand.R"]["world"]
        target = [point[0]+.05, point[1], point[2]+.04]
        before = time.monotonic()
        session.send("move", control="hand.R", world=target)
        data = ready(session)
        move_seconds = time.monotonic()-before
        assert data["dirty"]
        assert max(abs(a-b) for a, b in zip(data["points"]["hand.R"]["world"], target)) < .0001
        session.send("frame", frame=data["frame"]+1)
        try:
            ready(session)
            raise AssertionError("키 미저장 프레임 전환을 허용했다.")
        except RuntimeError as error:
            assert "키" in str(error)
        session.send("save")
        data = ready(session)
        assert not data["dirty"] and not data["file_dirty"]
        work = Path(data["work"])
        session.send("view", name="front")
        data = ready(session)
        session.send("export")
        data = ready(session)
        assert Path(data["exported"]).is_file()
        preset = json.loads(Path(data["exported"]).read_text(encoding="utf-8"))
        assert preset["frame_size_pixels"] == [240, 240]
        export_path = data["exported"]
        next_clip = next(c["name"] for c in data["clips"] if c["name"] != data["active"])
        session.send("clip", name=next_clip)
        switched = ready(session)
        assert switched["exported"] is None and switched["file_dirty"]
        session.close()
        session = PoseSession(work, work=work)
        resumed = ready(session)
        assert max(abs(a-b) for a, b in zip(resumed["points"]["hand.R"]["world"], target)) < .0001
        report = {"initial_seconds": initial_seconds, "move_preview_seconds": move_seconds,
                  "work": str(work), "export": export_path, "resume": True,
                  "clip_count": len(source_state["clips"]), "blender_window_opened": False}
        (session.directory / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("POSE_SESSION_CHECK_PASSED", json.dumps(report), flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
