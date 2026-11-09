"""애니메이션 작업본 입력의 모호한 구간과 손상된 표본을 거부한다."""
import copy
import unittest

from Tools.blender_pipeline.animation_pipeline import validate


class AnimationManifestTest(unittest.TestCase):
    def setUp(self):
        self.data = {'version': 1, 'fps': 8, 'clips': [
            {'name': 'idle', 'samples': [{'frame': 1, 'bones': {}}]},
            {'name': 'fire', 'samples': [{'frame': 4, 'bones': {}}]},
        ]}

    def test_distinct_clip_ranges(self):
        self.assertIs(validate(self.data), self.data)
        self.data['clips'][1]['samples'][0]['frame'] = 1
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_invalid_matrix(self):
        for matrix in ([[0]*4]*3, [[float('nan')]*4]*4):
            data = copy.deepcopy(self.data)
            data['clips'][0]['samples'][0]['bones']['root'] = matrix
            with self.assertRaises(ValueError):
                validate(data)

    def test_unique_safe_names_and_nonempty_clips(self):
        for name in ('idle', '../file', ''):
            data = copy.deepcopy(self.data)
            data['clips'][1]['name'] = name
            with self.assertRaises(ValueError):
                validate(data)
        self.data['clips'][0]['samples'] = []
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_event_must_reference_existing_sample(self):
        self.data['clips'][0]['events'] = [{'frame': 1, 'type': 'hit'}]
        with self.assertRaises(ValueError):
            validate(self.data)
        self.data['clips'][0]['events'][0]['frame'] = 0
        validate(self.data)


if __name__ == '__main__':
    unittest.main()
