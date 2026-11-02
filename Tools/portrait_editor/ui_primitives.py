"""Shared painting primitives. Workspace layout lives in workspace_ui.py."""
import pygame

BG=(15,18,25);PANEL=(23,28,37);PANEL2=(28,34,45);BORDER=(44,53,68)
TEXT=(226,233,242);MUTED=(135,151,174);DIM=(85,101,124)
ACCENT=(91,215,188);BLUE=(109,160,255);PINK=(235,149,184);AMBER=(239,193,105)


class Painter:
    def __init__(self):
        self.fonts={};self.text_cache={};self.hits=[];self.surface=None
    def font(self,size,bold=False):
        key=(size,bold)
        if key not in self.fonts:
            font=pygame.font.Font('C:/Windows/Fonts/malgun.ttf',size);font.set_bold(bold);self.fonts[key]=font
        return self.fonts[key]
    def text(self,value,x,y,size=14,color=TEXT,bold=False,align='left',width=None):
        value=str(value);font=self.font(size,bold)
        if width:
            while value and font.size(value)[0]>width:value=value[:-2]+'…'
        key=(value,size,color,bold)
        if key not in self.text_cache:
            if len(self.text_cache)>1800:self.text_cache.clear()
            self.text_cache[key]=font.render(value,True,color)
        rendered=self.text_cache[key];rect=rendered.get_rect(topleft=(x,y))
        if align=='center':rect.centerx=x
        elif align=='right':rect.right=x
        self.surface.blit(rendered,rect);return rect
    def box(self,rect,color=PANEL,border=None,radius=0):
        pygame.draw.rect(self.surface,color,rect,border_radius=radius)
        if border:pygame.draw.rect(self.surface,border,rect,1,border_radius=radius)
    def hit(self,name,rect,data=None):self.hits.append((name,pygame.Rect(rect),data))
    def button(self,name,rect,label,active=False,enabled=True,primary=False,data=None,size=13):
        rect=pygame.Rect(rect);hover=enabled and rect.collidepoint(pygame.mouse.get_pos())
        color=(39,78,73) if active or primary else (42,51,67) if hover else PANEL2
        self.box(rect,color,ACCENT if active or primary else BORDER,5)
        self.text(label,rect.centerx,rect.y+(rect.h-size-4)//2,size,ACCENT if active or primary else TEXT if enabled else DIM,align='center')
        if enabled:self.hit(name,rect,data)
    def field(self,app,name,rect,value,enabled=True,precision=3):
        rect=pygame.Rect(rect);editing=app.edit_field==name
        self.box(rect,(15,21,30),ACCENT if editing else BORDER,4)
        text=app.edit_text if editing else f'{value:.{precision}f}'
        self.text(text+('|' if editing else ''),rect.x+10,rect.y+5,14,TEXT if enabled else DIM)
        if enabled:self.hit('field',rect,name)
    def draw_modal(self,app):
        shade=pygame.Surface(app.size,pygame.SRCALPHA);shade.fill((5,9,16,185));self.surface.blit(shade,(0,0))
        rect=pygame.Rect(0,0,500,198);rect.center=(app.size[0]/2,app.size[1]/2)
        self.box(rect,PANEL2,BORDER,10);self.text('저장하지 않은 변경이 있어',rect.x+24,rect.y+22,19,TEXT,True)
        self.text('작업을 저장하고 계속할까?',rect.x+24,rect.y+65,13,MUTED)
        for i,(action,label) in enumerate([('modal_cancel','취소'),('modal_discard','저장 안 함'),('modal_save','저장 후 계속')]):
            self.button(action,(rect.x+24+i*153,rect.y+125,143,36),label,primary=i==2)
