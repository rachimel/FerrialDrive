"""입력용 자세 선택과 회전된 검날·총구·발 부착의 공통 좌표를 검사한다."""

from copy import deepcopy
from types import SimpleNamespace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ferrial_drive.combat.aim_follow import AimFollow, AimFollowSettings
from ferrial_drive.combat.movement_application import MovementApplication
from ferrial_drive.combat.upper_lower import UpperLowerCatalog, PoseAttachments, PoseBladeTrajectory, direction_index


def fixture():
    row = {"seconds":0,"root":[0,0,0],"waist":[1,0,5],
           "points":{"blade_root":[3,0,5],"blade_tip":[4,0,5],"muzzle":[4,0,5],"sole_l":[1,0,0]}}
    end = deepcopy(row);end["seconds"] = .5
    return {"version":1,"type":"upper_lower_pose_table","directions":8,"fps":12,
            "pixel_scale":1,"camera":{"position":[0,10,5],"target":[0,0,0],"size":[100,100],"width_cm":100},
            "motions":{"combo_01":{"frames":7,"source_frame_count":6,"loop":False}},
            "attachments":{"combo_01":{"duration_seconds":.5,"loop":False,
                "upper_points":["blade_root","blade_tip","muzzle"],"samples":[row,end]}}}


class UpperLowerRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.catalog = UpperLowerCatalog(fixture())

    def test_angle_wrap_and_eight_direction_pair(self):
        pose = self.catalog.select("combo_01",.25,359,-90)
        self.assertEqual((pose.clip_name,pose.frame_index),("combo_01/u0l6",3))
        self.assertEqual(direction_index(-22.5),0)
        self.assertEqual(direction_index(22.5),1)

    def test_phase_endpoint_and_loop_use_source_duration(self):
        self.assertEqual(self.catalog.select("combo_01",99,0,0).frame_index,6)
        self.assertEqual(self.catalog.select("combo_01",.5,0,0,loop=True).frame_index,0)
        self.assertIsNone(self.catalog.select("unsupported",0,0,0))

    def test_waist_translation_weapon_and_foot_share_rotated_pose(self):
        tracks = PoseAttachments(self.catalog)
        tracks.begin_frame((90,-90),(90,-90),[],1/60)
        for value,expected in [(tracks.point("combo_01",.2,"blade_root"),(0,1,5)),
                               (tracks.point("combo_01",.2,"blade_tip"),(0,2,5)),
                               (tracks.point("combo_01",.2,"sole_l"),(0,-1,0))]:
            for a,b in zip(value,expected):
                self.assertAlmostEqual(a,b)
        blade = PoseBladeTrajectory(tracks,None)
        root,tip = blade.pose("combo_01/w",.2,1,2)
        self.assertAlmostEqual((tip-root).length,2*(tracks.projected("combo_01",.2,"blade_tip")-root).length)
        self.assertEqual(blade.echo_clip_name("combo_01/w",.2),"combo_01/u2l6")
        self.assertIsInstance(tracks.ground_offsets("combo_01",.2,1)["sole_l"],tuple)

    def test_source_frame_and_both_directions_ignore_locked_attack_heading(self):
        app = MovementApplication.__new__(MovementApplication)
        app.pose_catalog = self.catalog
        app.current_weapon_motion = lambda:None
        app.combat = SimpleNamespace(active=True,combo=SimpleNamespace(clip_name="combo_01/w",elapsed_seconds=.25,waiting_for_input=False))
        app.aim_follow = AimFollow(AimFollowSettings(.12,.24),yaw_degrees=0)
        app.aim_follow.upper_yaw_degrees = 90
        app.config = {"combat":{"easing":"linear"}}
        pose = app.current_pose()
        self.assertEqual((pose.clip_name,pose.frame_index),("combo_01/u2l0",3))
        app.combat.combo.waiting_for_input = True
        self.assertEqual(app.current_pose().frame_index,0)

    def test_turn_between_frames_sweeps_effects_without_old_fixed_trajectory(self):
        tracks = PoseAttachments(self.catalog)
        step = SimpleNamespace(clip_name="combo_01/e",duration_seconds=.5,start_seconds=0,end_seconds=.5,real_seconds=.5)
        tracks.begin_frame((0,0),(90,0),[step],.5)
        self.assertAlmostEqual(tracks.frame_fraction("combo_01",.25),.5,places=5)
        before = tracks.projected("combo_01",0,"blade_tip",fraction=0)
        after = tracks.projected("combo_01",.5,"blade_tip",fraction=1)
        self.assertNotEqual(before,after)

    def test_hit_detection_uses_rotated_blade_instead_of_old_fixed_heading(self):
        from ferrial_drive.combat.sword_effects import BladeTrajectory, SwordEffects, SwordTarget
        from ferrial_drive.combat.movement_combat import AttackStep
        from ferrial_drive.combat.geometry import Vec2
        tracks = PoseAttachments(self.catalog)
        tracks.begin_frame((0,0),(0,0),[],.5)
        a,b = (tracks.projected("combo_01",0,key) for key in ("blade_root","blade_tip"))
        fixed = BladeTrajectory({"combo_01/e":[(0,a,b),(.5,a,b)]})
        tracks.begin_frame((90,0),(90,0),[],.5)
        target = (tracks.projected("combo_01",0,"blade_root")+tracks.projected("combo_01",0,"blade_tip"))*50
        profile = {"reach_scale":1,"trail_seconds":1,"echo_count":0,"echo_seconds":.2,
                   "echo_interval_seconds":.1,"echo_opacity":.2}
        settings = {"levels":[profile]*3,"sample_seconds":.01,"max_sections":100,"half_width_pixels":.1,
                    "active_phase_windows":[[0,1]]*4,"hit_y_margin_m":0}
        step = AttackStep(1,"combo_01/e",0,.5,.5,.5,(0,0),(0,0))
        outcomes = []
        for trajectory in (fixed,PoseBladeTrajectory(tracks,fixed)):
            effects = SwordEffects(trajectory,settings,scale=100,project=lambda p:p,easing="linear",hitbox_type="capsule")
            effects.update(.5,[step],1,[SwordTarget("probe",target,1)],energy_color="#FFFFFF")
            outcomes.append(effects.hits)
        self.assertEqual(outcomes,[[],[(1,"probe")]])


class PoseCacheTest(unittest.TestCase):
    def test_live_echo_and_body_stay_resident_while_old_motion_is_released(self):
        from ferrial_drive.rendering.pico_pose_table import PicoPoseTable
        class Sprite:
            def __init__(self,*args,**kwargs):
                self.estimated_bytes,self.closed = 4,False
            def close(self):
                self.closed = True
        with TemporaryDirectory() as directory:
            root = Path(directory)
            motions = {}
            for name in ("a","b","c"):
                (root/(name+".json")).write_text(json.dumps({
                    "pages":{"color":[{"width":1,"height":1,"codec":"rgba_zlib"}]},
                    "clips":{name+"/u0l0":{"pixel_scale":1,"pivot":[0,0],"source_size":[1,1]}}
                }))
                motions[name] = {"variants":{"high":name+".json"}}
            catalog = SimpleNamespace(motions=motions,directory=root)
            with patch('ferrial_drive.rendering.pico_pose_table.PicoAtlasSprite',Sprite):
                cache = PicoPoseTable(None,catalog,'high',budget_bytes=8)
                first = cache.sprites['a']
                cache.prepare_frame(['a/u0l0','b/u0l0'])
                second = cache.sprites['b']
                cache.prepare_frame(['b/u0l0','c/u0l0'])
                self.assertTrue(first.closed)
                self.assertIs(second,cache.sprites['b'])
                self.assertFalse(second.closed)
                self.assertEqual(cache.estimated_bytes,8)
                cache.prepare_frame(['a/u0l0','b/u0l0','c/u0l0'])
                self.assertEqual(set(cache.sprites),{'a','b','c'})
                cache.close()
                self.assertTrue(second.closed)
