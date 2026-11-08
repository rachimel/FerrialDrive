"""별도 Blender에서 모델 외부 의존성과 패킹 여부를 기록한다."""
import argparse
import json
from pathlib import Path
import sys


def inspect(source):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=str(source))
    return {'source': str(source), 'libraries': [lib.filepath for lib in bpy.data.libraries],
            'unpacked_paths': list(bpy.utils.blend_paths(absolute=True, packed=False, local=False)),
            'images': [{'name': im.name, 'source': im.source, 'size': list(im.size),
                        'packed': bool(im.packed_file), 'path': im.filepath}
                       for im in bpy.data.images if im.source != 'VIEWER']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.output.exists():
        raise FileExistsError(args.output)
    report = inspect(args.source.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"External paths: {len(report['unpacked_paths'])}; libraries: {len(report['libraries'])}")
