"""Curve, persistence and real export contracts, independent of the window."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from core import (DEFAULT_SOURCE,WORK,PRESETS,FIXED_DT,Playback,Project,
    compile_model,delete_curve_node,evaluate,insert_curve_node,inverse,
    move_curve_point,new_curve,track_source,validate_curve,validate_document,
    split_curve_node,encode_curve_clipboard,decode_curve_clipboard)


class Curves(unittest.TestCase):
    def test_control_point_split_preserves_shape(self):
        curve=new_curve('Ease In-Out');xs=np.linspace(0,1,151)
        before=[evaluate(curve,x) for x in xs]
        index=split_curve_node(curve,.37);self.assertEqual(index,1);validate_curve(curve)
        np.testing.assert_allclose([evaluate(curve,x) for x in xs],before,atol=2e-6)
    def test_curve_clipboard_roundtrip_is_independent(self):
        curve=new_curve('Ease Out');restored=decode_curve_clipboard(encode_curve_clipboard(curve))
        self.assertEqual(restored,curve);restored['nodes'][0]['out'][0]=.3
        self.assertNotEqual(restored,curve)
        with self.assertRaises(ValueError):decode_curve_clipboard('not a curve')
    def test_presets_and_reverse_read_same_curve(self):
        for preset in PRESETS:
            curve=new_curve(preset);validate_curve(curve)
            samples=[evaluate(curve,x) for x in np.linspace(0,1,101)]
            self.assertEqual(samples[0],0);self.assertEqual(samples[-1],1)
            self.assertTrue(all(a<=b for a,b in zip(samples,samples[1:])))
            for x in [.1,.3,.7,.9]:self.assertAlmostEqual(inverse(curve,evaluate(curve,x)),x,places=5)
        curve=new_curve('Smoothstep')
        for x in [.1,.25,.7,.9]:self.assertAlmostEqual(evaluate(curve,x),x*x*(3-2*x),places=6)
    def test_drag_insert_delete_remain_bounded_and_saved(self):
        curve=new_curve('Ease In');move_curve_point(curve,0,'out',1.5,-1)
        validate_curve(curve);index=insert_curve_node(curve,.4,.3);self.assertEqual(index,1)
        move_curve_point(curve,index,'node',.99,.9);validate_curve(curve)
        self.assertFalse(delete_curve_node(curve,0));self.assertTrue(delete_curve_node(curve,index))
        validate_curve(curve);self.assertEqual(json.loads(json.dumps(curve)),curve)
    def test_non_finite_and_backwards_time_rejected(self):
        curve=new_curve();curve['nodes'][0]['out'][0]=float('nan')
        with self.assertRaises(ValueError):validate_curve(curve)
        curve=new_curve();insert_curve_node(curve,.4,.5);curve['nodes'][1]['x']=0
        with self.assertRaises(ValueError):validate_curve(curve)


class Projects(unittest.TestCase):
    def test_save_roundtrip_and_history(self):
        WORK.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=WORK) as folder:
            project=Project(path=Path(folder)/'test.project.json');project.checkpoint()
            project.data['motion']['curve']=new_curve('Ease Out');project.changed()
            changed=copy.deepcopy(project.data);self.assertTrue(project.undo())
            self.assertEqual(project.data['motion']['curve']['preset'],'Linear')
            self.assertTrue(project.redo());self.assertEqual(project.data,changed)
            project.save();loaded=Project.load(project.path)
            self.assertEqual(loaded.data,project.data);self.assertFalse(loaded.dirty)
            self.assertEqual(loaded.source_path,DEFAULT_SOURCE.resolve())
    def test_playback_holds_and_reverses_without_restarting(self):
        doc=Project().data;p=Playback();duration=doc['motion']['duration']
        p.play(1)
        for _ in range(round(duration/FIXED_DT)+600):p.step(FIXED_DT,duration)
        self.assertEqual(p.position,1);self.assertFalse(p.playing)
        p.play(-1)
        for _ in range(40):p.step(FIXED_DT,duration)
        position=p.position;p.toggle()
        for _ in range(50):p.step(FIXED_DT,duration)
        self.assertEqual(p.position,position);p.toggle();self.assertEqual(p.direction,-1)
        for _ in range(round(duration/FIXED_DT)+600):p.step(FIXED_DT,duration)
        self.assertEqual(p.position,0);self.assertFalse(p.playing)
    def test_real_shape_export_changes_only_linked_track(self):
        project=Project();doc=copy.deepcopy(project.data);source=project.source
        doc['tracks']['mouth']['keys'][1]['curve']=new_curve('Ease In')
        WORK.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=WORK) as folder:
            path=compile_model(source,doc,DEFAULT_SOURCE.parent,folder,write_debug=True)
            self.assertTrue(path.is_file());compiled=json.loads((Path(folder)/'editor-keyforms.json').read_text())
            idx=compiled['parameter_keys'].index(.75)
            original={m['id']:m for m in source['meshes']};new={m['id']:m for m in compiled['meshes']}
            src_idx=source['parameter_keys'].index(.75)
            self.assertFalse(np.allclose(new['MouthOpening']['forms'][idx],original['MouthOpening']['forms'][src_idx]))
            np.testing.assert_allclose(new['EyeApertureL']['forms'][idx],original['EyeApertureL']['forms'][src_idx],atol=1e-5)
            self.assertEqual(new['EyeInteriorL']['neutral'],new['EyeInteriorL']['smile'])
            self.assertEqual(new['MouthInterior']['masks'],['MouthOpening'])
            closed=compiled['parameter_keys'].index(.5)
            np.testing.assert_allclose(new['MouthOpening']['forms'][closed],original['MouthOpening']['forms'][16],atol=1e-5)
            refs=json.loads(path.read_text())['FileReferences']
            self.assertTrue(all((path.parent/p).is_file() for p in refs['Textures']))
            self.assertEqual((path.parent/'character.moc3').read_bytes()[:5],b'MOC3\x04')


if __name__=='__main__':unittest.main()
