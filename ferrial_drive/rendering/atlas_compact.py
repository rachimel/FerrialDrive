"""해상도·프레임을 유지하는 그림자 R8·에너지 RGB8 아틀라스 후보 제작과 별도 검증."""

from collections import OrderedDict, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import zlib

from .motion_atlas import AtlasItem, pack_items
from .texture_codecs import texture_payload_size, unpack_payload


def read_document(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_document(path, document):
    Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_page(directory, page):
    packed = (Path(directory) / page["file"]).read_bytes()
    if hashlib.sha256(packed).hexdigest() != page["sha256"]:
        raise ValueError("아틀라스 원본 페이지 해시 불일치: " + page["file"])
    return unpack_payload(page["codec"], packed, page["width"], page["height"])[0]


def save_page(directory, name, codec, width, height, pixels):
    if len(pixels) != texture_payload_size(codec, width, height):
        raise ValueError("후보 페이지의 채널·크기가 다르다.")
    packed = zlib.compress(pixels, 6)
    filename = f"{name}.{codec.removesuffix('_zlib')}.zlib"
    (directory / filename).write_bytes(packed)
    return dict(file=filename, codec=codec, width=width, height=height,
                sha256=hashlib.sha256(packed).hexdigest())


def logical_bytes(document):
    return sum(texture_payload_size(page["codec"], page["width"], page["height"])
               for pages in document["pages"].values() for page in pages)


def compact_variant(source, destination):
    """원본은 읽기만 하고 새 후보 경로에 기록한다. 검증은 verify_variant로 분리한다."""
    import numpy as np
    source, destination = Path(source).resolve(), Path(destination).resolve()
    original = read_document(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if any(page["codec"] != "rgba_zlib" for channel in ("color", "energy")
           for page in original["pages"].get(channel, [])):
        raise ValueError("원본 RGBA 페이지가 필요하다. 기존 단축 후보를 중복 변환하지 않는다.")
    destination.mkdir(parents=True, exist_ok=False)
    result = deepcopy(original)
    pools = {"rgba_zlib": [], "a8_zlib": []}
    locations, by_page = {}, defaultdict(list)
    for index, frame in enumerate(original["frames"]["color"]):
        by_page[frame["page"]].append((index, frame["rect"]))
    for page_index, page in enumerate(original["pages"]["color"]):
        pixels = np.frombuffer(read_page(source.parent, page), np.uint8).reshape(page["height"], page["width"], 4)
        for index, (x,y,width,height) in by_page[page_index]:
            image = pixels[y:y+height, x:x+width]
            codec = "rgba_zlib" if np.any(image[:,:,:3]) else "a8_zlib"
            locations[index] = codec, len(pools[codec])
            pools[codec].append(AtlasItem(width,height,image.tobytes()))
    result["pages"]["color"] = []
    positions = {}
    for codec, items in pools.items():
        if not items:
            continue
        pages, packed_positions = pack_items(items)
        offset = len(result["pages"]["color"])
        positions[codec] = [{"page": row["page"]+offset, "rect": row["rect"]} for row in packed_positions]
        for page in pages:
            payload = page.pixels if codec == "rgba_zlib" else page.pixels[3::4]
            result["pages"]["color"].append(save_page(destination,
                f"color_{len(result['pages']['color']):03}",codec,page.width,page.height,payload))
        del pages
        items.clear()
    result["frames"]["color"] = [positions[locations[index][0]][locations[index][1]]
                                   for index in range(len(original["frames"]["color"]))]
    if "energy" in original["pages"]:
        result["pages"]["energy"] = []
        for index,page in enumerate(original["pages"]["energy"]):
            rgba = np.frombuffer(read_page(source.parent,page),np.uint8).reshape(-1,4)
            result["pages"]["energy"].append(save_page(destination,f"energy_{index:03}","rgb8_zlib",
                                                       page["width"],page["height"],rgba[:,:3].tobytes()))
    for page in original["pages"].get("vector",[]):
        shutil.copyfile(source.parent/page["file"],destination/page["file"])
    # 한 클립에 연결할 수 있는 페이지 수는 기존 렌더러의 제한을 따른다.
    for name,clip in result["clips"].items():
        for channel,fields in (("color",(0,1)),("vector",(2,3)),("energy",(4,5))):
            if channel not in result["pages"] or len(clip["pairs"][0]) <= max(fields):
                continue
            pages = {result["frames"][channel][pair[field]]["page"] for pair in clip["pairs"] for field in fields}
            if len(pages)>2:
                raise ValueError(f"재패킹한 클립이 2페이지 제한을 넘었다: {name}/{channel}")
    for channel,pages in result["pages"].items():
        result.setdefault("statistics",{}).setdefault(channel,{})["gpu_bytes"] = sum(
            texture_payload_size(p["codec"],p["width"],p["height"]) for p in pages)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:
        raise ValueError("제작 중 원본 아틀라스 명세가 바뀌었다.")
    result["compaction"] = {"source":str(source),"source_sha256":source_hash,
                            "color_pixels":"exact_rgba", "energy_pixels":"exact_rgb_alpha_unused",
                            "before_bytes":logical_bytes(original),"after_bytes":logical_bytes(result)}
    write_document(destination/"atlas.json",result)
    return result["compaction"]


class FrameReader:
    """검증 중 최근 세 페이지만 보관한다. GPU·창에 의존하지 않는다."""
    def __init__(self,path):
        self.path=Path(path)
        self.document=read_document(path)
        self.cache=OrderedDict()

    def frame(self,channel,index):
        import numpy as np
        frame=self.document["frames"][channel][index]
        page=self.document["pages"][channel][frame["page"]]
        key=channel,frame["page"]
        if key not in self.cache:
            channels={"rgba_zlib":4,"rgb8_zlib":3,"a8_zlib":1}[page["codec"]]
            self.cache[key]=np.frombuffer(read_page(self.path.parent,page),np.uint8).reshape(page["height"],page["width"],channels)
        self.cache.move_to_end(key)
        while len(self.cache)>3:
            self.cache.popitem(last=False)
        x,y,w,h=frame["rect"]
        image=self.cache[key][y:y+h,x:x+w]
        if page["codec"]=="a8_zlib":
            rgba=np.zeros((h,w,4),np.uint8);rgba[:,:,3]=image[:,:,0];image=rgba
        return image


def compact_energy_variant(source,destination):
    """기존 BC7 색상·벡터는 그대로 복사하고 에너지의 미사용 알파만 제거한다."""
    import numpy as np
    source,destination=Path(source).resolve(),Path(destination).resolve()
    original=read_document(source);source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    if any(p["codec"]!="rgba_zlib" for p in original["pages"].get("energy",[])):
        raise ValueError("원본 RGBA 에너지 페이지가 필요하다.")
    destination.mkdir(parents=True,exist_ok=False)
    result=deepcopy(original)
    for channel,pages in original["pages"].items():
        result["pages"][channel]=[]
        for index,page in enumerate(pages):
            if channel=="energy":
                rgba=np.frombuffer(read_page(source.parent,page),np.uint8).reshape(-1,4)
                new=save_page(destination,f"energy_{index:03}","rgb8_zlib",page["width"],page["height"],rgba[:,:3].tobytes())
            else:
                new=dict(page,file=f"{channel}_{index:03}.{page['codec']}.bin")
                shutil.copyfile(source.parent/page["file"],destination/new["file"])
            result["pages"][channel].append(new)
        result.setdefault("statistics",{}).setdefault(channel,{})["gpu_bytes"]=sum(
            texture_payload_size(p["codec"],p["width"],p["height"]) for p in result["pages"][channel])
    if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:
        raise ValueError("제작 중 원본 아틀라스 명세가 바뀌었다.")
    result["compaction"]={"source":str(source),"source_sha256":source_hash,
        "color_pixels":"unchanged_payload","energy_pixels":"exact_rgb_alpha_unused",
        "before_bytes":logical_bytes(original),"after_bytes":logical_bytes(result)}
    write_document(destination/"atlas.json",result)
    return result["compaction"]


def verify_variant(source,candidate):
    import numpy as np
    original,compact=FrameReader(source),FrameReader(candidate)
    metadata=compact.document["compaction"]
    if hashlib.sha256(Path(source).read_bytes()).hexdigest()!=metadata["source_sha256"]:
        raise ValueError("변환 이후 원본 명세가 바뀌었다.")
    if original.document["clips"]!=compact.document["clips"]:
        raise ValueError("클립·프레임 인덱스·피봇·해상도가 바뀌었다.")
    for channel in ("color","energy"):
        if channel=="color" and metadata["color_pixels"]=="unchanged_payload":
            if original.document["frames"][channel]!=compact.document["frames"][channel]:
                raise ValueError("보존한 색상 프레임 참조가 바뀌었다.")
            for before,after in zip(original.document["pages"][channel],compact.document["pages"][channel],strict=True):
                if (before["width"],before["height"],before["codec"],before["sha256"])!=(after["width"],after["height"],after["codec"],after["sha256"]):
                    raise ValueError("보존한 색상 페이지가 바뀌었다.")
                read_page(Path(candidate).parent,after)
            continue
        for index in range(len(original.document["frames"].get(channel,[]))):
            before,after=original.frame(channel,index),compact.frame(channel,index)
            if channel=="energy":
                before,after=before[:,:,:3],after[:,:,:3]
            if not np.array_equal(before,after):
                raise ValueError(f"원본과 후보의 픽셀이 다르다: {channel}/{index}")
    if original.document["frames"].get("vector")!=compact.document["frames"].get("vector"):
        raise ValueError("벡터 프레임 참조가 바뀌었다.")
    for page in compact.document["pages"].get("vector",[]):
        read_page(Path(candidate).parent,page)
    return {"color_frames":len(original.document["frames"]["color"]),
            "energy_frames":len(original.document["frames"].get("energy",[])),"pixels_equal":True}


def compact_catalog(source,destination,*,on_progress=None):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    catalog=read_document(source)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    destination.mkdir(parents=True,exist_ok=False)
    result=deepcopy(catalog);rows=[]
    for motion,spec in result["motions"].items():
        for quality,relative in spec["variants"].items():
            target=destination/quality/motion
            row=compact_variant(source.parent/relative,target)
            spec["variants"][quality]=(target/"atlas.json").relative_to(destination).as_posix()
            rows.append(dict(motion=motion,quality=quality,**row))
            if on_progress:on_progress(rows[-1])
    if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:
        raise ValueError("제작 중 원본 자세표 카탈로그가 바뀌었다.")
    result["compaction"]={"source":str(source),"source_sha256":source_hash,"variants":rows}
    write_document(destination/"catalog.json",result)
    return rows


def verify_catalog(path,*,on_progress=None):
    path=Path(path);catalog=read_document(path);rows=[]
    for motion,spec in catalog["motions"].items():
        for quality,relative in spec["variants"].items():
            candidate=path.parent/relative;original=read_document(candidate)["compaction"]["source"]
            row=dict(motion=motion,quality=quality,**verify_variant(original,candidate));rows.append(row)
            if on_progress:on_progress(row)
    return rows
