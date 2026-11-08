"""독립 검사들의 입력/JSON 출력만 공유한다. 검사를 묶어서 실행하지 않는다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main(check):
    import bpy
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.output.exists():
        raise FileExistsError(args.output)
    source = args.source.resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    config = json.loads(args.settings.read_text(encoding='utf-8')) if args.settings else {}
    bpy.ops.wm.open_mainfile(filepath=str(source))
    try:
        report = check(config)
        report.setdefault('status', 'failed' if report['errors'] else 'passed')
    except Exception as error:
        report = {'status': 'failed', 'errors': [str(error)]}
    checker_file = Path(check.__code__.co_filename)
    report.update(source_sha256=digest, checker=checker_file.name, visual_approval=False,
                  checker_sha256=hashlib.sha256(checker_file.read_bytes()).hexdigest(),
                  settings_sha256=hashlib.sha256(args.settings.read_bytes()).hexdigest() if args.settings else None)
    report['source_unchanged'] = digest == hashlib.sha256(source.read_bytes()).hexdigest()
    if not report['source_unchanged']:
        report['errors'].append('source_changed')
        report['status'] = 'failed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
    if report['errors']:
        raise RuntimeError('검사 실패. JSON 결과를 확인한다.')
