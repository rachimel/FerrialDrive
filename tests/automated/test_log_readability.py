"""사람이 읽는 표시와 원래 식별자·보완 대상의 연결이 함께 유지되는지 확인한다."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools"))
from conversation_log_viewer.model import parse_record
from conversation_log_viewer.readable import SECTION_TITLES, item_label, search_context
from conversation_log_viewer.text_layout import display_text, formatted_text, wrap_gap_lines


class LogReadabilityTests(unittest.TestCase):
    def test_ids_emphasis_and_comments_are_formatted_without_losing_gap_identity(self):
        token = "[[FDLOG_MISSING_TIME:FDLOG-demo:scope]]"
        source = '<!-- FDLOG_REVIEW_V1 -->\n\n- 기록 ID: `FDLOG-demo`\n**핵심** `'+token+'` U1-U3 / A1'
        displayed, gaps, styles = formatted_text(source)
        self.assertNotIn('FDLOG_REVIEW', displayed)
        self.assertFalse(displayed.startswith('\n'))
        self.assertIn('사용자 제안 1~3 / AI 제안 1', displayed)
        self.assertIn('[미확인: 시각 · 대화 전체]', displayed)
        self.assertEqual(gaps[0].token, token)
        self.assertTrue(any(mark.kind=='record_id' and displayed[mark.start:mark.end]=='FDLOG-demo' for mark in styles))
        self.assertTrue(any(mark.kind=='strong' and displayed[mark.start:mark.end]=='핵심' for mark in styles))
        lines=wrap_gap_lines(source,80,lambda text:len(text)*7)
        pieces=[line.text[mark.start:mark.end] for line in lines for mark in line.marks]
        self.assertEqual(''.join(pieces),'[미확인: 시각 · 대화 전체]')

    def test_old_and_new_section_orders_have_same_human_order_and_actor(self):
        old='# 제목\n\n- 기록 ID: FDLOG-demo\n\n## 1. 사용자가 제안한 것\n- U1: 사용자 내용\n\n## 2. AI가 제안한 것\n- A1: AI 내용\n\n## 3. 사용자 제안 중 AI가 수용한 것\n- U1 수용\n\n## 4. AI 제안 중 사용자가 수용한 것\n- A1 수용\n'
        new=old.replace('## 2. AI가 제안한 것','## 3. AI가 제안한 것').replace('## 3. 사용자 제안 중 AI가 수용한 것','## 2. 사용자 제안 중 AI가 수용한 것')
        human=new.replace('- 기록 ID: FDLOG-demo','- **기록 ID:** `FDLOG-demo`').replace('- U1: 사용자 내용','- **사용자 제안 1 (U1):** 사용자 내용').replace('- A1: AI 내용','- **AI 제안 1 (A1):** AI 내용')
        for content in (old,new,human):
            record=parse_record('demo.md',content.encode())
            self.assertEqual(record.title,'제목')
            self.assertEqual(record.record_id,'FDLOG-demo')
            headings=[bubble.title for bubble in record.bubbles if bubble.kind=='heading']
            self.assertEqual(headings,[f'{index+1}. {title}' for index,title in enumerate(SECTION_TITLES[:4])])
            self.assertTrue(any(bubble.actor=='AI' and 'AI 내용' in bubble.text for bubble in record.bubbles))
            self.assertTrue(any(bubble.actor=='사용자' and '사용자 내용' in bubble.text for bubble in record.bubbles))

    def test_display_uses_korean_time_across_midnight_without_duplicate_utc(self):
        displayed,_=display_text('원문 위치: 대화 demo / UTC 2026-11-03T15:16:58.747Z')
        self.assertIn('2026-11-04 00:16:58.747 KST',displayed)
        self.assertNotIn('UTC',displayed)
        displayed,_=display_text('시각: 2026-11-04 00:16:58.747 KST / `2026-11-03T15:16:58.747Z`')
        self.assertEqual(displayed.count('2026-11-04'),1)

    def test_context_explains_target_and_resolves_related_proposals_and_hints(self):
        content='# 글꼴 조정\n\n- 기록 ID: `FDLOG-demo`\n- 사용자 요청의 정확한 시각 — 모름 [[FDLOG_MISSING_TIME:FDLOG-demo:U1-U3]]. 보완 검색: “폭 20%”\n\n## 1. 사용자가 제안한 것\n- U1: 가로 폭을 넓힌다.\n- U2: 세로 높이를 유지한다.\n- U3: 모서리를 각지게 한다.\n'
        record=parse_record('demo.md',content.encode())
        context=search_context(record,record.gaps[0])
        self.assertEqual(context.label,'시각 · 사용자 제안 1~3')
        self.assertIn('정확한 시각',context.description)
        self.assertEqual(len(context.related),3)
        self.assertIn('가로 폭을 넓힌다',context.detail)
        self.assertEqual(context.suggestions,('폭 20%',))
        self.assertNotIn('FDLOG_MISSING',context.detail)

    def test_reference_names_keep_distinct_meanings(self):
        self.assertEqual(item_label('scope'),'대화 전체')
        self.assertEqual(item_label('A1'),'AI 제안 1')
        self.assertEqual(item_label('I1'),'발견한 문제 1')
        self.assertEqual(item_label('V1'),'확인 결과 1')
        self.assertEqual(item_label('adoption'),'수용·착수')


if __name__=='__main__':
    unittest.main()
