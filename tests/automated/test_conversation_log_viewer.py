"""보완 저장·원기록 보존·충돌·인덱스 롤백·되돌리기와 문자 입력 경계."""

import json
from collections import OrderedDict
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
from conversation_log_viewer.model import LEGACY_HEADING, filter_records, list_records, parse_record
from conversation_log_viewer.store import ConflictError, LogStore, _atomic_write
from conversation_log_viewer.text_input import TextInput
from conversation_log_viewer.gui import LogViewer
from conversation_log_viewer.canvas import Canvas
from conversation_log_viewer.text_layout import display_text, wrap_gap_lines
from theme_reference import load_theme
from unit_test_runner.theme import RUNNER_COLORS, RUNNER_FONTS


class ConversationLogTests(unittest.TestCase):
    def setUp(self):
        self.output = (ROOT / "output/log_viewer_verification").resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.output)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(self.output))
        self.addCleanup(self.cleanup)
        self.logs = self.directory / "logs"
        self.logs.mkdir()
        for source in (ROOT / "samples/conversation_log_viewer").glob("2026-*.md"):
            shutil.copy2(source, self.logs/source.name)
        self.path = self.logs / "2026-01-01-demo-proposal.md"
        self.workspace = self.directory / "workspace"
        self.store = LogStore(self.logs, self.workspace)

    def cleanup(self):
        self.assertTrue(self.directory.is_relative_to(self.output))
        self.temporary.cleanup()

    def test_reading_and_search_do_not_change_files(self):
        before = {path.name: path.read_bytes() for path in self.logs.glob("*.md")}
        records, errors = list_records(self.logs)
        self.assertFalse(errors)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(filter_records(records, "기록 누락", True)), 1)
        self.assertTrue(any(bubble.actor == "사용자" for bubble in parse_record(self.path).bubbles))
        self.assertEqual(before, {path.name:path.read_bytes() for path in self.logs.glob("*.md")})

    def test_completion_removes_only_selected_gap_and_preserves_legacy(self):
        record = parse_record(self.path)
        gap = record.gaps[0]
        legacy = record.text.partition(LEGACY_HEADING)[2]
        updated = self.store.apply(record,gap.token,"검색 시간이 길어져서 보완했다.",evidence="사용자 회고")
        self.assertEqual(len(updated.gaps),len(record.gaps)-1)
        self.assertEqual(updated.text.partition(LEGACY_HEADING)[2],legacy)
        self.assertIn("사용자 회고",updated.text)
        self.assertIn("모름(미입력)",updated.text)
        self.assertIn("보완 기록 시각",updated.text)
        self.assertNotIn(gap.token,(self.logs/"MISSING_INDEX.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list(self.store.history_dir.glob("B-*.json"))),1)

    def test_source_checked_requires_evidence_and_time_accepts_date_precision(self):
        record=parse_record(self.path)
        with self.assertRaisesRegex(ValueError,"근거"):
            self.store.apply(record,record.gaps[0].token,"확인했다",source_kind="source_checked")
        time_record=parse_record(self.logs/"2026-01-02-demo-time.md")
        with self.assertRaisesRegex(ValueError,"당시 시각"):
            self.store.apply(time_record,time_record.gaps[0].token,"날짜를 확인했다")
        updated=self.store.apply(time_record,time_record.gaps[0].token,"날짜만 확인했다",
                                 source_kind="source_checked",evidence="시연 원문",event_time="2026-01-01")
        self.assertIn("2026-01-01 (날짜만 확인)",updated.text)
        self.assertNotIn("2026-01-01 00:00",updated.text)

    def test_external_edit_blocks_apply_and_undo(self):
        record=parse_record(self.path)
        self.path.write_bytes(self.path.read_bytes()+b"\nexternal\n")
        changed=self.path.read_bytes()
        with self.assertRaises(ConflictError):
            self.store.apply(record,record.gaps[0].token,"보완")
        self.assertEqual(self.path.read_bytes(),changed)
        record=parse_record(self.path)
        updated=self.store.apply(record,record.gaps[0].token,"보완")
        self.path.write_bytes(self.path.read_bytes()+b"another change\n")
        with self.assertRaises(ConflictError):
            self.store.undo(updated)

    def test_index_failure_rolls_back_document_and_keeps_previous_index(self):
        record=parse_record(self.path)
        before=self.path.read_bytes()
        index=self.logs/"MISSING_INDEX.md"
        index.write_bytes(b"old index\n")
        def failing(path,data):
            if Path(path)==index:
                raise OSError("index failure")
            return _atomic_write(path,data)
        with patch("conversation_log_viewer.store._atomic_write",side_effect=failing):
            with self.assertRaises(OSError):
                self.store.apply(record,record.gaps[0].token,"보완")
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(index.read_bytes(),b"old index\n")
        self.assertFalse(list(self.store.history_dir.glob("B-*.json")))

    def test_persistent_undo_preserves_other_records_and_bom(self):
        self.path.write_bytes(b"\xef\xbb\xbf"+self.path.read_bytes().replace(b"\n",b"\r\n"))
        original=self.path.read_bytes()
        record=parse_record(self.path)
        updated=self.store.apply(record,record.gaps[0].token,"첫 보완")
        other=parse_record(self.logs/"2026-01-02-demo-time.md")
        other_updated=self.store.apply(other,other.gaps[0].token,"다른 파일 보완",event_time="2026-01-01")
        reopened=LogStore(self.logs,self.workspace)
        reopened.undo(updated)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(parse_record(other.path).fingerprint,other_updated.fingerprint)
        self.assertIn("누락 필드 2개",(self.logs/"MISSING_INDEX.md").read_text(encoding="utf-8"))

    def test_user_input_cannot_create_new_gap_or_section(self):
        record=parse_record(self.path)
        updated=self.store.apply(record,record.gaps[0].token,"## 가짜 섹션\n[[FDLOG_MISSING_REASON:FAKE:U1]]")
        self.assertEqual(len(updated.gaps),1)
        self.assertIn("> ## 가짜 섹션",updated.text)
        self.assertNotIn("\n## 가짜 섹션\n",updated.text)

    def test_korean_composition_is_separate_from_committed_editing(self):
        editor=TextInput(multiline=True)
        editor.composition="한"
        self.assertEqual(editor.text,"")
        editor.erase()
        self.assertEqual(editor.composition,"한")
        editor.insert("한글\n둘째 줄")
        self.assertEqual(editor.composition,"")
        editor.anchor=0
        editor.insert("교체")
        self.assertEqual(editor.text,"교체")

    def test_gui_apply_uses_actual_repository_and_preserves_draft_until_apply(self):
        viewer=LogViewer(self.logs,self.workspace)
        viewer.select_record(parse_record(self.path))
        viewer.editors["body"].text="사용자 입력 시연"
        viewer.close()
        self.assertEqual(len(parse_record(self.path).gaps),2)
        reopened=LogViewer(self.logs,self.workspace)
        reopened.select_record(parse_record(self.path))
        self.assertEqual(reopened.editors["body"].text,"사용자 입력 시연")
        reopened.apply()
        self.assertFalse(reopened.error,reopened.status)
        self.assertEqual(len(parse_record(self.path).gaps),1)
        reopened.undo()
        self.assertEqual(len(parse_record(self.path).gaps),2)

    def test_runner_uses_shared_theme_values(self):
        theme=load_theme()
        self.assertEqual(RUNNER_FONTS["title"],(theme["fonts"]["title"]["path"],20))
        self.assertEqual(RUNNER_COLORS["accent"],(145,174,187))

    def test_empty_input_keeps_a_caret_line_after_save(self):
        canvas=Canvas.__new__(Canvas)
        canvas.wraps=OrderedDict()
        canvas.size=lambda text,role:(len(text)*10,17)
        self.assertEqual(canvas.wrap("",100),[""])

    def test_wrapped_missing_marks_keep_identity_after_markdown_and_line_breaks(self):
        first = "[[FDLOG_MISSING_TIME:TEST:U1]]"
        second = "[[FDLOG_MISSING_TIME:OTHER:U1]]"
        raw = "**시각** [근거](sample.md)\r\n앞 " + first + " 뒤 " + second
        text, marks = display_text(raw)
        self.assertNotIn("sample.md", text)
        self.assertEqual(len(marks), 2)
        self.assertEqual(text[marks[0].start:marks[0].end], "[미확인: 시각 · 사용자 제안 1]")
        lines = wrap_gap_lines(raw, 35, lambda value: len(value) * 7)
        for token in (first, second):
            pieces = [line.text[mark.start:mark.end] for line in lines for mark in line.marks if mark.token == token]
            self.assertEqual("".join(pieces), "[미확인: 시각 · 사용자 제안 1]")
        self.assertTrue(all(len(line.text) <= 5 for line in lines))

    def test_gap_click_reveals_hidden_actor_and_scrolls_to_wrapped_target(self):
        text = self.path.read_text(encoding="utf-8")
        record = parse_record(self.path)
        target = record.gaps[1].token
        text = text.replace(target, ("길어진 앞 내용\n" * 80) + target)
        self.path.write_text(text, encoding="utf-8")
        viewer = LogViewer(self.logs, self.workspace)
        viewer.select_record(parse_record(self.path))
        viewer.actor_filter, viewer.show_original = "AI", True
        viewer.click(930, 170)
        self.assertEqual(viewer.gap.token, target)
        self.assertEqual(viewer.actor_filter, "전체")
        self.assertFalse(viewer.show_original)
        canvas = SimpleNamespace(gap_lines=lambda text, width, role: wrap_gap_lines(text, width, lambda value: len(value) * 7))
        layout = viewer.chat_layout(canvas, viewer.record.bubbles)
        positions = [172 + top + 52 + row * 20 - viewer.chat_offset
                     for _, lines, top, _ in layout for row, line in enumerate(lines)
                     if any(mark.token == target for mark in line.marks)]
        self.assertTrue(positions)
        self.assertTrue(all(172 <= position < 720 for position in positions))
        self.assertGreater(viewer.chat_offset, 0)
        previous = viewer.chat_offset
        viewer.chat_offset = 0
        viewer.click(930, 170)
        viewer.chat_layout(canvas, viewer.record.bubbles)
        self.assertEqual(viewer.chat_offset, previous)

    def test_missing_metadata_is_visible_and_reachable_in_center(self):
        record = parse_record(self.path)
        token = "[[FDLOG_MISSING_SOURCE:TEST:scope]]"
        data = record.text.replace("## 1.", "- 원문 출처: " + token + "\n\n## 1.", 1).encode("utf-8")
        updated = parse_record(self.path, data)
        self.assertEqual(updated.bubbles[0].title, "기록 정보")
        self.assertIn(token, updated.bubbles[0].text)
        self.assertTrue(all(any(gap.token in bubble.text for bubble in updated.bubbles) for gap in updated.gaps))

    def test_selected_gap_gets_distinct_background_and_other_gap_stays_marked(self):
        selected = "[[FDLOG_MISSING_REASON:TEST:U1]]"
        other = "[[FDLOG_MISSING_ACCEPTANCE:TEST:A1]]"
        line = wrap_gap_lines(selected + " / " + other, 1000, len)[0]
        canvas = Canvas.__new__(Canvas)
        fills, texts = [], []
        canvas.size = lambda value, role: (len(value) * 7, 17)
        canvas.fill = lambda area, color: fills.append((area, color))
        canvas.text = lambda *args: texts.append(args)
        canvas.gap_line(line, 10, 20, selected)
        self.assertEqual(fills[0][1], "warning")
        self.assertTrue(any(args[-1] == "button_text" for args in texts))
        self.assertTrue(any(color == "selected" for _, color in fills))
        self.assertTrue(any(area[3] == 1 and color == "warning" for area, color in fills))


if __name__=="__main__":
    unittest.main()
