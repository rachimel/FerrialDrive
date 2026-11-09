"""이미지 미검토·불일치·침묵이 사용자 OK로 바뀌지 않는지 검사한다."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from Tools.blender_pipeline.model_review import (
    digest, write_pending_review, record_ai_review, record_user_decision,
    require_stage_approval,
)


class ModelReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        (self.directory / 'candidate.blend').write_bytes(b'candidate')
        candidate_hash = digest(self.directory / 'candidate.blend')
        self.evidence = []
        for kind in ('before', 'after'):
            path = self.directory / f'{kind}.png'
            path.write_bytes(kind.encode())
            self.evidence.append({'file': path.name, 'sha256': digest(path), 'kind': kind})
        write_pending_review(self.directory,
            {'goal': '폭 줄이기', 'preserve': ['높이'], 'criteria': [{'id': 'width'}]},
            self.evidence, candidate_hash, {})
        (self.directory / 'report.json').write_text(json.dumps({'candidate_sha256': candidate_hash,
            'visual_approval': False, 'quality_checks_run': False}))
        review = self.read_review()
        self.assessment = {'candidate_sha256': candidate_hash,
            'evidence_digest': review['evidence_digest'],
            'checks': [{'criterion': 'width', 'verdict': 'met', 'observation': '정면 폭이 줄었다.',
                        'images': ['before.png', 'after.png']}],
            'preservation': {'verdict': 'met', 'observation': '높이는 같다.',
                             'images': ['before.png', 'after.png']},
            'inspected_images': ['before.png', 'after.png'], 'next_action': '사용자에게 전후 비교 제시'}

    def tearDown(self):
        self.temporary.cleanup()

    def read_review(self):
        return json.loads((self.directory / 'visual_review.json').read_text(encoding='utf-8'))

    def test_ai_pass_waits_for_actual_user_ok(self):
        with self.assertRaises(ValueError):
            record_user_decision(self.directory, 'ok', 'OK')
        self.assertEqual(record_ai_review(self.directory, self.assessment), 'awaiting_user')
        with self.assertRaises(ValueError):
            require_stage_approval(self.directory / 'candidate.blend')
        with self.assertRaises(ValueError):
            record_user_decision(self.directory, 'ok', '')
        self.assertEqual(record_user_decision(self.directory, 'ok', 'OK'), 'approved_for_next_stage')
        require_stage_approval(self.directory / 'candidate.blend')
        report = json.loads((self.directory / 'report.json').read_text())
        self.assertFalse(report['visual_approval'])
        self.assertFalse(report['quality_checks_run'])

    def test_unmet_or_uncertain_never_passes(self):
        for verdict, status in [('unmet', 'needs_revision'), ('uncertain', 'uncertain')]:
            assessment = copy.deepcopy(self.assessment)
            assessment['checks'][0]['verdict'] = verdict
            self.assertEqual(record_ai_review(self.directory, assessment), status)
            with self.assertRaises(ValueError):
                record_user_decision(self.directory, 'ok', 'OK')
            require_stage_approval(self.directory / 'candidate.blend', revision=True)

    def test_missing_images_or_one_sided_comparison_is_rejected(self):
        for key in ('inspected_images', 'checks'):
            assessment = copy.deepcopy(self.assessment)
            if key == 'checks':
                assessment[key][0]['images'] = ['after.png']
            else:
                assessment[key] = ['after.png']
            with self.assertRaises(ValueError):
                record_ai_review(self.directory, assessment)

    def test_changed_image_or_candidate_invalidates_review(self):
        for name in ('after.png', 'candidate.blend'):
            path = self.directory / name
            original = path.read_bytes()
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                record_ai_review(self.directory, self.assessment)
            path.write_bytes(original)

    def test_explicit_user_revision_blocks_next_stage(self):
        record_ai_review(self.directory, self.assessment)
        self.assertEqual(record_user_decision(self.directory, 'revise', '폭을 더 줄여줘'), 'needs_revision')
        self.assertFalse(self.read_review()['stage_approval'])


if __name__ == '__main__':
    unittest.main()
