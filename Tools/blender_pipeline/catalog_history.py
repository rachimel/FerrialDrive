"""구버전 스크립트를 실행하지 않고 출처·해시·역할을 목록화한다."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re


def catalog(directory):
    records = []
    for path in sorted(Path(directory).glob('*.py')):
        raw = path.read_bytes()
        source = raw.decode('utf-8-sig')
        record = {'file': path.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'version_references': sorted(set(re.findall(r'v(\d{3})(?!\d)', source + path.name)))}
        try:
            tree = ast.parse(source)
            record['summary'] = ast.get_docstring(tree) or ''
            record['functions'] = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            record['imports'] = sorted({n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
            record['dynamic_execution'] = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                              and n.func.id in ('exec', 'eval') for n in ast.walk(tree))
        except SyntaxError as error:
            record['parse_error'] = str(error)
        records.append(record)
    referenced = {v for r in records for v in r['version_references']}
    return {'schema_version': 1, 'executed_scripts': False, 'scripts': records,
            'missing_version_references_001_078': [f'{i:03}' for i in range(1, 79) if f'{i:03}' not in referenced]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('기존 목록은 덮어쓰지 않는다.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = catalog(args.directory)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Indexed {len(result['scripts'])} scripts; missing references: {result['missing_version_references_001_078']}")
