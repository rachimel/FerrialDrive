"""JSON 포즈·보행 매개변수로 초안 동작을 만들고 기존 출력 계약으로 전달한다."""
import hashlib
import json
import math
from pathlib import Path


def blend_pose(a, b, t):
    out = {key: a.get(key, 0) * (1-t) + b.get(key, 0) * t for key in a.keys() | b.keys()}
    for key in ['aim_x','aim_y','aim_z']:
        if key in a or key in b:
            out[key] = a.get(key,b.get(key))*(1-t)+b.get(key,a.get(key))*t
    return out


def sample_keys(keys, frame):
    for left, right in zip(keys, keys[1:]):
        if frame <= right[0]:
            t = max(0, (frame-left[0]) / (right[0]-left[0]))
            result = blend_pose(left[1], right[1], t*t*(3-2*t))
            for weapon in ['sword_stowed','gun_stowed']:
                result[weapon] = right[1].get(weapon,1) if t >= 1 else left[1].get(weapon,1)
            return result
    return keys[-1][1].copy()


class BlockingRig:
    def __init__(self, cfg):
        import bpy
        from mathutils import Matrix, Vector
        self.bpy, self.M, self.V = bpy, Matrix, Vector
        self.cfg = cfg
        self.r = bpy.data.objects[cfg['rig']]
        self.errors = []
        self.base = {b.name: b.matrix_basis.copy() for b in self.r.pose.bones}
        self.feet = {side: (self.r.matrix_world @ self.r.pose.bones['Foot.'+side].matrix).copy() for side in ['L', 'R']}
        self.grip_bind = {}
        self.hinge_axes = {}
        for side in ['L','R']:
            w = self.r.matrix_world @ self.r.pose.bones['Forearm.'+side].matrix
            axis = w.to_3x3().col[1].normalized().cross(Vector((1,0,0))).normalized()
            self.hinge_axes[side] = w.to_quaternion().inverted() @ axis
        self.skirt_fixed = self.repair_unbound(cfg.get('weight_repair'))

    def repair_unbound(self, spec):
        if not spec or spec.get('enabled') is not True:
            return 0
        from mathutils.kdtree import KDTree
        source, target = [self.bpy.data.objects[spec[k]] for k in ['source', 'target']]
        tree = KDTree(len(source.data.vertices))
        for v in source.data.vertices:
            tree.insert(source.matrix_world @ v.co, v.index)
        tree.balance()
        count = 0
        for v in target.data.vertices:
            if sum(g.weight for g in v.groups) > .001:
                continue
            _, index, _ = tree.find(target.matrix_world @ v.co)
            groups = source.data.vertices[index].groups
            for g in groups:
                name = source.vertex_groups[g.group].name
                group = target.vertex_groups.get(name) or target.vertex_groups.new(name=name)
                group.add([v.index], g.weight, 'REPLACE')
            count += 1
        return count

    def update(self):
        self.bpy.context.view_layer.update()

    def rotate(self, name, axis, degrees):
        if abs(degrees) < 1e-7:
            return
        b = self.r.pose.bones[name]
        w = self.r.matrix_world @ b.matrix
        b.matrix = self.r.matrix_world.inverted() @ self.M.Translation(w.translation) @ self.M.Rotation(math.radians(degrees), 4, axis) @ self.M.Translation(-w.translation) @ w
        self.update()

    def limb(self, upper, lower, end, target, pole, rotation=None):
        from model_operations import apply_operations
        r, V = self.r, self.V
        a, b = r.pose.bones[upper], r.pose.bones[lower]
        origin = r.matrix_world @ a.head
        target = V(target)
        delta = target-origin
        la = (r.matrix_world.to_3x3() @ (a.tail-a.head)).length
        lb = (r.matrix_world.to_3x3() @ (b.tail-b.head)).length
        distance = delta.length
        safe = min(la+lb-.002, max(abs(la-lb)+.002, distance))
        if abs(safe-distance) > .0001:
            self.errors.append({'bone': upper, 'reach_clamp': abs(safe-distance)})
        target = origin + delta.normalized()*safe
        axis = (target-origin).normalized()
        bend = V(pole)-origin
        bend -= axis*bend.dot(axis)
        along = (la*la-lb*lb+safe*safe)/(2*safe)
        elbow = origin+axis*along+bend.normalized()*math.sqrt(max(0,la*la-along*along))
        for name, direction in [(upper,elbow-origin),(lower,target-elbow)]:
            apply_operations([{'op':'aim_bone','object':r.name,'bone':name,'world_direction':list(direction)}])
            self.update()
        if rotation is not None:
            bone = r.pose.bones[end]
            w = r.matrix_world @ bone.matrix
            bone.matrix = r.matrix_world.inverted() @ self.M.LocRotScale(w.translation, rotation, w.to_scale())
            self.update()

    def pose(self, p):
        for n, m in self.base.items():
            self.r.pose.bones[n].matrix_basis = m
        self.update()
        pelvis = self.r.pose.bones['Pelvis']
        world = self.r.matrix_world @ pelvis.matrix
        world.translation += self.V((p.get('px',0), p.get('py',0), p.get('pz',-.08)))
        pelvis.matrix = self.r.matrix_world.inverted() @ world
        self.update()
        for name,axis,key in [('Pelvis','Z','hip_yaw'),('Waist','Y','lean'),('Waist','X','sway'),('Chest','Z','yaw')]:
            self.rotate(name,axis,p.get(key,0))
        for side,sign in [('L',1),('R',-1)]:
            foot = self.feet[side]
            target = foot.translation + self.V((p.get('foot_x_'+side,0),p.get('foot_y_'+side,0),p.get('foot_z_'+side,0)))
            self.limb('Thigh.'+side,'Shin.'+side,'Foot.'+side,target,(1.2,sign*.42,1),foot.to_quaternion())
            self.rotate('ShoulderWingLower.'+side,'X',sign*p.get('shoulder_'+side,0))
            self.rotate('UpperArm.'+side,'X',sign*p.get('spread_'+side,-15))
            self.rotate('UpperArm.'+side,'Y',-p.get('arm_'+side,0))
            self.rotate('UpperArm.'+side,'Z',p.get('arm_yaw_'+side,0))
            from mathutils import Quaternion
            forearm=self.r.pose.bones['Forearm.'+side]
            forearm.rotation_mode='QUATERNION'
            forearm.rotation_quaternion=Quaternion(self.hinge_axes[side],math.radians(p.get('elbow_'+side,8)))
            self.update()
            if side=='L' and p.get('sword_stowed',1)==0:
                forearm.rotation_quaternion=forearm.rotation_quaternion @ Quaternion((0,1,0),math.radians(-65))
                self.update()
            # 손목 방향을 독립적으로 강제하지 않고 전완에서 자연스럽게 잇는다.
            self.r.pose.bones['WristSwivel.'+side].matrix_basis = self.M.Identity(4)
            self.r.pose.bones['Hand.'+side].matrix_basis = self.M.Identity(4)
        self.update()
        if p.get('aim',0) > 0:
            hand = self.r.matrix_world @ self.r.pose.bones['Hand.R'].head
            target = hand.lerp(self.V((p.get('aim_x',.32),p.get('aim_y',.10),p.get('aim_z',2.20))),p['aim'])
            rotation=self.M(((0,1,0),(0,0,-1),(-1,0,0))).to_quaternion()
            current=(self.r.matrix_world@self.r.pose.bones['Hand.R'].matrix).to_quaternion()
            self.limb('UpperArm.R','Forearm.R','Hand.R',target,(-.4,-.75,2.15),current.slerp(rotation,p['aim']))
        control = self.bpy.data.objects[self.cfg['control']]
        for weapon in ['sword','gun']:
            control[weapon+'_stowed'] = p.get(weapon+'_stowed',1)
        control.update_tag(); self.update()
        if p.get('support',0) > 0:
            gun = self.bpy.data.objects['Gun']
            point = gun.matrix_world @ self.support_local
            hand = self.r.pose.bones['Hand.L']
            rotation=self.M(((0,1,0),(0,0,1),(1,0,0))).to_quaternion()
            target = point - rotation @ (self.V((.03,.60,-.10))*.52)
            old = self.r.matrix_world @ hand.head
            target = old.lerp(target,p['support'])
            current=(self.r.matrix_world@hand.matrix).to_quaternion()
            self.limb('UpperArm.L','Forearm.L','Hand.L',target,(-.3,.8,2.1),current.slerp(rotation,p['support']))
        for side, amount in [('L',1-p.get('sword_stowed',1)),('R',1-p.get('gun_stowed',1))]:
            if side=='L': amount=max(amount,p.get('support',0))
            for finger in ['Index','Middle','Ring','Little']:
                for part,angle in [('01',25),('02',65),('03',45)]:
                    b=self.r.pose.bones.get(finger+part+'.'+side)
                    if b:
                        b.rotation_mode='QUATERNION'
                        b.rotation_quaternion=self.M.Rotation(math.radians(angle*amount),4,'Z').to_quaternion()
            if amount>0 and self.cfg.get('finger_grip'):
                from mathutils import Quaternion
                for name,rows in self.cfg['finger_grip'].items():
                    if not name.endswith('.'+side):
                        continue
                    b=self.r.pose.bones[name]
                    b.rotation_mode='QUATERNION'
                    b.rotation_quaternion=Quaternion().slerp(self.M(rows).to_quaternion(),amount)
        self.update()

    def bind(self, poses):
        from model_geometry import set_world_matrix_from_parent_frame
        for weapon,side,preset in [('Sword','L','sword_idle'),('Gun','R','gun_aim')]:
            self.pose(poses[preset] | {'support':0})
            hand = self.r.matrix_world @ self.r.pose.bones['Hand.'+side].matrix
            palm = hand @ self.V((.03 if side=='L' else -.03,.60,-.10))
            mesh = self.bpy.data.objects[weapon+'_Grip']
            center = sum((v.co for v in mesh.data.vertices),self.V())/len(mesh.data.vertices)
            root = self.bpy.data.objects[weapon]
            center = root.matrix_world.inverted() @ mesh.matrix_world @ center
            rotation = self.M.Identity(4) if weapon=='Gun' else hand.to_quaternion().to_matrix().to_4x4() @ self.M(((0,0,1,0),(0,1,0,0),(-1,0,0,0),(0,0,0,1)))
            world = self.M.Translation(palm) @ rotation @ self.M.Translation(-center)
            anchor=self.bpy.data.objects[weapon+'_HandAnchor']
            set_world_matrix_from_parent_frame(anchor,world);self.update()
            self.grip_bind[anchor.name]=[list(row) for row in anchor.matrix_basis]
        mesh=self.bpy.data.objects['Gun_ForeGrip'];root=self.bpy.data.objects['Gun']
        self.support_local=root.matrix_world.inverted() @ mesh.matrix_world @ (sum((v.co for v in mesh.data.vertices),self.V())/len(mesh.data.vertices))


def compile_motion(config_path, only=None):
    import bpy
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'))
    source=Path(cfg['source'])
    assert hashlib.sha256(source.read_bytes()).hexdigest()==cfg['source_sha256']
    from model_review import require_stage_approval
    require_stage_approval(source)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    solver=BlockingRig(cfg)
    solver.bind(cfg['poses'])
    poses=cfg['poses']; clips=[]; frame=1; audit=[]
    previous = {}
    if only:
        previous = {c['name']:c for c in json.loads(Path(config_path).with_name('motions.json').read_text(encoding='utf-8'))['clips']}
    for spec in cfg['clips']:
        if only and spec['name'] not in only:
            clip=previous[spec['name']]
            for sample in clip['samples']:
                sample['objects']=solver.grip_bind
            clips.append(clip)
            frame=clip['samples'][-1]['frame']+3
            audit.append({'clip':spec['name'],'retained_from_previous':True})
            continue
        samples=[]; solver.errors=[]
        keys=[(k[0],poses[k[1]] | (k[2] if len(k)>2 else {})) for k in spec.get('keys',[])]
        for i in range(spec['frames']):
            p=sample_keys(keys,i) if keys else poses[spec['pose']].copy()
            if spec.get('gait'):
                speed=spec.get('speed',0)
                if spec['gait']=='accelerate':speed=i/(spec['frames']-1)
                if spec['gait']=='decelerate':speed=1-i/(spec['frames']-1)
                phase=2*math.pi*i/(spec.get('period',spec['frames']))
                direction=spec.get('direction',[1,0])
                stride=.24+.20*speed; lift=.12+.15*speed
                p.update(pz=-.14+.045*math.cos(phase*2),py=.065*math.sin(phase),lean=8+10*speed,yaw=12*math.sin(phase),sway=3*math.sin(phase))
                for side,offset,sign in [('L',0,1),('R',math.pi,-1)]:
                    wave=math.cos(phase+offset)
                    p['foot_x_'+side]=stride*wave*direction[0]
                    p['foot_y_'+side]=stride*wave*direction[1]
                    p['foot_z_'+side]=lift*max(0,-math.sin(phase+offset))
                    p['arm_'+side]=-(28+28*speed)*wave
                    p['elbow_'+side]=18+35*speed+8*math.sin(phase+offset)
                    p['shoulder_'+side]=3+5*speed
                if spec['gait']=='dash':
                    burst=math.sin(math.pi*i/(spec['frames']-1))
                    p.update(lean=15+23*burst,pz=-.18,arm_L=-35,arm_R=-45,elbow_L=10,elbow_R=10)
            elif not keys:
                breath=math.sin(i/spec['frames']*2*math.pi)
                p['pz']=p.get('pz',-.08)+.018*breath
                p['yaw']=p.get('yaw',0)+2*breath
            solver.pose(p)
            samples.append({'frame':frame,'bones':{b.name:[list(row) for row in b.matrix_basis] for b in solver.r.pose.bones},'objects':solver.grip_bind,'properties':{cfg['control']:{w+'_stowed':p.get(w+'_stowed',1) for w in ['sword','gun']}}})
            frame+=1
        clips.append({k:spec[k] for k in ['name','label','loop']} | {'samples':samples,'events':spec.get('events',[])})
        wrist_bend=max(math.degrees(math.acos(max(-1,min(1,s['bones'][n][1][1])))) for s in samples for n in ['Hand.L','Hand.R'])
        audit.append({'clip':spec['name'],'reach_clamps':solver.errors,'max_hand_bend_degrees':wrist_bend})
        frame+=2
    # 검사에서 보정한 웨이트를 별도 제작 소스로 저장한다.
    output=Path(cfg['output']);output.mkdir(parents=True,exist_ok=True)
    solver.pose(poses['neutral'])
    prepared=output/'prepared.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(prepared))
    manifest={'version':1,'asset_id':cfg['asset_id'],'source':str(prepared),'source_sha256':hashlib.sha256(prepared.read_bytes()).hexdigest(),'fps':12,'rig':cfg['rig'],'root':cfg['root'],'clips':clips,'render_settings':{'ortho_scale':5.4,'camera_target':[0,0,1.5]}}
    path=Path(config_path).with_name('motions.json');path.write_text(json.dumps(manifest),encoding='utf-8')
    (output/'audit.json').write_text(json.dumps({'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==cfg['source_sha256'],'weight_repair_enabled':cfg.get('weight_repair', {}).get('enabled', False),'unbound_vertices_repaired':solver.skirt_fixed,'clips':audit},indent=2),encoding='utf-8')
    from animation_pipeline import bake
    destination=Path(cfg['destination'])
    if destination.exists():
        import tempfile
        staging=Path(tempfile.mkdtemp(prefix='motion_bake_',dir=output))/'bake'
        bake(path,staging)
        for item in staging.rglob('*'):
            if item.is_file():
                target=destination/item.relative_to(staging)
                target.parent.mkdir(parents=True,exist_ok=True)
                item.replace(target)
    else:
        bake(path,destination)
    return {'clips':len(clips),'frames':sum(len(c['samples']) for c in clips)}


def render_clip(config_path, clip_name):
    import bpy
    from mathutils import Vector
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'))
    destination=Path(cfg['destination'])
    bpy.ops.wm.open_mainfile(filepath=str(destination/'animations.blend'))
    index=json.loads((destination/'clips.json').read_text(encoding='utf-8'))
    clip=next(c for c in index['clips'] if c['name']==clip_name)
    s=bpy.context.scene
    # 최종 형상과 다른 간이 메시를 기본 검토 근거로 사용하지 않는다.
    if cfg.get('simplified_preview', False):
        for o in bpy.data.objects:
            for m in o.modifiers:
                if m.type in {'BEVEL','BOOLEAN','WEIGHTED_NORMAL','SUBSURF','MULTIRES'}:m.show_render=False
    s.render.engine='BLENDER_WORKBENCH';s.render.resolution_x=s.render.resolution_y=cfg.get('preview_size',320);s.render.resolution_percentage=100
    s.render.image_settings.media_type='IMAGE';s.render.image_settings.file_format='PNG';s.render.film_transparent=False
    s.display.shading.light='STUDIO';s.display.shading.color_type='MATERIAL';s.display.shading.show_cavity=True
    s.display.shading.background_type='WORLD';s.world.color=(.045,.055,.075)
    s.camera.data.type='ORTHO';s.camera.data.ortho_scale=5.4
    out=Path(cfg['output'])/'frames'/clip_name;out.mkdir(parents=True,exist_ok=True)
    for view,position in cfg['views'].items():
        s.camera.location=position;s.camera.rotation_euler=(Vector((0,0,1.5))-s.camera.location).to_track_quat('-Z','Y').to_euler()
        for i,frame in enumerate(clip['frames']):
            s.frame_set(frame)
            s.render.filepath=str(out/f'{view}_{i:03}.png')
            bpy.ops.render.render(write_still=True)
    return {'clip':clip_name,'frames':len(clip['frames']),'views':len(cfg['views'])}
