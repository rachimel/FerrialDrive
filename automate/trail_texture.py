"""Trail 결 텍스처를 게임과 시연용으로 미리 준비한다. 창을 생성하지 않는다."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ferrial_drive.assets.trail_flow import DEFAULT_FLOW_DIRECTORY, prepare_flow_texture
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'samples/sword_movement/movement_config.json')
    parser.add_argument('--demo', action='store_true', help='게임 에셋 없이 시연 폴더에 준비한다.')
    parser.add_argument('--output-directory', type=Path, help='준비 파일 보관 폴더를 명시한다.')
    args = parser.parse_args()
    source = args.config.resolve()
    settings = json.loads(source.read_text(encoding='utf-8-sig'))['sword_effects']
    field = 'demo_flow_texture_directory' if args.demo else 'flow_texture_directory'
    default = 'generated/trail_flow' if args.demo else str(DEFAULT_FLOW_DIRECTORY)
    directory = args.output_directory or source.parent / settings.get(field, default)
    print(json.dumps(prepare_flow_texture(settings, directory.resolve()), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
