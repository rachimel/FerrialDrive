"""공개 가능한 수치 패턴으로 색상·검은 그림자·RGB 에너지 샘플을 만든다."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zlib

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def write_sample(directory):
    from ferrial_drive.rendering.motion_atlas import AtlasItem,pack_items
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    width,height=13,11
    color=bytes(v for y in range(height) for x in range(width) for v in (x*9,y*12,50,180))
    shadow=bytes(v for y in range(height) for x in range(width) for v in (0,0,0,(x+y)*9))
    energy=bytes(v for y in range(height) for x in range(width) for v in (255 if x%2 else 0,0 if x%2 else 255,y*7,180))
    pages,frames={},{}
    for channel,items in (("color",[AtlasItem(width,height,color),AtlasItem(width,height,shadow)]),
                          ("energy",[AtlasItem(width,height,energy)]),
                          ("vector",[AtlasItem(width,height,bytes((128,0,128,0))*width*height)])):
        packed,frames[channel]=pack_items(items,max_side=64);pages[channel]=[]
        for index,page in enumerate(packed):
            filename=f"{channel}_{index}.rgba.zlib";payload=zlib.compress(page.pixels)
            (directory/filename).write_bytes(payload)
            pages[channel].append(dict(file=filename,codec="rgba_zlib",width=page.width,height=page.height,
                                       sha256=hashlib.sha256(payload).hexdigest()))
    clip=dict(interval_seconds=1/12,source_size=[width,height],size=[width,height],pivot=[6,10],pixel_scale=1,loop=True)
    atlas=dict(version=1,divisor=1,color_alpha_mode="premultiplied",vector_encoding="signed16_rgba_x64",
               pages=pages,frames=frames,clips={"body":dict(clip,pairs=[[0,0,0,0,0,0]]),
                                              "shadow/body":dict(clip,pairs=[[1,1,0,0]])})
    (directory/"atlas.json").write_text(json.dumps(atlas,indent=2),encoding="utf-8")
    catalog=dict(version=1,motions={"sample":{"variants":{"high":"atlas.json"}}})
    path=directory/"catalog.json";path.write_text(json.dumps(catalog,indent=2),encoding="utf-8")
    return path


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    print(write_sample(parser.parse_args().output))
