"""레지스트리 기반 모델 디자인 편집기. 불러오기·설정 검증·형상/본/재질 편집·별도 저장."""
from pathlib import Path
from math import radians
import argparse
import hashlib
import json
import sys

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))
from model_design_schema import DesignConfig


class ModelDesign:
    """기존 파일을 기준으로 편집한다. 생성 시 Blender 상태를 바꾸지 않는다."""

    def __init__(self, registry_path):
        registry_path = Path(registry_path)
        self.registry = json.loads(registry_path.read_text(encoding='utf-8'))
        self.baseline = ROOT / self.registry['baseline']
        self.loaded = False
        self.applied = False
        self.report = {}

    def load(self):
        import bpy
        digest = hashlib.sha256(self.baseline.read_bytes()).hexdigest()
        if digest != self.registry['baseline_sha256']:
            raise ValueError('기준 파일이 바뀌었다. 레지스트리와 기준 파일을 함께 확인해야 한다')
        bpy.ops.wm.open_mainfile(filepath=str(self.baseline))
        self.root = bpy.data.objects[self.registry['root']]
        self.rig = bpy.data.objects[self.registry['rig']]
        bpy.context.view_layer.update()
        self.loaded = True
        self.applied = False
        return self

    def validate(self, config):
        """변경 전 전체 설정을 확인한다. 실패한 설정은 저장하지 않는다."""
        import bpy
        if not self.loaded:
            raise RuntimeError('load()가 먼저 필요하다')
        for edits, field in ((config.parts, 'part'), (config.bones, 'bone'), (config.materials, 'material'), (config.mounts, 'mount')):
            names = [getattr(edit, field) for edit in edits]
            if len(names) != len(set(names)):
                raise ValueError(f'{field} 중복 편집은 하나로 합쳐야 한다')
        for edit in config.parts:
            if edit.part not in self.registry['parts']:
                raise ValueError(f'알 수 없는 부위: {edit.part}')
            if edit.part == 'helpers':
                raise ValueError('검사용 helpers는 디자인 편집 대상이 아니다')
            for name in self.registry['parts'][edit.part]['objects']:
                if name not in bpy.data.objects:
                    raise ValueError(f'부위 메시 누락: {name}')
        for edit in config.bones:
            if edit.bone not in self.rig.data.bones:
                raise ValueError(f'알 수 없는 본: {edit.bone}')
        for edit in config.materials:
            if edit.material not in self.registry['materials']:
                raise ValueError(f'알 수 없는 기준 재질: {edit.material}')
            material = bpy.data.materials[edit.material]
            shader = self.shader(material)
            for field, socket in [('base_color', 'Base Color'), ('metallic', 'Metallic'), ('roughness', 'Roughness')]:
                if getattr(edit, field) is not None and shader and shader.inputs[socket].is_linked:
                    raise ValueError(f'{edit.material}/{socket}: 이미지나 다른 노드에 연결돼 있어 상수로 바꿀 수 없다')
        for edit in config.mounts:
            if edit.mount not in self.registry.get('mounts', {}):
                raise ValueError(f'알 수 없는 부착부: {edit.mount}')
            entry = self.registry['mounts'][edit.mount]
            for key, value in edit.controls.items():
                ui = entry['controls'].get(key)
                if ui is None or not isinstance(value, (int, float)) or not ui.get('min', -1e30) <= value <= ui.get('max', 1e30):
                    raise ValueError(f'부착부 제어 범위 오류: {edit.mount}/{key}')
        for key, value in config.controls.items():
            if key not in self.registry['controls']:
                raise ValueError(f'알 수 없는 장치 제어: {key}')
            ui = self.registry['controls'][key]['ui']
            if not isinstance(value, (int, float)) or not ui.get('min', -1e30) <= value <= ui.get('max', 1e30):
                raise ValueError(f'장치 값 범위 오류: {key}')

    @staticmethod
    def shader(material):
        return next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if material.use_nodes else None

    @staticmethod
    def interpolate(knots, position):
        position = max(0., min(1., position))
        for a, b in zip(knots, knots[1:]):
            if position <= b[0]:
                t = (position - a[0]) / (b[0] - a[0])
                return a[1] * (1 - t) + b[1] * t, a[2] * (1 - t) + b[2] * t
        return knots[-1][1:]

    def edit_part(self, edit):
        import bpy
        from mathutils import Vector
        part = self.registry['parts'][edit.part]
        pivot = Vector(edit.pivot if edit.pivot is not None else part['pivot'])
        lower, upper = part['bounds_min'], part['bounds_max']
        root_inverse = self.root.matrix_world.inverted()
        for name in part['objects']:
            obj = bpy.data.objects[name]
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            matrix = root_inverse @ obj.matrix_world
            inverse = matrix.inverted()

            def deform(co):
                reference = matrix @ co
                value = reference.copy()
                for profile in edit.profiles:
                    along, axis = 'XYZ'.index(profile.along_axis), 'XYZ'.index(profile.deform_axis)
                    span = upper[along] - lower[along]
                    if span <= 1e-12:
                        raise ValueError(f'{edit.part}: 프로파일 기준축 길이가0이다')
                    scale, offset = self.interpolate(profile.knots, (reference[along] - lower[along]) / span)
                    value[axis] = pivot[axis] + (value[axis] - pivot[axis]) * scale + offset
                value = Vector([pivot[i] + (value[i] - pivot[i]) * edit.scale[i] + edit.offset[i] for i in range(3)])
                return inverse @ value

            if obj.data.shape_keys:
                for key in obj.data.shape_keys.key_blocks:
                    for vertex in key.data:
                        vertex.co = deform(vertex.co)
            else:
                for vertex in obj.data.vertices:
                    vertex.co = deform(vertex.co)
            obj.data.update()

    def edit_bones(self, edits):
        import bpy
        from mathutils import Vector
        if not edits:
            return
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        conversion = (self.rig.matrix_world.inverted() @ self.root.matrix_world).to_3x3()
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            # 연결 본의 암묵적 전파가 있는지 요청 좌표와 비교한다.
            before = {b.name: (b.head.copy(), b.tail.copy()) for b in self.rig.data.edit_bones}
            expected = {}
            for edit in edits:
                bone = self.rig.data.edit_bones[edit.bone]
                expected[edit.bone] = (bone.head + conversion @ Vector(edit.head_offset), bone.tail + conversion @ Vector(edit.tail_offset))
            for edit in edits:
                bone = self.rig.data.edit_bones[edit.bone]
                bone.head, bone.tail = expected[edit.bone]
                bone.roll += radians(edit.roll_offset_degrees)
            for name, (head, tail) in expected.items():
                bone = self.rig.data.edit_bones[name]
                if (bone.head - head).length > 1e-6 or (bone.tail - tail).length > 1e-6 or bone.length <= 1e-6:
                    raise ValueError(f'{name}: 연결 본의 요청 좌표가 맞지 않거나 길이가0이다')
            for name, (head, tail) in before.items():
                bone = self.rig.data.edit_bones[name]
                if name not in expected and ((bone.head - head).length > 1e-6 or (bone.tail - tail).length > 1e-6):
                    raise ValueError(f'{name}: 연결 때문에 미지정 본도 움직였다. 함께 편집할 본을 명시해야 한다')
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

    def apply(self, config):
        import bpy
        if self.applied:
            raise RuntimeError('중복 적용을 막기 위해 새 load()가 필요하다')
        self.validate(config)
        # 처리 중 실패하면 부분 적용된 장면을 다시 쓰지 못하게 한다.
        self.loaded = False
        action = self.rig.animation_data.action if self.rig.animation_data else None
        if self.rig.animation_data:
            self.rig.animation_data.action = None
        for bone in self.rig.pose.bones:
            bone.matrix_basis.identity()
        for key, value in self.registry.get('rest_controls', {}).items():
            self.root[key] = value
        self.root.update_tag()
        bpy.context.view_layer.update()
        for edit in config.parts:
            self.edit_part(edit)
        from mathutils import Vector
        for edit in config.mounts:
            obj = bpy.data.objects[self.registry['mounts'][edit.mount]['object']]
            # VERTEX_3 부모의 기준 프레임을 포함해 로컬 이동량으로 변환한다.
            parent_frame = obj.matrix_world @ obj.matrix_basis.inverted()
            delta = self.root.matrix_world.to_3x3() @ Vector(edit.offset)
            obj.location += parent_frame.to_3x3().inverted() @ delta
            for key, value in edit.controls.items():
                obj[key] = value
            obj.update_tag()
            bpy.context.view_layer.update()
        self.edit_bones(config.bones)
        for edit in config.materials:
            material = bpy.data.materials[edit.material]
            shader = self.shader(material)
            for field, socket in [('base_color', 'Base Color'), ('metallic', 'Metallic'), ('roughness', 'Roughness')]:
                value = getattr(edit, field)
                if value is not None:
                    setattr(material, 'diffuse_color' if field == 'base_color' else field, value)
                    if shader:
                        shader.inputs[socket].default_value = value
        if self.rig.animation_data:
            self.rig.animation_data.action = action
        bpy.context.scene.frame_set(1)
        for key, value in config.controls.items():
            self.root[key] = value
        self.root.update_tag()
        bpy.context.view_layer.update()
        self.applied = True
        self.loaded = True
        self.report = {'name': config.name, 'baseline_sha256': self.registry['baseline_sha256'], 'parts': [v.part for v in config.parts], 'bones': [v.bone for v in config.bones], 'materials': [v.material for v in config.materials], 'mounts': [{'mount': v.mount, 'offset': v.offset, 'controls': v.controls} for v in config.mounts], 'controls': config.controls, 'uv_reunwrap_needed': bool(config.parts), 'normal_and_joint_review_needed': bool(config.parts or config.bones or config.mounts), 'full_motion_validated': False}
        return self.report

    def save(self, output):
        import bpy
        if not self.applied:
            raise RuntimeError('검증한 설정을 apply()한 다음 저장해야 한다')
        output = Path(output).resolve()
        protected = ROOT / 'data/models'
        if output == self.baseline.resolve() or protected.resolve() in output.parents:
            raise ValueError('디자인 편집 결과는 원본 모델 폴더 밖에 저장해야 한다')
        if output.exists() or output.with_suffix('.design_report.json').exists():
            raise FileExistsError(f'기존 결과를 덮어쓰지 않는다: {output}')
        if output.suffix.lower() != '.blend':
            raise ValueError('출력 확장자는 .blend')
        output.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(output))
        if hashlib.sha256(self.baseline.read_bytes()).hexdigest() != self.registry['baseline_sha256']:
            raise RuntimeError('기준 원본 해시가 달라졌다')
        output.with_suffix('.design_report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='레지스트리 기반 모델 디자인 편집')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    config = DesignConfig.from_dict(json.loads(args.config.read_text(encoding='utf-8')))
    design = ModelDesign(args.registry).load()
    design.apply(config)
    design.save(args.output)
    print('MECH_DESIGN_SAVED', str(args.output), flush=True)


if __name__ == '__main__':
    main()
