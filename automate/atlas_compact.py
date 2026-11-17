"""기존 아틀라스의 해상도·프레임을 유지하며 채널을 줄인 후보를 제작·검증한다."""

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from ferrial_drive.rendering.atlas_compact import compact_catalog,compact_energy_variant,verify_catalog,verify_variant,read_document
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=("prepare","verify"))
    sources=parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--catalog",type=Path)
    sources.add_argument("--manifest",type=Path,help="기존 BC7 색상 아틀라스는 에너지 알파만 제거한다.")
    parser.add_argument("--output",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    def progress(row):
        print(json.dumps(row,ensure_ascii=False),flush=True)
    if args.operation=="prepare":
        if args.output is None:parser.error("prepare에는 새 --output 경로가 필요하다.")
        if args.manifest:
            rows=[compact_energy_variant(args.manifest,args.output)];progress(rows[0])
        else:
            rows=compact_catalog(args.catalog,args.output,on_progress=progress)
    else:
        if args.manifest:
            rows=[verify_variant(read_document(args.manifest)["compaction"]["source"],args.manifest)];progress(rows[0])
        else:
            rows=verify_catalog(args.catalog,on_progress=progress)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({"operation":args.operation,"results":rows},ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
