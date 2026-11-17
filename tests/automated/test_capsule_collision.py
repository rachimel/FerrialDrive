"""단순 캡슐의 경계·보수적 포함·공격 시간·중복 명중·검풍 후방 빈틈을 검사한다."""

from math import cos,sin,pi
import random
import unittest

from ferrial_drive.combat.geometry import Capsule,Vec2,bounding_capsule,capsule_touches_circle
from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.combat.sword_effects import SwordTarget,body_wind_sector
from tests.automated.test_sword_effects import make_effects,settings,step


class CapsuleGeometryTests(unittest.TestCase):
    def test_side_end_caps_tangency_and_zero_length(self):
        capsule = Capsule(Vec2(),Vec2(10,0),2)
        self.assertTrue(capsule_touches_circle(capsule,Vec2(5,3),1))
        self.assertFalse(capsule_touches_circle(capsule,Vec2(5,3.01),1))
        self.assertTrue(capsule_touches_circle(capsule,Vec2(-3,0),1))
        self.assertFalse(capsule_touches_circle(capsule,Vec2(-3.01,0),1))
        self.assertTrue(capsule_touches_circle(Capsule(Vec2(),Vec2(),2),Vec2(0,3),1))

    def test_bounding_volume_contains_all_points_and_margin(self):
        rng = random.Random(1205)
        for _ in range(100):
            points = [Vec2(rng.uniform(-100,100),rng.uniform(-100,100)) for _ in range(10)]
            capsule = bounding_capsule(points,Vec2(7,11),Vec2(60,-32),4)
            for point in points:
                self.assertTrue(capsule_touches_circle(capsule,point,0))
        with self.assertRaises(ValueError):
            bounding_capsule([],Vec2(),Vec2())


class CapsuleAttackTests(unittest.TestCase):
    def test_preserves_old_hits_adds_margin_and_records_capsules(self):
        targets = [SwordTarget(str(i),Vec2(x,y),2) for i,(x,y) in enumerate(
            ( (x,y) for x in range(-5,251,15) for y in range(-15,181,15) ))]
        polygon,capsule = make_effects(),make_effects()
        capsule.hitbox_type = "capsule"
        polygon.update(.9,[step(end=.9)],3,targets)
        capsule.update(.9,[step(end=.9)],3,targets)
        self.assertLessEqual(set(polygon.hits),set(capsule.hits))
        self.assertTrue(capsule.hit_sections)
        self.assertTrue(all(row.hit_capsule is not None for row in capsule.hit_sections))
        self.assertTrue(all(not row.hit_vertices for row in capsule.hit_sections))

    def test_no_lingering_or_duplicate_hit(self):
        effect = make_effects()
        effect.hitbox_type = "capsule"
        target = SwordTarget("near",Vec2(50,25),3)
        effect.update(.5,[step(0,.5)],3,[target])
        self.assertEqual(effect.hits,[(1,"near")])
        effect.update(.5,[step(.5,1)],3,[target])
        self.assertFalse(effect.hits)
        effect.update(.01,[],3,[target])
        self.assertFalse(effect.hit_sections)
        self.assertFalse(effect.hits)
        effect.update(1,[step(strike_id=2)],3,[target])
        self.assertEqual(effect.hits,[(2,"near")])

    def test_active_window_and_fast_frame_steps(self):
        for fps in (30,60,165):
            effect = make_effects()
            effect.hitbox_type = "capsule"
            hits = []
            for index in range(fps):
                effect.update(1/fps,[step(index/fps,(index+1)/fps)],3,[SwordTarget("inside",Vec2(60,30),1)])
                hits.extend(effect.hits)
            self.assertEqual(hits,[(1,"inside")])
        config = settings()
        config["active_phase_windows"] = [[.4,.6]]*4
        effect = make_effects(config)
        effect.hitbox_type = "capsule"
        effect.update(.3,[step(0,.3)],3,[SwordTarget("inside",Vec2(60,30),10)])
        self.assertFalse(effect.hits)
        self.assertFalse(effect.hit_sections)

    def test_body_wind_retains_far_rear_gap(self):
        config = settings()
        config["body_wind"]["enabled"] = True
        effect = make_effects(config)
        effect.hitbox_type = "capsule"
        wind = body_wind_sector(Vec2(),"e",config["body_wind"],3)
        angle = SCREEN_DIRECTIONS.index("e")*pi/4
        forward = Vec2(cos(angle),sin(angle))*wind.radius_pixels*.75
        front,rear = wind.center+forward,wind.center-forward
        effect.update(.05,[step(0,.05)],3,[SwordTarget("front",front,.5),SwordTarget("rear",rear,.5)])
        self.assertIn((1,"front"),effect.hits)
        self.assertNotIn((1,"rear"),effect.hits)

    def test_sector_capsules_keep_rear_gap_at_all_directions_and_levels(self):
        config = settings()["body_wind"]
        for direction in SCREEN_DIRECTIONS:
            for level in (1,2,3):
                wind = body_wind_sector(Vec2(),direction,config,level)
                volumes = []
                for triangle in wind.triangles:
                    a,b,c = triangle
                    volumes.append(bounding_capsule(triangle,a,Vec2((b.x+c.x)*.5,(b.y+c.y)*.5)))
                angle = SCREEN_DIRECTIONS.index(direction)*pi/4
                offset = Vec2(cos(angle),sin(angle))*wind.radius_pixels*.75
                with self.subTest(direction=direction,level=level):
                    self.assertTrue(any(capsule_touches_circle(volume,wind.center+offset,.5) for volume in volumes))
                    self.assertFalse(any(capsule_touches_circle(volume,wind.center-offset,.5) for volume in volumes))


if __name__=="__main__":
    unittest.main()
