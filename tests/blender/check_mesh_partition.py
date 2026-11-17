"""강체 패널 면 분리 검사
기본 도형에서 원래 면·UV·재질·코너 노멀 보존과 잘못된 분할 거절을 확인한다.
"""
from pathlib import Path
import sys
import unittest

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Tools/blender_pipeline'))
from model_geometry import freeze_evaluated_meshes, partition_mesh_faces


class MeshPartitionCheck(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        self.source = bpy.context.object
        self.source.name = 'Source'
        material = bpy.data.materials.new('Exterior')
        self.source.data.materials.append(material)
        bpy.data.materials.new('Interior')
        self.groups = [dict(name='Panel_A', faces=[0, 3, 4]),
                       dict(name='Panel_B', faces=[1, 2, 5])]

    def test_surface_data_and_closed_caps(self):
        source = self.source.data
        old_uv = {index: [tuple(source.uv_layers[0].data[i].uv) for i in face.loop_indices]
                  for index, face in enumerate(source.polygons)}
        old_normals = {index: [source.corner_normals[i].vector.copy() for i in face.loop_indices]
                       for index, face in enumerate(source.polygons)}
        panels = partition_mesh_faces(self.source, self.groups, 'Interior')
        self.assertTrue(self.source.hide_render)
        seen = []
        for panel in panels:
            mesh = panel.data
            edge_counts = {}
            for face in mesh.polygons:
                indices = list(face.vertices)
                for a, b in zip(indices, indices[1:] + indices[:1]):
                    key = tuple(sorted((a, b)))
                    edge_counts[key] = edge_counts.get(key, 0) + 1
                index = mesh.attributes['FD_PartitionSourceFace'].data[face.index].value
                if index < 0:
                    self.assertEqual(mesh.materials[face.material_index].name, 'Interior')
                    continue
                seen.append(index)
                actual_uv = [tuple(mesh.uv_layers[0].data[i].uv) for i in face.loop_indices]
                self.assertEqual(actual_uv, old_uv[index])
                for loop, expected in zip(face.loop_indices, old_normals[index]):
                    self.assertLess((mesh.corner_normals[loop].vector - expected).length, 1e-5)
                self.assertEqual(mesh.materials[face.material_index].name, 'Exterior')
            self.assertTrue(all(count == 2 for count in edge_counts.values()))
        self.assertEqual(sorted(seen), list(range(6)))

    def test_duplicate_faces_rejected_before_changes(self):
        self.groups[1]['faces'] = [0, 1, 2, 5]
        with self.assertRaises(ValueError):
            partition_mesh_faces(self.source, self.groups)
        self.assertEqual(len(bpy.data.objects), 1)
        self.assertFalse(self.source.hide_render)

    def test_plane_halves_cover_cube_and_keep_uv(self):
        import bmesh
        groups = [dict(name='Positive', planes=[[1, 0, 0, 0]]),
                  dict(name='Negative', planes=[[-1, 0, 0, 0]])]
        panels = partition_mesh_faces(self.source, groups, 'Interior', planes=True)
        volumes = []
        exterior_area = 0
        for panel in panels:
            bm = bmesh.new()
            bm.from_mesh(panel.data)
            self.assertTrue(all(edge.is_manifold for edge in bm.edges))
            volumes.append(bm.calc_volume(signed=True))
            bm.free()
            self.assertEqual(len(panel.data.uv_layers), 1)
            for face in panel.data.polygons:
                if panel.data.materials[face.material_index].name == 'Exterior':
                    exterior_area += face.area
        self.assertAlmostEqual(sum(volumes), 8.0, places=5)
        self.assertAlmostEqual(exterior_area, 24.0, places=5)
        from check_model_uv import check
        self.assertEqual(check({'uv_objects': [panel.name for panel in panels], 'uv_layer': 'UVMap',
                                'untextured_materials': ['Interior']})['errors'], [])
        from check_model_uv_preservation import compare_mesh_uv
        for panel in panels:
            self.assertEqual(compare_mesh_uv(self.source.data, panel.data, 'UVMap')['errors'], [])
        panels[0].data.uv_layers[0].data[0].uv.x += 0.1
        self.assertTrue(compare_mesh_uv(self.source.data, panels[0].data, 'UVMap')['errors'])

    def test_evaluated_surface_is_frozen(self):
        modifier = self.source.modifiers.new('Bevel', 'BEVEL')
        modifier.width = 0.1
        bpy.context.view_layer.update()
        expected = len(self.source.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.polygons)
        freeze_evaluated_meshes(['Source'])
        self.assertEqual(len(self.source.data.polygons), expected)
        self.assertEqual(len(self.source.modifiers), 0)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MeshPartitionCheck)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError('강체 패널 분리 검사가 실패했다.')
