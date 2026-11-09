"""기본 도형의 폭 수정 전후를 고정된 6면으로 렌더한다. 실제 게임 에셋은 사용하지 않는다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/blender_pipeline'))
from model_pipeline import build


def run(output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('새 출력 폴더를 지정한다.')
    output.mkdir(parents=True)
    config = json.loads((ROOT / 'samples/model_pipeline/manifest.json').read_text(encoding='utf-8'))
    config.pop('review')
    base_request = output / 'baseline.json'
    base_request.write_text(json.dumps(config), encoding='utf-8')
    build(base_request, output / 'baseline')
    source = output / 'baseline/candidate.blend'
    config.update(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  change_objects=['Plate'], allow_additions=False,
                  operations=[{'op': 'transform_vertices', 'object': 'Plate', 'root': 'ActorRoot',
                               'pivot': [0, 0, 1.2], 'scale': [1, .65, 1]}],
                  review={'root_object': 'ActorRoot', 'detail_size': 512, 'game_size': 240, 'samples': 8,
                          'intent': {'goal': '위쪽 판의 좌우 폭만 줄인다.',
                                     'preserve': ['판의 높이와 두께', '아래 관절의 형상과 위치'],
                                     'criteria': [{'id': 'width', 'expectation': '정면과 후면에서 판의 폭이 줄어든다.'}]}})
    request = output / 'narrow_plate.json'
    request.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    report = build(request, output / 'comparison')
    print(json.dumps({'output': str(output / 'comparison'), 'timings': report['timings'],
                      'checkpoint': report['review_checkpoint']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    run(args.output)
