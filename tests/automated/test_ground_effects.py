"""마찰 효과의 실제 부착 보간·재질 분기·입자 상한과 소멸을 검사한다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ferrial_drive.combat.ground_effects import GroundEffects, ground_effect_mode, trail_in_front
from ferrial_drive.combat.training_ground import GroundProjection, GroundTextureColors


class GroundEffectTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        anchors = Path(self.directory.name) / "anchors.json"
        first = {name: [0, 0] for name in ("sole_l", "sole_r", "calf_nozzle_l", "calf_nozzle_r")}
        second = {name: [10, 20] for name in first}
        anchors.write_text(json.dumps({"clips": {"dash_loop/s": {
            "sample_hz": 1, "duration_seconds": 1, "samples": [first, second]}}}), encoding="utf-8")
        config = Path(__file__).resolve().parents[2] / "samples/sword_movement/movement_config.json"
        appearance = json.loads(config.read_text(encoding="utf-8"))["ground_effects"]["appearance"]
        self.effects = GroundEffects(anchors, appearance=appearance, capacity=32)
        self.offsets = first

    def step(self, seconds, *, active=True, material="soil", center=(100, 100)):
        self.effects.update(seconds, center=center, velocity=(100, 0), offsets=self.offsets,
                            active=active, material=material, energy_color="#FF0000")

    def test_offsets_use_native_subframe_and_loop_wrap(self):
        self.assertEqual(self.effects.attachment_offsets("dash_loop/s", 0.5, loop=False, scale=2)["sole_l"], (10, 20))
        self.assertEqual(self.effects.attachment_offsets("dash_loop/s", 1.5, loop=True, scale=2)["sole_l"], (10, 20))
        self.assertEqual(self.effects.attachment_offsets("unknown", 1, loop=True, scale=1), {})

    def test_material_switch_and_live_trail_follow_nozzle(self):
        self.step(0.04)
        self.assertIn("dirt_debris_gray", {p.kind for p in self.effects.particles})
        self.effects.reset()
        self.step(0.04, material="metal")
        self.assertNotIn("dirt_debris_gray", {p.kind for p in self.effects.particles})
        self.assertIn("spark", {p.kind for p in self.effects.particles})
        self.step(0.001, material="metal", center=(200, 100))
        trails = [p for p in self.effects.particles if p.kind == "trail"]
        self.assertEqual(len(trails), 2)
        self.assertTrue(all(p.color == "#FF0000" and p.position[0] > 180 for p in trails))

    def test_sustained_emission_stays_bounded_and_stopping_expires(self):
        for _ in range(180):
            self.step(1 / 60)
            self.assertLessEqual(len(self.effects.particles), 32)
        self.step(1, active=False)
        self.assertEqual(self.effects.particles, [])

    def test_attack_rules_and_front_view_occlusion(self):
        for index in range(4):
            self.assertEqual(ground_effect_mode("run", attack_index=index), "attack" if index >= 2 else None)
            self.assertEqual(ground_effect_mode("dash", attack_index=index, dash=True), "dash_attack")
            self.assertIsNone(ground_effect_mode("dash", attack_index=index, dash=True, waiting=True))
        self.assertEqual(ground_effect_mode("boost"), "boost")
        self.assertEqual(ground_effect_mode("boost", attack_index=0), "boost")
        for direction in ("s", "sw", "se"):
            self.assertFalse(trail_in_front(direction))
        for direction in ("n", "nw", "ne", "w", "e"):
            self.assertTrue(trail_in_front(direction))

    def test_scrape_expires_in_three_sixty_hz_frames_while_debris_remains(self):
        self.step(0.04)
        self.assertTrue(any(p.kind == "scrape_gray" for p in self.effects.particles))
        self.step(0.051, active=False)
        self.assertFalse(any(p.kind == "scrape_gray" for p in self.effects.particles))
        self.assertTrue(any(p.kind == "dirt_debris_gray" for p in self.effects.particles))
        self.step(0.04)
        self.effects.reset()
        self.assertEqual(self.effects.particles, [])

    def test_foot_smoke_and_round_nozzle_spray_use_separate_origins(self):
        self.offsets = {**self.offsets, "calf_nozzle_l": [80, 40], "calf_nozzle_r": [80, 40]}
        self.step(0.04)
        normal_width = next(p.size[1] for p in self.effects.particles if p.kind == "trail")
        smoke = next(p for p in self.effects.particles if p.kind == "smoke_gray")
        spray = next(p for p in self.effects.particles if p.kind == "thruster_smoke")
        self.assertEqual(smoke.position, (100, 100))
        self.assertEqual(spray.position, (180, 140))
        self.assertLess(spray.velocity[0], 0)
        self.assertEqual(spray.size[0], spray.size[1])
        self.assertGreater(spray.roundness, 0.5)
        self.assertLess(spray.detail, 0.5)
        self.effects.reset()
        self.effects.update(0.04, center=(100, 100), velocity=(100, 0), offsets=self.offsets,
                            active=True, material="soil", energy_color="#FF0000", strength=1.8)
        self.assertGreater(next(p.size[1] for p in self.effects.particles if p.kind == "trail"), normal_width)
        self.assertTrue(all(p.lifetime_seconds == 0.05 for p in self.effects.particles if p.kind == "scrape_gray"))

    def test_back_spray_is_larger_and_only_spawns_while_boosting(self):
        self.effects.capacity = 128
        offsets = {**self.offsets, "back_nozzle_l": [-40, -100], "back_nozzle_r": [40, -100],
                   "back_exit_l": [-140, -100], "back_exit_r": [-60, -100]}
        args = dict(center=(100, 100), velocity=(100, 0), offsets=offsets, active=True,
                    material="soil", energy_color="#FF0000", ground_color=lambda point: "#784B2A")
        self.effects.update(0.04, **args)
        self.assertFalse(any(p.emitter.startswith("back") for p in self.effects.particles))
        self.effects.reset()
        self.effects.update(0.04, **args, boost_active=True)
        sprays = [p for p in self.effects.particles if p.kind == "thruster_smoke"]
        self.assertGreater(next(p.size[0] for p in sprays if p.emitter == "back_l"),
                           next(p.size[0] for p in sprays if p.emitter == "calf_l"))
        self.assertTrue(all(p.color == "#784B2A" for p in self.effects.particles if p.kind in ("smoke_gray", "dirt_debris_gray")))

    def test_ground_colors_repeat_at_the_same_tile_coordinates(self):
        pixels = bytes(channel for y in range(16) for x in range(16)
                       for channel in ((120, 60, 20, 255) if x < 8 else (20, 60, 120, 255)))
        colors = GroundTextureColors(16, 16, pixels, GroundProjection(1, 1), 16)
        self.assertEqual(colors.color_at((4, 4), blend=1), "#783C14")
        self.assertEqual(colors.color_at((20, 4), blend=1), "#783C14")
        self.assertEqual(colors.color_at((12, 4), blend=1), "#143C78")
        self.assertEqual(colors.color_at((12, 4), blend=0), "#FFFFFF")

    def test_back_and_leg_trails_share_angle_and_linearly_interpolate_then_fade(self):
        self.effects.capacity = 128
        offsets = {**self.offsets, "back_nozzle_l": [-40, -100], "back_nozzle_r": [40, -100],
                   "back_exit_l": [-40, -200], "back_exit_r": [40, -200]}
        args = dict(center=(100, 100), velocity=(100, 0), offsets=offsets, active=True,
                    material="soil", energy_color="#FF0000", boost_active=True)
        style = self.effects.appearance["trail"]
        half_fade_in = style["strength_interpolation_seconds"] / 2
        self.effects.update(half_fade_in, **args)
        first = {p.emitter: (p.size[0], p.opacity, p.angle) for p in self.effects.particles if p.kind == "trail"}
        self.effects.update(half_fade_in, **args)
        full = {p.emitter: (p.size[0], p.opacity, p.angle) for p in self.effects.particles if p.kind == "trail"}
        for emitter in first:
            self.assertAlmostEqual(first[emitter][0] * 2, full[emitter][0])
            self.assertAlmostEqual(first[emitter][1], 0.5)
            self.assertAlmostEqual(full[emitter][1], 1)
        self.assertEqual(full["calf_l"][2], full["back_l"][2])
        args["boost_active"] = False
        self.effects.update(style["afterimage_hold_seconds"], **args)
        held = next(p for p in self.effects.particles if p.kind == "trail" and p.emitter == "back_l")
        self.assertAlmostEqual(held.opacity, 1)
        self.assertAlmostEqual(held.size[0], full["back_l"][0])
        self.assertTrue(any(p.kind == "trail_echo" for p in self.effects.particles))
        self.effects.update(style["fade_out_seconds"] / 2, **args)
        fading = next(p for p in self.effects.particles if p.kind == "trail" and p.emitter == "back_l")
        self.assertAlmostEqual(fading.opacity, 0.5)
        self.assertAlmostEqual(fading.size[0], full["back_l"][0] / 2)
        self.effects.update(style["fade_out_seconds"] / 2, **args)
        self.assertFalse(any(p.kind == "trail" and p.emitter == "back_l" for p in self.effects.particles))

    def test_small_energy_orbs_scatter_to_both_sides_in_energy_color(self):
        self.effects.capacity = 128
        self.step(0.08)
        particles = [p for p in self.effects.particles if p.kind == "energy_orb"]
        self.assertTrue(particles)
        self.assertTrue(all(p.color == "#FF0000" and p.size[0] == p.size[1] for p in particles))
        self.assertLess(min(p.velocity[1] for p in particles), 0)
        self.assertGreater(max(p.velocity[1] for p in particles), 0)
        self.step(0.2, active=False)
        self.assertFalse(any(p.kind == "energy_orb" for p in self.effects.particles))

    def test_live_friction_follows_each_foot_without_emission_or_afterimage(self):
        offsets = {**self.offsets, "sole_l": [-20, 10], "sole_r": [20, 12]}
        args = dict(velocity=(100, 0), offsets=offsets, active=True,
                    material="soil", energy_color="#FF0000", foot_contact=True)
        self.effects.update(0.001, center=(100, 100), **args)
        contact = [p for p in self.effects.particles if p.kind == "foot_friction"]
        self.assertEqual({p.position for p in contact}, {(80, 110), (120, 112)})
        self.assertFalse(any(p.kind == "scrape_gray" for p in self.effects.particles))
        self.effects.update(0.001, center=(300, 200), **args)
        contact = [p for p in self.effects.particles if p.kind == "foot_friction"]
        self.assertEqual(len(contact), 2)
        self.assertEqual({p.position for p in contact}, {(280, 210), (320, 212)})
        self.assertTrue(all(p.age_seconds == 0 and p.velocity == (0, 0) for p in contact))
        self.effects.capacity = 2
        self.effects.update(0.1, center=(300, 200), **args)
        self.assertEqual(len(self.effects.particles), 2)
        self.assertTrue(all(p.kind == "foot_friction" for p in self.effects.particles))
        args["foot_contact"] = False
        self.effects.update(0.001, center=(300, 200), **args)
        self.assertFalse(any(p.kind == "foot_friction" for p in self.effects.particles))
        args["foot_contact"], args["active"] = True, False
        self.effects.update(0.001, center=(300, 200), **args)
        self.assertFalse(any(p.kind == "foot_friction" for p in self.effects.particles))

    def test_foot_friction_mirrors_facing_without_rotating_or_following_velocity(self):
        for facing_x in (-1, 0, 1):
            for velocity in ((100, 0), (-100, 0), (0, 100), (0, -100)):
                with self.subTest(facing_x=facing_x, velocity=velocity):
                    self.effects.reset()
                    self.effects.update(0.04, center=(100, 100), velocity=velocity, offsets=self.offsets,
                                        active=True, material="soil", energy_color="#FF0000",
                                        foot_contact=True, foot_facing_x=facing_x)
                    contact = [p for p in self.effects.particles if p.kind == "foot_friction"]
                    self.assertEqual(len(contact), 2)
                    self.assertTrue(all(p.angle == 0 and p.mirror_x == (facing_x < 0) for p in contact))
                    self.assertTrue(all(not p.mirror_x for p in self.effects.particles if p.kind != "foot_friction"))

    def test_live_foot_friction_samples_each_foot_and_updates_color_after_moving(self):
        offsets = {**self.offsets,"sole_l":[-20,10],"sole_r":[20,12]}
        args = dict(velocity=(100,0),offsets=offsets,active=True,material="soil",
                    energy_color="#FF0000",foot_contact=True,
                    ground_color=lambda point: "#705030" if point[0]<100 else "#406040")
        self.effects.update(.001,center=(100,100),**args)
        colors = {p.emitter:p.color for p in self.effects.particles if p.kind=="foot_friction"}
        self.assertEqual(colors,{"sole_l":"#705030","sole_r":"#406040"})
        self.effects.update(.001,center=(200,100),**args)
        self.assertTrue(all(p.color=="#406040" for p in self.effects.particles if p.kind=="foot_friction"))


if __name__ == "__main__":
    unittest.main()
