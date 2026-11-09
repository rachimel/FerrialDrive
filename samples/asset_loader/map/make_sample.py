"""공개 가능한 직접 작성 도형으로 작은 맵을 생성한다."""

import json
from pathlib import Path
from samples.asset_loader.make_sample import write_png


def write_sample(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_png(directory / 'background.png', 320, 180,
              lambda x, y: (42, 60, 78, 255) if y < 70 else (24, 36, 45, 255))
    write_png(directory / 'ground.png', 320, 180,
              lambda x, y: ((88, 109, 111, 255) if (x // 20 + y // 20) % 2 else (73, 94, 98, 255))
              if y >= 70 else (0, 0, 0, 0))
    data = dict(version=1, type='map', asset_id='sample_map', coordinates='bottom-left', size=[320, 180],
                background='background.png', ground='ground.png',
                walkable=[[[20, 12], [300, 12], [300, 96], [200, 96], [180, 70], [20, 70]]])
    (directory / 'bundle.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    return directory / 'bundle.json'


if __name__ == '__main__':
    write_sample(Path(__file__).parent)
