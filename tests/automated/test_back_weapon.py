"""백웨폰 없는 슬롯의 전개 방지와 스왑 도중 전개/복귀를 검사한다."""

import unittest

from ferrial_drive.combat.back_weapon import BackWeaponDeployment


class BackWeaponTests(unittest.TestCase):
    def test_empty_swap_stays_folded_and_equipped_slot_deploys(self):
        controller = BackWeaponDeployment(duration_seconds=0.5)
        controller.swap(0, back_weapon_equipped=False)
        controller.update(1)
        self.assertEqual(controller.phase, 0)
        controller.swap(1, back_weapon_equipped=True)
        controller.update(0.25)
        self.assertEqual(controller.frame_position(7), 3)
        controller.update(1)
        self.assertEqual(controller.phase, 1)

    def test_swapping_to_empty_slot_retracts_without_pose_snap(self):
        controller = BackWeaponDeployment(duration_seconds=0.5)
        controller.swap("back", back_weapon_equipped=True)
        controller.update(0.3)
        before = controller.phase
        controller.swap("normal", back_weapon_equipped=False)
        self.assertEqual(controller.phase, before)
        controller.update(0.1)
        self.assertAlmostEqual(controller.phase, 0.4)
        controller.update(1)
        self.assertEqual(controller.phase, 0)


if __name__ == "__main__":
    unittest.main()
