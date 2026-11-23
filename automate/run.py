"""프로젝트 루트를 기준으로 기존 자동화 모듈을 실행한다."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    "enemy-crowd-atlas": "automate/enemy_crowd_atlas.py",
    "part-sparse-atlas": "automate/part_sparse_atlas.py",
    "part-surface-downsample": "automate/part_surface_downsample.py",
    "part-metadata-cache": "automate/part_metadata_cache.py",
    "hud-theme": "Tools/hud_theme_editor/run.py",
    "sound-import": "automate/sound_import.py",
    "sound-preview": "automate/sound_preview.py",
    "sound-sources": "automate/sound_sources.py",
    "sound-effects": "automate/sound_effects.py",
    "sound-project": "automate/audacity_project.py",
    "trail-texture": "automate/trail_texture.py",
    "alpha-textures": "automate/alpha_textures.py",
    "atlas-compact": "automate/atlas_compact.py",
    "unreal-rig": "automate/unreal/prepare_units.py",
    "texture-compare": "automate/texture_compare.py",
    "unreal-motion-vectors": "automate/unreal/motion_vectors.py",
    "unreal-attachments": "automate/unreal/project_attachments.py",
    "unreal-runtime": "automate/unreal/runtime_catalog.py",
    "unreal-plan": "automate/unreal/pose_targets.py",
    "unreal-aim-review": "automate/unreal/aim_review.py",
    "unreal-pose-table": "automate/unreal/pose_table.py",
    "unreal-surface": "automate/unreal/prepare_units.py",
    "unreal-animation": "automate/unreal/prepare_units.py",
    "unreal-units": "automate/unreal/prepare_units.py",
    "unreal-render": "automate/unreal/render.py",
    "unreal-review": "Tools/unreal_pipeline/motion_review.py",
    "unreal-directional": "automate/unreal/directional_catalog.py",
    "asset": "Tools/asset_loader/asset_pipeline.py",
    "model": "Tools/blender_pipeline/model_pipeline.py",
    "model-icon": "Tools/blender_pipeline/icon_render.py",
    "mcp": "automate/mcp_client.py",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, help="model 경로에 사용할 Blender 실행 파일")
    parser.add_argument("route", choices=ROUTES)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if args.route in ("model", "model-icon"):
        config_path = ROOT / "automate/config.local.json"
        config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
        blender = args.blender or config.get("blender_executable") or shutil.which("blender")
        if not blender or not Path(blender).is_file():
            parser.error("--blender 또는 automate/config.local.json의 blender_executable을 지정한다.")
        command = [str(blender), "--background", "--python", str(ROOT / ROUTES[args.route]), "--", *arguments]
        if args.route == "model-icon":
            command = [str(blender), "--background", "--factory-startup", "--python-exit-code", "1",
                       "--python", str(ROOT / ROUTES[args.route]), "--", *arguments]
    else:
        command = [sys.executable, str(ROOT / ROUTES[args.route]), *arguments]
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
