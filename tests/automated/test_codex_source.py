"""원문 범위·시각 정밀도·공개 응답 필터·초안 가져오기와 실제 보완 경계."""

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
from conversation_log_viewer.codex_source import CodexSource, export_messages, selection_data
from conversation_log_viewer.gui import LogViewer
from conversation_log_viewer.model import parse_record

FIRST = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


class CodexSourceTests(unittest.TestCase):
    def setUp(self):
        output = ROOT / "output/log_viewer_verification"
        output.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=output)
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(output.resolve()))
        self.addCleanup(self.temporary.cleanup)
        self.home = self.root / "codex"
        shutil.copytree(ROOT / "samples/conversation_log_viewer/codex_demo", self.home)
        self.source = CodexSource(self.home)
        self.path = self.source.threads([FIRST])[0].paths[0]
        self.logs, self.workspace = self.root / "logs", self.root / "workspace"
        self.logs.mkdir()
        for path in (ROOT / "samples/conversation_log_viewer").glob("*.md"):
            if path.name[:4].isdigit():
                shutil.copy2(path, self.logs / path.name)

    def append(self, item, timestamp="2026-01-01T03:05:00.500Z", event_type="response_item"):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"timestamp": timestamp, "type": event_type, "payload": item}) + "\n")

    def message(self, identity, text, **kwargs):
        return dict(type="message", id=identity, role="user", content=[{"type":"input_text", "text":text}], **kwargs)

    def viewer(self):
        viewer = LogViewer(self.logs, self.workspace, codex_home=self.home)
        viewer.select_record(parse_record(self.logs / "2026-01-02-demo-time.md"))
        self.addCleanup(viewer.source_browser.close)
        return viewer

    def test_project_membership_separates_shared_working_directory_and_reads_only(self):
        before = {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}
        project = next(project for project in self.source.projects() if project.name == "Ferrial Drive")
        self.assertEqual(project.thread_ids, (FIRST,))
        messages, errors = self.source.search(project.thread_ids, "시연용 보호")
        self.assertFalse(errors)
        self.assertEqual(len(messages), 3)
        self.assertTrue(all(message.thread_id == FIRST for message in messages))
        self.assertEqual(before, {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()})

    def test_message_record_time_keeps_milliseconds_and_turn_identity(self):
        messages, _ = self.source.search([FIRST], actor="사용자")
        self.assertEqual(messages[0].kst, "2026-01-01 12:00:00.125")
        self.assertEqual(messages[0].utc, "2026-01-01T03:00:00.125Z")
        self.assertEqual(messages[0].turn_id, "demo-turn-1")
        self.assertEqual(messages[0].item_id, "demo-user-1")

    def test_non_dialogue_and_analysis_are_excluded_without_deduplicating_real_repeats(self):
        self.append(self.message("hidden", "시연용 추론", channel="analysis", role_override="ignored"))
        self.append(self.message("context", "# AGENTS.md instructions for demo\n시연용"))
        self.append({"type": "function_call_output", "output": "시연용 도구 출력"})
        self.append({"type": "user_message", "message": "시연용 보호 기능은 자동으로 동작한다."}, event_type="event_msg")
        self.append(self.message("repeat", "시연용 보호 기능은 자동으로 동작한다."))
        messages, errors = self.source.search([FIRST], "시연용")
        self.assertFalse(errors)
        self.assertEqual(len(messages), 4)
        self.assertNotIn("hidden", [message.item_id for message in messages])
        self.assertEqual(sum(message.text == "시연용 보호 기능은 자동으로 동작한다." for message in messages), 2)

    def test_missing_or_naive_time_is_not_replaced_with_turn_or_file_time(self):
        self.append(self.message("missing", "시간 없는 시연용 발언"), timestamp=None)
        self.append(self.message("naive", "시간대 없는 시연용 발언"), timestamp="2026-01-01T12:00:00")
        messages, _ = self.source.search([FIRST], "없는")
        self.assertTrue(all(not message.kst for message in messages))
        with self.assertRaisesRegex(ValueError, "기록 시각"):
            selection_data(messages, require_time=True)
        self.assertIn("미상", selection_data(messages)[1])

    def test_time_range_uses_chronological_endpoints_and_excludes_private_paths(self):
        messages, _ = self.source.search([FIRST])
        time, evidence = selection_data([messages[0], messages[-1]], require_time=True)
        self.assertEqual(time, "2026-01-01 12:00:00.125 ~ 2026-01-01 12:02:00.500")
        self.assertIn("demo-agent-2", evidence)
        self.assertNotIn("UTC", evidence)
        self.assertNotIn(str(self.home), evidence)
        seconds = replace(messages[0], timestamp="2026-01-01T03:00:00Z")
        millis = replace(messages[-1], timestamp="2026-01-01T12:00:00.125+09:00")
        self.assertEqual(selection_data([millis, seconds])[0], "2026-01-01 12:00:00 ~ 2026-01-01 12:00:00.125")

    def test_partial_tail_preserves_complete_messages_and_reports_error(self):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('{"timestamp":')
        messages, errors = self.source.search([FIRST])
        self.assertEqual(len(messages), 3)
        self.assertTrue(errors)

    def test_unknown_project_schema_fails_without_folder_fallback(self):
        (self.home / ".codex-global-state.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "형식"):
            self.source.projects()
        self.assertEqual(len(self.source.search([OTHER])[0]), 1)
        with self.assertRaisesRegex(ValueError, "UUID"):
            self.source.threads(["../../*"])

    def test_verification_detects_changed_record_and_export_contains_only_selected_messages(self):
        messages, _ = self.source.search([FIRST])
        self.source.verify(messages[0])
        exported = export_messages(messages, self.workspace / "exports/messages.json")
        rows = json.loads(exported.read_text(encoding="utf-8"))["messages"]
        self.assertEqual(len(rows), 3)
        self.assertNotIn("path", rows[0])
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace("확인을 마쳤다", "내용이 바뀌었다"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "변경"):
            self.source.verify(messages[0])

    def test_gui_import_stays_draft_then_apply_and_undo_preserve_precision(self):
        viewer = self.viewer()
        original = viewer.record.path.read_bytes()
        messages, _ = self.source.search([FIRST])
        viewer.editors["body"].text = "내가 확인한 범위다."
        viewer.use_codex_messages([messages[0], messages[-1]])
        self.assertEqual(viewer.record.path.read_bytes(), original)
        self.assertEqual(viewer.editors["body"].text, "내가 확인한 범위다.")
        self.assertEqual(viewer.source_kind, "codex_record")
        viewer.close()
        reopened = self.viewer()
        self.assertIn(".125 ~ ", reopened.editors["event_time"].text)
        reopened.apply()
        self.assertFalse(reopened.error, reopened.status)
        saved = reopened.record.path.read_text(encoding="utf-8")
        self.assertIn("12:00:00.125 ~ 2026-01-01 12:02:00.500 KST", saved)
        self.assertIn("의미의 연결은 사용자가 선택", saved)
        reopened.undo()
        self.assertFalse(reopened.error, reopened.status)
        self.assertEqual(reopened.record.path.read_bytes(), original)

    def test_browser_project_search_manual_add_and_selection_use_same_pipeline(self):
        viewer = self.viewer()
        browser = viewer.source_browser
        browser.open()
        self.assertEqual(browser.context.record_id, viewer.record.record_id)
        self.assertIn("시각", browser.context.label)
        browser.editors["source_query"].text = "시연용"
        browser.search()
        browser.future.result(timeout=10)
        browser.poll()
        self.assertEqual(len(browser.messages), 3)
        browser.anchor = browser.messages[-1]
        browser.import_selection()
        self.assertFalse(browser.visible)
        self.assertEqual(len(viewer.record.gaps), 1)
        self.assertIn(" ~ ", viewer.editors["event_time"].text)
        browser.open()
        browser.editors["source_thread"].text = OTHER
        browser.add_thread()
        browser.future.result(timeout=10)
        browser.poll()
        self.assertEqual(len(browser.messages), 1)
        self.assertEqual(browser.messages[0].thread_id, OTHER)

    def test_bad_range_and_import_overflow_do_not_change_draft_or_document(self):
        viewer = self.viewer()
        original = viewer.record.path.read_bytes()
        messages, _ = self.source.search([FIRST])
        viewer.editors["evidence"].text = "기존 근거" * 450
        with self.assertRaisesRegex(ValueError, "2000"):
            viewer.use_codex_messages([messages[0]])
        self.assertEqual(viewer.editors["evidence"].text, "기존 근거" * 450)
        viewer.editors["evidence"].text = ""
        viewer.editors["body"].text = "범위"
        viewer.editors["event_time"].text = "2026-01-02 12:00:00.125 ~ 2026-01-01 12:00:00.125"
        viewer.apply()
        self.assertTrue(viewer.error)
        self.assertEqual(viewer.record.path.read_bytes(), original)

    def test_modal_click_enter_and_import_do_not_apply_main_document(self):
        viewer = self.viewer()
        original = viewer.record.path.read_bytes()
        viewer.click(1120, 282)
        self.assertFalse(viewer.source_browser.visible)
        self.assertEqual(viewer.source_kind, "recollection")
        viewer.click(1120, 105)
        self.assertTrue(viewer.source_browser.visible)
        viewer.click(80, 273)
        viewer.insert("시연용")
        pico = SimpleNamespace(KMOD_CTRL=1, KMOD_SHIFT=2, SDLK_ESCAPE=27, SDLK_RETURN=13,
                               SDLK_F5=116, SDLK_TAB=9)
        viewer.key(SimpleNamespace(key=13, mod=1), pico)
        browser = viewer.source_browser
        browser.future.result(timeout=10)
        browser.poll()
        viewer.focus = None
        viewer.key(SimpleNamespace(key=9, mod=0), pico)
        self.assertEqual(viewer.focus, "source_query")
        viewer.click(400, 385)
        self.assertEqual(browser.selected.role, "user")
        viewer.click(850, 730)
        self.assertFalse(browser.visible)
        self.assertIn("12:00:00.125", viewer.editors["event_time"].text)
        self.assertEqual(viewer.record.path.read_bytes(), original)
        viewer.record = None
        viewer.click(1120, 105)
        self.assertTrue(browser.visible)

    def test_added_threads_stay_with_project_and_can_be_removed(self):
        viewer = self.viewer()
        browser = viewer.source_browser
        browser.open()
        browser.editors["source_thread"].text = OTHER
        browser.add_thread()
        browser.click(635, 225)
        self.assertEqual(browser.extra_ids, [])
        browser.click(80, 225)
        self.assertEqual(browser.extra_ids, [OTHER])
        browser.add_thread()
        self.assertEqual(browser.extra_ids, [])
        self.assertNotIn(OTHER, [thread.id for thread in browser.threads])

    def test_session_identity_mismatch_is_not_imported(self):
        content = self.path.read_text(encoding="utf-8")
        self.path.write_text(content.replace(FIRST, OTHER, 1), encoding="utf-8")
        messages, errors = self.source.search([FIRST])
        self.assertEqual(messages, [])
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
