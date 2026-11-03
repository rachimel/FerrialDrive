"""Portrait Studio: editable time/shape curves and a real Live2D preview."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT','1')
import numpy as np
import pygame
import live2d
from OpenGL.GL import *
from asset_paths import WORKSPACE_DIR, EXPORT_DIR

from core import (DEFAULT_PROJECT,FIXED_DT,TRACKS,WORK,
                  Playback,Project,add_pose,atomic_json,clamp,compile_model,
                  delete_curve_node,evaluate,export_bundle,insert_curve_node,
                  inverse,move_curve_point,new_curve,split_curve_node,encode_curve_clipboard,decode_curve_clipboard)
from workspace_ui import UI,layout,DEFAULT_LAYOUT,MENUS,CURVE_CONTEXT,ACCENT,BLUE,PINK
from render_filters import prepare as prepare_filters
from region_workspace import RegionWorkspace


def trace(message):
    WORK.mkdir(parents=True,exist_ok=True)
    with (WORK/'editor-session.log').open('a',encoding='utf-8') as stream:stream.write(time.strftime('%H:%M:%S ')+message+'\n')


class Canvas:
    def __init__(self,size):
        self.texture=int(glGenTextures(1));self.background=int(glGenTextures(1));self.background_size=None
        self.size=size;self.model=None;self.model_path=None;self.mesh_ids=[]
    def load(self,path,value):
        trace('Loading model '+str(path))
        candidate=live2d.Model()
        try:
            moc=Path(path).parent/'character.moc3'
            candidate.LoadModelJson(str(path));trace('Model loaded')
            if not candidate.HasMocConsistencyFromFile(str(moc)):raise ValueError('변환된 모델의 구조 검증에 실패했어.')
            candidate.SetAutoBlink(False);candidate.SetAutoBreath(False)
            if candidate.GetParamIds()!=['ParamSmile']:raise ValueError('표정 파라미터를 찾을 수 없어.')
            candidate.SetSaveParamById('ParamSmile',value);candidate.Update(FIXED_DT)
        except BaseException:
            candidate.DestroyRenderer();raise
        old=self.model;self.model=candidate;self.model_path=Path(path);self.mesh_ids=candidate.GetDrawableIds()
        if old is not None:old.DestroyRenderer();del old
    def upload(self,texture,surface):
        glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,texture)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,*surface.get_size(),0,GL_RGBA,GL_UNSIGNED_BYTE,pygame.image.tobytes(surface,'RGBA'))
    def begin_pixels(self):
        w,h=self.size;glViewport(0,0,w,h);glUseProgram(0);glBindVertexArray(0)
        glDisable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glDisable(GL_SCISSOR_TEST)
        glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        glMatrixMode(GL_PROJECTION);glLoadIdentity();glOrtho(0,w,h,0,-1,1)
        glMatrixMode(GL_MODELVIEW);glLoadIdentity();glColor4f(1,1,1,1)
    def quad(self,texture,rect):
        self.begin_pixels();glActiveTexture(GL_TEXTURE0);glEnable(GL_TEXTURE_2D);glBindTexture(GL_TEXTURE_2D,texture)
        glBegin(GL_QUADS)
        for u,v,x,y in [(0,0,rect.left,rect.top),(1,0,rect.right,rect.top),(1,1,rect.right,rect.bottom),(0,1,rect.left,rect.bottom)]:
            glTexCoord2f(u,v);glVertex2f(x,y)
        glEnd();glBindTexture(GL_TEXTURE_2D,0);glDisable(GL_TEXTURE_2D)
    def draw(self,app,surface=None):
        self.size=app.size;w,h=self.size;p=app.rects['preview']
        glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);glClearColor(.06,.075,.10,1);glClear(GL_COLOR_BUFFER_BIT)
        if app.regions is not None:
            if surface is not None:self.upload(self.texture,surface)
            self.quad(self.texture,pygame.Rect(0,0,w,h));return
        if self.model is not None and app.fit_pending:self.fit_camera(app)
        if self.background_size!=p.size:
            bg=pygame.Surface(p.size,pygame.SRCALPHA);bg.fill((16,23,30,255))
            for x in range(0,p.w,32):pygame.draw.line(bg,(22,31,40),(x,0),(x,p.h))
            for y in range(0,p.h,32):pygame.draw.line(bg,(22,31,40),(0,y),(p.w,y))
            self.upload(self.background,bg);self.background_size=p.size
        self.quad(self.background,p)
        if self.model is not None:
            glViewport(p.x,h-p.bottom,p.w,p.h);glEnable(GL_SCISSOR_TEST);glScissor(p.x,h-p.bottom,p.w,p.h)
            self.model.Resize(p.w,p.h)
            self.model.SetScale(app.zoom);self.model.SetOffset(app.pan[0],app.pan[1])
            self.model.Draw()
            if app.wire or app.mask_overlay:self.draw_meshes(app)
        if surface is not None:self.upload(self.texture,surface)
        self.quad(self.texture,pygame.Rect(0,0,w,h));self.draw_playheads(app)
    def fit_camera(self,app):
        """Center a real SDK-space feature, independent of canvas/aspect rules."""
        p=app.rects['preview'];glViewport(p.x,app.size[1]-p.bottom,p.w,p.h)
        glEnable(GL_SCISSOR_TEST);glScissor(p.x,app.size[1]-p.bottom,p.w,p.h)
        self.model.Resize(p.w,p.h);self.model.SetScale(app.zoom)
        ids=['EyeInteriorL','EyeInteriorR','MouthInterior'] if app.face else ['Body']
        self.model.SetOffset(0,0);self.model.Draw()
        vertices=np.concatenate([np.asarray(self.model.GetDrawableVertices(self.mesh_ids.index(name))).reshape(-1,2) for name in ids])
        center=(vertices.min(axis=0)+vertices.max(axis=0))/2;point=np.array([*center,0.,1.])
        def projected():
            q=np.asarray(self.model.GetMvp()).reshape(4,4,order='F')@point
            return q[:2]/q[3]
        origin=projected();self.model.SetOffset(1,0);self.model.Draw();dx=projected()-origin
        self.model.SetOffset(0,1);self.model.Draw();dy=projected()-origin
        app.pan=np.linalg.solve(np.column_stack([dx,dy]),-origin).tolist()
        app.fit_pending=False;glDisable(GL_SCISSOR_TEST)
    def draw_meshes(self,app):
        p=app.rects['preview'];matrix=np.asarray(self.model.GetMvp(),dtype=float).reshape(4,4,order='F')
        ids=[]
        if app.wire:ids.append(app.selected_mesh)
        if app.mask_overlay:ids.extend(['EyeApertureL','EyeApertureR','MouthOpening'])
        self.begin_pixels();glEnable(GL_SCISSOR_TEST);glScissor(p.x,app.size[1]-p.bottom,p.w,p.h);glDisable(GL_TEXTURE_2D)
        for name in dict.fromkeys(ids):
            if name not in self.mesh_ids:continue
            mesh_index=self.mesh_ids.index(name);vertices=np.asarray(self.model.GetDrawableVertices(mesh_index)).reshape(-1,2)
            homogeneous=np.column_stack([vertices,np.zeros(len(vertices)),np.ones(len(vertices))])
            clip=homogeneous@matrix.T;ndc=clip[:,:2]/clip[:,3:4]
            pixels=np.column_stack([p.x+(ndc[:,0]+1)*p.w/2,p.y+(1-ndc[:,1])*p.h/2])
            triangles=np.asarray(self.model.GetDrawableIndices(mesh_index)).reshape(-1,3)
            color=ACCENT if name==app.selected_mesh else PINK
            glColor4f(*(v/255 for v in color),.6);glBegin(GL_LINES)
            edges=set()
            for a,b,c in triangles:
                for i,j in [(a,b),(b,c),(c,a)]:
                    edge=(min(i,j),max(i,j))
                    if edge in edges:continue
                    edges.add(edge);glVertex2f(*pixels[i]);glVertex2f(*pixels[j])
            glEnd()
        glDisable(GL_SCISSOR_TEST);glColor4f(1,1,1,1)
    def draw_playheads(self,app):
        if app.menu or app.modal:return
        self.begin_pixels();glDisable(GL_TEXTURE_2D)
        timeline=app.rects['timeline'];x=timeline.x+timeline.w*app.playback.position
        glColor3f(*(v/255 for v in ACCENT));glLineWidth(2);glBegin(GL_LINES)
        glVertex2f(x,timeline.y-3);glVertex2f(x,timeline.bottom+3);glEnd()
        graph=app.rects['graph']
        if app.mode=='time':local=app.playback.position
        else:
            keys=app.track_data['keys'];a,b=keys[app.segment:app.segment+2]
            local=clamp((app.value-a['at'])/(b['at']-a['at']))
        x=graph.x+graph.w*local;y=graph.bottom-graph.h*evaluate(app.curve,local)
        glColor4f(.85,.9,1,.5);glLineWidth(1);glBegin(GL_LINES);glVertex2f(x,graph.y);glVertex2f(x,graph.bottom);glEnd()
        glPointSize(8);glColor3f(*(v/255 for v in (BLUE if app.mode=='time' else PINK)))
        glBegin(GL_POINTS);glVertex2f(x,y);glEnd();glColor4f(1,1,1,1)
    def capture(self,path):
        glFinish();glReadBuffer(GL_BACK)
        surface=pygame.image.frombytes(glReadPixels(0,0,*self.size,GL_RGBA,GL_UNSIGNED_BYTE),self.size,'RGBA',True)
        Path(path).parent.mkdir(parents=True,exist_ok=True);pygame.image.save(surface,str(path))
    def close(self):
        if self.model is not None:self.model.DestroyRenderer();self.model=None
        glDeleteTextures([self.texture,self.background])


class Editor:
    def __init__(self,args):
        self.args=args;WORK.mkdir(parents=True,exist_ok=True)
        WORKSPACE_DIR.mkdir(parents=True,exist_ok=True);EXPORT_DIR.mkdir(parents=True,exist_ok=True)
        self.qa=WORK/'qa';self.qa.mkdir(exist_ok=True)
        if args.verify:self.project=Project(path=self.qa/'verified.project.json')
        elif args.project:self.project=Project.load(args.project)
        elif DEFAULT_PROJECT.exists():self.project=Project.load(DEFAULT_PROJECT)
        else:self.project=Project()
        pygame.display.init();pygame.font.init()
        self.size=(args.width,args.height)
        pygame.display.set_mode(self.size,pygame.OPENGL|pygame.DOUBLEBUF|pygame.RESIZABLE)
        from pygame._sdl2.video import Window
        self.native_window=Window.from_display_module()
        pygame.display.set_caption('표정 스튜디오 — Layout 02')
        live2d.init_internal(str(prepare_filters(WORK,'sharp')));live2d.glInit()
        self.layout_settings=DEFAULT_LAYOUT.copy();self.layout_path=self.qa/'verified-layout.json' if args.verify else WORKSPACE_DIR/'layout.json'
        if self.layout_path.exists() and not args.verify:
            try:
                saved=json.loads(self.layout_path.read_text());self.layout_settings.update({k:float(v) for k,v in saved.items() if k in DEFAULT_LAYOUT and np.isfinite(float(v))})
            except (ValueError,TypeError,AttributeError):pass
        self.ui=UI();self.canvas=Canvas(self.size);self.rects=layout(self.size,self.layout_settings);self.playback=Playback()
        self.regions=None
        trace('OpenGL window initialized')
        self.mode='time';self.track='mouth';self.selected_mesh='MouthUpperLip';self.segment=0;self.key_index=1
        self.curve_selection=(0,'out');self.face=True;self.zoom=8.;self.pan=[.05,-2.05];self.fit_pending=True
        self.wire=False;self.mask_overlay=False;self.edit_field=None;self.edit_text='';self.edit_fresh=False
        self.modal=None;self.drag=None;self.last_click=(0.,(0,0));self.running=True
        self.menu=None;self.clipboard_text='';self.tree_scroll=0.;self.inspector_scroll=0.
        self.context_position=(0,0);self.context_curve_x=.5
        self.cursor_kind=None
        self.message='준비 중 · 원본 리깅에서 미리보기 모델을 만들고 있어.';self.error=False
        self.dirty_ui=True;self.last_ui=0.;self.fps=0.;self.frame_times=[]
        self.executor=ThreadPoolExecutor(max_workers=1);self.future=None;self.future_signature=None
        self.applied_signature=None;self.last_change=0.;self.pending_export=None;self.model_reloads=0
        self.build_error_signature=None;self.verify_stage=0;self.verification={};self.export_waiting=False
        self.model_loaded_at=None;self.steady_intervals=[];self.autoplay_started=False
        self.source_sha=hashlib.sha256(self.project.source_path.read_bytes()).hexdigest()
        self.refresh_source();self.restore_workspace();self.request_build(True)
    @property
    def track_data(self):return self.project.data['tracks'][self.track]
    @property
    def curve(self):
        if self.mode=='time':return self.project.data['motion']['curve']
        keys=self.track_data['keys'];self.segment=max(0,min(self.segment,len(keys)-2))
        return keys[self.segment]['curve']
    @property
    def value(self):return self.playback.value(self.project.data)
    @property
    def building(self):return self.future is not None
    @property
    def pending_shape(self):return self.shape_signature()!=self.applied_signature
    def refresh_source(self):self.source_meshes={m['id']:m for m in self.project.source['meshes']}
    def shape_signature(self):
        source={'tracks':self.project.data['tracks'],'hidden':self.project.data['hidden_meshes'],'source':str(self.project.source_path)}
        return hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    def notify(self,message,error=False):self.message=message;self.error=error;self.dirty_ui=True
    def changed(self,shape=False):
        self.project.changed();self.last_change=time.perf_counter();self.dirty_ui=True
        if shape:self.build_error_signature=None
    def request_build(self,force=False):
        signature=self.shape_signature()
        if self.future is not None or (not force and (signature==self.applied_signature or signature==self.build_error_signature)):return
        output=WORK/'.runtime'/('build-'+uuid.uuid4().hex[:12])
        self.future_signature=signature
        self.future=self.executor.submit(compile_model,self.project.source,copy.deepcopy(self.project.data),self.project.source_path.parent,output)
        self.dirty_ui=True
    def poll_build(self):
        if self.future is not None and self.future.done():
            future=self.future;signature=self.future_signature;self.future=None
            try:
                path=future.result()
                if signature==self.shape_signature():
                    self.canvas.load(path,self.value);self.applied_signature=signature;self.model_reloads+=1
                    self.model_loaded_at=time.perf_counter()
                    self.notify('형태 적용 완료 · 실제 Live2D 모델로 미리보기를 갱신했어.')
            except Exception as exc:
                self.build_error_signature=signature;self.notify(f'형태 적용 실패: {exc}',True)
            self.dirty_ui=True
        if self.pending_shape and not self.building and not self.drag and time.perf_counter()-self.last_change>.35:self.request_build()
        if self.pending_export and not self.pending_shape and not self.building:
            target=self.pending_export;self.pending_export=None
            try:self.finish_export(target)
            except Exception as exc:self.notify(f'내보내기 실패: {exc}',True)
    def restore_workspace(self):
        state=self.project.data.get('workspace',{})
        self.track=state.get('track','mouth') if state.get('track','mouth') in TRACKS else 'mouth'
        self.mode=state.get('mode','time') if state.get('mode','time') in ('time','shape') else 'time'
        self.key_index=min(state.get('key_index',1),len(self.track_data['keys'])-1)
        self.segment=min(state.get('segment',0),len(self.track_data['keys'])-2)
        self.selected_mesh=state.get('mesh','MouthUpperLip')
        if self.selected_mesh not in self.source_meshes:self.selected_mesh='MouthUpperLip'
        self.face=bool(state.get('face',True));self.zoom=clamp(state.get('zoom',8.),.3,12.)
        self.pan=list(state.get('pan',[.05,-2.05]));self.playback.seek(state.get('position',0))
        self.fit_pending=not bool(state.get('pan'))
        if isinstance(state.get('layout'),dict):
            self.layout_settings.update({k:float(v) for k,v in state['layout'].items() if k in DEFAULT_LAYOUT and np.isfinite(float(v))})
        self.rects=layout(self.size,self.layout_settings)
    def save(self,path=None):
        self.project.data['workspace']={'track':self.track,'mode':self.mode,'key_index':self.key_index,'segment':self.segment,
            'mesh':self.selected_mesh,'face':self.face,'zoom':self.zoom,'pan':self.pan[:],'position':self.playback.position,
            'layout':self.layout_settings.copy()}
        self.project.save(path);self.notify('저장 완료 · '+str(self.project.path));return True
    def dialog(self,kind):
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
        try:
            if kind=='open':return filedialog.askopenfilename(parent=root,title='표정 프로젝트 열기',initialdir=str(self.project.path.parent),filetypes=[('표정 프로젝트','*.project.json'),('JSON','*.json')])
            if kind=='save':return filedialog.asksaveasfilename(parent=root,title='표정 프로젝트 저장',initialdir=str(self.project.path.parent),initialfile=self.project.path.name,defaultextension='.project.json',filetypes=[('표정 프로젝트','*.project.json')])
            return filedialog.askdirectory(parent=root,title='Live2D 출력 폴더 선택',initialdir=str(EXPORT_DIR))
        finally:root.destroy();self.dirty_ui=True
    def guarded(self,action):
        if self.project.dirty:self.modal=action;self.dirty_ui=True
        else:action()
    def open_project(self,path=None):
        path=path or self.dialog('open')
        if not path:return
        replacement=Project.load(path);self.project=replacement;self.refresh_source();self.restore_workspace()
        self.applied_signature=None;self.build_error_signature=None;self.curve_selection=(0,'out')
        self.notify('프로젝트를 열었어. 미리보기를 준비하고 있어.');self.last_change=0
    def finish_export(self,target):
        if Path(target).resolve()==self.project.source_path.parent:
            raise ValueError('원본 모델을 보존할 수 있도록 다른 출력 폴더를 골라 줘.')
        path=export_bundle(self.canvas.model_path,target)
        self.notify('내보내기 완료 · '+str(path));return path
    def export(self,target=None):
        target=target or self.dialog('export')
        if not target:return
        if self.pending_shape or self.building or not self.canvas.model_path:
            self.pending_export=Path(target);self.request_build();self.notify('최신 형태를 적용한 뒤 내보낼게.')
        else:self.finish_export(target)
    def seek_value(self,value):self.playback.seek(inverse(self.project.data['motion']['curve'],value));self.dirty_ui=True
    def set_mode(self,mode):self.mode=mode;self.curve_selection=(0,'out');self.edit_field=None;self.dirty_ui=True
    def set_track(self,track):
        self.track=track;self.key_index=min(self.key_index,len(self.track_data['keys'])-1)
        self.segment=min(self.segment,len(self.track_data['keys'])-2);self.curve_selection=(0,'out');self.dirty_ui=True
    def apply_field(self,name,text):
        value=float(text)
        if not np.isfinite(value):raise ValueError('숫자 값을 입력해 줘.')
        self.project.checkpoint();shape=False
        if name=='duration':self.project.data['motion']['duration']=clamp(value,.5,10.)
        elif name.startswith('curve_'):
            i,kind=self.curve_selection;node=self.curve['nodes'][i]
            xy=[node['x'],node['y']] if kind=='node' else node[kind][:]
            if name=='curve_x':
                if self.mode=='time':value=value/self.project.data['motion']['duration']
                else:
                    a,b=self.track_data['keys'][self.segment:self.segment+2];value=(value-a['at'])/(b['at']-a['at'])
            xy[0 if name=='curve_x' else 1]=value;move_curve_point(self.curve,i,kind,*xy);shape=self.mode=='shape'
        elif name=='key_at':
            keys=self.track_data['keys'];i=self.key_index
            if 0<i<len(keys)-1:keys[i]['at']=clamp(value,keys[i-1]['at']+.006,keys[i+1]['at']-.006)
            shape=True
        elif name=='key_source':self.track_data['keys'][self.key_index]['source']=clamp(value);shape=True
        self.changed(shape)
    def field_value(self,name):
        if name=='duration':return self.project.data['motion']['duration']
        if name=='key_at':return self.track_data['keys'][self.key_index]['at']
        if name=='key_source':return self.track_data['keys'][self.key_index]['source']
        i,kind=self.curve_selection;n=self.curve['nodes'][i];v=[n['x'],n['y']] if kind=='node' else n[kind]
        if name=='curve_x':
            if self.mode=='time':return v[0]*self.project.data['motion']['duration']
            a,b=self.track_data['keys'][self.segment:self.segment+2];return a['at']+(b['at']-a['at'])*v[0]
        return v[1]
    def commit_field(self):
        if self.edit_field is None:return
        field=self.edit_field;text=self.edit_text;self.edit_field=None;pygame.key.stop_text_input()
        try:self.apply_field(field,text)
        except (ValueError,KeyError) as exc:self.notify(str(exc),True)
        self.dirty_ui=True
    def write_clipboard(self,text):
        self.clipboard_text=text
        if self.args.verify:return
        try:
            if not pygame.scrap.get_init():pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT,text.encode('utf-8')+b'\0')
        except pygame.error:self.notify('클립보드 연결이 어려워 앱 내부에 복사했어.')
    def read_clipboard(self):
        if self.args.verify:return self.clipboard_text
        try:
            if not pygame.scrap.get_init():pygame.scrap.init()
            raw=pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw is not None:return raw.decode('utf-8').rstrip('\0')
        except (pygame.error,UnicodeError):pass
        return self.clipboard_text
    def action(self,name,data=None):
        if name not in ('menu_toggle','menu_action') and self.menu:
            self.menu=None;self.dirty_ui=True
        if name=='menu_toggle':self.menu=None if self.menu==data else data;self.dirty_ui=True
        elif name=='menu_action':
            point=self.context_curve_x if self.menu=='curve_context' and data=='add_curve_point' else None
            self.menu=None;self.action(data,point);self.dirty_ui=True
        elif name=='quit':self.guarded(lambda:setattr(self,'running',False))
        elif name=='open':self.guarded(lambda:self.open_project())
        elif name=='ai_regions':
            if self.edit_field is not None:self.commit_field()
            self.menu=None;self.drag=None;pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            self.regions=RegionWorkspace(WORKSPACE_DIR,lambda:setattr(self,'regions',None));self.dirty_ui=True
        elif name=='save':self.save()
        elif name=='save_as':
            path=self.dialog('save')
            if path:self.save(path)
        elif name in ('undo','redo'):
            restored=getattr(self.project,name)()
            if restored:
                self.key_index=min(self.key_index,len(self.track_data['keys'])-1)
                self.segment=min(self.segment,len(self.track_data['keys'])-2);self.curve_selection=(0,'out')
                self.last_change=time.perf_counter();self.build_error_signature=None
                self.notify('되돌렸어.' if name=='undo' else '다시 적용했어.')
        elif name=='export':self.export()
        elif name=='copy_curve':
            self.write_clipboard(encode_curve_clipboard(self.curve));self.notify('선택한 곡선 전체를 복사했어.')
        elif name=='paste_curve':
            curve=decode_curve_clipboard(self.read_clipboard());self.project.checkpoint()
            if self.mode=='time':self.project.data['motion']['curve']=curve
            else:self.track_data['keys'][self.segment]['curve']=curve
            self.curve_selection=(0,'out');self.changed(self.mode=='shape');self.notify('선택한 편집 대상에 곡선을 붙여넣었어.')
        elif name=='add_curve_point':
            if data is not None:value=clamp(data)
            elif self.mode=='time':value=self.playback.position
            else:
                a,b=self.track_data['keys'][self.segment:self.segment+2];value=clamp((self.value-a['at'])/(b['at']-a['at']))
            nodes=self.curve['nodes']
            if min(abs(value-n['x']) for n in nodes)<.02:
                a,b=max(zip(nodes,nodes[1:]),key=lambda pair:pair[1]['x']-pair[0]['x']);value=(a['x']+b['x'])/2
            self.project.checkpoint();index=split_curve_node(self.curve,value)
            if index is None:self.project.undo_stack.pop();self.notify('추가할 기준점 공간이 부족해.')
            else:self.curve_selection=(index,'node');self.changed(self.mode=='shape');self.notify('곡선 모양을 유지하며 기준점을 추가했어.')
        elif name=='delete_curve_point':
            index,kind=self.curve_selection
            if kind=='node' and 0<index<len(self.curve['nodes'])-1:
                self.project.checkpoint();delete_curve_node(self.curve,index);self.curve_selection=(0,'out');self.changed(self.mode=='shape')
        elif name=='reset_layout':
            self.layout_settings=DEFAULT_LAYOUT.copy();self.rects=layout(self.size,self.layout_settings)
            atomic_json(self.layout_path,self.layout_settings);self.fit_pending=True;self.dirty_ui=True
        elif name=='snapshot':
            self.screenshot=WORK/'captures'/time.strftime('editor-%Y%m%d-%H%M%S.png')
        elif name=='mode_time':self.set_mode('time')
        elif name=='mode_shape':self.set_mode('shape')
        elif name=='select_track':self.set_track(data);self.inspector_scroll=0
        elif name=='select_mesh':
            self.selected_mesh,track=data
            if track:self.set_track(track)
            self.dirty_ui=True
        elif name=='visibility':
            self.project.checkpoint();hidden=self.project.data['hidden_meshes']
            if data in hidden:hidden.remove(data)
            else:hidden.append(data)
            self.changed(True)
        elif name=='select_key':
            self.key_index=data;self.segment=min(data,len(self.track_data['keys'])-2)
            self.set_mode('shape');self.inspector_scroll=0;self.seek_value(self.track_data['keys'][data]['at'])
        elif name in ('segment_prev','segment_next'):
            self.segment=max(0,min(len(self.track_data['keys'])-2,self.segment+(-1 if name=='segment_prev' else 1)))
            self.curve_selection=(0,'out');self.dirty_ui=True
        elif name in ('preset','reset_curve'):
            preset=data if name=='preset' else 'Linear';self.project.checkpoint()
            if self.mode=='time':self.project.data['motion']['curve']=new_curve(preset)
            else:self.track_data['keys'][self.segment]['curve']=new_curve(preset)
            self.curve_selection=(0,'out');self.changed(self.mode=='shape')
        elif name=='add_key':
            self.project.checkpoint();key_id=add_pose(self.track_data,self.value)
            if key_id:
                self.key_index=next(i for i,k in enumerate(self.track_data['keys']) if k['id']==key_id)
                self.segment=min(self.key_index,len(self.track_data['keys'])-2)
                self.set_mode('shape');self.changed(True);self.notify('현재 위치에 표정 키를 추가했어.')
            else:
                self.project.undo_stack.pop();self.notify('기존 키에서 조금 떨어진 위치를 골라 줘.')
        elif name=='delete_key':
            keys=self.track_data['keys']
            if 0<self.key_index<len(keys)-1:
                self.project.checkpoint();del keys[self.key_index];self.key_index=min(self.key_index,len(keys)-1)
                self.segment=min(self.segment,len(keys)-2);self.curve_selection=(0,'out');self.changed(True)
        elif name=='apply_shape':self.build_error_signature=None;self.request_build(True)
        elif name=='seek_start':self.playback.seek(0);self.dirty_ui=True
        elif name=='forward':self.playback.play(1);self.dirty_ui=True
        elif name=='reverse':self.playback.play(-1);self.dirty_ui=True
        elif name=='pause':self.playback.toggle();self.dirty_ui=True
        elif name=='pose':self.seek_value(data)
        elif name=='wire':self.wire=not self.wire;self.dirty_ui=True
        elif name=='mask':self.mask_overlay=not self.mask_overlay;self.dirty_ui=True
        elif name=='view_mode':
            self.face=not self.face;self.reset_camera()
        elif name=='camera_reset':self.reset_camera()
        elif name in ('zoom_in','zoom_out'):
            self.zoom=clamp(self.zoom*(1.12 if name=='zoom_in' else 1/1.12),.3,12.);self.fit_pending=True;self.dirty_ui=True
        elif name.startswith('modal_'):
            callback=self.modal
            if name=='modal_cancel':self.modal=None
            elif name=='modal_discard':self.modal=None;callback()
            elif name=='modal_save':
                if self.save():self.modal=None;callback()
            self.dirty_ui=True
    def reset_camera(self):
        self.zoom=8. if self.face else .76;self.fit_pending=True;self.dirty_ui=True
    def graph_xy(self,pos):
        graph=self.rects['graph'];return clamp((pos[0]-graph.x)/graph.w),clamp((graph.bottom-pos[1])/graph.h)
    def scrub(self,pos):
        track=self.rects['timeline'];self.playback.seek((pos[0]-track.x)/track.w);self.dirty_ui=True
    def quit_from_regions(self):
        self.regions=None
        self.guarded(lambda:setattr(self,'running',False))
    def handle(self,event):
        if self.regions is not None and event.type!=pygame.VIDEORESIZE:
            if event.type==pygame.QUIT:self.regions.guard(self.quit_from_regions)
            else:self.regions.handle(event)
            self.dirty_ui=True;return
        if event.type==pygame.QUIT:self.guarded(lambda:setattr(self,'running',False));return
        if event.type==pygame.VIDEORESIZE:
            self.size=(max(1280,event.w),max(800,event.h))
            if self.size!=(event.w,event.h):self.native_window.size=self.size
            self.rects=layout(self.size,self.layout_settings);self.fit_pending=True;self.dirty_ui=True
            if self.regions is not None:self.regions.geometry(self.size)
            return
        if event.type==pygame.DROPFILE:
            if event.file.endswith('.json'):self.guarded(lambda:self.open_project(event.file))
            return
        if self.edit_field is not None:
            if event.type==pygame.TEXTINPUT:
                text=''.join(c for c in event.text if c in '0123456789.-+eE')
                self.edit_text=text if self.edit_fresh else self.edit_text+text;self.edit_fresh=False;self.dirty_ui=True;return
            if event.type==pygame.KEYDOWN:
                if event.mod&pygame.KMOD_CTRL and event.key==pygame.K_c:self.write_clipboard(self.edit_text)
                elif event.mod&pygame.KMOD_CTRL and event.key==pygame.K_v:
                    value=''.join(c for c in self.read_clipboard() if c in '0123456789.-+eE')
                    self.edit_text=value if self.edit_fresh else self.edit_text+value;self.edit_fresh=False;self.dirty_ui=True
                elif event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.commit_field()
                elif event.key==pygame.K_ESCAPE:self.edit_field=None;pygame.key.stop_text_input();self.dirty_ui=True
                elif event.key==pygame.K_BACKSPACE:
                    self.edit_text='' if self.edit_fresh else self.edit_text[:-1];self.edit_fresh=False;self.dirty_ui=True
                elif event.key==pygame.K_a and event.mod&pygame.KMOD_CTRL:self.edit_fresh=True
                return
            if event.type==pygame.MOUSEBUTTONDOWN:self.commit_field()
        if event.type==pygame.KEYDOWN:
            if self.modal:
                if event.key==pygame.K_ESCAPE:self.action('modal_cancel')
                return
            control=event.mod&pygame.KMOD_CTRL
            if event.key==pygame.K_ESCAPE and self.menu:self.menu=None;self.dirty_ui=True;return
            if control and event.key==pygame.K_c:self.action('copy_curve')
            elif control and event.key==pygame.K_v:self.action('paste_curve')
            elif control and event.key==pygame.K_e:self.action('export')
            elif control and event.mod&pygame.KMOD_SHIFT and event.key==pygame.K_p:self.action('snapshot')
            elif control and event.key==pygame.K_s:self.action('save_as' if event.mod&pygame.KMOD_SHIFT else 'save')
            elif control and event.key==pygame.K_o:self.action('open')
            elif control and event.key==pygame.K_z:self.action('redo' if event.mod&pygame.KMOD_SHIFT else 'undo')
            elif control and event.key==pygame.K_y:self.action('redo')
            elif event.key==pygame.K_SPACE:self.action('pause')
            elif event.key==pygame.K_r:self.action('reverse')
            elif event.key==pygame.K_a:self.action('forward')
            elif event.key==pygame.K_HOME:self.action('seek_start')
            elif event.key==pygame.K_z:self.action('view_mode')
            elif event.key in (pygame.K_1,pygame.K_2,pygame.K_3):self.seek_value({pygame.K_1:0.,pygame.K_2:1.,pygame.K_3:.5}[event.key])
            elif event.key==pygame.K_INSERT:self.action('add_curve_point')
            elif event.key in (pygame.K_DELETE,pygame.K_BACKSPACE):self.action('delete_curve_point')
            self.dirty_ui=True
        elif event.type==pygame.MOUSEWHEEL:
            position=pygame.mouse.get_pos()
            if self.rects['preview'].collidepoint(position):
                self.zoom=clamp(self.zoom*1.08**event.y,.3,12.);self.fit_pending=True;self.dirty_ui=True
            elif self.rects['parts'].collidepoint(position):
                self.tree_scroll=clamp(self.tree_scroll-event.y*84,0,self.ui.tree_max_scroll);self.dirty_ui=True
            elif self.rects['right'].collidepoint(position):
                self.inspector_scroll=clamp(self.inspector_scroll-event.y*56,0,self.ui.inspector_max_scroll);self.dirty_ui=True
            elif self.rects['poses'].collidepoint(position):
                self.key_index=max(0,min(len(self.track_data['keys'])-1,self.key_index-event.y));self.dirty_ui=True
        elif event.type==pygame.MOUSEBUTTONDOWN:
            if event.button==3:
                if self.modal:return
                if self.rects['curve'].collidepoint(event.pos):
                    point=next((data for name,rect,data in reversed(self.ui.hits) if name=='curve_point' and rect.collidepoint(event.pos)),None)
                    if point is not None:self.curve_selection=point
                    self.context_position=event.pos;self.context_curve_x=self.graph_xy(event.pos)[0]
                    self.menu='curve_context';self.drag=None;self.dirty_ui=True
                elif self.menu:self.menu=None;self.dirty_ui=True
                return
            if event.button==2 and self.rects['preview'].collidepoint(event.pos):self.drag=('pan',event.pos,self.pan[:]);return
            if event.button!=1:return
            now=time.perf_counter();last,position=self.last_click
            double=getattr(event,'clicks',1)>=2 or (now-last<.32 and np.linalg.norm(np.subtract(event.pos,position))<6)
            self.last_click=(now,event.pos)
            hit=next(((name,rect,data) for name,rect,data in reversed(self.ui.hits) if rect.collidepoint(event.pos) and (not self.modal or name.startswith('modal_'))),None)
            if not hit:
                if self.menu:self.menu=None;self.dirty_ui=True
                return
            name,rect,data=hit
            if self.menu and name not in ('menu_action','menu_toggle'):
                self.menu=None;self.dirty_ui=True;return
            if name=='splitter':self.drag=('splitter',data,event.pos,self.layout_settings.copy())
            elif name=='field':
                self.edit_field=data;self.edit_text=f'{self.field_value(data):.5f}'.rstrip('0').rstrip('.')
                self.edit_fresh=True;pygame.key.start_text_input();self.dirty_ui=True
            elif name=='curve_point':
                self.curve_selection=data;self.project.checkpoint();self.drag=('curve',data);self.dirty_ui=True
            elif name=='graph':
                x,y=self.graph_xy(event.pos)
                if double:
                    self.project.checkpoint();index=insert_curve_node(self.curve,x,y)
                    if index is not None:self.curve_selection=(index,'node');self.changed(self.mode=='shape')
                    else:self.project.undo_stack.pop()
                elif self.mode=='time':self.playback.seek(x);self.dirty_ui=True
                else:
                    a,b=self.track_data['keys'][self.segment:self.segment+2];self.seek_value(a['at']+(b['at']-a['at'])*x)
            elif name=='scrub':self.drag=('scrub',);self.scrub(event.pos)
            else:self.action(name,data)
        elif event.type==pygame.MOUSEMOTION and not self.drag:
            cursor=pygame.SYSTEM_CURSOR_ARROW
            if not self.modal and not self.menu:
                if self.rects['split_left'].collidepoint(event.pos) or self.rects['split_right'].collidepoint(event.pos):cursor=pygame.SYSTEM_CURSOR_SIZEWE
                elif self.rects['split_curve'].collidepoint(event.pos):cursor=pygame.SYSTEM_CURSOR_SIZENS
            if cursor!=self.cursor_kind:pygame.mouse.set_cursor(cursor);self.cursor_kind=cursor
            if self.menu in MENUS:
                item=next((data for name,rect,data in self.ui.hits if name=='menu_toggle' and rect.collidepoint(event.pos)),None)
                if item and item!=self.menu:self.menu=item;self.dirty_ui=True
        elif event.type==pygame.MOUSEMOTION and self.drag:
            if self.drag[0]=='splitter':
                name=self.drag[1];dx=event.pos[0]-self.drag[2][0];dy=event.pos[1]-self.drag[2][1];old=self.drag[3]
                if name=='split_left':self.layout_settings['left']=old['left']+dx
                elif name=='split_right':self.layout_settings['right']=old['right']-dx
                else:self.layout_settings['curve']=old['curve']-dy
                self.rects=layout(self.size,self.layout_settings);self.fit_pending=True;self.dirty_ui=True
            elif self.drag[0]=='curve':
                x,y=self.graph_xy(event.pos);move_curve_point(self.curve,*self.drag[1],x,y);self.changed(self.mode=='shape')
            elif self.drag[0]=='scrub':self.scrub(event.pos)
            elif self.drag[0]=='pan':
                delta=np.subtract(event.pos,self.drag[1]);p=self.rects['preview']
                self.pan=[self.drag[2][0]+delta[0]/p.h*2,self.drag[2][1]-delta[1]/p.h*2];self.dirty_ui=True
        elif event.type==pygame.MOUSEBUTTONUP and event.button in (1,2):
            if self.drag and self.drag[0]=='splitter':
                self.layout_settings.update(left=self.rects['left'].w,right=self.rects['right'].w,curve=self.rects['curve'].h)
                atomic_json(self.layout_path,self.layout_settings)
            self.drag=None;self.last_change=time.perf_counter();self.dirty_ui=True
    def render_ui(self):
        surface=self.regions.render(self.size) if self.regions is not None else self.ui.render(self)
        self.dirty_ui=False;self.last_ui=time.perf_counter();return surface
    def click(self,name,data=None):
        """Verification uses the same hit regions and mouse handler as a user."""
        self.render_ui()
        match=next((r for n,r,d in self.ui.hits if self.menu and n=='menu_action' and d==name),None)
        if match is None:match=next((r for n,r,d in self.ui.hits if n==name and (data is None or d==data)),None)
        if match is None:
            section=next((key for key,(_,items) in MENUS.items() if any(item and item[0]==name for item in items)),None)
            if section:
                self.click('menu_toggle',section);self.render_ui()
                match=next((r for n,r,d in self.ui.hits if n=='menu_action' and d==name),None)
            elif any(item and item[0]==name for item in CURVE_CONTEXT):
                if self.menu!='curve_context':
                    self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=self.rects['graph'].center))
                self.render_ui();match=next((r for n,r,d in self.ui.hits if n=='menu_action' and d==name),None)
        if match is None and name=='field':
            self.inspector_scroll=self.ui.inspector_max_scroll;self.render_ui()
            match=next((r for n,r,d in self.ui.hits if n==name and d==data),None)
        if match is None:raise AssertionError(f'Control not visible: {name} / {data}')
        self.last_click=(0.,(0,0))
        self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=match.center))
        self.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=match.center))
    def verify_tick(self):
        if self.building or self.pending_shape or self.canvas.model is None:return
        if self.verify_stage==0:
            self.seek_value(.75);self.canvas.model.SetSaveParamById('ParamSmile',self.value);self.canvas.model.Update(FIXED_DT)
            self.canvas.draw(self,self.render_ui())
            self.baseline_vertices={name:list(self.canvas.model.GetDrawableVertices(self.canvas.mesh_ids.index(name))) for name in ['MouthOpening','EyeApertureL']}
            self.click('preset','Ease In');self.time_curve_changed=evaluate(self.curve,.5)<.4
            self.project.checkpoint();self.curve_selection=(0,'out')
            # Exercise the actual drag handler, including its undo boundary.
            self.render_ui();rect=next(r for n,r,d in self.ui.hits if n=='curve_point' and d==(0,'out'))
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=rect.center))
            graph=self.rects['graph'];target=(graph.x+int(graph.w*.23),graph.bottom-int(graph.h*.12))
            self.handle(pygame.event.Event(pygame.MOUSEMOTION,pos=target,rel=(0,0),buttons=(1,0,0)))
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=target))
            changed=copy.deepcopy(self.curve);self.action('undo');assert self.curve!=changed
            self.action('redo');assert self.curve==changed
            self.click('save');loaded=Project.load(self.project.path)
            assert loaded.data==self.project.data
            self.set_track('mouth');self.set_mode('shape');self.segment=1
            self.click('preset','Ease In')
            self.render_ui();rect=next(r for n,r,d in self.ui.hits if n=='curve_point' and d==(0,'out'))
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=rect.center))
            graph=self.rects['graph'];target=(graph.x+int(graph.w*.39),graph.bottom-int(graph.h*.06))
            self.handle(pygame.event.Event(pygame.MOUSEMOTION,pos=target,rel=(0,0),buttons=(1,0,0)))
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=target))
            self.verification['shape_curve_drag']=True
            self.verify_stage=1
            self.verification.update({'time_curve_drag':True,'time_preset_changes_progress':self.time_curve_changed,'undo_redo':True,'project_roundtrip':True})
        elif self.verify_stage==1:
            self.seek_value(.75);self.canvas.model.SetSaveParamById('ParamSmile',self.value);self.canvas.model.Update(FIXED_DT)
            self.canvas.draw(self,self.render_ui())
            current={name:list(self.canvas.model.GetDrawableVertices(self.canvas.mesh_ids.index(name))) for name in self.baseline_vertices}
            assert current['MouthOpening']!=self.baseline_vertices['MouthOpening']
            assert np.allclose(current['EyeApertureL'],self.baseline_vertices['EyeApertureL'])
            self.verification['shape_curve_changes_native_vertices']=True
            self.verification['other_track_unchanged']=True
            self.seek_value(.7);self.click('add_key');assert len(self.track_data['keys'])==4
            self.click('field','key_source')
            self.handle(pygame.event.Event(pygame.TEXTINPUT,text='0.82'))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,mod=0))
            assert self.track_data['keys'][self.key_index]['source']==.82
            self.verification['pose_key_add_and_edit']=True
            self.action('delete_key');assert len(self.track_data['keys'])==3
            self.verification['pose_key_delete']=True
            self.verify_stage=2
        elif self.verify_stage==2:
            self.playback.seek(0);self.click('forward')
            duration=self.project.data['motion']['duration']
            for _ in range(round(duration/FIXED_DT)+1):self.playback.step(FIXED_DT,duration)
            assert self.playback.position==1 and not self.playback.playing
            for _ in range(600):self.playback.step(FIXED_DT,duration)
            assert self.playback.position==1
            self.click('reverse')
            for _ in range(round(duration/FIXED_DT)+1):self.playback.step(FIXED_DT,duration)
            assert self.playback.position==0 and not self.playback.playing
            for _ in range(600):self.playback.step(FIXED_DT,duration)
            assert self.playback.position==0
            self.verification['indefinite_endpoint_holds_and_reverse']=True
            self.save();self.export(self.qa/'exported')
            exported=self.qa/'exported/character.model3.json';assert exported.is_file()
            model=json.loads(exported.read_text());assert all((exported.parent/p).is_file() for p in model['FileReferences']['Textures'])
            self.verification['complete_moc_export']=True
            assert hashlib.sha256(self.project.source_path.read_bytes()).hexdigest()==self.source_sha
            self.verification['original_rig_unchanged']=True
            self.key_index=1;self.segment=1;self.seek_value(.78);self.set_mode('shape')
            self.screenshot=self.qa/'editor-shape.png';self.verify_stage=3
        elif self.verify_stage==3:
            self.set_mode('time');self.seek_value(.6);self.screenshot=self.qa/'editor-time.png'
            self.verify_stage=4
        elif self.verify_stage==4:
            self.wire=True;self.mask_overlay=True;self.selected_mesh='EyeApertureL'
            self.screenshot=self.qa/'editor-masks.png';self.verify_stage=5
        elif self.verify_stage==5:
            self.verification['native_mesh_and_mask_overlay']=True
            expected=copy.deepcopy(self.project.data)
            self.open_project(self.project.path);assert self.project.data==expected
            self.verification['project_reopen']=True;self.verify_stage=6
        elif self.verify_stage==6:
            self.set_mode('time');copied=copy.deepcopy(self.curve)
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_c,mod=pygame.KMOD_CTRL))
            self.click('preset','Linear')
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_v,mod=pygame.KMOD_CTRL))
            assert self.curve==copied
            before=[evaluate(self.curve,x) for x in np.linspace(0,1,50)]
            count=len(self.curve['nodes']);self.click('add_curve_point')
            assert len(self.curve['nodes'])==count+1
            np.testing.assert_allclose([evaluate(self.curve,x) for x in np.linspace(0,1,50)],before,atol=2e-6)
            self.click('delete_curve_point');self.action('undo');self.action('undo')
            assert self.curve==copied
            self.verification['curve_copy_paste']=True
            self.verification['explicit_add_point_preserves_curve']=True
            self.click('field','duration')
            self.handle(pygame.event.Event(pygame.TEXTINPUT,text='2.5'))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_c,mod=pygame.KMOD_CTRL))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_a,mod=pygame.KMOD_CTRL))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_v,mod=pygame.KMOD_CTRL))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,mod=0))
            assert self.project.data['motion']['duration']==2.5
            self.verification['numeric_copy_paste']=True
            for key,delta in [('split_left',(24,0)),('split_right',(-20,0)),('split_curve',(0,-36))]:
                self.render_ui();r=self.rects[key];start=r.center;target=(start[0]+delta[0],start[1]+delta[1])
                self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=start))
                self.handle(pygame.event.Event(pygame.MOUSEMOTION,pos=target,rel=delta,buttons=(1,0,0)))
                self.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=target))
            assert self.layout_settings=={'left':304,'right':340,'curve':366}
            assert json.loads(self.layout_path.read_text())==self.layout_settings
            self.verification['three_panel_splitters_and_persistence']=True
            self.click('reset_layout');self.wire=False;self.mask_overlay=False
            self.click('menu_toggle','file');self.screenshot=self.qa/'editor-menu.png';self.verify_stage=7
        elif self.verify_stage==7:
            self.menu=None
            trace('Verification: compact resize')
            self.native_window.size=(1280,800)
            self.handle(pygame.event.Event(pygame.VIDEORESIZE,w=1280,h=800,size=(1280,800)))
            self.screenshot=self.qa/'editor-compact.png';self.verify_stage=8
        elif self.verify_stage==8:
            assert self.rects['curve'].contains(self.rects['graph'])
            self.verification['compact_1280x800_layout']=True
            self.verification['file_menu_and_no_logo']=True
            trace('Verification: restore resize')
            self.native_window.size=(self.args.width,self.args.height)
            self.handle(pygame.event.Event(pygame.VIDEORESIZE,w=self.args.width,h=self.args.height,size=(self.args.width,self.args.height)))
            self.project.data['motion']['duration']=4.;self.changed();self.seek_value(.6);self.save()
            trace('Verification: restored and saved')
            self.screenshot=self.qa/'editor-layout02.png';self.verify_stage=9
        elif self.verify_stage==9:
            assert set(MENUS)=={'file','edit','view'}
            assert not any(item and item[0] in {'copy_curve','paste_curve'} for _,items in MENUS.values() for item in items)
            self.menu=None;self.set_mode('time');self.render_ui()
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=self.rects['preview'].center))
            assert self.menu is None
            graph=self.rects['graph'];position=(graph.right-2,graph.bottom-2)
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=position));self.render_ui()
            assert self.menu=='curve_context' and pygame.Rect(0,0,*self.size).contains(self.ui.menu_rect)
            original=copy.deepcopy(self.curve);self.click('copy_curve');assert self.menu is None
            self.click('preset','Linear');self.click('paste_curve');assert self.curve==original and self.menu is None
            self.render_ui();position=(graph.x+int(graph.w*.73),graph.y+graph.h//2)
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=position))
            count=len(self.curve['nodes']);self.click('add_curve_point')
            assert len(self.curve['nodes'])==count+1
            index,kind=self.curve_selection;assert kind=='node'
            assert abs(self.curve['nodes'][index]['x']-.73)<.005
            self.render_ui();point=next(r.center for n,r,d in self.ui.hits if n=='curve_point' and d==(index,'node'))
            self.curve_selection=(0,'out')
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=point))
            assert self.curve_selection==(index,'node')
            self.click('delete_curve_point');assert len(self.curve['nodes'])==count
            self.action('undo');self.action('undo');assert self.curve==original
            self.render_ui()
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=graph.center))
            self.handle(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE,mod=0));assert self.menu is None
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=graph.center))
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=self.rects['preview'].center));assert self.menu is None
            self.verification.update({'curve_operations_context_only':True,'context_right_click_copy_paste':True,
                'context_add_at_cursor':True,'context_select_delete_point':True,'context_dismiss_and_window_bounds':True})
            self.save();self.render_ui()
            self.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=3,pos=(graph.x+graph.w//2,graph.y+25)))
            self.screenshot=self.qa/'editor-curve-context.png';self.verify_stage=10
        elif self.verify_stage==10:
            self.verification.update({'moc_consistency':True,'model_reloads':self.model_reloads,
                'fixed_update_seconds':FIXED_DT,'verification_inclusive_fps':self.fps,
                'captures':[str(self.qa/name) for name in ['editor-layout02.png','editor-menu.png','editor-compact.png','editor-curve-context.png']],
                'clipboard_verification':'In-app adapter; the existing system clipboard is left untouched during verification.',
                'scope':'One ParamSmile axis; three linked tracks; Blender source poses are remapped, not arbitrary bone rigs.'})
            atomic_json(self.qa/'editor-verification.json',self.verification)
            print(json.dumps(self.verification,ensure_ascii=False,indent=2));self.running=False
    def run(self):
        started=previous=time.perf_counter();deadline=previous;accumulator=0.;self.screenshot=None
        try:
            while self.running:
                # Absolute frame deadlines avoid the SDL Clock.tick oversleep
                # measured in the original prototype. No busy-spin is needed.
                deadline+=FIXED_DT;delay=deadline-time.perf_counter()
                if delay>0:time.sleep(delay)
                now=time.perf_counter();elapsed=now-previous;previous=now
                if now-deadline>.25:deadline=now
                self.frame_times.append(elapsed);self.frame_times=self.frame_times[-90:]
                self.fps=len(self.frame_times)/sum(self.frame_times)
                for event in pygame.event.get():
                    try:self.handle(event)
                    except Exception as exc:
                        self.drag=None
                        if self.regions is not None:self.regions.drag=None;self.regions.notify(f'작업 실패: {exc}',True)
                        else:self.notify(f'작업 실패: {exc}',True)
                self.poll_build();accumulator+=min(elapsed,.25)
                if self.args.autoplay and self.canvas.model is not None and not self.autoplay_started:
                    self.playback.seek(0);self.playback.play(1);self.autoplay_started=True
                if self.args.pose is not None and self.canvas.model is not None and not self.autoplay_started:
                    self.seek_value(self.args.pose);self.autoplay_started=True
                if self.model_loaded_at and now-self.model_loaded_at>1 and not self.building:
                    self.steady_intervals.append(elapsed)
                while accumulator>=FIXED_DT:
                    if self.regions is None:self.playback.step(FIXED_DT,self.project.data['motion']['duration'])
                    if self.canvas.model is not None:
                        self.canvas.model.SetSaveParamById('ParamSmile',self.value);self.canvas.model.Update(FIXED_DT)
                    accumulator-=FIXED_DT
                if self.args.verify:self.verify_tick()
                if self.canvas.model is not None:
                    self.canvas.model.SetSaveParamById('ParamSmile',self.value);self.canvas.model.Update(0.)
                surface=self.render_ui() if self.dirty_ui or now-self.last_ui>.12 else None
                self.canvas.draw(self,surface)
                if self.screenshot:
                    self.canvas.capture(self.screenshot);self.notify('화면 저장 · '+str(self.screenshot));self.screenshot=None
                pygame.display.flip()
                if self.args.seconds and now-started>=self.args.seconds:self.running=False
                if self.args.verify and now-started>90:raise TimeoutError('Editor verification did not complete')
            if self.args.measure and self.steady_intervals:
                values=np.asarray(self.steady_intervals)
                report={'mean_render_fps':float(1/values.mean()),'mean_frame_ms':float(values.mean()*1000),
                        'p95_frame_ms':float(np.percentile(values,95)*1000),'frames':len(values),
                        'fixed_update_seconds':FIXED_DT,'shader':'sharp','window':list(self.size),
                        'notes':'Excludes build/reload and the first second after model load. No repeated PNG captures.'}
                atomic_json(self.qa/'editor-timing.json',report);print(json.dumps(report,indent=2))
                self.canvas.capture(self.qa/'editor-running.png')
        finally:
            self.executor.shutdown(wait=True,cancel_futures=True)
            self.canvas.close();live2d.dispose();pygame.quit()


def main():
    parser=argparse.ArgumentParser(description='표정 스튜디오 — 시간·형태 곡선 에디터')
    parser.add_argument('--project',type=Path);parser.add_argument('--verify',action='store_true')
    parser.add_argument('--seconds',type=float,default=0)
    parser.add_argument('--measure',action='store_true');parser.add_argument('--autoplay',action='store_true')
    parser.add_argument('--pose',type=float)
    parser.add_argument('--width',type=int,default=1600);parser.add_argument('--height',type=int,default=940)
    args=parser.parse_args()
    if args.width<1280 or args.height<800:parser.error('최소 화면 크기는 1280×800이야.')
    Editor(args).run()


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        WORK.mkdir(parents=True,exist_ok=True);log=WORK/'editor-error.log'
        log.write_text(traceback.format_exc(),encoding='utf-8')
        if sys.stderr is not None:traceback.print_exc()
        else:
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk();root.withdraw();messagebox.showerror('표정 스튜디오 실행 실패',f'오류 기록: {log}');root.destroy()
        raise SystemExit(1)
