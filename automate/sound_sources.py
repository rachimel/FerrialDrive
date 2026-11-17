"""CC0·출처 표기형 선택 음원의 원본과 라이선스 근거를 로컬에 보존한다."""

import argparse
from hashlib import sha256
from html.parser import HTMLParser
import io
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "samples/sound_effects/sources.json"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(value for key, value in attrs if key == "href" and value)


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "FerrialDrive-CC0-audio/1.0"}), timeout=45) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="명세의 CC0 원본 다운로드")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="기본 CC0 또는 별도 선택 음원 명세")
    parser.add_argument("--directory", type=Path, default=ROOT / "data/source/audio/sources")
    parser.add_argument("--only", action="append", help="지정한 원본 묶음만 처리한다. 반복 지정 가능")
    args = parser.parse_args()
    sources = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.only:
        unknown = set(args.only) - {source["id"] for source in sources}
        if unknown:
            parser.error(f"지원하지 않는 원본: {', '.join(sorted(unknown))}")
        sources = [source for source in sources if source["id"] in args.only]
    if not args.download:
        print(json.dumps(sources, ensure_ascii=False, indent=2))
        return
    for source in sources:
        target = args.directory / source["id"]
        record_path = target / "source.json"
        if record_path.is_file() and json.loads(record_path.read_text(encoding="utf-8")).get("files"):
            print(f"보존 원본 사용: {source['id']}")
            continue
        page = fetch(source["page"])
        text = page.decode("utf-8")
        marks = {"CC0-1.0":("creativecommons.org/publicdomain/zero","license_images/cc0.png"),
                 "CC-BY-4.0":("creativecommons.org/licenses/by/4.0",)}
        if (source["license"] not in marks or not any(mark in text.lower() for mark in marks[source["license"]])
                or source["license"] == "CC-BY-4.0" and not source.get("attribution")):
            raise ValueError(f"라이선스 표시·출처 문구를 확인할 수 없다: {source['page']}")
        links = Links()
        links.feed(text)
        urls = source.get("download_urls") or list(dict.fromkeys(urljoin(source["page"], value) for value in links.urls
            if "/sites/default/files/" in value and unquote(value).endswith(source["file_suffix"])))
        if not urls and urlparse(source["page"]).hostname in ("freesound.org", "www.freesound.org"):
            sound_id = int(urlparse(source["page"]).path.rstrip("/").split("/")[-1])
            urls = list(dict.fromkeys(re.findall(
                rf'https://cdn\.freesound\.org/previews/{sound_id // 1000}/{sound_id}_\d+-hq\.mp3', text)))
        if not urls:
            raise ValueError(f"원본 링크를 확인할 수 없다: {source['page']}")
        target.mkdir(parents=True, exist_ok=True)
        (target / "source_page.html").write_bytes(page)
        records, files = [], []
        for url in urls:
            payload = fetch(url)
            if zipfile.is_zipfile(io.BytesIO(payload)):
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    for item in archive.infolist():
                        relative = PurePosixPath(item.filename)
                        if relative.is_absolute() or ".." in relative.parts or ":" in item.filename or "\\" in item.filename:
                            raise ValueError("압축 파일 내부 경로 오류")
                        if item.is_dir() or relative.suffix.lower() not in (".wav", ".ogg", ".mp3", ".txt", ".md"):
                            continue
                        output = target.joinpath(*relative.parts)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(archive.read(item))
                        files.append(str(output.relative_to(target)))
            elif payload.startswith((b"RIFF", b"OggS", b"ID3")) or (
                    len(payload) > 1 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0):
                name = Path(unquote(urlparse(url).path)).name
                (target / name).write_bytes(payload)
                files.append(name)
            else:
                raise ValueError(f"음원 형식이 아닌 응답: {url}")
            records.append({"url": url, "sha256": sha256(payload).hexdigest()})
        record = dict(source, downloads=records, files=files)
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{source['license']} 원본 저장: {source['id']} ({len(files)} files)")


if __name__ == "__main__":
    main()
