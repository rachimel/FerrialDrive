"""기준 리그와 JSON 자세 목록으로 보간 없는 키포즈 카탈로그를 제작한다."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class KeyposeRig:
    """기존 본·장착을 유지하며 실제 굽힘 면으로 두 마디를 배치한다."""

    def __init__(self, config):
        import bpy
        from mathutils import Matrix, Vector
        self.bpy, self.M, self.V = bpy, Matrix, Vector
        self.cfg = config
        self.rig = bpy.data.objects[config['rig']]
        self.base = {b.name: b.matrix_basis.copy() for b in self.rig.pose.bones}
        self.base_chest = self.world('Chest')
        self.root = bpy.data.objects[config['root']]
        self.root_basis = self.root.matrix_basis.copy()
        self.feet = {side: self.world('Foot.' + side) for side in ('L', 'R')}
        self.control = bpy.data.objects[config['control']]
        self.held = {}
        self.anchor_matrices = {}
        for weapon, side in config['weapons'].items():
            prop = weapon.lower() + '_stowed'
            old = self.control[prop]
            self.control[prop] = 0
            self.control.update_tag()
            self.update()
            hand = self.world('Hand.' + side)
            obj = bpy.data.objects[weapon]
            mesh = bpy.data.objects[weapon + '_Grip']
            center = mesh.matrix_world @ (sum((v.co for v in mesh.data.vertices), Vector()) / len(mesh.data.vertices))
            if weapon in config.get('bind_grips', {}):
                from model_geometry import set_world_matrix_from_parent_frame
                anchor = bpy.data.objects[weapon+'_HandAnchor']
                binding = config['bind_grips'][weapon]
                matrix = anchor.matrix_world.copy()
                if binding.get('hand_reference_rotation'):
                    local_center = obj.matrix_world.inverted() @ center
                    rotation = hand.to_quaternion() @ Matrix(binding['hand_reference_rotation']).to_quaternion().inverted()
                    matrix = Matrix.LocRotScale(Vector(), rotation, obj.matrix_world.to_scale())
                    matrix.translation = hand @ Vector(binding['palm'])-matrix.to_3x3() @ local_center
                else:
                    matrix.translation += hand @ Vector(binding['palm'])-center
                set_world_matrix_from_parent_frame(anchor, matrix)
                self.update()
                self.anchor_matrices[anchor.name] = [list(row) for row in anchor.matrix_basis]
                center = mesh.matrix_world @ (sum((v.co for v in mesh.data.vertices), Vector()) / len(mesh.data.vertices))
            self.held[weapon] = {'relation': hand.inverted() @ obj.matrix_world,
                                 'palm': hand.inverted() @ center}
            self.control[prop] = old
            self.control.update_tag()
            self.update()

    def update(self):
        self.bpy.context.view_layer.update()

    def world(self, name):
        return (self.rig.matrix_world @ self.rig.pose.bones[name].matrix).copy()

    def set_world(self, name, matrix):
        self.rig.pose.bones[name].matrix = self.rig.matrix_world.inverted() @ matrix
        self.update()

    def rotate(self, name, axis, degrees):
        if not degrees:
            return
        matrix = self.world(name)
        self.set_world(name, self.M.Translation(matrix.translation) @
                       self.M.Rotation(math.radians(degrees), 4, axis) @
                       self.M.Translation(-matrix.translation) @ matrix)

    def limb(self, upper, lower, end, target, pole, end_rotation=None, forward=1):
        """본 길이와 원래 굽힘축을 보존한다. 도달 불가는 숨기지 않는다."""
        from mathutils import Matrix, Vector
        worlds = [self.world(n) for n in (upper, lower, end)]
        a, b, c = (w.translation for w in worlds)
        v1, v2 = b-a, c-b
        length1, length2 = v1.length, v2.length
        target = Vector(target)
        delta = target-a
        distance = delta.length
        if not abs(length1-length2)+1e-5 < distance < length1+length2-1e-5:
            raise ValueError(f'{upper}: 도달 불가 목표 {distance:.4f}, 범위 {length1+length2:.4f}')
        direction = delta.normalized()
        bend = Vector(pole)-a
        bend -= direction*bend.dot(direction)
        if bend.length < 1e-6:
            raise ValueError(f'{upper}: 굽힘 면을 정할 수 없다.')
        along = (length1*length1-length2*length2+distance*distance)/(2*distance)
        joint = a+direction*along+bend.normalized()*math.sqrt(max(0, length1*length1-along*along))
        desired = [(joint-a).normalized(), (target-joint).normalized()]
        reference_axis = v1.cross(v2)
        if reference_axis.length < 1e-6:
            reference_axis = v1.cross(Vector((forward, 0, 0)))
        if reference_axis.cross(v1).x*forward < 0:
            reference_axis.negate()
        reference_axis.normalize()
        axis = desired[0].cross(desired[1]).normalized()

        def frame(tangent, normal):
            tangent = tangent.normalized()
            normal = (normal-tangent*normal.dot(tangent)).normalized()
            return Matrix((normal, tangent, normal.cross(tangent))).transposed()

        for name, old, native, tangent in zip((upper, lower), worlds, (v1, v2), desired):
            rotation = frame(tangent, axis) @ frame(native, reference_axis).transposed()
            result = rotation.to_4x4() @ old
            result.translation = a if name == upper else joint
            self.set_world(name, result)
        if end_rotation is not None:
            if end.startswith('Hand.') and 'WristSwivel.'+end[-1] in self.rig.pose.bones:
                wrist = 'WristSwivel.' + end[-1]
                old_hand, old_wrist = self.world(end), self.world(wrist)
                rotation = end_rotation @ old_hand.to_quaternion().inverted()
                result = rotation.to_matrix().to_4x4() @ old_wrist
                result.translation = target
                self.set_world(wrist, result)
            else:
                self.set_world(end, Matrix.LocRotScale(target, end_rotation, worlds[2].to_scale()))

    def arm(self, side, target, rotation, pole=None):
        if pole is None:
            pole = (-.65, .95 if side == 'L' else -.95, 1.75)
        pole = self.body_delta @ self.V(pole)
        self.limb('UpperArm.'+side, 'Forearm.'+side, 'Hand.'+side, target, pole, rotation)

    def fingers(self, side, amount):
        from mathutils import Quaternion, Vector
        bones = self.rig.data.bones
        roots = [bones.get(n+'01.'+side) for n in ('Index', 'Middle', 'Ring', 'Little')]
        if not all(roots):
            return
        forward = sum((b.matrix_local.to_3x3().col[1] for b in roots), Vector()).normalized()
        axis = roots[-1].head_local-roots[0].head_local
        axis = (axis-forward*axis.dot(forward)).normalized()
        if axis.cross(forward).dot(-bones['Hand.'+side].matrix_local.to_3x3().col[2]) < 0:
            axis.negate()
        for finger in ('Index', 'Middle', 'Ring', 'Little'):
            for part, degrees in (('01', 45), ('02', 65), ('03', 40)):
                bone = self.rig.pose.bones[finger+part+'.'+side]
                local_axis = bone.bone.matrix_local.to_3x3().inverted() @ axis
                bone.rotation_mode = 'QUATERNION'
                bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees*amount))
        for stem, degrees in (('ThumbBase', 20), ('Thumb01', 35), ('Thumb02', 40)):
            bone = self.rig.pose.bones.get(stem+'.'+side)
            if bone:
                axis = bones['ThumbBase.'+side].matrix_local.to_3x3().col[2]
                if side == 'L':
                    axis = -axis
                local_axis = bone.bone.matrix_local.to_3x3().inverted() @ axis
                bone.rotation_mode = 'QUATERNION'
                bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees*amount))
        self.update()

    def pose(self, p):
        from mathutils import Matrix, Vector
        self.issues = []
        self.root.matrix_basis = self.root_basis
        for name, matrix in self.base.items():
            self.rig.pose.bones[name].matrix_basis = matrix
        self.update()
        pelvis = self.world('Pelvis')
        pelvis.translation += Vector(p.get('pelvis', (0, 0, -.08)))
        self.set_world('Pelvis', pelvis)
        for bone, axis, key in (('Pelvis', 'Z', 'hip_yaw'), ('Waist', 'Y', 'lean'),
                                ('Waist', 'X', 'sway'), ('Chest', 'Z', 'yaw')):
            self.rotate(bone, axis, p.get(key, 0))
        self.body_delta = self.world('Chest') @ self.base_chest.inverted()
        for side in ('L', 'R'):
            foot = self.feet[side]
            target = foot.translation+Vector(p.get('foot_'+side, (0, 0, 0)))
            self.limb('Thigh.'+side, 'Shin.'+side, 'Foot.'+side, target,
                      (1.5, .5 if side == 'L' else -.5, 1), foot.to_quaternion(), forward=-1)
        mode = p.get('mode', 'sword')
        for weapon, side in self.cfg['weapons'].items():
            stowed = not ((weapon == 'Sword' and mode == 'sword') or (weapon == 'Gun' and mode != 'sword'))
            self.control[weapon.lower()+'_stowed'] = int(stowed)
        self.control.update_tag()
        self.update()
        for side in ('L', 'R'):
            weapon = next((w for w, s in self.cfg['weapons'].items() if s == side), None)
            active = (weapon == 'Sword' and mode == 'sword') or (weapon == 'Gun' and mode != 'sword')
            default = ([.12, .62, 1.94] if side == 'L' else [.08, -.60, 1.91])
            target = self.body_delta @ Vector(p.get('hand_'+side, default))
            if active:
                direction = Vector(p.get('blade' if weapon == 'Sword' else 'barrel',
                                         [1, 0, -.25] if weapon == 'Sword' else [1, 0, -.55])).normalized()
                desired = direction.to_track_quat('Z', 'Y') if weapon == 'Sword' else direction.to_track_quat('X', 'Z')
                rotation = desired @ self.held[weapon]['relation'].to_quaternion().inverted()
            else:
                rotation = self.world('Hand.'+side).to_quaternion()
            self.arm(side, target, rotation, p.get('pole_'+side))
            self.fingers(side, 1 if active else .15)
        if mode == 'aim':
            mesh = self.bpy.data.objects['Gun_ForeGrip']
            center = mesh.matrix_world @ (sum((v.co for v in mesh.data.vertices), Vector())/len(mesh.data.vertices))
            rotation = Matrix(((0, 1, 0), (0, 0, 1), (1, 0, 0))).to_quaternion()
            palm = self.held['Sword']['palm'] * self.rig.matrix_world.to_scale().x
            target = center-rotation@palm
            self.arm('L', target, rotation, p.get('support_pole', (-.5, .8, 1.7)))
            self.fingers('L', 1)
        if p.get('stow_reach'):
            weapon = p['stow_reach']
            side = self.cfg['weapons'][weapon]
            self.control[weapon.lower()+'_stowed'] = 1
            self.control.update_tag()
            self.update()
            obj = self.bpy.data.objects[weapon]
            mesh = self.bpy.data.objects[weapon+'_Grip']
            center = mesh.matrix_world @ (sum((v.co for v in mesh.data.vertices), Vector())/len(mesh.data.vertices))
            rotation = obj.matrix_world.to_quaternion() @ self.held[weapon]['relation'].to_quaternion().inverted()
            target = center-rotation @ (self.held[weapon]['palm']*self.rig.matrix_world.to_scale().x)
            if p.get('allow_stow_approach'):
                origin = self.world('UpperArm.'+side).translation
                elbow = self.world('Forearm.'+side).translation
                wrist = self.world('Hand.'+side).translation
                reach = (elbow-origin).length+(wrist-elbow).length
                if (target-origin).length >= reach-.005:
                    requested = target.copy()
                    target = origin+(target-origin).normalized()*(reach-.015)
                    self.issues.append({'kind': 'stow_contact_unresolved', 'weapon': weapon,
                                        'gap_to_requested_wrist': (requested-target).length})
            self.arm(side, target, rotation, p.get('stow_pole'))
            self.fingers(side, 1)
        for name, values in p.get('properties', {}).items():
            obj = self.bpy.data.objects[name]
            for key, value in values.items():
                obj[key] = value
            obj.update_tag()
        self.update()
        if p.get('heading'):
            self.root.matrix_basis = self.M.Rotation(math.radians(p['heading']), 4, 'Z') @ self.root_basis
            self.update()


def build(config_path, output):
    import bpy
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    cfg = json.loads(config_path.read_text(encoding='utf-8'))
    source = (config_path.parent/cfg['source']).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != cfg['source_sha256']:
        raise ValueError('기준 파일 해시 불일치')
    if output.exists():
        raise FileExistsError(output)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    solver = KeyposeRig(cfg)
    clips, audit, frames = [], [], {}
    for i, entry in enumerate(cfg['poses'], 1):
        try:
            solver.pose(entry['parameters'])
        except ValueError as error:
            raise ValueError(f"{entry['id']}: {error}") from error
        frames[entry['id']] = i
        sample = {'frame': i, 'bones': {b.name: [list(row) for row in b.matrix_basis] for b in solver.rig.pose.bones},
                  'objects': dict(solver.anchor_matrices, **{cfg['root']: [list(row) for row in solver.root.matrix_basis]}),
                  'properties': {cfg['control']: {k: solver.control[k] for k in ('sword_stowed', 'gun_stowed')}}}
        clips.append({'name': entry['id'], 'label': entry['label'], 'loop': False, 'events': [], 'samples': [sample]})
        bends = {}
        for part, upper, lower, end in (('elbow', 'UpperArm', 'Forearm', 'Hand'), ('knee', 'Thigh', 'Shin', 'Foot')):
            for side in ('L', 'R'):
                a, b, c = (solver.world(n+'.'+side).translation for n in (upper, lower, end))
                bends[part+'.'+side] = math.degrees((b-a).angle(c-b))
        audit.append({'pose': entry['id'], 'frame': i, 'bend_degrees': bends,
                      'angular_constraints_added': False, 'angle_limit_pass': None, 'issues': solver.issues})
    manifest = {'version': 1, 'asset_id': cfg['asset_id'], 'source': str(source), 'source_sha256': cfg['source_sha256'],
                'fps': 12, 'rig': cfg['rig'], 'root': cfg['root'], 'clips': clips}
    manifest_path = config_path.with_name('samples.json')
    write_json(manifest_path, manifest)
    from animation_pipeline import bake
    bake(manifest_path, output)
    groups = [dict(g, frames=[frames[n] for n in g['poses']]) for g in cfg['groups']]
    write_json(output/'keypose_groups.json', {'status': 'candidate_unchecked', 'frames_are_pose_ids': True,
               'inbetweens_created': False, 'angular_constraints_added': False, 'groups': groups,
               'poses': [dict(p, frame=frames[p['id']]) for p in cfg['poses']], 'pending_design': cfg.get('pending_design', [])})
    write_json(output/'pose_measurements.json', audit)
    print(json.dumps({'poses': len(clips), 'groups': len(groups), 'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest()==cfg['source_sha256']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    build(args.config, args.output)
