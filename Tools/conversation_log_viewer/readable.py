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
