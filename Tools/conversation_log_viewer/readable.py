"""기록 식별자는 보존하고 화면용 이름·시각·검색 맥락을 만든다."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

REFERENCE = re.compile(r"(?<![A-Za-z0-9_])([UAIV])(\d+)(?:\s*[-~–]\s*(?:\1)?(\d+))?(?![A-Za-z0-9_])")
REFERENCE_NAMES = {"U": "사용자 제안", "A": "AI 제안", "I": "발견한 문제", "V": "확인 결과"}
ITEM_NAMES = {"scope": "대화 전체", "adoption": "수용·착수", "style-values": "표현 값 결정"}
SECTION_TITLES = (
    "사용자가 제안한 것", "사용자 제안 중 AI가 수용한 것", "AI가 제안한 것",
    "AI가 제안한 것 중 사용자가 수용한 것", "반영 후 발견한 문제",
    "사용자 해결 제안과 실제 해결 과정", "AI 해결 제안과 실제 해결 과정",
)
UTC_STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)"


def reference_label(match):
    return REFERENCE_NAMES[match[1]] + " " + match[2] + ("~" + match[3] if match[3] else "")


def item_label(value):
    return ITEM_NAMES.get(value, REFERENCE_NAMES.get(value, REFERENCE.sub(reference_label, value)))


def proposal_id(line):
    match = re.match(r"\s*-\s*(?:\*\*)?(?:([UAIV]\d+)(?!\d)|(?:사용자 제안|AI 제안|발견한 문제|확인 결과)\s*\d+\s*\(([UAIV]\d+)\))", line)
    return (match[1] or match[2]) if match else None


def human_times(text):
    result = []
    for line in text.splitlines():
        if "KST" in line:
            line = re.sub(r"\s*/\s*`?(?:UTC\s*)?" + UTC_STAMP + r"`?", "", line)
        def convert(match):
            try:
                parsed = datetime.fromisoformat(match[1].replace("Z", "+00:00"))
            except ValueError:
                return match[0]
            local = parsed.astimezone(timezone(timedelta(hours=9)))
            precision = "microseconds" if re.search(r"\.\d{4,}", match[1]) else "milliseconds" if "." in match[1] else "seconds"
            return local.replace(tzinfo=None).isoformat(sep=" ", timespec=precision) + " KST"
        line = re.sub(r"(?:UTC\s+)?(" + UTC_STAMP + r")", convert, line)
        line = re.sub(r"(기록|발언) UTC\s*:", r"\1 시각:", line)
        result.append(line)
    return "\n".join(result)


def section_number(heading):
    normalized = re.sub(r"^\d+\.\s*|\s+", "", heading)
    aliases = {re.sub(r"\s+", "", title): index + 1 for index, title in enumerate(SECTION_TITLES)}
    aliases["AI제안중사용자가수용한것"] = 4
    return aliases.get(normalized)


def linked_metadata(metadata, record_text):
    """같은 원문으로 완료한 시각·출처 행만 읽기용으로 묶는다."""
    history = record_text.partition("## 사용자 보완 기록")[2]
    entries = {}
    for match in re.finditer(r"(?ms)^### (B-[0-9a-f]+) — [^\n]+\n(.*?)(?=^### |\Z)", history):
        body = match[2]
        field = re.search(r"(?m)^- 보완 필드: `FDLOG_MISSING_(TIME|SOURCE):([^`]+)`", body)
        time = re.search(r"(?m)^- 당시 발언/사건 시각: (.+)$", body)
        evidence = body.partition("- 근거·원문 위치:\n")[2]
        evidence = "\n".join(line[2:].rstrip() for line in evidence.splitlines() if line.startswith("> "))
        if not field or not time or not re.match(r"\d{4}-\d{2}-\d{2}", time[1]):
            continue
        if "출처: Codex 원문 선택으로 보완" not in body or not re.search(r"(?m)^발언 ID: (?!기록 없음).+", evidence):
            continue
        entries[match[1]] = (field[1], field[2], time[1], evidence, body)
    lines = metadata.splitlines()
    groups = {}
    for index, line in enumerate(lines):
        match = re.search(r"— 사용자 보완 (B-[0-9a-f]+):", line)
        entry = entries.get(match[1]) if match else None
        if entry:
            kind, target, time, evidence, body = entry
            groups.setdefault((target, time, evidence), []).append((index, kind, body))
    replacements, removed = {}, set()
    for (target, time, evidence), rows in groups.items():
        if len(rows) != 2 or {kind for _, kind, _ in rows} != {"TIME", "SOURCE"}:
            continue
        first, second = sorted(index for index, _, _ in rows)
        title = re.search(r"(?m)^대화: (.+)$", evidence)
        actor = re.search(r"(?m)^발언자: (.+)$", evidence)
        quotes = re.findall(r"(?ms)^원문: (.*?)(?=\n\n대화: |\Z)", evidence)
        item = target.rsplit(":", 1)[-1]
        merged = ["- **연결된 원문 근거 · " + item_label(item) + "**",
                  "  - **기록 시각:** " + time]
        if title:
            merged.append("  - **대화:** " + title[1] + (" · " + actor[1] if actor else ""))
        for number, quote in enumerate(quotes, 1):
            label = "원문" + (f" {number}" if len(quotes) > 1 else "")
            merged.append("  - **" + label + ":** " + " ".join(quote.split()))
        for _, kind, body in rows:
            content = body.partition("- 내용:\n")[2].partition("- 근거·원문 위치:")[0]
            content = " ".join(line[2:].strip() for line in content.splitlines() if line.startswith("> ")).strip()
            if content and content != "선택한 Codex 원문 기록을 근거로 연결했다.":
                merged.append("  - " + ("시각" if kind == "TIME" else "출처") + " 보완: " + content)
        replacements[first] = "\n".join(merged)
        removed.add(second)
    return "\n".join(replacements.get(index, line) for index, line in enumerate(lines) if index not in removed)


@dataclass(frozen=True)
class SearchContext:
    record_title: str
    record_id: str
    label: str
    description: str
    related: tuple[str, ...]
    suggestions: tuple[str, ...]
    hint: str = ""

    @property
    def detail(self):
        return "\n".join(["기록: " + self.record_title, self.description,
                          *("관련 내용: " + value for value in self.related), self.hint]).rstrip()


def search_context(record, gap):
    if record is None or gap is None:
        return None
    from .model import GAP_NAMES, GAP_PATTERN, reviewed_part
    from .text_layout import display_text
    front = reviewed_part(record.text)
    wanted = set()
    for match in REFERENCE.finditer(gap.item + " " + gap.context):
        end = min(int(match[3] or match[2]), int(match[2]) + 30)
        wanted.update(match[1] + str(number) for number in range(int(match[2]), end + 1))
    related = []
    for line in front.splitlines():
        identity = proposal_id(line)
        if identity in wanted and not GAP_PATTERN.search(line):
            related.append(display_text(line)[0])
    before, _, after = gap.context.partition(gap.token)
    description = display_text(before)[0].strip("- `.")
    hint = display_text(after)[0].strip("- `.")
    suggestions = re.findall(r"[‘“\"]([^’”\"\n]{3,100})[’”\"]", gap.context)
    if not suggestions:
        match = re.search(r"검색 구절[:：]([^\n]+)", front)
        if match:
            suggestions = re.findall(r"[‘“\"]([^’”\"\n]{3,100})[’”\"]", match[1])
    return SearchContext(record.title, record.record_id,
                         GAP_NAMES.get(gap.kind, gap.kind) + " · " + item_label(gap.item),
                         description, tuple(dict.fromkeys(related)), tuple(dict.fromkeys(suggestions)), hint)
