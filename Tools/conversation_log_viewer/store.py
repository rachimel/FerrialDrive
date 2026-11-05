"""보완 저장·인덱스 동기화·충돌 검사·기록별 되돌리기."""

from contextlib import contextmanager
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .model import LEGACY_HEADING, build_missing_index, digest, list_records, parse_record, reviewed_part

KST = timezone(timedelta(hours=9))


class ConflictError(ValueError):
    pass


def _atomic_write(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _literal(value):
    # 입력을 새 누락 태그나 섹션으로 오인하지 않도록 본문은 인용문으로 보관한다.
    return value.replace("[[", "［［").replace("]]", "］］").replace("\x00", "")


class LogStore:
    def __init__(self, directory, workspace):
        self.directory = Path(directory).resolve()
        self.workspace = Path(workspace).resolve()
        self.history_dir = self.workspace / "history"

    def _path(self, path):
        path = Path(path).resolve()
        if path.parent != self.directory or path.suffix != ".md":
            raise ValueError("선택한 로그 폴더의 Markdown만 수정할 수 있다.")
        return path

    @contextmanager
    def _lock(self):
        self.history_dir.mkdir(parents=True, exist_ok=True)
        with (self.workspace / "save.lock").open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise ConflictError("다른 창에서 저장 중이다. 잠시 후 다시 적용한다.") from None
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _index(self, path, after, now):
        records, errors = list_records(self.directory)
        if errors:
            raise ValueError("인덱스 갱신 전 로그 읽기 오류를 확인한다: " + errors[0])
        records = [parse_record(path, after) if record.path.resolve() == path else record for record in records]
        return build_missing_index(records, now).encode("utf-8")

    def _commit(self, path, before, after, history, history_path):
        index_path = self.directory / "MISSING_INDEX.md"
        index_before = index_path.read_bytes() if index_path.exists() else None
        index_after = self._index(path, after, history["updated_at"])
        if path.read_bytes() != before:
            raise ConflictError("다른 곳에서 파일을 수정했다. 새로고침 후 다시 적용한다.")
        current_index = index_path.read_bytes() if index_path.exists() else None
        if current_index != index_before:
            raise ConflictError("다른 곳에서 누락 인덱스를 수정했다. 새로고침한다.")
        previous_history = history_path.read_bytes() if history_path.exists() else None
        history_data = json.dumps(history, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            _atomic_write(path, after)
            _atomic_write(index_path, index_after)
            _atomic_write(history_path, history_data)
        except BaseException:
            # 우리 쓰기가 남아 있을 때만 되돌려 외부 변경을 덮어쓰지 않는다.
            if path.read_bytes() == after:
                _atomic_write(path, before)
            if index_path.exists() and index_path.read_bytes() == index_after:
                if index_before is None:
                    index_path.unlink()
                else:
                    _atomic_write(index_path, index_before)
            if previous_history is not None:
                _atomic_write(history_path, previous_history)
            elif history_path.exists():
                history_path.unlink()
            raise

    def apply(self, record, token, body, *, source_kind="recollection", evidence="", event_time=""):
        body, evidence, event_time = body.strip(), evidence.strip(), event_time.strip()
        if not body or len(body) > 8000 or len(evidence) > 2000:
            raise ValueError("보완 내용은 1~8000자, 근거는 2000자 이내로 입력한다.")
        if source_kind not in ("recollection", "source_checked", "codex_record"):
            raise ValueError("보완 출처를 선택한다.")
        if source_kind in ("source_checked", "codex_record") and not evidence:
            raise ValueError("원문 확인을 선택한 경우 원문 위치나 확인 근거를 입력한다.")
        gap = next((gap for gap in record.gaps if gap.token == token), None)
        if gap is None:
            raise ConflictError("선택한 누락 항목이 없다. 새로고침한다.")
        if gap.kind == "TIME" and not event_time:
            raise ValueError("시각 항목은 당시 시각 또는 날짜도 입력한다.")
        if event_time:
            parts = event_time.split(" ~ ")
            if len(parts) > 2 or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?", part) for part in parts):
                raise ValueError("당시 시각은 날짜·시각(소수 초 허용), 범위는 시작 ~ 끝으로 입력한다.")
            try:
                values = [datetime.fromisoformat(part) for part in parts]
            except ValueError:
                raise ValueError("실제로 존재하는 날짜와 시각을 입력한다.") from None
            if len(values) == 2 and values[0] > values[1]:
                raise ValueError("시각 범위의 시작은 끝보다 늦을 수 없다.")
        with self._lock():
            path = self._path(record.path)
            before = path.read_bytes()
            if digest(before) != record.fingerprint:
                raise ConflictError("다른 곳에서 파일을 수정했다. 새로고침 후 다시 적용한다.")
            text = before.decode("utf-8-sig")
            front, separator, legacy = text.partition(LEGACY_HEADING)
            if front.count(token) != 1:
                raise ConflictError("누락 표식이 바뀌었다. 새로고침한다.")
            now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " KST"
            entry_id = "B-" + uuid4().hex[:12]
            source = {"recollection": "사용자 회고", "source_checked": "사용자가 원문 확인으로 보완",
                      "codex_record": "Codex 원문 선택으로 보완"}[source_kind]
            lines = front.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if token in line:
                    if line.count("[[FDLOG_MISSING_") != 1:
                        raise ValueError("같은 줄에 여러 누락이 있어 개별 적용할 수 없다.")
                    label = line.split("— 모름", 1)[0].split("모름", 1)[0].split(token, 1)[0].rstrip(" `—.\r\n")
                    compact = re.sub(r"\s+", " ", _literal(body))
                    compact = compact[:160] + ("…" if len(compact) > 160 else "")
                    lines[index] = f"{label} — 사용자 보완 {entry_id}: {compact} ({source}).\n"
                    break
            front = "".join(lines).rstrip()
            if "## 사용자 보완 기록" not in front:
                front += "\n\n## 사용자 보완 기록"
            original_time = event_time.replace("T", " ") + (" (날짜만 확인)" if len(event_time) == 10 else " KST") if event_time else "모름(미입력)"
            addition = [f"### {entry_id} — {now}", "", f"- 작성자: 사용자 입력 / 출처: {source}",
                        f"- 보완 필드: `{token[2:-2]}`", f"- 당시 발언/사건 시각: {original_time}",
                        f"- 보완 기록 시각: {now}", "- 내용:"]
            addition += ["> " + _literal(line) for line in body.splitlines()]
            addition += ["- 근거·원문 위치:"] + ["> " + _literal(line) for line in (evidence or "미입력 — 원문 검증으로 간주하지 않는다.").splitlines()]
            addition += ["- Codex 원문과 기록 시각을 가져왔으며 제안·수용 등 의미의 연결은 사용자가 선택했다."
                         if source_kind == "codex_record" else
                         "- 원문 확인 여부는 사용자의 입력 표시이며 툴이 원문을 자동 검증한 결과가 아니다."]
            after = (front + "\n\n" + "\n".join(addition) + "\n\n" + separator + legacy).encode("utf-8")
            if before.startswith(b"\xef\xbb\xbf"):
                after = b"\xef\xbb\xbf" + after
            history = {"id": entry_id, "file": str(path), "created_at": now, "updated_at": now,
                       "before_base64": base64.b64encode(before).decode("ascii"),
                       "after_sha256": digest(after), "status": "applied", "token": token}
            self._commit(path, before, after, history, self.history_dir / (entry_id + ".json"))
            return parse_record(path)

    def undo(self, record):
        with self._lock():
            path = self._path(record.path)
            histories = []
            for history_path in self.history_dir.glob("B-*.json"):
                item = json.loads(history_path.read_text(encoding="utf-8"))
                if item.get("file") == str(path) and item.get("status") == "applied":
                    histories.append((item["created_at"], history_path, item))
            if not histories:
                raise ValueError("이 기록에서 되돌릴 보완이 없다.")
            _, history_path, history = max(histories, key=lambda item: (item[0], item[1].name))
            before = path.read_bytes()
            if digest(before) != record.fingerprint or digest(before) != history["after_sha256"]:
                raise ConflictError("저장 후 외부 변경이 있어 되돌릴 수 없다. 원본과 보완 이력을 확인한다.")
            after = base64.b64decode(history["before_base64"])
            history["status"] = "undone"
            history["updated_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
            self._commit(path, before, after, history, history_path)
            return parse_record(path)
