"""백그라운드 Blender에서 실제 데이터로 제작 경계와 실패 처리를 검사한다."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/blender_pipeline'))
from model_pipeline import build
from check_model_geometry import check as check_geometry
from check_model_uv import check as check_uv
from check_model_images import check as check_images
from check_model_collisions import check as check_collisions
from model_geometry import set_world_matrix_from_parent_frame, transform_vertices


class ModelPipelineTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'output').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='model-pipeline-test-', dir=ROOT / 'output')
        self.directory = Path(self.temporary.name)
        self.spec = json.loads((ROOT / 'samples/model_pipeline/manifest.json').read_text())
        self.spec.pop('review')
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        assert self.directory.resolve().parent == (ROOT / 'output').resolve()
        self.temporary.cleanup()

    def run_build(self, name='run'):
        manifest = self.directory / f'{name}.json'
        manifest.write_text(json.dumps(self.spec))
        return build(manifest, self.directory / name)

    def test_saved_reload_and_no_automatic_approval(self):
        result = self.run_build()
        self.assertEqual(result['status'], 'candidate_unchecked')
        self.assertFalse(result['visual_approval'])
        self.assertFalse(result['quality_checks_run'])
        self.assertFalse(check_geometry({})['errors'])
        with self.assertRaises(FileExistsError):
            self.run_build()

    def test_bone_attachment_preserves_world_and_follows_pose(self):
        from model_operations import apply_operations
        from mathutils import Vector
        bpy.ops.object.armature_add()
        rig = bpy.context.object
        rig.name = 'FitRig'
        apply_operations([
            {'op': 'create_empty', 'name': 'Attachment'},
            {'op': 'attach_world', 'object': 'Attachment', 'parent': 'FitRig',
             'bone': 'Bone', 'matrix_world': [[1, 0, 0, 2], [0, 1, 0, 0], [0, 0, 1, 1], [0, 0, 0, 1]]},
        ])
        attached = bpy.data.objects['Attachment']
        self.assertLess((attached.matrix_world.translation - Vector((2, 0, 1))).length, 1e-5)
        local = (rig.matrix_world @ rig.pose.bones['Bone'].matrix).inverted() @ attached.matrix_world
        apply_operations([{'op': 'aim_bone', 'object': 'FitRig', 'bone': 'Bone', 'world_direction': [1, 0, 0]}])
        expected = rig.matrix_world @ rig.pose.bones['Bone'].matrix @ local
        self.assertLess((attached.matrix_world.translation - expected.translation).length, 1e-5)

    def test_attachment_switch_uses_same_object(self):
        from model_operations import apply_operations
        apply_operations([
            {'op': 'create_empty', 'name': 'Control', 'properties': {'stowed': 0.0}},
            {'op': 'create_empty', 'name': 'Held', 'location': [2, 0, 0]},
            {'op': 'create_empty', 'name': 'Stowed', 'location': [-2, 0, 0]},
            {'op': 'create_empty', 'name': 'Prop'},
            {'op': 'attachment_switch', 'object': 'Prop', 'control': 'Control',
             'property': 'stowed', 'stowed_target': 'Stowed', 'held_target': 'Held'},
        ])
        self.assertAlmostEqual(bpy.data.objects['Prop'].matrix_world.translation.x, 2)
        apply_operations([{'op': 'set_properties', 'object': 'Control', 'values': {'stowed': 1.0}}])
        self.assertAlmostEqual(bpy.data.objects['Prop'].matrix_world.translation.x, -2)

    def test_limb_pose_reaches_without_stretching(self):
        from model_operations import apply_operations
        from mathutils import Vector
        bpy.ops.object.armature_add()
        rig = bpy.context.object
        bpy.ops.object.mode_set(mode='EDIT')
        upper = rig.data.edit_bones[0]
        upper.name = 'Upper'
        lower = rig.data.edit_bones.new('Lower')
        lower.head, lower.tail = (0, 0, 1), (0, 0, 2)
        lower.parent, lower.use_connect = upper, True
        end = rig.data.edit_bones.new('End')
        end.head, end.tail = (0, 0, 2), (0, 0, 2.3)
        end.parent, end.use_connect = lower, True
        bpy.ops.object.mode_set(mode='OBJECT')
        op = dict(op='pose_limb', object=rig.name, upper='Upper', lower='Lower', end='End',
                  target_world=[1, 0, 1], bend_world=[0, -1, 0], end_rotation_world=[1, 0, 0, 0])
        apply_operations([op])
        self.assertLess((rig.pose.bones['End'].head - Vector((1, 0, 1))).length, 1e-5)
        self.assertAlmostEqual(rig.pose.bones['Upper'].length, 1, places=6)
        self.assertAlmostEqual(rig.pose.bones['Lower'].length, 1, places=6)
        with self.assertRaisesRegex(ValueError, '도달 범위'):
            apply_operations([{**op, 'target_world': [10, 0, 0]}])

    def test_collision_is_failure_not_just_console_message(self):
        self.spec['operations'][2]['location'] = [.1, .1, 1.2]
        result = self.run_build()
        self.assertFalse(result['quality_checks_run'])
        report = check_collisions({'collision_pairs': [['Plate', 'Joint']]})
        self.assertTrue(any('intersection:' in e for e in report['errors']))

    def test_source_hash_and_out_of_scope_edit(self):
        self.run_build()
        source = self.directory / 'run/candidate.blend'
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.spec.update(source=str(source), source_sha256='bad', operations=[
            {'op': 'transform_vertices', 'object': 'Plate', 'root': 'ActorRoot', 'offset': [.1, 0, 0]}])
        with self.assertRaisesRegex(ValueError, '해시'):
            self.run_build('bad_hash')
        self.spec['source_sha256'] = digest
        with self.assertRaisesRegex(ValueError, '수정 범위'):
            self.run_build('bad_scope')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
        self.spec['change_objects'] = ['Plate']
        self.assertTrue(self.run_build('allowed')['source_unchanged'])

    def test_invalid_pair_cannot_pass_silently(self):
        self.run_build()
        with self.assertRaisesRegex(ValueError, '가시 메시'):
            check_collisions({'collision_pairs': [['Missing', 'Joint']]})

    def test_new_profile_asset_needs_only_json(self):
        self.spec['asset_id'] = 'another_asset'
        self.spec['operations'] = [
            {'op': 'create_empty', 'name': 'NewRoot'},
            {'op': 'create_material', 'name': 'Armor', 'metallic': .6},
            {'op': 'create_profile', 'name': 'Hull', 'parent': 'NewRoot', 'material': 'Armor',
             'profiles': [[[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                          [[-.8, -.8, 2], [.8, -.8, 2], [.8, .8, 2], [-.8, .8, 2]]]},
            {'op': 'add_bevel', 'object': 'Hull', 'width': .02}]
        result = self.run_build()
        self.assertEqual(result['added_objects'], ['Hull', 'NewRoot'])
        self.assertFalse(check_geometry({'required_objects': ['Hull']})['errors'])

    def test_unknown_operation_does_not_save_candidate(self):
        self.spec['operations'].append({'op': 'run_arbitrary_script'})
        with self.assertRaisesRegex(ValueError, '지원하지 않는'):
            self.run_build()
        self.assertFalse((self.directory / 'run/candidate.blend').exists())

    def test_uv_and_image_errors(self):
        self.run_build()
        plate = bpy.data.objects['Plate']
        layer = plate.data.uv_layers.new(name='UV_Paint')
        for v in layer.data:
            v.uv = (2, 2)
        bpy.data.images.new('Unpacked', width=2048, height=1)
        errors = check_uv({'uv_objects': ['Plate']})['errors'] + check_images({})['errors']
        self.assertIn('uv_bounds:Plate', errors)
        self.assertIn('zero_area_uv:Plate', errors)
        self.assertIn('image_size:Unpacked', errors)
        self.assertIn('unpacked_image:Unpacked', errors)

    def test_shape_keys_are_transformed_together(self):
        self.run_build()
        obj = bpy.data.objects['Plate']
        obj.shape_key_add(name='Basis')
        key = obj.shape_key_add(name='Raised')
        key.data[0].co.z += .3
        difference = key.data[0].co.z - obj.data.shape_keys.key_blocks['Basis'].data[0].co.z
        transform_vertices(obj, bpy.data.objects['ActorRoot'], lambda p: p * 2)
        self.assertAlmostEqual(key.data[0].co.z - obj.data.shape_keys.key_blocks['Basis'].data[0].co.z,
                               difference * 2, places=5)

    def test_vertex_parent_frame_and_zero_angle_guard(self):
        self.run_build()
        parent = bpy.data.objects['Plate']
        child = bpy.data.objects.new('Attachment', None)
        bpy.context.scene.collection.objects.link(child)
        child.parent = parent
        child.parent_type = 'VERTEX_3'
        child.parent_vertices = (0, 1, 2)
        bpy.context.view_layer.update()
        target = child.matrix_world @ Matrix.Rotation(.3, 4, 'Z')
        set_world_matrix_from_parent_frame(child, target)
        bpy.context.view_layer.update()
        bpy.context.scene.frame_set(2)
        self.assertLess(max(abs(child.matrix_world[i][j] - target[i][j]) for i in range(4) for j in range(4)), 1e-5)
        child.rotation_mode = 'AXIS_ANGLE'
        child.rotation_axis_angle = (0, 1, 0, 0)
        with self.assertRaises(ValueError):
            set_world_matrix_from_parent_frame(child, target)
        self.assertEqual(tuple(child.rotation_axis_angle), (0, 1, 0, 0))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ModelPipelineTests))
    if not result.wasSuccessful():
        raise RuntimeError('모델 파이프라인 검증 실패')
