"""Markdown 요약과 누락 필드. 원시 채팅/게임 코드를 읽거나 실행하지 않는다."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re

LEGACY_HEADING = "## 원기록 — 이전 형식/당시 상태 보존"
GAP_PATTERN = re.compile(r"\[\[FDLOG_MISSING_([A-Z_]+):([^\]]+)\]\]")
GAP_NAMES = {"TIME": "시각", "SOURCE": "출처", "PROPOSAL": "제안·주체", "REASON": "이유·의도",
             "ACCEPTANCE": "수용 여부", "PROBLEM": "문제 발견", "CAUSE": "원인", "RESULT": "결과"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reviewed_part(text):
    return text.split(LEGACY_HEADING, 1)[0]


@dataclass(frozen=True)
class Gap:
    token: str
    kind: str
    item: str
    context: str


@dataclass(frozen=True)
class Bubble:
    actor: str
    title: str
    text: str
    origin: str = "요약"


@dataclass(frozen=True)
class LogRecord:
    path: Path
    title: str
    record_id: str
    text: str
    fingerprint: str
    gaps: tuple[Gap, ...]
    bubbles: tuple[Bubble, ...]


def parse_record(path, data=None):
    path = Path(path)
    data = path.read_bytes() if data is None else data
    text = data.decode("utf-8-sig")
    front = reviewed_part(text)
    title = next((line[2:].strip() for line in front.splitlines() if line.startswith("# ")), path.stem)
    identity = re.search(r"- 기록 ID:\s*`([^`]+)`", front)
    gaps = []
    for line in front.splitlines():
        for match in GAP_PATTERN.finditer(line):
            gaps.append(Gap(match.group(0), match.group(1), match.group(2).rsplit(":", 1)[-1], line.strip()))
    bubbles = []
    sections = re.split(r"(?m)^## ", front)
    if GAP_PATTERN.search(sections[0]):
        metadata = "\n".join(line for line in sections[0].splitlines() if not line.startswith("# "))
        bubbles.append(Bubble("기록", "기록 정보", metadata.strip()))
    for part in sections[1:]:
        heading, _, body = part.partition("\n")
        heading, body = heading.strip(), body.strip()
        if not body:
            continue
        number = re.match(r"([1-7])\.", heading)
        actor = ("사용자" if number and number[1] in ("1", "6") else
                 "AI" if number and number[1] in ("2", "7") else "기록")
        origin = "사용자 보완" if heading.startswith("사용자 보완") else "요약 · 원문 연결" if "원문 위치:" in body else "요약"
        chunks = re.split(r"(?m)(?=^- \*\*U\d+)", body) if number and number[1] == "1" else [body]
        for chunk in chunks:
            if chunk.strip():
                bubbles.append(Bubble("사용자 보완" if origin == "사용자 보완" else actor,
                                      heading, chunk.strip(), origin))
    return LogRecord(path, title, identity[1] if identity else path.stem, text, digest(data),
                     tuple(gaps), tuple(bubbles))


def list_records(directory):
    records, errors = [], []
    for path in sorted(Path(directory).glob("????-??-??-*.md"), reverse=True):
        try:
            records.append(parse_record(path))
        except (OSError, UnicodeError) as error:
            errors.append(f"{path.name}: {error}")
    def order(record):
        match = re.search(r"(?:확인한 사용자 발언 범위|사용자 제안 시각|사용자 요청 시각):\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", reviewed_part(record.text))
        return (match[1] if match else record.path.name[:10] + " 00:00:00", record.path.name)
    records.sort(key=order, reverse=True)
    return records, errors


def filter_records(records, query="", missing_only=False):
    words = query.casefold().split()
    return [record for record in records if (not missing_only or record.gaps)
            and all(word in (record.title + "\n" + reviewed_part(record.text)).casefold() for word in words)]


def build_missing_index(records, now):
    counts = {}
    lines = ["# 대화 기록의 누락 인덱스", "", f"- 갱신 시각: {now}",
             "- 새 요약 영역만 집계한다. 원기록은 변경하거나 집계하지 않는다.",
             f"- 기록 {len(records)}개 · 누락 필드 {sum(len(record.gaps) for record in records)}개.",
             "- 사용자 보완은 원문 확인/회고의 출처 표시와 함께 각 기록에 남는다.",
             "", "[작성 규칙](FORMAT.md) · [기록 양식](_template.md)", "",
             "검색: `rg -n 'FDLOG_MISSING_' docs/ai-dev-log -g '2026-*.md'`", "",
             "## 기록별 빠진 필드", "", "| 기록 | 개수 | 종류·항목 |", "| --- | ---: | --- |"]
    for record in records:
        if not record.gaps:
            continue
        fields = []
        for gap in record.gaps:
            counts[gap.kind] = counts.get(gap.kind, 0) + 1
            fields.append(f"{gap.kind}({gap.item})")
        label = record.title.replace("|", "／").replace("[", "(").replace("]", ")")
        lines.append(f"| [{label}]({record.path.name}) | {len(record.gaps)} | {'; '.join(fields)} |")
    lines += ["", "## 유형별 남은 필드", "", "| 유형 | 개수 |", "| --- | ---: |"]
    lines += [f"| {kind} | {count} |" for kind, count in sorted(counts.items())]
    return "\n".join(lines) + "\n"
