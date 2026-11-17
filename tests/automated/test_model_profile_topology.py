"""기존 닫힌 단면과 순환 외피의 경계·위상을 확인한다."""
from collections import Counter
import unittest

from Tools.blender_pipeline.model_primitives import profile_faces


def edge_counts(faces):
    return Counter(tuple(sorted((a, b))) for face in faces
                   for a, b in zip(face, (*face[1:], face[0])))


class ModelProfileTopologyTests(unittest.TestCase):
    def test_capped_box_remains_a_closed_solid(self):
        faces = profile_faces(2, 4)
        edges = edge_counts(faces)
        self.assertEqual(len(faces), 6)
        self.assertEqual(set(edges.values()), {2})
        self.assertEqual(8-len(edges)+len(faces), 2)

    def test_cyclic_shell_is_closed_and_keeps_its_through_hole(self):
        faces = profile_faces(4, 8, capped=False, cyclic_profiles=True)
        edges = edge_counts(faces)
        self.assertEqual(len(faces), 32)
        self.assertEqual(set(edges.values()), {2})
        self.assertEqual(32-len(edges)+len(faces), 0)
        self.assertEqual(max(i for face in faces for i in face), 31)

    def test_uncapped_loft_keeps_two_open_boundaries(self):
        edges = edge_counts(profile_faces(2, 4, capped=False))
        self.assertEqual(sum(count == 1 for count in edges.values()), 8)

    def test_cyclic_caps_and_degenerate_loops_are_rejected(self):
        for args in [(4, 8, True, True), (2, 8, False, True), (1, 4, True, False)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                profile_faces(*args)


if __name__ == '__main__':
    unittest.main()
