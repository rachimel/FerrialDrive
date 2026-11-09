"""현재 리그를 수정하지 않고 관절별 진단 동작을 영상으로 출력한다."""
import hashlib
import json
import math
from pathlib import Path


def render(config_path, motion):
    import bpy
    from mathutils import Matrix, Vector
    from model_operations import apply_operations
    from animation_pipeline import curves

    cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
    source = Path(cfg['source'])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != cfg['source_sha256']:
        raise ValueError('진단 원본 해시 불일치')
    output = Path(cfg['output'])
    output.mkdir(parents=True, exist_ok=True)
    video = output / (motion+'.mp4')
    if video.exists():
        raise FileExistsError(video)
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    rig = bpy.data.objects[cfg['rig']]
    scene.frame_set(cfg.get('base_frame', 1))
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data.action = None
            for track in obj.animation_data.nla_tracks:
                track.mute = True
        for modifier in obj.modifiers:
            if modifier.type in {'BEVEL', 'WEIGHTED_NORMAL', 'BOOLEAN', 'SUBSURF', 'MULTIRES'}:
                modifier.show_viewport = False
                modifier.show_render = False
    # 무기 수납과 이완된 팔을 공통 출발 자세로 사용한다.
    for name in cfg['relaxed_bones']:
        rig.pose.bones[name].matrix_basis = Matrix.Identity(4)
    for name, values in cfg.get('properties', {}).items():
        for key, value in values.items():
            bpy.data.objects[name][key] = value
        bpy.data.objects[name].update_tag()
    bpy.context.view_layer.update()
    base = {b.name: b.matrix_basis.copy() for b in rig.pose.bones}
    feet = {leg['end']: rig.matrix_world@rig.pose.bones[leg['end']].matrix for leg in cfg['legs']}
    max_foot_error = 0.0
    view_frames = cfg['view_frames']

    def rotate_world(name, radians):
        bone = rig.pose.bones[name]
        world = rig.matrix_world@bone.matrix
        bone.matrix = rig.matrix_world.inverted()@Matrix.Translation(world.translation)@Matrix.Rotation(radians, 4, 'Y')@Matrix.Translation(-world.translation)@world
        bpy.context.view_layer.update()

    for frame in range(1, view_frames*2+1):
        for name, matrix in base.items():
            rig.pose.bones[name].matrix_basis = matrix
        bpy.context.view_layer.update()
        phase = ((frame-1) % view_frames)/(view_frames-1)
        if phase < .12 or phase > .9:
            amount = 0.0
        elif phase < .42:
            amount = (phase-.12)/.30
        elif phase < .58:
            amount = 1.0
        else:
            amount = 1-(phase-.58)/.32
        amount = amount*amount*(3-2*amount)
        if motion == 'arm_raise':
            for name in cfg['upper_arms']:
                rotate_world(name, math.radians(-cfg['arm_degrees']*amount))
        elif motion == 'knee_bend':
            rotate_world(cfg['knee_bone'], math.radians(cfg['knee_degrees']*amount))
        elif motion == 'pelvis_lower':
            pelvis = rig.pose.bones[cfg['pelvis']]
            world = rig.matrix_world@pelvis.matrix
            world.translation.z -= cfg['pelvis_drop']*amount
            pelvis.matrix = rig.matrix_world.inverted()@world
            bpy.context.view_layer.update()
            for leg in cfg['legs']:
                target = feet[leg['end']]
                apply_operations([dict(op='pose_limb', object=rig.name,
                    upper=leg['upper'], lower=leg['lower'], end=leg['end'],
                    target_world=list(target.translation), bend_world=leg['pole'],
                    end_rotation_world=list(target.to_quaternion()))])
                max_foot_error = max(max_foot_error,
                    (rig.matrix_world@rig.pose.bones[leg['end']].head-target.translation).length)
        else:
            raise ValueError(motion)
        for bone in rig.pose.bones:
            bone.rotation_mode = 'QUATERNION'
            for channel in ('location', 'rotation_quaternion', 'scale'):
                bone.keyframe_insert(channel, frame=frame, group=bone.name)
    for curve in curves(rig.animation_data.action):
        for point in curve.keyframe_points:
            point.interpolation = 'CONSTANT'
    scene.frame_start, scene.frame_end = 1, view_frames*2
    scene.render.fps, scene.render.fps_base = cfg['fps'], 1
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = cfg['size']
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.background_type = 'WORLD'
    scene.world.color = (.06, .07, .09)
    scene.display.shading.show_cavity = True
    camera = scene.camera
    camera.data.type, camera.data.ortho_scale = 'ORTHO', cfg['ortho_scale']
    for frame, position in [(1, cfg['front']), (view_frames, cfg['front']),
                            (view_frames+1, cfg['side']), (view_frames*2, cfg['side'])]:
        camera.location = position
        camera.rotation_euler = (Vector(cfg['target'])-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.keyframe_insert('location', frame=frame)
        camera.keyframe_insert('rotation_euler', frame=frame)
    for curve in curves(camera.animation_data.action):
        for point in curve.keyframe_points:
            point.interpolation = 'CONSTANT'
    if hasattr(scene.render.image_settings, 'media_type'):
        scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    for label, frame in [('front', int(view_frames*.5)), ('side', int(view_frames*1.5))]:
        scene.frame_set(frame)
        scene.render.filepath = str(output/(motion+'_'+label+'.png'))
        bpy.ops.render.render(write_still=True)
    if hasattr(scene.render.image_settings, 'media_type'):
        scene.render.image_settings.media_type = 'VIDEO'
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
    scene.render.filepath = str(video)
    bpy.ops.render.render(animation=True)
    result = {'motion': motion, 'source': str(source), 'source_sha256': digest,
              'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest() == digest,
              'fps': cfg['fps'], 'frames': view_frames*2,
              'seconds': view_frames*2/cfg['fps'], 'front_then_side': True,
              'foot_target_error': max_foot_error if motion == 'pelvis_lower' else None,
              'rig_modified': False, 'new_ik_controls': False,
              'video': str(video), 'bytes': video.stat().st_size if video.exists() else 0}
    (output/(motion+'.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
