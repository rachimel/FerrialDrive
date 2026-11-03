"""Editable curve/project data and a restricted Blender-keyform MOC3 build.

The original Blender export is read-only. Editor output lives in a separate
folder; changing a shape curve remaps sampled source poses within each track.
Linked aperture/lash meshes deliberately share a track so masks stay aligned.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np

from asset_paths import ROOT, RIG_DIR, WORKSPACE_DIR, OUTPUT_DIR
from export_moc3 import export as export_moc3

DEFAULT_SOURCE=RIG_DIR/'blender-keyforms.json'
WORK=OUTPUT_DIR
DEFAULT_PROJECT=WORKSPACE_DIR/'portrait.project.json'
FIXED_DT=1/60
PRESETS={
    'Linear':((1/3,1/3),(2/3,2/3)),
    'Smoothstep':((1/3,0),(2/3,1)),
    'Ease In':((.42,0),(1,1)),
    'Ease Out':((0,0),(.58,1)),
    'Ease In-Out':((.42,0),(.58,1)),
}
TRACKS={
    'eye_l':('왼쪽 눈',['EyeApertureL','LowerLidL','UpperLidL']),
    'eye_r':('오른쪽 눈',['EyeApertureR','LowerLidR','UpperLidR']),
    'mouth':('입',['MouthOpening','MouthUpperLip']),
}
MESH_LABELS={
    'Body':'상체 · 기본 그림','EyeApertureL':'눈 안쪽 마스크','EyeInteriorL':'홍채와 흰자',
    'LowerLidL':'아래 속눈썹','UpperLidL':'위 속눈썹','BrowL':'눈썹',
    'EyeApertureR':'눈 안쪽 마스크','EyeInteriorR':'홍채와 흰자',
    'LowerLidR':'아래 속눈썹','UpperLidR':'위 속눈썹','BrowR':'눈썹',
    'MouthUpperLip':'다문 입술선','MouthOpening':'입 안쪽 마스크','MouthInterior':'입 안쪽 그림',
}


def clamp(value,low=0.,high=1.):return min(high,max(low,float(value)))


def new_curve(name='Linear'):
    a,b=PRESETS[name]
    return {'preset':name,'nodes':[
        {'x':0.,'y':0.,'in':[0.,0.],'out':list(a)},
        {'x':1.,'y':1.,'in':list(b),'out':[1.,1.]},
    ]}


def bezier(a,b,c,d,t):
    u=1-t
    return u*u*u*a+3*u*u*t*b+3*u*t*t*c+t*t*t*d


def evaluate(curve,x):
    x=clamp(x);nodes=curve['nodes']
    if x<=0:return 0.
    if x>=1:return 1.
    index=max(0,min(len(nodes)-2,bisect.bisect_right([n['x'] for n in nodes],x)-1))
    a,b=nodes[index:index+2];lo,hi=0.,1.
    for _ in range(24):
        t=(lo+hi)/2
        if bezier(a['x'],a['out'][0],b['in'][0],b['x'],t)<x:lo=t
        else:hi=t
    return clamp(bezier(a['y'],a['out'][1],b['in'][1],b['y'],(lo+hi)/2))


def inverse(curve,value):
    lo,hi=0.,1.;value=clamp(value)
    if value in (0.,1.):return value
    for _ in range(30):
        mid=(lo+hi)/2
        if evaluate(curve,mid)<value:lo=mid
        else:hi=mid
    return (lo+hi)/2


def validate_curve(curve):
    if not isinstance(curve,dict) or curve.get('preset') not in {*PRESETS,'Custom'}:
        raise ValueError('곡선 프리셋 정보가 맞지 않아.')
    nodes=curve.get('nodes',[])
    if not 2<=len(nodes)<=32:raise ValueError('곡선의 기준점은 2~32개여야 해.')
    if (nodes[0]['x'],nodes[0]['y'],nodes[-1]['x'],nodes[-1]['y'])!=(0.,0.,1.,1.):
        raise ValueError('곡선의 시작과 끝은 (0, 0), (1, 1)이어야 해.')
    previous=None
    for node in nodes:
        values=[node['x'],node['y'],*node['in'],*node['out']]
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in values):
            raise ValueError('곡선 좌표는 0~1 범위의 숫자여야 해.')
        if previous:
            if node['x']-previous['x']<.001 or node['y']<previous['y']:
                raise ValueError('곡선의 시간과 값은 앞 방향으로 이어져야 해.')
            for handle in [previous['out'],node['in']]:
                if not previous['x']<=handle[0]<=node['x'] or not previous['y']<=handle[1]<=node['y']:
                    raise ValueError('곡선 핸들은 해당 구간 안에 있어야 해.')
        previous=node


def move_curve_point(curve,index,kind,x,y):
    nodes=curve['nodes'];node=nodes[index];x=clamp(x);y=clamp(y)
    if kind=='node':
        if index in (0,len(nodes)-1):return
        before,after=nodes[index-1],nodes[index+1]
        x=clamp(x,before['x']+.005,after['x']-.005);y=clamp(y,before['y'],after['y'])
        dx,dy=x-node['x'],y-node['y'];node['x']=x;node['y']=y
        node['in']=[clamp(node['in'][0]+dx,before['x'],x),clamp(node['in'][1]+dy,before['y'],y)]
        node['out']=[clamp(node['out'][0]+dx,x,after['x']),clamp(node['out'][1]+dy,y,after['y'])]
        before['out']=[min(before['out'][0],x),min(before['out'][1],y)]
        after['in']=[max(after['in'][0],x),max(after['in'][1],y)]
    elif kind=='out' and index<len(nodes)-1:
        other=nodes[index+1];node['out']=[clamp(x,node['x'],other['x']),clamp(y,node['y'],other['y'])]
    elif kind=='in' and index>0:
        other=nodes[index-1];node['in']=[clamp(x,other['x'],node['x']),clamp(y,other['y'],node['y'])]
    curve['preset']='Custom'


def insert_curve_node(curve,x,y):
    nodes=curve['nodes'];x=clamp(x,.01,.99)
    if len(nodes)>=32:return None
    index=bisect.bisect_left([n['x'] for n in nodes],x)
    a,b=nodes[index-1],nodes[index]
    if min(x-a['x'],b['x']-x)<.015:return None
    y=clamp(y,a['y'],b['y'])
    a['out']=[a['x']+(x-a['x'])/3,a['y']+(y-a['y'])/3]
    b['in']=[x+2*(b['x']-x)/3,y+2*(b['y']-y)/3]
    nodes.insert(index,{'x':x,'y':y,'in':[a['x']+2*(x-a['x'])/3,a['y']+2*(y-a['y'])/3],
                        'out':[x+(b['x']-x)/3,y+(b['y']-y)/3]})
    curve['preset']='Custom';return index


def split_curve_node(curve,x):
    """Add a Bezier anchor without changing the existing curve's shape."""
    nodes=curve['nodes'];x=clamp(x,.01,.99)
    if len(nodes)>=32:return None
    index=bisect.bisect_left([n['x'] for n in nodes],x);a,b=nodes[index-1:index+1]
    if min(x-a['x'],b['x']-x)<.015:return None
    lo,hi=0.,1.
    for _ in range(26):
        t=(lo+hi)/2
        if bezier(a['x'],a['out'][0],b['in'][0],b['x'],t)<x:lo=t
        else:hi=t
    t=(lo+hi)/2;lerp=lambda p,q:[p[i]+(q[i]-p[i])*t for i in range(2)]
    p0=[a['x'],a['y']];p1=a['out'][:];p2=b['in'][:];p3=[b['x'],b['y']]
    q0,q1,q2=lerp(p0,p1),lerp(p1,p2),lerp(p2,p3)
    r0,r1=lerp(q0,q1),lerp(q1,q2);point=lerp(r0,r1)
    a['out']=q0;b['in']=q2
    nodes.insert(index,{'x':point[0],'y':point[1],'in':r0,'out':r1});curve['preset']='Custom'
    return index


def encode_curve_clipboard(curve):
    validate_curve(curve)
    return json.dumps({'kind':'portrait-curve','version':1,'curve':curve},ensure_ascii=True)


def decode_curve_clipboard(text):
    if len(text)>200000:raise ValueError('붙여넣을 곡선 데이터가 너무 커.')
    try:
        data=json.loads(text)
        if data.get('kind')!='portrait-curve' or data.get('version')!=1:raise ValueError('곡선을 복사한 뒤 붙여넣어 줘.')
        curve=copy.deepcopy(data['curve']);validate_curve(curve);return curve
    except (KeyError,TypeError,AttributeError,json.JSONDecodeError) as exc:
        raise ValueError('붙여넣을 곡선 데이터 형식이 맞지 않아.') from exc


def delete_curve_node(curve,index):
    if index in (0,len(curve['nodes'])-1):return False
    nodes=curve['nodes'];del nodes[index];a,b=nodes[index-1:index+1]
    a['out']=[a['x']+(b['x']-a['x'])/3,a['y']+(b['y']-a['y'])/3]
    b['in']=[a['x']+2*(b['x']-a['x'])/3,a['y']+2*(b['y']-a['y'])/3]
    curve['preset']='Custom';return True


def default_document(source=DEFAULT_SOURCE):
    return {'format':'portrait-editor','version':1,'title':'Portrait / 표정 연구',
            'rig_source':str(Path(source).resolve()),'motion':{'duration':4.,'curve':new_curve()},
            'tracks':{name:{'label':label,'meshes':meshes,'keys':[
                {'id':'neutral','label':'중립','at':0.,'source':0.,'curve':new_curve()},
                {'id':'closed','label':'다문 미소','at':.5,'source':.5,'curve':new_curve()},
                {'id':'smile','label':'웃음','at':1.,'source':1.,'curve':new_curve()},
            ]} for name,(label,meshes) in TRACKS.items()},'hidden_meshes':[]}


def validate_document(doc):
    if doc.get('format')!='portrait-editor' or doc.get('version')!=1:raise ValueError('지원하지 않는 프로젝트 형식이야.')
    if not .5<=float(doc['motion']['duration'])<=10:raise ValueError('재생 시간은 0.5~10초여야 해.')
    validate_curve(doc['motion']['curve'])
    if set(doc['tracks'])!=set(TRACKS):raise ValueError('현재 버전은 왼눈·오른눈·입 트랙을 지원해.')
    for name,track in doc['tracks'].items():
        if track['meshes']!=TRACKS[name][1]:raise ValueError('트랙의 연결 파츠 구성이 맞지 않아.')
        keys=track['keys']
        if not 2<=len(keys)<=32 or keys[0]['at']!=0 or keys[-1]['at']!=1:raise ValueError('표정 키의 시작과 끝은 0과 1이어야 해.')
        if len({k['id'] for k in keys})!=len(keys):raise ValueError('표정 키 ID가 중복됐어.')
        for i,key in enumerate(keys):
            if not math.isfinite(key['at']) or not 0<=key['source']<=1:raise ValueError('표정 키 값이 잘못됐어.')
            if i and key['at']-keys[i-1]['at']<.005:raise ValueError('표정 키 사이 간격이 너무 작아.')
            validate_curve(key['curve'])


def track_source(track,value):
    keys=track['keys'];value=clamp(value)
    if value>=1:return keys[-1]['source']
    i=max(0,bisect.bisect_right([k['at'] for k in keys],value)-1)
    a,b=keys[i:i+2];weight=evaluate(a['curve'],(value-a['at'])/(b['at']-a['at']))
    return a['source']+(b['source']-a['source'])*weight


def add_pose(track,value):
    value=clamp(value)
    if len(track['keys'])>=32:return None
    if any(abs(k['at']-value)<.025 for k in track['keys']):return None
    source=track_source(track,value)
    key={'id':uuid.uuid4().hex[:10],'label':'사용자 키','at':value,'source':source,'curve':new_curve()}
    track['keys'].append(key);track['keys'].sort(key=lambda k:k['at']);return key['id']


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=path.stem+'-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    except BaseException:
        Path(temp).unlink(missing_ok=True);raise


class Project:
    def __init__(self,document=None,path=None):
        self.data=copy.deepcopy(document or default_document());validate_document(self.data)
        self.path=Path(path or DEFAULT_PROJECT).resolve()
        source=Path(self.data['rig_source'])
        self.source_path=(source if source.is_absolute() else self.path.parent/source).resolve()
        if not self.source_path.is_file():raise ValueError(f'리깅 원본을 찾을 수 없어: {self.source_path}')
        self.source=json.loads(self.source_path.read_text(encoding='utf-8'))
        self.saved=copy.deepcopy(self.data);self.undo_stack=[];self.redo_stack=[];self.revision=0
    @property
    def dirty(self):return self.saved!=self.data
    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.data));self.undo_stack=self.undo_stack[-80:];self.redo_stack.clear()
    def changed(self):validate_document(self.data);self.revision+=1
    def undo(self):
        if not self.undo_stack:return False
        self.redo_stack.append(copy.deepcopy(self.data));self.data=self.undo_stack.pop();self.revision+=1;return True
    def redo(self):
        if not self.redo_stack:return False
        self.undo_stack.append(copy.deepcopy(self.data));self.data=self.redo_stack.pop();self.revision+=1;return True
    def save(self,path=None):
        path=Path(path or self.path).resolve();document=copy.deepcopy(self.data)
        if path==self.source_path:raise ValueError('리깅 원본 파일에는 프로젝트를 덮어쓸 수 없어.')
        try:document['rig_source']=os.path.relpath(self.source_path,path.parent).replace('\\','/')
        except ValueError:document['rig_source']=str(self.source_path)
        validate_document(document);atomic_json(path,document);self.path=path;self.data=document;self.saved=copy.deepcopy(document)
    @classmethod
    def load(cls,path):
        path=Path(path);result=cls(json.loads(path.read_text(encoding='utf-8')),path)
        result.saved=copy.deepcopy(result.data);return result


class Playback:
    def __init__(self):self.position=0.;self.playing=False;self.direction=1
    def seek(self,position):self.position=clamp(position);self.playing=False
    def play(self,direction=1):
        self.direction=1 if direction>0 else -1
        self.playing=self.position<1 if self.direction>0 else self.position>0
    def toggle(self):
        if self.playing:self.playing=False
        else:self.play(-1 if self.position>=1 else 1 if self.position<=0 else self.direction)
    def step(self,dt,duration):
        if not self.playing:return
        self.position=clamp(self.position+self.direction*dt/duration)
        if self.position<1e-10:self.position=0.;self.playing=False
        if self.position>1-1e-10:self.position=1.;self.playing=False
    def value(self,document):return evaluate(document['motion']['curve'],self.position)
    @property
    def status(self):
        if self.playing:return '정방향 재생' if self.direction>0 else '역방향 재생'
        if self.position==0:return '중립 유지'
        if self.position==1:return '웃음 유지'
        return '일시정지'


def compile_model(source,document,source_dir,output_dir,write_debug=False):
    """Map linked shape tracks to immutable source poses and export a new MOC.

    Source parameter knots, user pose knots and dense samples all remain in the
    output, including the exact closed-smile anchor. Static eye artwork stays
    static: the moving aperture continues to provide real clipping.
    """
    validate_document(document);source_dir=Path(source_dir);output_dir=Path(output_dir)
    compiled=copy.deepcopy(source);oldkeys=np.asarray(source['parameter_keys'],dtype=float)
    keys=set(np.linspace(0,1,129).tolist())|set(oldkeys.tolist())
    for track in document['tracks'].values():keys.update(k['at'] for k in track['keys'])
    keys=sorted(keys);compiled['parameter_keys']=keys
    owner={mesh:track for track in document['tracks'].values() for mesh in track['meshes']}
    for mesh in compiled['meshes']:
        original=next(m for m in source['meshes'] if m['id']==mesh['id'])
        mapped=np.asarray([track_source(owner[mesh['id']],v) if mesh['id'] in owner else v for v in keys])
        indices=np.searchsorted(oldkeys,mapped,side='right')-1;indices=np.clip(indices,0,len(oldkeys)-2)
        weights=(mapped-oldkeys[indices])/(oldkeys[indices+1]-oldkeys[indices])
        forms=np.asarray(original['forms'],dtype=float)
        new=forms[indices]*(1-weights[:,None])+forms[indices+1]*weights[:,None]
        alpha=np.asarray(original['opacities'],dtype=float)
        mesh['forms']=new.tolist();mesh['neutral']=mesh['forms'][0];mesh['smile']=mesh['forms'][-1]
        mesh['opacities']=np.interp(mapped,oldkeys,alpha).tolist()
        if mesh['id'] in document['hidden_meshes']:mesh['opacities']=[0.]*len(keys)
    output_dir.mkdir(parents=True,exist_ok=True)
    for path in source['textures']:
        if not (source_dir/path).is_file():raise ValueError(f'텍스처를 찾을 수 없어: {path}')
    compiled['textures']=[os.path.relpath(source_dir/p,output_dir).replace('\\','/') for p in source['textures']]
    if write_debug:atomic_json(output_dir/'editor-keyforms.json',compiled)
    export_moc3(compiled,output_dir)
    digest=hashlib.sha256(json.dumps(document,sort_keys=True).encode()).hexdigest()
    atomic_json(output_dir/'build-info.json',{'source':'Blender keyforms','project_sha256':digest,'sample_count':len(keys)})
    return output_dir/'character.model3.json'


def export_bundle(model_path,target):
    """Publish complete runtime assets, including texture copies, atomically per file."""
    model_path=Path(model_path);target=Path(target);target.mkdir(parents=True,exist_ok=True)
    model=json.loads(model_path.read_text(encoding='utf-8'));refs=model['FileReferences'];names=[]
    textures=target/'textures';textures.mkdir(exist_ok=True)
    for i,p in enumerate(refs['Textures']):
        source=(model_path.parent/p).resolve();name=f'{i:02d}-{source.name}'
        shutil.copy2(source,textures/name);names.append('textures/'+name)
    shutil.copy2(model_path.parent/refs['Moc'],target/'character.moc3')
    refs['Moc']='character.moc3';refs['Textures']=names
    atomic_json(target/'character.model3.json',model)
    return target/'character.model3.json'
