"""선택한 Codex 프로젝트의 로컬 공개 발언과 기록 시각을 읽는다."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

KST = timezone(timedelta(hours=9))
THREAD_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
CONTEXT_PREFIXES = ("# AGENTS.md instructions", "<environment_context>",
                    "<external_codex_apps_open_page>")


def recorded_time(value):
    """시간대가 기록되지 않은 값이나 잘못된 시각을 추정하지 않는다."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def time_text(value, *, local=False):
    parsed = recorded_time(value)
    if parsed is None:
        return ""
    fraction = re.search(r"\.(\d+)", value)
    precision = "microseconds" if fraction and len(fraction[1]) > 3 else "milliseconds" if fraction else "seconds"
    parsed = parsed.astimezone(KST if local else timezone.utc)
    if local:
        return parsed.replace(tzinfo=None).isoformat(sep=" ", timespec=precision)
    return parsed.isoformat(timespec=precision).replace("+00:00", "Z")


@dataclass(frozen=True)
class CodexProject:
    id: str
    name: str
    thread_ids: tuple[str, ...]


@dataclass(frozen=True)
class CodexThread:
    id: str
    title: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class CodexMessage:
    thread_id: str
    thread_title: str
    turn_id: str
    item_id: str
    role: str
    phase: str
    text: str
    timestamp: str
    path: Path
    line: int

    @property
    def utc(self):
        return time_text(self.timestamp)

    @property
    def kst(self):
        return time_text(self.timestamp, local=True)

    @property
    def actor(self):
        return "사용자" if self.role == "user" else "AI"

    @property
    def identity(self):
        return self.thread_id, self.item_id or (str(self.path), self.line)

    @property
    def time_order(self):
        return recorded_time(self.timestamp) or datetime.min.replace(tzinfo=timezone.utc)


def read_messages(thread):
    messages, errors, seen = [], [], set()
    for path in thread.paths:
        turn_id = ""
        try:
            with path.open(encoding="utf-8-sig") as stream:
                for number, raw in enumerate(stream, 1):
                    try:
                        event = json.loads(raw)
                    except (ValueError, TypeError):
                        # 쓰는 중인 마지막 줄도 시각을 만들어 보충하지 않는다.
                        errors.append(f"{thread.title}: {number}번째 줄을 읽지 못했다.")
                        continue
                    if not isinstance(event, dict):
                        continue
                    item = event.get("payload")
                    if not isinstance(item, dict):
                        continue
                    if event.get("type") == "session_meta" and item.get("id") and item["id"] != thread.id:
                        errors.append(f"{thread.title}: 파일과 채팅 ID가 일치하지 않는다.")
                        break
                    if event.get("type") == "turn_context":
                        turn_id = str(item.get("turn_id") or "")
                    if event.get("type") == "event_msg" and item.get("type") == "task_started":
                        turn_id = str(item.get("turn_id") or "")
                    if event.get("type") != "response_item" or item.get("type") != "message":
                        continue
                    role = item.get("role")
                    if role not in ("user", "assistant") or item.get("channel") == "analysis" or item.get("phase") == "analysis":
                        continue
                    content = item.get("content")
                    if not isinstance(content, list):
                        continue
                    text = "\n".join(part["text"] for part in content if isinstance(part, dict)
                                     and part.get("type") in ("input_text", "output_text", "text")
                                     and isinstance(part.get("text"), str))
                    if not text.strip() or role == "user" and text.lstrip().startswith(CONTEXT_PREFIXES):
                        continue
                    value = event.get("timestamp")
                    message = CodexMessage(thread.id, thread.title, turn_id, str(item.get("id") or ""),
                                           role, str(item.get("phase") or item.get("channel") or ""),
                                           text, value if isinstance(value, str) else "", path, number)
                    if message.identity not in seen:
                        messages.append(message)
                        seen.add(message.identity)
        except (OSError, UnicodeError) as error:
            errors.append(f"{thread.title}: 기록 읽기 실패 ({type(error).__name__}).")
    return messages, errors


class CodexSource:
    """데스크톱 로컬 저장 형식용 읽기 전용 어댑터. 경로로 프로젝트를 추측하지 않는다."""

    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()

    def projects(self):
        try:
            data = json.loads((self.home / ".codex-global-state.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ValueError("Codex 프로젝트 정보를 읽지 못했다. 채팅 ID로 직접 추가할 수 있다.") from error
        projects = data.get("local-projects") if isinstance(data, dict) else None
        assignments = data.get("thread-project-assignments") if isinstance(data, dict) else None
        if not isinstance(projects, dict) or not isinstance(assignments, dict):
            raise ValueError("지원하지 않는 Codex 프로젝트 형식이다. 채팅 ID로 직접 추가한다.")
        hosts = data.get("thread-project-membership-host-ids", {})
        result = []
        for identity, project in projects.items():
            if not isinstance(project, dict):
                continue
            ids = tuple(key for key, membership in assignments.items()
                        if THREAD_ID.fullmatch(key) and isinstance(membership, dict)
                        and membership.get("projectKind") == "local"
                        and membership.get("projectId") == identity
                        and (not isinstance(hosts, dict) or hosts.get(key, "local") == "local"))
            result.append(CodexProject(identity, str(project.get("name") or identity), ids))
        return sorted(result, key=lambda project: project.name.casefold())

    def threads(self, identities):
        identities = set(identities)
        if any(not THREAD_ID.fullmatch(value) for value in identities):
            raise ValueError("채팅 ID는 UUID 형식이어야 한다.")
        titles = {}
        index = self.home / "session_index.jsonl"
        if index.is_file():
            with index.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and row.get("id") in identities:
                        titles[row["id"]] = str(row.get("thread_name") or row["id"])
        paths = {identity: [] for identity in identities}
        for folder in (self.home / "sessions", self.home / "archived_sessions"):
            if not folder.is_dir():
                continue
            for path in folder.rglob("*.jsonl"):
                identity = path.stem[-36:]
                if identity in paths and path.resolve().is_relative_to(folder.resolve()):
                    paths[identity].append(path.resolve())
        return [CodexThread(identity, titles.get(identity, identity), tuple(sorted(paths[identity])))
                for identity in sorted(identities, reverse=True)]

    def search(self, identities, query="", actor="전체"):
        words = query.casefold().split()
        found, errors = [], []
        for thread in self.threads(identities):
            if not thread.paths:
                errors.append(f"{thread.title}: 로컬 원문 파일이 없다.")
                continue
            messages, failures = read_messages(thread)
            errors.extend(failures)
            found.extend(message for message in messages
                         if (actor == "전체" or message.actor == actor)
                         and all(word in message.text.casefold() for word in words))
        found.sort(key=lambda message: (message.time_order, message.thread_id, message.line), reverse=True)
        return found, errors

    def verify(self, message):
        roots = (self.home / "sessions", self.home / "archived_sessions")
        if not any(message.path.resolve().is_relative_to(root.resolve()) for root in roots):
            raise ValueError("Codex 기록 범위 밖의 원문이다.")
        current, _ = read_messages(CodexThread(message.thread_id, message.thread_title, (message.path,)))
        if not any(item.line == message.line and item == message for item in current):
            raise ValueError("선택 후 원문이 변경됐다. 다시 검색한다.")


def selection_data(messages, *, require_time=False):
    """의미 연결은 사용자가 선택한다. 원문 기록의 시각과 위치만 채운다."""
    messages = list(dict((message.identity, message) for message in messages).values())
    if not messages:
        raise ValueError("원문 발언을 선택한다.")
    if require_time and any(not message.kst for message in messages):
        raise ValueError("기록 시각이 없는 발언은 TIME 항목의 시각으로 가져올 수 없다.")
    messages.sort(key=lambda message: (message.time_order, message.thread_id, message.line))
    times = [message.kst for message in messages if message.kst]
    event_time = (times[0] if len(set(times)) == 1 else times[0] + " ~ " + times[-1]) if times else ""
    evidence = []
    for message in messages:
        evidence.extend((f"대화: {message.thread_title}", f"대화 ID: {message.thread_id}",
                         f"턴 ID: {message.turn_id or '기록 없음'}", f"발언 ID: {message.item_id or '기록 없음'}",
                         f"원문 위치: 기록 {message.line}번째 줄", f"발언자: {message.actor}",
                         f"기록 시각: {message.kst + ' KST' if message.kst else '미상'}",
                         "원문: " + message.text.strip()[:240], ""))
    return event_time, "\n".join(evidence).rstrip()


def export_messages(messages, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for message in messages:
        row = asdict(message)
        row.pop("path")
        row.update(timestamp_utc=message.utc or None, timestamp_kst=message.kst or None)
        rows.append(row)
    from .store import _atomic_write
    _atomic_write(destination, json.dumps({"format": "codex-visible-messages-v1", "messages": rows},
                                         ensure_ascii=False, indent=2).encode("utf-8"))
    return destination
