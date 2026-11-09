"""화면을 멈추지 않는 포즈 작업자 통신. Blender/Pico2D 미의존."""

from collections import deque
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from Tools.blender_pipeline.asset_build import find_blender
from Tools.blender_pipeline.child_scope import ChildScope

ROOT = Path(__file__).resolve().parents[2]


class PoseSession:
    def __init__(self, source=None, *, sample=False, profile=None, clip=None, work=None,
                 directory=None, blender=None):
        identity = uuid4().hex
        self.directory = Path(directory or ROOT / "output/asset_loader/pose_sessions" / identity).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.work = Path(work or ROOT / "Tools/pose_tool/workspace/integrated" / identity / "pose_work.blend").resolve()
        config = {"source": str(Path(source).resolve()) if source else None, "sample": sample,
                  "work": str(self.work), "profile": str(Path(profile).resolve()) if profile else None, "clip": clip}
        self.process = self.scope = self.log = None
        self.state = None
        self.error = None
        self.sequence, self.received, self.inflight = 0, -1, True
        self.queue = deque()
        self.revision = -1
        path = self.directory / "session.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        try:
            self.scope = ChildScope()
            self.log = (self.directory / "worker.log").open("wb")
            self.process = subprocess.Popen([str(find_blender(blender)), "--background", "--factory-startup",
                "--python-exit-code", "1", "--python", str(Path(__file__).with_name("worker.py")),
                "--", "--session", str(path)], cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=self.log, stderr=subprocess.STDOUT, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.scope.attach(self.process)
        except BaseException:
            self.close()
            raise

    @property
    def busy(self):
        return self.inflight or bool(self.queue)

    def send(self, command, **fields):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("포즈 작업자가 종료됐다.")
        item = {"command": command, **fields}
        if command in ("move", "bend") and self.queue and self.queue[-1]["command"] == command and self.queue[-1].get("control") == fields.get("control"):
            self.queue[-1] = item
        else:
            self.queue.append(item)
        self._dispatch()

    def _dispatch(self):
        if self.inflight or not self.queue:
            return
        self.sequence += 1
        item = self.queue.popleft() | {"seq": self.sequence}
        temporary = self.directory / f"request_{self.sequence}.tmp"
        temporary.write_text(json.dumps(item), encoding="utf-8")
        os.replace(temporary, self.directory / f"request_{self.sequence}.json")
        self.inflight = True

    def poll(self):
        path = self.directory / f"reply_{self.sequence}.json"
        changed = False
        if path.exists():
            reply = json.loads(path.read_text(encoding="utf-8"))
            if reply["seq"] > self.received:
                self.received = reply["seq"]
                if reply.get("state"):
                    self.state = reply["state"]
                self.error = None if reply["ok"] else reply["error"]
                if reply["ok"]:
                    self.revision = self.received
                self.inflight = False
                changed = True
        if self.process and self.process.poll() is not None:
            self.inflight = False
            self.queue.clear()
            self.error = f"포즈 작업자 종료 ({self.process.returncode}). 로그: {self.directory / 'worker.log'}"
        else:
            self._dispatch()
        return changed

    def close(self):
        if self.process:
            (self.directory / "stop").touch()
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=5)
            self.process = None
        if self.scope:
            self.scope.close()
            self.scope = None
        if self.log:
            self.log.close()
            self.log = None
