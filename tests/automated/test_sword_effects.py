"""레벨별 검 범위·같은 면의 명중·중복 방지·잔상과 고속 타격 경계를 검사한다."""

import json
from math import cos, pi
from pathlib import Path
import unittest
from unittest.mock import Mock

from ferrial_drive.combat.geometry import Vec2, point_in_polygon
from ferrial_drive.combat.movement_combat import AttackStep
from ferrial_drive.combat.sword_effects import BladeTrajectory, SwordEffects, SwordTarget, camera_root
from ferrial_drive.rendering.slash_rim import slash_rim_color

ROOT = Path(__file__).resolve().parents[2]


def settings():
    data = json.loads((ROOT / "samples/sword_movement/movement_config.json").read_text(encoding="utf-8"))["sword_effects"]
    data["active_phase_windows"] = [[0, 1]] * 4
    data["body_wind"]["enabled"] = False
    # 동작 검사는 튜닝 값과 분리한 고정 수치로 비교한다.
    for profile, reach, life, count, echo_life in zip(data["levels"],
            (1.3, 1.8, 2.4), (0.1, 0.18, 0.26), (0, 3, 6), (0.08, 0.15, 0.22)):
        profile.update(reach_scale=reach, trail_seconds=life, echo_count=count, echo_seconds=echo_life)
    data["thrust_width_ratio"] = 0.25
    return data


def make_effects(config=None):
    trajectory = BladeTrajectory({"combo_01/e": [(0, Vec2(), Vec2(100, 0)), (1, Vec2(), Vec2(100, 100))]})
    return SwordEffects(trajectory, config or settings(), scale=1, project=lambda point: point, easing="linear")


def step(start=0, end=1, strike_id=1, origin=(0, 0)):
    return AttackStep(strike_id, "combo_01/e", start, end, 1, end - start, origin, origin)


class SwordEffectTests(unittest.TestCase):
    def test_slash_rim_uses_metal_color_only_at_edges_and_preserves_center(self):
        metal_center = slash_rim_color(0,"metal",{},1)
        generic_center = slash_rim_color(0,"generic",{},1)
        self.assertEqual(metal_center,generic_center)
        metal_edge = slash_rim_color(.96,"metal",{},1)
        generic_edge = slash_rim_color(.96,"generic",{},1)
        self.assertGreater(metal_edge[0],generic_edge[0])
        self.assertLess(metal_edge[2],generic_edge[2])
        self.assertEqual(slash_rim_color(1,"metal",{},1)[3],0)
        self.assertEqual(slash_rim_color(.96,"metal",{},0)[3],0)

    def test_contact_slash_follows_actual_tip_path_and_sparks_require_metal(self):
        for material in ("generic", "metal"):
            effect = make_effects()
            target = SwordTarget("inside", Vec2(50,25), 3, material)
            effect.update(.5, [step(0,.5)], 1, [target])
            contact = effect.contact_effects
            self.assertEqual(len(contact.slashes), 1)
            mark = contact.slashes[0]
            self.assertEqual(mark.points[1], target.center)
            self.assertEqual(mark.target_id, target.target_id)
            pairs = [(s.tip_a,s.tip_b) for s in effect.sections]
            a,b = min(pairs,key=lambda pair: ((pair[0]+pair[1])*.5-target.center).length)
            direction = (mark.points[-1]-mark.points[0]).normalized()
            base = (b-a).normalized()
            self.assertGreaterEqual(direction.x*base.x+direction.y*base.y, cos(6*pi/180)-1e-8)
            self.assertEqual(mark.material, material)
            self.assertEqual(bool(contact.sparks), material == "metal")
            life = max(effect.settings["contact_effects"][key] for key in ("slash_seconds", "spark_seconds"))
            effect.update(life + .01, [], 1, [target])
            self.assertFalse(contact.slashes)
            self.assertFalse(contact.sparks)

    def test_misses_emit_no_contact_vfx_and_reset_clears_hit_particles(self):
        effect = make_effects()
        effect.update(.5, [step(0,.5)], 1)
        self.assertFalse(effect.contact_effects.slashes)
        self.assertFalse(effect.contact_effects.sparks)
        effect.update(.3, [step(.5,.8)], 1, [SwordTarget("A",Vec2(50,60),40,"metal")])
        self.assertTrue(effect.contact_effects.sparks)
        effect.reset()
        self.assertFalse(effect.contact_effects.slashes)
        self.assertFalse(effect.contact_effects.sparks)

    def test_contact_slash_keeps_surviving_geometry_and_only_tapers_erased_edge(self):
        effect = make_effects()
        target = SwordTarget("A",Vec2(50,25),3)
        effect.update(.5,[step(0,.5)],1,[target])
        contact = effect.contact_effects
        mark = contact.slashes[0]
        thin = contact.slash_visual(mark)
        grow = contact.settings["slash_grow_seconds"]
        hold = contact.settings["slash_hold_seconds"]
        mark.age_seconds = grow * .5
        halfway = contact.slash_visual(mark)
        mark.age_seconds = grow * .25
        quarter = contact.slash_visual(mark)
        mark.age_seconds = grow * .75
        three_quarters = contact.slash_visual(mark)
        mark.age_seconds = grow
        wide = contact.slash_visual(mark)
        mark.age_seconds = grow + hold * .5
        held = contact.slash_visual(mark)
        mark.age_seconds = (grow + hold + contact.settings["slash_seconds"]) * .5
        fading = contact.slash_visual(mark)
        self.assertGreater(wide[1],thin[1]*10)
        self.assertAlmostEqual(halfway[1],(thin[1]+wide[1])*.5)
        self.assertLess(quarter[1],thin[1]+(wide[1]-thin[1])*.25)
        self.assertGreater(three_quarters[1],thin[1]+(wide[1]-thin[1])*.75)
        self.assertEqual((thin[2],halfway[2],wide[2]),(1,1,1))
        self.assertEqual(wide,held)
        self.assertEqual(fading[:2], held[:2])
        self.assertTrue(0 < fading[2] < held[2])
        mark.age_seconds = grow + (contact.settings["slash_seconds"]-grow)*.75
        late = contact.slash_visual(mark)
        self.assertEqual(late[:2], held[:2])
        self.assertTrue(0 < late[2] < fading[2])
        mark.age_seconds = (grow + hold + contact.settings["slash_seconds"]) * .5
        self.assertLess(contact.slash_visibility(mark,.1),contact.slash_visibility(mark,.9))
        self.assertTrue(any(0 < contact.slash_visibility(mark,i/40) < 1 for i in range(41)))
        self.assertEqual(contact.slash_width_scale(1), 1)
        self.assertEqual(contact.slash_width_scale(0), 0)
        self.assertTrue(0 < contact.slash_width_scale(.5) < 1)
        self.assertGreater(contact.slash_visibility(mark,.5),.95)
        mark.age_seconds = contact.settings["slash_seconds"]
        self.assertEqual(contact.slash_visibility(mark,1),0)
        self.assertEqual(contact.slash_visual(mark)[2], 0)
        self.assertEqual(fading[0][1],target.center)
        self.assertGreater((mark.points[2]-mark.points[1]).length,0)
        self.assertGreater((mark.points[2]-mark.points[0]).length,(mark.points[1]-mark.points[0]).length)

    def test_contact_edge_interpolates_opacity_even_without_blur(self):
        effect = make_effects()
        effect.update(.5, [step(0, .5)], 1, [SwordTarget("A", Vec2(50, 25), 3)])
        contact = effect.contact_effects
        contact.settings["fade_blur_ratio"] = 0
        mark = contact.slashes[0]
        mark.age_seconds = (contact.settings["slash_grow_seconds"] + contact.settings["slash_seconds"]) / 2
        values = [contact.slash_visibility(mark, index / 200) for index in range(201)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0)
        self.assertEqual(values[-1], 1)
        self.assertGreater(sum(0 < value < 1 for value in values), 10)

    def test_contact_size_and_angles_are_bounded_and_stay_fixed_after_spawn(self):
        scales = []
        for strike_id in range(1,21):
            effect = make_effects()
            effect.update(.5,[step(0,.5,strike_id)],1,[SwordTarget("A",Vec2(50,25),3,"metal")])
            mark = effect.contact_effects.slashes[0]
            self.assertTrue(.9 <= mark.size_scale <= 1.1)
            self.assertLessEqual(abs(mark.angle_offset_degrees),6)
            self.assertLessEqual(abs(mark.spark_angle_offset_degrees),6)
            state = (mark.points,mark.size_scale,mark.angle_offset_degrees,mark.spark_angle_offset_degrees)
            effect.update(.01,[],1)
            self.assertEqual(state,(mark.points,mark.size_scale,mark.angle_offset_degrees,mark.spark_angle_offset_degrees))
            scales.append(mark.size_scale)
        self.assertGreater(len(set(scales)),10)

    def test_higher_energy_extends_real_collision_and_visible_geometry_together(self):
        target = SwordTarget("outside", Vec2(210, 105), 1)
        maxima, hits = [], []
        for level in (1, 2, 3):
            effect = make_effects()
            effect.update(1, [step()], level, [target])
            maxima.append(max(v.x for s in effect.hit_sections for v in s.vertices))
            hits.append(effect.hits[:])
            self.assertTrue(all(s in effect.hit_sections for s in effect.sections))
        self.assertLess(maxima[0], maxima[1])
        self.assertLess(maxima[1], maxima[2])
        self.assertEqual(hits[:2], [[], []])
        self.assertEqual(hits[2], [(1, "outside")])

    def test_contact_sizes_scale_with_energy_without_changing_spark_count_speed_or_lifetime(self):
        baseline = None
        for level, size_scale in ((1, 1), (2, 1.25), (3, 1.5)):
            with self.subTest(level=level):
                effect = make_effects()
                effect.update(.5, [step(0, .5)], level, [SwordTarget("A", Vec2(50, 25), 3, "metal")])
                contact = effect.contact_effects
                mark = contact.slashes[0]
                spark = contact.sparks[0]
                sizes = ((mark.points[-1] - mark.points[0]).length, mark.size_scale, spark.width_pixels)
                if baseline is None:
                    baseline = sizes, spark.velocity.length, spark.lifetime_seconds, len(contact.sparks)
                for actual, base in zip(sizes, baseline[0]):
                    self.assertAlmostEqual(actual, base * size_scale)
                self.assertEqual(spark.size_scale, size_scale)
                self.assertAlmostEqual(spark.velocity.length, baseline[1])
                self.assertEqual(spark.lifetime_seconds, baseline[2])
                self.assertEqual(len(contact.sparks), baseline[3])
                effect.update(.01, [], 1)
                self.assertEqual(mark.size_scale, sizes[1])
                self.assertEqual(spark.size_scale, size_scale)

    def test_one_hit_per_target_per_strike_and_next_strike_can_hit_again(self):
        effect = make_effects()
        target = SwordTarget("inside", Vec2(50, 25), 3)
        effect.update(0.5, [step(0, 0.5)], 3, [target])
        self.assertEqual(effect.hits, [(1, "inside")])
        effect.update(0.5, [step(0.5, 1)], 3, [target])
        self.assertEqual(effect.hits, [])
        effect.update(1, [step(strike_id=2)], 3, [target])
        self.assertEqual(effect.hits, [(2, "inside")])

    def test_fading_visual_trail_has_no_lingering_hitbox(self):
        effect = make_effects()
        effect.update(1, [step()], 3)
        self.assertTrue(effect.sections)
        effect.update(0.01, [], 3, [SwordTarget("late", Vec2(50, 50), 2)])
        self.assertTrue(effect.sections)
        self.assertEqual(effect.hit_sections, [])
        self.assertEqual(effect.hits, [])

    def test_windup_and_recovery_do_not_emit_or_hit(self):
        config = settings()
        config["active_phase_windows"] = [[0.4, 0.6]] * 4
        effect = make_effects(config)
        effect.update(0.3, [step(0, 0.3)], 3)
        self.assertEqual(effect.sections, [])
        self.assertEqual(effect.echoes, [])
        effect.update(0.3, [step(0.7, 1)], 3)
        self.assertEqual(effect.hit_sections, [])

    def test_frame_rates_and_whole_strike_in_one_update_do_not_tunnel(self):
        for fps in (1, 30, 60, 144):
            effect, hits = make_effects(), []
            for index in range(fps):
                effect.update(1 / fps, [step(index / fps, (index + 1) / fps)], 3,
                              [SwordTarget("thin", Vec2(120, 60), 0.2)])
                hits.extend(effect.hits)
            self.assertEqual(hits, [(1, "thin")])

    def test_echo_limits_level_drop_and_expiry(self):
        for level, count in ((1, 0), (2, 3), (3, 6)):
            effect = make_effects()
            effect.update(1, [step()], level)
            self.assertEqual(len(effect.echoes), count)
            self.assertTrue(all(e.position_m == (0, 0) for e in effect.echoes))
            effect.update(0.3, [], level)
            self.assertEqual(effect.echoes, [])
            self.assertEqual(effect.sections, [])
        effect = make_effects()
        effect.update(1, [step()], 3)
        effect.update(0, [], 1)
        self.assertEqual(effect.echoes, [])

    def test_strike_boundaries_do_not_join_distant_ribbons(self):
        effect = make_effects()
        first = step(0, 0.5)
        second = step(0, 0.5, strike_id=2, origin=(1000, 0))
        effect.update(1, [first, second], 3)
        for section in effect.hit_sections:
            self.assertLess(max(v.x for v in section.vertices) - min(v.x for v in section.vertices), 300)

    def test_dash_extends_visible_and_real_reach_beyond_normal_strike(self):
        normal, dash = make_effects(), make_effects()
        target = SwordTarget("dash_only", Vec2(300, 150), 1)
        normal.update(1, [step()], 3, [target])
        dash_step = AttackStep(1, "combo_01/e", 0, 1, 1, 1, (0, 0), (0, 0), dash=True)
        dash.update(1, [dash_step], 3, [target])
        self.assertEqual(normal.hits, [])
        self.assertEqual(dash.hits, [(1, "dash_only")])
        self.assertGreater(max(v.x for s in dash.hit_sections for v in s.vertices),
                           max(v.x for s in normal.hit_sections for v in s.vertices))

    def test_sample_and_camera_root_are_independent_of_game_assets(self):
        sample = BladeTrajectory.load(ROOT / "samples/sword_movement/trail_sample.json")
        self.assertEqual(len(sample.clips), 32)
        root, tip = sample.pose("combo_01/e", 0.25, 1, 1)
        _, enlarged = sample.pose("combo_01/e", 0.25, 1, 1.3)
        self.assertAlmostEqual((enlarged - root).length, (tip - root).length * 1.3)
        camera = {"position": [0, -10, 10], "target": [0, 0, 0], "size": [100, 100], "width_cm": 100}
        self.assertEqual(camera_root(camera), Vec2(50, 50))

    def test_invalid_level_and_time_fail(self):
        for seconds, level in ((-1, 1), (float("nan"), 1), (0, 0), (0, 4), (0, True)):
            with self.assertRaises(ValueError):
                make_effects().update(seconds, [], level)

    def test_training_reset_precedes_same_frame_dash_energy_and_attack_inputs(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        app.playback = Mock()
        app.script = [{"frame": 1, "reset": True, "keys": ["left_shift"],
                       "energy_level": 3, "attack_held": True}]
        app.update(1 / 60)
        self.assertEqual(app.keys, {"left_shift"})
        self.assertEqual(app.energy_level, 3)
        self.assertTrue(app.attack_held)

    def test_y_margin_relaxes_hit_without_distorting_visible_trail(self):
        trajectory = BladeTrajectory({"combo_01/e": [(0, Vec2(), Vec2(100, 0)),
                                                     (1, Vec2(), Vec2(110, 0))]})
        results = []
        for margin in (0, 1.5):
            config = settings()
            config["hit_y_margin_m"] = margin
            effect = SwordEffects(trajectory, config, scale=1, project=lambda value: value,
                                  easing="linear", y_pixels_per_meter=8)
            target = SwordTarget("y_near_miss", Vec2(60, 10), 1)
            effect.update(1, [step()], 1, [target])
            results.append(effect.hits[:])
            self.assertFalse(point_in_polygon(target.center, effect.hit_sections[-1].vertices))
        self.assertEqual(results, [[], [(1, "y_near_miss")]])

    def test_thrust_chevron_faces_tip_and_both_wings_are_in_hit_polygon(self):
        trajectory = BladeTrajectory({"combo_03/e": [(0, Vec2(), Vec2(100, 0)),
                                                     (1, Vec2(), Vec2(110, 0))]})
        effect = SwordEffects(trajectory, settings(), scale=1, project=lambda value: value, easing="linear")
        thrust = AttackStep(1, "combo_03/e", 0, 1, 1, 1, (0, 0), (0, 0))
        effect.update(1, [thrust], 3)
        section = effect.hit_sections[-1]
        left, tip, right = section.chevron
        self.assertGreater(tip.x, left.x)
        self.assertGreater(tip.x, right.x)
        self.assertGreater(left.y, tip.y)
        self.assertLess(right.y, tip.y)
        self.assertTrue(all(point_in_polygon(wing, section.hit_vertices) for wing in section.chevron))

    def test_level_one_thrust_total_width_is_quarter_original_blade_length(self):
        config = settings()
        trajectory = BladeTrajectory({"combo_03/e": [(0, Vec2(), Vec2(100, 0)),
                                                     (1, Vec2(), Vec2(110, 0))]})
        for level in (1, 2, 3):
            for dash in (False, True):
                with self.subTest(level=level, dash=dash):
                    effect = SwordEffects(trajectory, config, scale=1, project=lambda value: value, easing="linear")
                    thrust = AttackStep(1, "combo_03/e", 0, 1, 1, 1, (0, 0), (0, 0), dash=dash)
                    effect.update(1, [thrust], level)
                    left, _, right = effect.hit_sections[-1].chevron
                    growth = config["levels"][level - 1]["reach_scale"] / config["levels"][0]["reach_scale"]
                    if dash:
                        growth *= config["dash_reach_scale"]
                    self.assertAlmostEqual((left - right).length, 110 * 0.25 * growth, delta=1e-5)

    def test_rebased_level_one_preserves_previous_level_three_and_higher_levels_are_stronger(self):
        config = json.loads((ROOT / "samples/sword_movement/movement_config.json").read_text(encoding="utf-8"))["sword_effects"]
        first, second, third = config["levels"]
        # 색상은 별도 표현 설정이다. 범위·수명·잔상의 기준만 보존한다.
        for name, value in {"reach_scale": 2.4, "trail_seconds": 0.26, "trail_opacity": 0.5,
                            "echo_count": 0, "echo_seconds": 0.22, "echo_opacity": 0.3}.items():
            self.assertEqual(first[name], value)
        for name in ("reach_scale", "trail_seconds", "trail_opacity", "echo_count", "echo_tint_mix"):
            self.assertLess(first[name], second[name])
            self.assertLess(second[name], third[name])
        self.assertAlmostEqual(config["thrust_width_ratio"], 0.25 * 2.4 / 1.3)
        self.assertGreater(config["thrust_outer_half_width_pixels"], config["thrust_core_half_width_pixels"])
        self.assertGreater(config["thrust_core_half_width_pixels"], 0)

    def test_echo_keeps_energy_color_from_creation_and_blend_amount(self):
        effect = make_effects()
        effect.update(1, [step()], 3, energy_color="#FF0000")
        self.assertTrue(effect.echoes)
        self.assertTrue(all(e.tint == (1, 0, 0) for e in effect.echoes))

        self.assertTrue(all(e.tint_mix == effect.profiles[2]["echo_tint_mix"] for e in effect.echoes))
        effect.update(0.001, [], 3, energy_color="#0000FF")
        self.assertTrue(all(e.tint == (1, 0, 0) for e in effect.echoes))

    def test_trail_color_can_change_without_recoloring_echoes(self):
        effect = make_effects()
        effect.update(.3, [step(0, .3)], 3, energy_color="#0000FF", trail_color="#FF0000")
        self.assertTrue(effect.sections)
        self.assertTrue(all(section.color == "#FF0000" for section in effect.sections))
        self.assertTrue(effect.echoes)
        self.assertTrue(all(echo.tint == (0, 0, 1) for echo in effect.echoes))


if __name__ == "__main__":
    unittest.main()
