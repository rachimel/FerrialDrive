"""Current portrait asset builder: painted textures and converging eyelids.

Blender previews project the eye texture onto the moving aperture. Cubism
exports use the same aperture as a clipping drawable over a fixed eye texture,
so the iris is occluded by the lid instead of being squashed or faded out.
"""
from pathlib import Path
import json
import shutil
import bpy
import numpy as np

ROOT=Path(r'C:\Z_Workspace\01_Projects\01_ActivePython\Iso2D')
OUT=ROOT/'output/capability_test/live2d_refined'
OUT.mkdir(parents=True,exist_ok=True);(OUT/'textures').mkdir(exist_ok=True)
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
for obj in list(bpy.context.scene.objects):bpy.data.objects.remove(obj,do_unlink=True)
for mat in list(bpy.data.materials):
    if mat.users==0:bpy.data.materials.remove(mat)
neutral=bpy.data.images.load(str(ROOT/'output/capability_test/character-cutout-generated.png'),check_existing=False)
smile=bpy.data.images.load(str(ROOT/'output/capability_test/live2d_v2/smile-generated.png'),check_existing=False)
closed=bpy.data.images.load(str(OUT/'inputs/closed-smile-generated.png'),check_existing=False)
W,H=neutral.size
assert tuple(smile.size)==(W,H)
assert tuple(closed.size)==(W,H)
shutil.copyfile(ROOT/'output/capability_test/character-clean-face-generated.png',OUT/'textures/body.png')
body=bpy.data.images.load(str(OUT/'textures/body.png'),check_existing=False)
arrays={n:np.array(im.pixels[:],dtype=np.float32).reshape(H,W,4) for n,im in [('neutral',neutral),('smile',smile),('closed',closed),('clean',body)]}
images=[body];textures=['textures/body.png'];records=[];KEYS=np.linspace(0,1,33).tolist()

def smooth(t):
    t=np.clip(t,0,1);return t*t*(3-2*t)

def image_from_array(name,array):
    h,w=array.shape[:2];im=bpy.data.images.new(name,width=w,height=h,alpha=True)
    im.colorspace_settings.name=neutral.colorspace_settings.name
    im.pixels.foreach_set(array.astype(np.float32).ravel())
    im.filepath_raw=str(OUT/'textures'/f'{name}.png');im.file_format='PNG';im.save()
    images.append(im);textures.append(f'textures/{name}.png');return len(images)-1

def crop(name,rect,state,mode='feather',curve=None,subtract_alpha=None,lash_span=None):
    x0,y0,x1,y1=rect;patch=arrays[state][H-y1:H-y0,x0:x1].copy()
    h,w=patch.shape[:2];yy,xx=np.mgrid[:h,:w]
    x=xx+x0;y=y1-1-yy
    edge=np.minimum.reduce([xx,yy,w-1-xx,h-1-yy]).astype(float)
    if mode=='opaque':patch[:,:,3]=1
    elif mode=='eye':
        upper,lower,_=curve(x,0)
        # Static feather at the neutral artwork boundary; the moving
        # Cubism mask supplies actual eyelid occlusion during animation.
        patch[:,:,3]=smooth(np.minimum(y-upper,lower-y)/1.35)
        if subtract_alpha is not None:patch[:,:,3]*=1-subtract_alpha
    else:
        patch[:,:,3]*=smooth(edge/2)
        if mode in ('lash','lower-lash'):
            # Retain actual painted lashes and their anti-aliasing, not skin.
            darkness=smooth((.82-np.max(patch[:,:,:3],axis=2))/.35)
            width=4 if mode=='lower-lash' else 5
            band=smooth((width-np.abs(y-curve(x)))/2)
            patch[:,:,3]*=darkness*band
            if lash_span:patch[:,:,3]*=smooth(np.minimum(x-lash_span[0],lash_span[1]-x)/1.5)
        elif mode=='lip':
            luma=patch[:,:,0]*.3+patch[:,:,1]*.6+patch[:,:,2]*.1
            patch[:,:,3]*=smooth((.9-luma)/.22)*smooth((5-np.abs(y-curve(x)))/2)
    return image_from_array(name,patch)

arm=bpy.data.armatures.new('Geometry portrait skeleton')
rig=bpy.data.objects.new('PORTRAIT RIGGED | ParamSmile',arm);bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
b=arm.edit_bones.new('body');b.head=(0,-3,0);b.tail=(0,0,0)
b=arm.edit_bones.new('face');b.head=(0,2.1,0);b.tail=(0,3.2,0);b.parent=arm.edit_bones['body']
bpy.ops.object.mode_set(mode='OBJECT');rig.show_in_front=True
rig['ParamSmile']=0.0;rig['transition']='Smoothstep geometry; upper/lower lashes converge. Only the closed-mouth lip line fades during initial opening.'
rig.id_properties_ui('ParamSmile').update(min=0.,max=1.)

def driver(fcurve,expr):
    if len(expr)>255:raise ValueError('Blender driver expression exceeds its 255-character limit')
    d=fcurve.driver;v=d.variables.new();v.name='s';v.type='SINGLE_PROP'
    v.targets[0].id=rig;v.targets[0].data_path='["ParamSmile"]';d.expression=expr

def material(name,texture,projection=None,opacities=None):
    m=bpy.data.materials.new(name);m.use_nodes=True;m.surface_render_method='DITHERED'
    ns=m.node_tree.nodes;ns.clear();ls=m.node_tree.links
    tex=ns.new('ShaderNodeTexImage');tex.image=images[texture]
    emission=ns.new('ShaderNodeEmission');transparent=ns.new('ShaderNodeBsdfTransparent');mix=ns.new('ShaderNodeMixShader')
    out=ns.new('ShaderNodeOutputMaterial')
    ls.new(tex.outputs['Color'],emission.inputs['Color']);ls.new(tex.outputs['Alpha'],mix.inputs[0])
    if opacities is not None:
        gain=ns.new('ShaderNodeValue');gain.name='Closed lip visibility';gain.outputs[0].default_value=opacities[0]
        terms=[str(opacities[0])]
        for i in range(1,len(KEYS)):
            delta=opacities[i]-opacities[i-1]
            a,b=KEYS[i-1:i+1]
            if delta:terms.append(f'{delta:.9g}*min(max({1/(b-a):g}*s-{a/(b-a):g},0),1)')
        driver(gain.outputs[0].driver_add('default_value'),'min(max('+ '+'.join(terms)+',0),1)')
        alpha=ns.new('ShaderNodeMath');alpha.operation='MULTIPLY'
        ls.new(tex.outputs['Alpha'],alpha.inputs[0]);ls.new(gain.outputs[0],alpha.inputs[1]);ls.new(alpha.outputs[0],mix.inputs[0])
    ls.new(transparent.outputs[0],mix.inputs[1]);ls.new(emission.outputs[0],mix.inputs[2]);ls.new(mix.outputs[0],out.inputs[0])
    if projection:
        # Sample a stationary eye by world position while its aperture moves.
        x0,y0,x1,y1=projection
        geo=ns.new('ShaderNodeNewGeometry');sep=ns.new('ShaderNodeSeparateXYZ');combine=ns.new('ShaderNodeCombineXYZ')
        ls.new(geo.outputs['Position'],sep.inputs[0])
        for axis,scale,offset in [('X',200/(x1-x0),(W/2-x0)/(x1-x0)),('Y',200/(y1-y0),(y1-H/2)/(y1-y0))]:
            mul=ns.new('ShaderNodeMath');mul.operation='MULTIPLY_ADD';mul.inputs[1].default_value=scale;mul.inputs[2].default_value=offset
            ls.new(sep.outputs[axis],mul.inputs[0]);ls.new(mul.outputs[0],combine.inputs[axis])
        ls.new(combine.outputs[0],tex.inputs['Vector'])
    return m

def grid(rect,columns=24,rows=8):
    x0,y0,x1,y1=rect;uv=[(i/columns,j/rows) for j in range(rows+1) for i in range(columns+1)]
    xy=np.array([(x0+u*(x1-x0),y1-v*(y1-y0)) for u,v in uv],dtype=float)
    tri=[]
    for j in range(rows):
        for i in range(columns):
            a=j*(columns+1)+i;c=a+columns+1;tri.extend([a,a+1,c+1,a,c+1,c])
    return xy,uv,tri

def make(name,xy,uv,tri,texture,order,deform=None,masks=None,projection=None,export_override=None,hide=False,opacity=None):
    forms=[deform(xy.copy(),s) if deform else xy.copy() for s in KEYS]
    alphas=[float(opacity(s)) if opacity else (0. if hide else 1.) for s in KEYS]
    world=lambda points:[((x-W/2)/200,(H/2-y)/200,order*.001) for x,y in points]
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(world(forms[0]),[],[tri[i:i+3] for i in range(0,len(tri),3)]);mesh.update()
    layer=mesh.uv_layers.new()
    for poly in mesh.polygons:
        for li in poly.loop_indices:layer.data[li].uv=uv[mesh.loops[li].vertex_index]
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj.parent=rig
    obj.data.materials.append(material(name,texture,projection,alphas if opacity else None));obj.hide_render=hide
    group=obj.vertex_groups.new(name='body' if name=='Body' else 'face');group.add(list(range(len(xy))),1,'REPLACE')
    mod=obj.modifiers.new('Portrait bones','ARMATURE');mod.object=rig
    if deform:
        obj.shape_key_add(name='Basis');previous=forms[0]
        for i,points in enumerate(forms[1:],1):
            key=obj.shape_key_add(name=f'Smile {KEYS[i]:.2f}')
            for vertex,co in zip(key.data,world(forms[0]+points-previous)):vertex.co=co
            a,b=KEYS[i-1:i+1];driver(key.driver_add('value'),f'min(max((s-{a})/{b-a},0),1)');previous=points
    cv=lambda points:[float(q) for x,y in points for q in (x-W/2,H/2-y)]
    rec={'id':name,'texture':texture,'order':order,'neutral':cv(forms[0]),'smile':cv(forms[-1]),'forms':[cv(f) for f in forms],'uv':[v for pair in uv for v in pair],'triangles':tri,'animated':bool(deform or opacity),'opacities':alphas,'masks':masks or [],'render_role':'clip-helper' if hide else 'artwork'}
    if export_override:rec.update(export_override)
    records.append(rec);return obj

make('Body',*grid((0,0,W,H),1,1),0,0)

for side,cx,cy,xmin,xmax,up,down,level,eye_rect,lash_rect,brow_rect in [
    ('L',509.,217.,488.,532.,12.,10.,216.,(480,198,540,242),(483,207,540,229),(477,185,535,202)),
    ('R',577.,233.,553.,601.,12.,11.,237.,(546,213,610,260),(550,228,607,250),(550,198,605,216)),
]:
    def curves(x,s,cx=cx,cy=cy,xmin=xmin,xmax=xmax,up=up,down=down,level=level):
        s=float(smooth(s))
        t=np.clip((x-(xmin+xmax)/2)/((xmax-xmin)/2),-1,1)
        bulge=np.sqrt(np.maximum(0,1-t*t))
        baseline=cy+.24*(x-cx)
        happy=level+.22*(x-cx)+.004*(x-cx)**2
        return (1-s)*(baseline-up*bulge)+s*happy,(1-s)*(baseline+down*bulge)+s*happy,happy
    xs=np.linspace(xmin,xmax,49)
    aperture=np.array([(x,float(y[0])) for x in xs for y in curves(np.array([x]),0)[:2]],dtype=float)
    x0,y0,x1,y1=eye_rect
    uv=[((x-x0)/(x1-x0),(y1-y)/(y1-y0)) for x,y in aperture];tri=[]
    for i in range(len(xs)-1):a=i*2;tri.extend([a,a+1,a+3,a,a+3,a+2])
    def aperture_form(points,s,curves=curves):
        x=points[::2,0];top,bottom,_=curves(x,s)
        points[::2,1]=top;points[1::2,1]=bottom;return points
    mask_name='EyeAperture'+side
    mask_texture=crop('eye-skin-mask-'+side,eye_rect,'clean','opaque')
    make(mask_name,aperture,uv,tri,mask_texture,10,deform=aperture_form,hide=True)
    lower_curve=lambda x,curves=curves:curves(x,0)[1]
    lower_tex=crop('painted-lower-lash-'+side,eye_rect,'neutral','lower-lash',lower_curve,lash_span=(xmin+1,cx+10))
    lower_pixels=np.array(images[lower_tex].pixels[:]).reshape(y1-y0,x1-x0,4)
    texture=crop('eye-interior-'+side,eye_rect,'neutral','eye',curves,subtract_alpha=lower_pixels[:,:,3])
    fixed_xy,fixed_uv,fixed_tri=grid(eye_rect,1,1)
    cv=lambda points:[float(q) for x,y in points for q in (x-W/2,H/2-y)]
    # Cubism: fixed iris/sclera texture clipped by EyeAperture. Blender:
    # the same stationary texture projected onto that aperture geometry.
    override={'neutral':cv(fixed_xy),'smile':cv(fixed_xy),'forms':[cv(fixed_xy)]*len(KEYS),'uv':[v for pair in fixed_uv for v in pair],'triangles':fixed_tri,'animated':False,'preview_projection_mask':mask_name}
    make('EyeInterior'+side,aperture,uv,tri,texture,11,deform=aperture_form,masks=[mask_name],projection=eye_rect,export_override=override)
    closed_curve=lambda x,curves=curves:curves(x,1)[2]
    lash_tex=crop('painted-upper-lash-'+side,lash_rect,'smile','lash',closed_curve)
    def measured_center(texture,rect):
        x0,y0,x1,y1=rect;a=np.array(images[texture].pixels[:]).reshape(y1-y0,x1-x0,4)[:,:,3]
        mass=a.sum(axis=0);valid=np.where(mass>.02)[0]
        center=(a*(y1-1-np.arange(y1-y0))[:,None]).sum(axis=0)/np.maximum(mass,1e-9)
        return lambda x:np.interp(x,x0+valid,center[valid])
    lower_center=measured_center(lower_tex,eye_rect)
    upper_center=measured_center(lash_tex,lash_rect)
    def lower_form(points,s,curves=curves,center=lower_center):
        x=points[:,0];happy=curves(x,1)[2]
        points[:,1]+=float(smooth(s))*(happy-center(x));return points
    make('LowerLid'+side,*grid(eye_rect,x1-x0,8),lower_tex,12,deform=lower_form)
    records[-1]['source_rect']=eye_rect
    def lash_form(points,s,curves=curves,center=upper_center):
        upper,_,_=curves(points[:,0],s);points[:,1]+=upper-center(points[:,0]);return points
    make('UpperLid'+side,*grid(lash_rect,40,6),lash_tex,13,deform=lash_form)
    records[-1]['source_rect']=lash_rect
    brow_tex=crop('painted-brow-'+side,brow_rect,'neutral')
    make('Brow'+side,*grid(brow_rect,12,4),brow_tex,14)

mouth_rect=(520,257,552,276)
mouth_global=(527,257,559,276)
def closed_curve(x):
    t=np.clip((x-535)/12,-1,1)
    return 263+3*np.sqrt(np.maximum(0,1-t*t))
def open_curves(x):
    t=np.clip((x-535)/12,-1,1);arc=np.sqrt(np.maximum(0,1-t*t))
    return 261+.18*(x-535)+arc,261+.18*(x-535)+10*arc
closed_tex=crop('painted-closed-smile',mouth_rect,'closed','lip',closed_curve)
lip_pixels=np.array(images[closed_tex].pixels[:],dtype=float).reshape(mouth_rect[3]-mouth_rect[1],mouth_rect[2]-mouth_rect[0],4)
lip_alpha=lip_pixels[:,:,3]
lip_mass=lip_alpha.sum(axis=0)
lip_valid=np.where(lip_mass>.02)[0]
lip_rows=mouth_rect[3]-1-np.arange(lip_pixels.shape[0])
lip_centers=(lip_alpha*lip_rows[:,None]).sum(axis=0)/np.maximum(lip_mass,1e-9)
def measured_lip(x):
    # Use the painted line's actual center per column, not the approximate
    # guide curve, otherwise a corner floats above the opened mouth.
    return np.interp(x,mouth_rect[0]+lip_valid,lip_centers[lip_valid])
def lip_form(points,s):
    x=points[:,0].copy();y=points[:,1].copy();c=measured_lip(x)
    smile=float(smooth(s/.5));opening=float(smooth((s-.5)/.5))
    points[:,0]=542+(x-535)*(.28+.72*smile)
    line=(1-smile)*265+smile*c
    upper,_=open_curves(x)
    points[:,1]=(1-opening)*line+opening*upper+(y-c)*(.35+.65*smile)
    return points
make('MouthUpperLip',*grid(mouth_rect,32,10),closed_tex,33,deform=lip_form,opacity=lambda s:1-float(smooth((s-.5)/.15)))

xs=np.linspace(523,547,49)
opening_xy=np.array([(x+7,float(closed_curve(np.array([x]))[0])) for x in xs for _ in range(2)])
mouth_uv=[((x-mouth_global[0])/(mouth_global[2]-mouth_global[0]),(mouth_global[3]-y)/(mouth_global[3]-mouth_global[1])) for x,y in opening_xy]
mouth_tri=[]
for i in range(len(xs)-1):a=i*2;mouth_tri.extend([a,a+1,a+3,a,a+3,a+2])
def opening_form(points,s):
    x=points[::2,0]-7;c=closed_curve(x);upper,lower=open_curves(x)
    opening=float(smooth((s-.5)/.5))
    points[::2,1]=(1-opening)*c+opening*upper
    points[1::2,1]=(1-opening)*c+opening*lower
    return points
skin_tex=crop('mouth-skin-mask',mouth_global,'clean','opaque')
make('MouthOpening',opening_xy,mouth_uv,mouth_tri,skin_tex,30,deform=opening_form,hide=True)
mouth_tex=crop('painted-open-mouth',mouth_rect,'smile','opaque')
fixed_xy,fixed_uv,fixed_tri=grid(mouth_global,1,1)
cv=lambda points:[float(q) for x,y in points for q in (x-W/2,H/2-y)]
override={'neutral':cv(fixed_xy),'smile':cv(fixed_xy),'forms':[cv(fixed_xy)]*len(KEYS),'uv':[v for pair in fixed_uv for v in pair],'triangles':fixed_tri,'animated':False,'preview_projection_mask':'MouthOpening'}
make('MouthInterior',opening_xy,mouth_uv,mouth_tri,mouth_tex,31,deform=opening_form,masks=['MouthOpening'],projection=mouth_global,export_override=override)

for frame,value in [(1,0.),(31,.25),(61,.5),(91,.75),(121,1.),(181,0.)]:
    rig['ParamSmile']=float(value);rig.keyframe_insert(data_path='["ParamSmile"]',frame=frame)
for layer in rig.animation_data.action.layers:
    for strip in layer.strips:
        for bag in strip.channelbags:
            for fcurve in bag.fcurves:
                for point in fcurve.keyframe_points:point.interpolation='LINEAR'
scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=181;scene.render.fps=60
cam_data=bpy.data.cameras.new('Geometry portrait camera');cam=bpy.data.objects.new('Geometry portrait camera',cam_data);bpy.context.collection.objects.link(cam)
cam.location=((540-W/2)/200,(H/2-230)/200,10);cam_data.type='ORTHO';cam_data.ortho_scale=1.5;scene.camera=cam
scene.render.engine='CYCLES';scene.cycles.samples=12;scene.view_settings.view_transform='Standard';scene.world.color=(0,0,0)
scene.render.resolution_x=900;scene.render.resolution_y=900;scene.render.resolution_percentage=100;scene.render.film_transparent=True;scene.render.image_settings.file_format='PNG'
for frame,label in [(1,'neutral'),(61,'closed-smile'),(91,'mid-open'),(121,'smile')]:
    scene.frame_set(frame);scene.render.filepath=str(OUT/f'blender-face-{label}.png');bpy.ops.render.render(write_still=True)
scene.frame_set(1)
for image in images:image.pack()
bpy.context.view_layer.objects.active=rig
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'portrait-refined-rig.blend'))
payload={'canvas':[W,H],'parameter_keys':KEYS,'textures':textures,'meshes':records,'transition':'smoothstep geometry, converging upper/lower lashes; only closed lip line fades from 0.5 to 0.65','interpolation':'smoothstep sampled at 33 keys','closed_smile_parameter':.5,'lip_fade_parameter_range':[.5,.65],'expected_moving_meshes':['EyeApertureL','EyeApertureR','UpperLidL','UpperLidR','LowerLidL','LowerLidR','MouthUpperLip','MouthOpening']}
(OUT/'blender-keyforms.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps({'meshes':len(records),'clipping_masks':3,'opacity_animated_meshes':[m['id'] for m in records if len(set(m['opacities']))>1],'fps':60,'rig':'portrait-refined-rig.blend'}))
