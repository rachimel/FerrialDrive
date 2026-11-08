"""직접 작성한 도형 PNG·기존 시트/번들·카탈로그를 재생성한다."""

import hashlib
import json
from pathlib import Path
import struct
import zlib


def write_png(path, width, height, pixel):
    def chunk(kind, payload):
        return struct.pack("!I", len(payload)) + kind + payload + struct.pack("!I", zlib.crc32(kind + payload) & 0xffffffff)

    rows = [b"\0" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height)]
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def write_samples(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_png(directory / "image.png", 128, 128,
              lambda x, y: (145, 174, 187, 255) if 20 <= x < 108 and 20 <= y < 108 else (0, 0, 0, 0))
    directions = ("e", "ne", "n", "nw", "w", "sw", "s", "se")

    def body(x, y):
        frame, row = x // 64, y // 64
        px, py = x % 64, y % 64
        if 17 <= px <= 46 and 14 + frame <= py <= 49:
            return (80 + row * 18, 174, 215 - frame * 22, 255)
        if 28 <= px <= 35 and 7 <= py <= 13:
            return (241, 135, 117, 255)
        return (0, 0, 0, 0)

    def shadow(x, y):
        px, py = x % 64, y % 64
        return (8, 18, 23, 120) if ((px - 32) / 23) ** 2 + ((py - 52) / 7) ** 2 < 1 else (0, 0, 0, 0)

    write_png(directory / "body.png", 256, 512, body)
    write_png(directory / "shadow.png", 256, 512, shadow)
    animations = [{"name": f"idle/{direction}", "fps": 6,
                   "frames": [{"rect": [frame * 64, 512 - (row + 1) * 64, 64, 64], "pivot": [32, 9]}
                              for frame in range(4)]}
                  for row, direction in enumerate(directions)]
    for layer in ("body", "shadow"):
        document = {"version": 1, "coordinates": "bottom-left",
                    "image": {"path": f"{layer}.png", "size": [256, 512]},
                    "animations": animations, "event_bindings": {}}
        (directory / f"{layer}.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    bundle = {"version": 1, "asset_id": "sample_mech", "body": "body.json", "shadow": "shadow.json",
              "directions": {direction: f"idle/{direction}" for direction in directions},
              "config_sha256": hashlib.sha256(b"asset-loader-geometric-sample-v1").hexdigest()}
    (directory / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    catalog = {"version": 1, "assets": [{"id": "sample_image", "kind": "image", "source": "image.png"},
                                       {"id": "sample_sheet", "kind": "sheet", "source": "body.json"},
                                       {"id": "sample_mech", "kind": "bundle", "source": "bundle.json"}]}
    (directory / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return directory


if __name__ == "__main__":
    write_samples(Path(__file__).parent)
