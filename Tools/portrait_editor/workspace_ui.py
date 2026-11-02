"""Aligned menu-based workspace. Panel sizes come from one shared layout."""
from pathlib import Path
import pygame
from core import MESH_LABELS,PRESETS,TRACKS,clamp,evaluate,inverse
from ui_primitives import Painter as BaseUI,BG,PANEL,PANEL2,BORDER,TEXT,MUTED,DIM,ACCENT,BLUE,PINK,AMBER

PAD=16;GAP=8;ROW=28;CONTROL=32;TOP=80;STATUS=28
DEFAULT_LAYOUT={'left':280,'right':320,'curve':330}
MENUS={
    'file':('파일',[
        ('open','열기…','Ctrl+O'),('save','저장','Ctrl+S'),('save_as','다른 이름으로 저장…','Ctrl+Shift+S'),None,
        ('ai_regions','AI 영역 지정…',''),None,
        ('snapshot','화면 저장','Ctrl+Shift+P'),('export','.moc3 내보내기…','Ctrl+E'),None,('quit','종료','Alt+F4')]),
    'edit':('편집',[
        ('undo','되돌리기','Ctrl+Z'),('redo','다시 적용','Ctrl+Shift+Z')]),
    'view':('보기',[
        ('view_mode','얼굴 / 전신 전환','Z'),('camera_reset','미리보기 맞춤',''),None,
        ('wire','선택 메시 표시',''),('mask','마스크 표시',''),None,('reset_layout','패널 배치 초기화','')]),
}
CURVE_CONTEXT=[('copy_curve','곡선 복사','Ctrl+C'),('paste_curve','곡선 붙여넣기','Ctrl+V'),None,
    ('add_curve_point','기준점 추가','Insert'),('delete_curve_point','기준점 삭제','Delete'),None,
    ('reset_curve','곡선 초기화','')]


def context_rect(size,position):
    width=300;height=8+sum(10 if item is None else 32 for item in CURVE_CONTEXT)
    return pygame.Rect(int(clamp(position[0],8,size[0]-width-8)),
                       int(clamp(position[1],8,size[1]-height-8)),width,height)


def layout(size,settings=None):
    w,h=size;s={**DEFAULT_LAYOUT,**(settings or {})}
    left=int(clamp(s['left'],230,min(380,w-288-620)))
    right=int(clamp(s['right'],288,min(420,w-left-620)))
    center=pygame.Rect(left+4,TOP,max(300,w-left-right-8),h-TOP-STATUS)
    player_h=108 if center.w<800 else 76
    curve_h=int(clamp(s['curve'],240,min(480,center.h-player_h-36-160)))
    curve=pygame.Rect(center.x,center.bottom-curve_h,center.w,curve_h)
    player=pygame.Rect(center.x,curve.y-player_h,center.w,player_h)
    preview=pygame.Rect(center.x,TOP+36,center.w,max(80,player.y-TOP-36))
    left_rect=pygame.Rect(0,TOP,left,h-TOP-STATUS);right_rect=pygame.Rect(w-right,TOP,right,h-TOP-STATUS)
    poses_h=242;poses=pygame.Rect(0,left_rect.bottom-poses_h,left,poses_h)
    parts=pygame.Rect(8,TOP+72,left-16,max(80,poses.y-TOP-84))
    return {'left':left_rect,'right':right_rect,'center':center,'curve':curve,'player':player,'preview':preview,
        'graph':pygame.Rect(curve.x+58,curve.y+86,curve.w-88,curve.h-132),
        'timeline':pygame.Rect(player.x+16,player.bottom-22,player.w-32,8),
        'parts':parts,'poses':poses,'inspector':pygame.Rect(right_rect.x+1,TOP+36,right-2,right_rect.h-36),
        'split_left':pygame.Rect(left-2,TOP,7,h-TOP-STATUS),
        'split_right':pygame.Rect(right_rect.x-5,TOP,7,h-TOP-STATUS),
        'split_curve':pygame.Rect(center.x,curve.y-4,center.w,7)}


class UI(BaseUI):
    def __init__(self):
        super().__init__();self.hit_clip=None;self.tree_max_scroll=0;self.inspector_max_scroll=0;self.menu_rect=None
    def hit(self,name,rect,data=None):
        rect=pygame.Rect(rect)
        if self.hit_clip is not None:rect=rect.clip(self.hit_clip)
        if rect.w>0 and rect.h>0:super().hit(name,rect,data)
    def clip(self,rect=None):self.surface.set_clip(rect);self.hit_clip=rect
    def section(self,label,x,y,width):
        self.text(label,x,y,13,TEXT,True);pygame.draw.line(self.surface,BORDER,(x,y+27),(x+width,y+27))
    def render(self,app):
        w,h=app.size;L=app.rects;self.surface=pygame.Surface((w,h),pygame.SRCALPHA);self.hits=[];self.clip()
        self.box((0,0,w,TOP),BG);self.box(L['left'],PANEL);self.box(L['right'],PANEL)
        self.box(L['player'],PANEL);self.box(L['curve'],(20,25,34));self.box((0,h-STATUS,w,STATUS),(19,25,34))
        for key in ['split_left','split_right','split_curve']:
            rect=L[key];hover=rect.collidepoint(pygame.mouse.get_pos())
            self.box(rect,(64,85,105) if hover else BORDER);self.hit('splitter',rect,key)
        self.draw_bar(app);self.draw_tree(app);self.draw_preview_header(app);self.draw_player(app)
        self.draw_curve(app);self.draw_inspector(app)
        message=app.message
        if ' · ' in message:
            prefix,last=message.rsplit(' · ',1)
            if '\\' in last or '/' in last:message=prefix+' · '+Path(last).name
        self.text(message,16,h-23,12,AMBER if app.error else MUTED,width=w-340)
        self.text(f'{app.fps:.1f} FPS  |  갱신 60 Hz',w-16,h-23,12,MUTED,align='right')
        if app.menu:self.draw_menu(app)
        if app.modal:self.draw_modal(app)
        return self.surface
    def draw_bar(self,app):
        w,h=app.size
        x=8
        for key,(label,items) in MENUS.items():
            rect=pygame.Rect(x,0,64,32)
            if app.menu==key:self.box(rect,PANEL2)
            self.text(label,rect.centerx,6,14,TEXT,align='center');self.hit('menu_toggle',rect,key);x+=64
        self.text('표정 스튜디오',w-16,7,13,MUTED,align='right')
        pygame.draw.line(self.surface,BORDER,(0,32),(w,32))
        self.text(app.project.data['title'],16,46,16,TEXT,True,width=400)
        state='수정됨' if app.project.dirty else '저장됨' if app.project.path.exists() else '새 프로젝트'
        self.text('● '+state,430,49,12,AMBER if app.project.dirty else MUTED)
        clip=app.project.data['motion'].get('name','표정 전환')
        self.text('애니메이션  /  '+clip,w-16,46,14,TEXT,align='right')
        pygame.draw.line(self.surface,BORDER,(0,TOP-1),(w,TOP-1))
    def draw_menu(self,app):
        if app.menu=='curve_context':items=CURVE_CONTEXT;rect=context_rect(app.size,app.context_position)
        else:
            label,items=MENUS[app.menu];x=8+list(MENUS).index(app.menu)*64
            height=8+sum(10 if item is None else 32 for item in items)
            rect=pygame.Rect(x,32,300,height)
        x=rect.x;self.menu_rect=rect
        self.box(rect,(32,40,53),(70,85,105),4);y=rect.y+4
        for item in items:
            if item is None:pygame.draw.line(self.surface,BORDER,(x+10,y+4),(rect.right-10,y+4));y+=10;continue
            action,text,shortcut=item;enabled=True
            if action=='undo':enabled=bool(app.project.undo_stack)
            elif action=='redo':enabled=bool(app.project.redo_stack)
            elif action=='delete_curve_point':
                i,kind=app.curve_selection;enabled=kind=='node' and 0<i<len(app.curve['nodes'])-1
            row=pygame.Rect(x+4,y,292,32)
            if enabled and row.collidepoint(pygame.mouse.get_pos()):self.box(row,(46,67,83),radius=3)
            if (action=='wire' and app.wire) or (action=='mask' and app.mask_overlay):self.text('✓',x+9,y+6,13,ACCENT)
            self.text(text,x+25,y+6,13,TEXT if enabled else DIM)
            self.text(shortcut,rect.right-12,y+7,11,MUTED if enabled else DIM,align='right')
            if enabled:self.hit('menu_action',row,action)
            y+=32
    def panel_header(self,title,rect,detail=None):
        self.box((rect.x,rect.y,rect.w,36),(27,34,45))
        self.text(title,rect.x+PAD,rect.y+9,14,TEXT,True)
        if detail:self.text(detail,rect.right-PAD,rect.y+11,11,MUTED,align='right')
        pygame.draw.line(self.surface,BORDER,(rect.x,rect.y+35),(rect.right,rect.y+35))
    def draw_tree(self,app):
        left=app.rects['left'];parts=app.rects['parts'];poses=app.rects['poses']
        self.panel_header('리깅 파츠',left,'14개')
        self.text('연결 트랙 3개',left.x+PAD,TOP+47,12,MUTED)
        rows=[('mesh','Body',None)]
        for group,meshes in [('eye_l',['EyeApertureL','EyeInteriorL','LowerLidL','UpperLidL','BrowL']),
                             ('eye_r',['EyeApertureR','EyeInteriorR','LowerLidR','UpperLidR','BrowR']),
                             ('mouth',['MouthOpening','MouthInterior','MouthUpperLip'])]:
            rows.append(('group',group,group));rows.extend(('mesh',name,group) for name in meshes)
        self.tree_max_scroll=max(0,len(rows)*ROW-parts.h);app.tree_scroll=clamp(app.tree_scroll,0,self.tree_max_scroll)
        self.clip(parts);y=parts.y-int(app.tree_scroll)
        for kind,name,group in rows:
            rect=pygame.Rect(parts.x,y,parts.w,ROW-2)
            if kind=='group':
                selected=app.track==group
                if selected:self.box(rect,(33,54,67),radius=3)
                pygame.draw.polygon(self.surface,ACCENT,[(rect.x+9,y+10),(rect.x+17,y+10),(rect.x+13,y+15)])
                self.text(TRACKS[name][0],rect.x+27,y+4,13,TEXT,True)
                self.text('연결 트랙',rect.right-12,y+6,10,ACCENT if selected else MUTED,align='right')
                self.hit('select_track',rect,group)
            else:
                helper=app.source_meshes[name].get('render_role')=='clip-helper';hidden=name in app.project.data['hidden_meshes']
                if app.selected_mesh==name:self.box(rect,(41,52,70),radius=3)
                indent=36 if group else 17
                self.text('◇' if helper else '▧',rect.x+indent-17,y+5,12,MUTED)
                self.text(MESH_LABELS.get(name,name),rect.x+indent,y+4,13,MUTED if hidden else TEXT,width=rect.w-indent-48)
                self.hit('select_mesh',rect,(name,group))
                if helper:self.text('마스크',rect.right-9,y+7,10,MUTED,align='right')
                else:
                    eye=pygame.Rect(rect.right-26,y+8,14,11);self.box(eye,(44,96,82) if not hidden else PANEL,BORDER,2)
                    if not hidden:pygame.draw.line(self.surface,ACCENT,(eye.x+3,eye.centery),(eye.right-3,eye.centery),2)
                    self.hit('visibility',pygame.Rect(rect.right-35,y,32,ROW-2),name)
            y+=ROW
        self.clip()
        if self.tree_max_scroll>0:
            bar_h=max(28,parts.h*parts.h/(parts.h+self.tree_max_scroll))
            bar_y=parts.y+(parts.h-bar_h)*app.tree_scroll/self.tree_max_scroll
            self.box((parts.right-3,bar_y,3,bar_h),(79,98,121),radius=1)
        self.panel_header('키포즈',poses,TRACKS[app.track][0]+' 트랙')
        keys=app.track_data['keys'];start=max(0,min(app.key_index-2,len(keys)-4));y=poses.y+44
        for i,key in enumerate(keys[start:start+4],start):
            row=pygame.Rect(8,y,left.w-16,ROW)
            if i==app.key_index:self.box(row,(41,52,70),radius=3)
            self.text('◆',row.x+9,y+6,11,PINK if i==app.key_index else MUTED)
            self.text(key['label'],row.x+29,y+4,13,TEXT,width=row.w-110)
            self.text(f'{key["at"]:.3f}',row.right-10,y+4,13,MUTED,align='right')
            self.hit('select_key',row,i);y+=ROW+2
        y=poses.bottom-67;col=(left.w-2*PAD-GAP)//2
        self.button('add_key',(PAD,y,col,32),'키포즈 추가',size=12)
        self.button('delete_key',(PAD+col+GAP,y,col,32),'키포즈 삭제',enabled=0<app.key_index<len(keys)-1,size=12)
        self.text('값은 ParamSmile 기준 (0~1)',PAD,poses.bottom-25,11,MUTED)
    def draw_preview_header(self,app):
        c=app.rects['center'];header=pygame.Rect(c.x,TOP,c.w,36)
        self.panel_header('미리보기',header)
        x=c.right-414;y=TOP+4
        self.button('view_mode',(x,y,82,28),'전신 보기' if app.face else '얼굴 보기',size=12)
        self.button('wire',(x+90,y,58,28),'메시',active=app.wire,size=12)
        self.button('mask',(x+156,y,66,28),'마스크',active=app.mask_overlay,size=12)
        self.button('zoom_out',(x+234,y,28,28),'-',size=16)
        self.text(f'{app.zoom*100:.0f}%',x+295,y+5,12,MUTED,align='center')
        self.button('zoom_in',(x+329,y,28,28),'+',size=16)
        self.button('camera_reset',(x+365,y,42,28),'맞춤',size=11)
        p=app.rects['preview'];self.box((p.x+16,p.y+16,176,52),(23,32,43),BORDER,4)
        self.text('ParamSmile',p.x+28,p.y+23,12,MUTED);self.text(f'{app.value:.3f}',p.x+178,p.y+21,18,ACCENT,True,align='right')
        self.text(app.playback.status,p.x+28,p.y+46,12,TEXT)
        if app.building or app.pending_shape:
            label='형태 적용 중…' if app.building else '형태 변경 · 적용 대기'
            self.box((p.right-202,p.bottom-44,186,28),(50,42,30),radius=4)
            self.text(label,p.right-109,p.bottom-39,12,AMBER,align='center')
    def draw_player(self,app):
        p=app.rects['player'];x=p.x+PAD;y=p.y+10
        for name,label,width in [('seek_start','처음',48),('reverse','◀ 역재생',88),('forward','▶ 재생',88),('pause','일시정지' if app.playback.playing else '계속',76)]:
            self.button(name,(x,y,width,32),label,size=12);x+=width+GAP
        compact=p.w<800
        pose_x=p.x+PAD if compact else x+8;pose_y=y+38 if compact else y
        for label,value in [('중립',0.),('다문 미소',.5),('웃음',1.)]:
            self.button('pose',(pose_x,pose_y,72,28 if compact else 32),label,active=abs(app.value-value)<.001,data=value,size=12);pose_x+=80
        self.text(f'{app.playback.position*app.project.data["motion"]["duration"]:.2f} / {app.project.data["motion"]["duration"]:.2f} 초',p.right-PAD,y+7,12,MUTED,align='right')
        t=app.rects['timeline'];self.box(t,(49,61,79),radius=3)
        for key in app.track_data['keys']:
            px=t.x+t.w*inverse(app.project.data['motion']['curve'],key['at'])
            pygame.draw.line(self.surface,MUTED,(px,t.y-3),(px,t.bottom+3))
        self.hit('scrub',t.inflate(0,14))
    def draw_inspector(self,app):
        r=app.rects['right'];view=app.rects['inspector'];self.panel_header('속성',r)
        scroll=clamp(app.inspector_scroll,0,self.inspector_max_scroll);x=r.x+PAD;width=r.w-2*PAD
        y=view.y+16-int(scroll);start=y;self.clip(view)
        self.text('시간 보간' if app.mode=='time' else '형태 보간',x,y,18,TEXT,True);y+=32
        self.text('편집 대상: '+('애니메이션 전체' if app.mode=='time' else TRACKS[app.track][0]+' 연결 트랙'),x,y,12,ACCENT if app.mode=='time' else PINK);y+=24
        self.text('선택 파츠: '+MESH_LABELS.get(app.selected_mesh,app.selected_mesh),x,y,12,MUTED,width=width);y+=36
        self.text('한 방향 재생 시간 (초)',x,y,12,MUTED);y+=22
        self.field(app,'duration',(x,y,width,34),app.project.data['motion']['duration'],precision=2);y+=52
        self.section('보간 프리셋',x,y,width);y+=38;col=(width-GAP)//2
        for i,label in enumerate(PRESETS):
            self.button('preset',(x+(i%2)*(col+GAP),y+(i//2)*40,col,32),label,active=app.curve['preset']==label,data=label,size=12)
        y+=128;self.section('제어점',x,y,width);y+=38
        index,kind=app.curve_selection;index=min(index,len(app.curve['nodes'])-1)
        caption=f'기준점 {index+1}' if kind=='node' else f'기준점 {index+1} / '+('출력 핸들' if kind=='out' else '입력 핸들')
        self.text(caption,x,y,12,MUTED);y+=26
        disabled=kind=='node' and index in (0,len(app.curve['nodes'])-1)
        labels=['시간 (초)','ParamSmile'] if app.mode=='time' else ['파라미터','변형 비율']
        for i,field in enumerate(['curve_x','curve_y']):
            xx=x+i*(col+GAP);self.text(labels[i],xx,y,12,MUTED)
            self.field(app,field,(xx,y+22,col,34),app.field_value(field),enabled=not disabled)
        y+=72
        self.text('핸들 드래그로 곡선 조절',x,y,12,MUTED);y+=24
        self.text('기준점 추가: 아래 + 버튼 / 더블클릭',x,y,11,MUTED,width=width);y+=36
        if app.mode=='shape':
            key=app.track_data['keys'][app.key_index];self.section('선택 키포즈',x,y,width);y+=38
            self.text(key['label'],x,y,14,TEXT,True);y+=30
            for field,label in [('key_at','키 위치 (파라미터)'),('key_source','참조할 원본 자세 (0~1)')]:
                self.text(label,x,y,12,MUTED);y+=22
                self.field(app,field,(x,y,width,34),key['at'] if field=='key_at' else key['source'],enabled=field!='key_at' or 0<app.key_index<len(app.track_data['keys'])-1);y+=50
            self.button('apply_shape',(x,y,width,34),'형태 적용 / 미리보기 갱신',primary=app.pending_shape,size=12);y+=48
        self.section('재생 상태',x,y,width);y+=38
        self.text(app.playback.status+' · 끝 자세 유지',x,y,12,MUTED);y+=25
        self.text('형태 적용 대기' if app.pending_shape else '편집 형태와 미리보기 일치',x,y,12,AMBER if app.pending_shape else ACCENT);y+=36
        self.inspector_max_scroll=max(0,y-start+32-view.h);app.inspector_scroll=clamp(app.inspector_scroll,0,self.inspector_max_scroll)
        self.clip()
        if self.inspector_max_scroll>0:
            ratio=view.h/(view.h+self.inspector_max_scroll);height=max(32,view.h*ratio)
            pos=view.y+(view.h-height)*app.inspector_scroll/self.inspector_max_scroll
            self.box((view.right-5,pos,3,height),(79,98,121),radius=1)
    def draw_curve(self,app):
        c=app.rects['curve'];g=app.rects['graph'];color=BLUE if app.mode=='time' else PINK
        y=c.y+12
        self.button('mode_time',(c.x+16,y,106,32),'시간 곡선',active=app.mode=='time',size=13)
        self.button('mode_shape',(c.x+130,y,106,32),'형태 곡선',active=app.mode=='shape',size=13)
        x=c.right-264
        self.button('add_curve_point',(x,y,92,32),'+ 기준점',size=12)
        i,kind=app.curve_selection;enabled=kind=='node' and 0<i<len(app.curve['nodes'])-1
        self.button('delete_curve_point',(x+100,y,72,32),'점 삭제',enabled=enabled,size=12)
        self.button('reset_curve',(x+180,y,68,32),'초기화',size=12)
        y+=42
        if app.mode=='shape':
            keys=app.track_data['keys'];a,b=keys[app.segment:app.segment+2]
            self.text('편집: '+TRACKS[app.track][0]+' 연결 트랙',c.x+16,y,12,PINK)
            self.button('segment_prev',(c.x+200,y-4,26,26),'<',enabled=app.segment>0,size=13)
            self.text(f'{a["at"]:.3f} → {b["at"]:.3f}',c.x+238,y,12,MUTED)
            self.button('segment_next',(c.x+364,y-4,26,26),'>',enabled=app.segment<len(keys)-2,size=13)
        else:self.text('편집: 애니메이션 시간 → ParamSmile',c.x+16,y,12,BLUE)
        self.text(app.curve['preset'],c.right-16,y,12,MUTED,align='right')
        self.box(g,(16,23,32),BORDER,3)
        for i in range(5):
            f=i/4;x=g.x+g.w*f;yy=g.bottom-g.h*f
            pygame.draw.line(self.surface,(38,49,65),(x,g.y),(x,g.bottom))
            pygame.draw.line(self.surface,(38,49,65),(g.x,yy),(g.right,yy))
            self.text(f'{f:.2f}',g.x-12,yy-8,11,MUTED,align='right')
            if app.mode=='time':label=f'{f*app.project.data["motion"]["duration"]:.2f}s'
            else:
                a,b=app.track_data['keys'][app.segment:app.segment+2];label=f'{a["at"]+(b["at"]-a["at"])*f:.3f}'
            self.text(label,x,g.bottom+9,11,MUTED,align='center')
        for i in range(0,g.w,12):
            x=g.x+i;yy=g.bottom-i/g.w*g.h
            pygame.draw.line(self.surface,(64,78,98),(x,yy),(x+4,yy-4*g.h/g.w))
        points=[(g.x+g.w*i/220,g.bottom-g.h*evaluate(app.curve,i/220)) for i in range(221)]
        pygame.draw.lines(self.surface,color,False,points,2);self.hit('graph',g)
        nodes=app.curve['nodes']
        for i,node in enumerate(nodes):
            anchor=(g.x+node['x']*g.w,g.bottom-node['y']*g.h)
            for kind in ['in','out']:
                if (i==0 and kind=='in') or (i==len(nodes)-1 and kind=='out'):continue
                p=node[kind];xy=(g.x+p[0]*g.w,g.bottom-p[1]*g.h)
                pygame.draw.line(self.surface,(114,133,158),anchor,xy)
                pygame.draw.circle(self.surface,color if app.curve_selection==(i,kind) else PANEL2,xy,6)
                pygame.draw.circle(self.surface,color,xy,6,1);self.hit('curve_point',pygame.Rect(xy[0]-10,xy[1]-10,20,20),(i,kind))
            r=pygame.Rect(anchor[0]-5,anchor[1]-5,10,10)
            self.box(r,color if app.curve_selection==(i,'node') else PANEL2,color,2)
            if i not in (0,len(nodes)-1):self.hit('curve_point',r.inflate(10,10),(i,'node'))
        self.text('시간 (초)' if app.mode=='time' else '선택 구간의 파라미터',g.centerx,c.bottom-22,12,MUTED,align='center')
