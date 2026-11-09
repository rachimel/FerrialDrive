"""JSON 공통 연산으로 모델 후보를 제작한다. 품질 검사는 별도 파일에서 실행한다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review(config, directory):
    from model_review import render_review
    return [item['file'] for item in render_review(config, directory)]


def build(manifest, output):
    import bpy
    from model_review import capture_fixture, render_review, write_pending_review, require_stage_approval
    started = perf_counter()
    timings = {}
    from model_snapshot import fingerprint
    from model_operations import apply_operations
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    config = json.loads(manifest.read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or not config.get('asset_id'):
        raise ValueError('schema_version=1 및 asset_id가 필요하다.')
    if output.exists():
        raise FileExistsError('새 출력 폴더를 사용한다. 기존 작업은 덮어쓰지 않는다.')
    def path(value):
        return (manifest.parent / value).resolve()
    source = path(config['source']) if config.get('source') else None
    if source and sha256(source) != config.get('source_sha256'):
        raise ValueError('기준 파일 해시가 다르다. 기준 버전을 확인한다.')
    if source and config.get('operations'):
        if config.get('review_revision') and not config.get('review'):
            raise ValueError('같은 단계의 재수정에도 중간 이미지 검토 설정이 필요하다.')
        require_stage_approval(source, revision=config.get('review_revision', False))
    if 'recipe' in config:
        raise ValueError('버전별 Python recipe 대신 operations JSON을 사용한다.')
    if not isinstance(config.get('operations'), list):
        raise ValueError('operations 배열이 필요하다. 검사/복사용 후보는 빈 배열을 사용한다.')
    output.mkdir(parents=True)
    report = {'schema_version': 1, 'asset_id': config['asset_id'], 'status': 'failed',
              'source_sha256': sha256(source) if source else None,
              'manifest_sha256': sha256(manifest), 'blender_version': bpy.app.version_string,
              'visual_approval': False, 'game_exported': False, 'quality_checks_run': False,
              'source': str(source) if source else None,
              'review_checkpoint': 'not_requested',
              'scope_check_excludes': ['modifier settings', 'material node contents', 'driver expressions', 'actions']}
    report['tool_hashes'] = {name: sha256(Path(__file__).with_name(name)) for name in
                            tuple(p.name for p in sorted(Path(__file__).parent.glob('*.py')))}
    (output / 'request.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        stage_started = perf_counter()
        if source:
            bpy.ops.wm.open_mainfile(filepath=str(source))
        else:
            bpy.ops.wm.read_factory_settings(use_empty=True)
        timings['load_seconds'] = perf_counter() - stage_started
        # 촬영 조건은 수정 전에 고정하고, 렌더는 후보 저장 후 실행한다.
        fixture = capture_fixture(config['review']) if source and config.get('review') else None
        before = {o.name: fingerprint(o) for o in bpy.data.objects}
        for operation in config['operations']:
            target = operation.get('object')
            if target in before and target not in config.get('change_objects', []):
                raise ValueError(f'선언한 수정 범위 밖의 대상: {target}')
        stage_started = perf_counter()
        apply_operations(config['operations'])
        timings['operations_seconds'] = perf_counter() - stage_started
        bpy.context.view_layer.update()
        after = {o.name: fingerprint(o) for o in bpy.data.objects}
        changed = sorted(n for n in before if before[n] != after.get(n))
        added = sorted(set(after) - set(before))
        report.update(changed_objects=changed, added_objects=added)
        unexpected = set(changed) - set(config.get('change_objects', []))
        if unexpected or (added and not config.get('allow_additions', False)):
            raise ValueError(f'선언한 수정 범위 밖의 변경: {sorted(unexpected)}; additions={added}')
        stage_started = perf_counter()
        candidate = output / 'candidate.blend'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(candidate))
        bpy.ops.wm.open_mainfile(filepath=str(candidate))
        loaded = {o.name: fingerprint(o) for o in bpy.data.objects}
        if loaded != after:
            raise ValueError('저장/재로딩 뒤 구조가 달라졌다.')
        report['candidate_sha256'] = sha256(candidate)
        timings['save_reload_seconds'] = perf_counter() - stage_started
        if config.get('review'):
            review_config = config['review']
            fixture = fixture or capture_fixture(review_config)
            (output / 'review_fixture.json').write_text(json.dumps(fixture, indent=2), encoding='utf-8')
            evidence = []
            stage_started = perf_counter()
            if source and config['operations']:
                bpy.ops.wm.open_mainfile(filepath=str(source))
                for item in render_review(review_config, output / 'before', fixture):
                    evidence.append(dict(item, file='before/' + item['file'], kind='before'))
                bpy.ops.wm.open_mainfile(filepath=str(candidate))
            for item in render_review(review_config, output / 'after', fixture):
                evidence.append(dict(item, file='after/' + item['file'], kind='after'))
            timings['review_seconds'] = perf_counter() - stage_started
            report['previews'] = [item['file'] for item in evidence]
            report['review_checkpoint'] = write_pending_review(
                output, review_config.get('intent', {}), evidence, report['candidate_sha256'], fixture)
            report['review_file'] = 'visual_review.json'
        report['status'] = 'candidate_unchecked'
        return report
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        timings['total_seconds'] = perf_counter() - started
        report['timings'] = timings
        if source:
            report['source_unchanged'] = sha256(source) == report['source_sha256']
            if not report['source_unchanged']:
                report['status'] = 'failed'
                report['error'] = '기준 파일 해시가 변경됐다. 원본 보존을 확인한다.'
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if report.get('source_unchanged') is False:
            raise RuntimeError(report['error'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    print(json.dumps(build(args.manifest, args.output), ensure_ascii=True))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
