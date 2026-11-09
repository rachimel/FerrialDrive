"""현재 편집 장면과 Undo를 유지하면서 별도 Blender에서 동작을 굽는다."""

import json
from pathlib import Path
import subprocess

import bpy
from . import scene as engine

ROOT = Path(__file__).resolve().parents[2]


def bake_clip(destination):
    destination = Path(destination).resolve()
    manifest = engine.export_clip(destination)
    subprocess.run([bpy.app.binary_path, "--background", "--factory-startup", "--python-exit-code", "1",
                    "--python", str(ROOT/"Tools/blender_pipeline/animation_pipeline.py"), "--",
                    "--manifest", str(manifest), "--output", str(destination/"baked")],
                   check=True, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    preset = destination/"baked/export_configs"/(engine.state()["active"]+".json")
    config = json.loads(preset.read_text(encoding="utf-8"))
    config["frame_size_pixels"] = [240, 240]
    config["extra_root_objects"] = engine.state().get("independent_parts", [])
    preset.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return preset
