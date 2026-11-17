"""CPU 궤적·판정과 분리한 Compute Trail 정점 생성. GPU 결과를 다시 읽지 않는다."""

from array import array
from contextlib import contextmanager
import ctypes as ct
from math import ceil

from ferrial_drive.diagnostics.gpu_profile import bind_gl
from .bicubic import BicubicSampler
from .sword_trail_geometry import sweep_runs


SSBO = 0x90D2
SSBO_BINDING = 0x90D3

COMPUTE_SHADER = b'''#version 430
layout(local_size_x=64) in;
layout(std430,binding=0) readonly buffer Controls { vec4 c[]; };
layout(std430,binding=1) readonly buffer Jobs { vec4 jobs[]; };
layout(std430,binding=2) writeonly buffer Vertices { vec4 output_data[]; };
uniform uint job_count;
uniform float sample_seconds;
uniform float inner_ratio;
vec4 pointAt(int start,int count,int index) {
    index=clamp(index,0,count);
    return index==0 ? c[start*4] : c[(start+index-1)*4+1];
}
vec4 smoothPoint(int start,int count,int index) {
    index=clamp(index,0,count);
    if (index==0 || index==count) return pointAt(start,count,index);
    return (pointAt(start,count,index-2)+pointAt(start,count,index-1)*2.0+
            pointAt(start,count,index)*3.0+pointAt(start,count,index+1)*2.0+
            pointAt(start,count,index+2))/9.0;
}
vec4 curve(int start,int count,int index,float t) {
    vec4 a=smoothPoint(start,count,index-1),b=smoothPoint(start,count,index);
    vec4 cc=smoothPoint(start,count,index+1),d=smoothPoint(start,count,index+2);
    return (b*2.0+(cc-a)*t+(a*2.0-b*5.0+cc*4.0-d)*t*t+
            (b*3.0-a-cc*3.0+d)*t*t*t)*0.5;
}
vec2 normalOf(vec2 tangent,vec2 fallback) {
    float size=length(tangent);
    return size>0.000000001 ? vec2(-tangent.y,tangent.x)/size : fallback;
}
void main() {
    uint job=gl_GlobalInvocationID.x;
    if (job>=job_count) return;
    ivec4 info=ivec4(jobs[job*2]);
    vec4 shape=jobs[job*2+1];
    int row=info.x,start=info.y,count=info.z,part=info.w;
    vec4 times=c[row*4+2],ink=c[row*4+3];
    vec2 positions[4]; vec2 uv[4]; float alpha[4];
    if (part<4) {
        vec4 a=c[row*4],b=c[row*4+1];
        float created=times.x;
        float previous=row==start ? times.x-sample_seconds : c[(row-1)*4+2].x;
        float begin=previous,end=created;
        if (part<3) {
            a=curve(start,count,row-start,float(part)/3.0);
            b=curve(start,count,row-start,float(part+1)/3.0);
            begin=mix(previous,created,float(part)/3.0);
            end=mix(previous,created,float(part+1)/3.0);
        }
        if (row==start && (part==0 || part==3)) begin=times.z;
        float duration=max(0.000000001,times.w-times.z);
        float ua=max(0.0,(begin-times.z)/duration),ub=max(0.0,(end-times.z)/duration);
        positions[0]=mix(a.xy,a.zw,inner_ratio); positions[1]=a.zw;
        positions[2]=b.zw; positions[3]=mix(b.xy,b.zw,inner_ratio);
        uv[0]=vec2(ua,0); uv[1]=vec2(ua,1); uv[2]=vec2(ub,1); uv[3]=vec2(ub,0);
        float opacity=clamp(1.0+end/times.y,0.0,1.0);
        for (int i=0;i<4;++i) alpha[i]=roundEven(255.0*opacity*opacity*ink.a)/255.0;
    } else {
        vec2 tip=c[row*4].zw;
        vec2 left=tip+(c[row*4].xy-tip)*shape.w;
        vec2 right=tip+(c[row*4+1].xy-tip)*shape.w;
        vec2 n0=normalOf(tip-left,vec2(0,1));
        vec2 n1=normalOf(right-left,n0); if (dot(n0,n1)<0.0) n1=-n1;
        vec2 n2=normalOf(right-tip,n1); if (dot(n1,n2)<0.0) n2=-n2;
        int leg=part-4;
        vec2 a=leg==0 ? left : tip,b=leg==0 ? tip : right;
        vec2 na=leg==0 ? n0 : n1,nb=leg==0 ? n1 : n2;
        positions[0]=a-na*shape.x; positions[1]=a+na*shape.x;
        positions[2]=b+nb*shape.x; positions[3]=b-nb*shape.x;
        float ua=float(leg)*0.5,ub=float(leg+1)*0.5;
        uv[0]=vec2(ua,0); uv[1]=vec2(ua,1); uv[2]=vec2(ub,1); uv[3]=vec2(ub,0);
        float opacity=clamp(1.0+times.x/times.y,0.0,1.0);
        for (int i=0;i<4;++i) {
            float strength=(leg==0 && i<2 || leg==1 && i>=2) ? shape.z : 1.0;
            alpha[i]=roundEven(255.0*opacity*opacity*ink.a*shape.y*strength)/255.0;
        }
    }
    for (int i=0;i<4;++i) {
        output_data[job*8+uint(i)*2]=vec4(positions[i],uv[i]);
        output_data[job*8+uint(i)*2+1]=vec4(ink.rgb,alpha[i]);
    }
}
'''

VERTEX_SHADER = b'''#version 430
layout(std430,binding=2) readonly buffer Vertices { vec4 data[]; };
uniform vec2 outputSize;
uniform float targetFlip;
uniform vec4 transform;
uniform vec2 camera_offset;
uniform float camera_zoom;
out vec2 uv;
out vec4 ink;
void main() {
    int corner[6]=int[6](0,1,2,0,2,3);
    int index=(gl_InstanceID*4+corner[gl_VertexID])*2;
    vec4 value=data[index]; uv=value.zw; ink=data[index+1];
    vec2 screen=transform.xy+(value.xy*camera_zoom+camera_offset)*transform.zw;
    vec2 ndc=screen/outputSize;
    gl_Position=vec4(ndc.x*2.0-1.0,(1.0-ndc.y*2.0)*targetFlip,0,1);
}
'''

FRAGMENT_SHADER = b'''#version 430
uniform sampler2D artwork;
in vec2 uv;
in vec4 ink;
out vec4 result;
void main() { result=ink*texture(artwork,uv); }
'''


def trail_inputs(effects, color):
    """구간 분류와 작은 제어점 전송만 수행한다. 곡선·정점 객체는 만들지 않는다."""
    controls, jobs, cores = array("f"), [], []
    runs = sweep_runs(effects.sections, effects.settings.get("trail_min_sweep_ratio", .12))
    sample = effects.settings.get("sample_seconds", 1/240)
    starts = []
    for rows in runs:
        start = len(controls)//16
        starts.append(start)
        curved = not rows[0].chevron and len(rows) >= 3
        low = rows[0].created_seconds - sample*(5/3 if curved else 1)
        high = rows[-1].created_seconds
        for row in rows:
            profile = effects.profiles[row.energy_level-1]
            rgb = getattr(row, "color", None) or profile.get("color", color)
            ink = [int(rgb[i:i+2],16)/255 for i in (1,3,5)]
            opacity = profile.get("trail_opacity", .3)
            if row.chevron:
                left, tip, right = row.chevron
                a,b = (left.x,left.y,tip.x,tip.y),(right.x,right.y,0,0)
                next_start = min((r.created_seconds for r in effects.sections if r.strike_id > row.strike_id), default=None)
                if next_start is not None:
                    opacity *= max(0,1-(effects.time_seconds-next_start)/effects.settings.get("thrust_transition_fade_seconds",.08))
            else:
                a,b = (row.root_a.x,row.root_a.y,row.tip_a.x,row.tip_a.y),(row.root_b.x,row.root_b.y,row.tip_b.x,row.tip_b.y)
            controls.extend((*a,*b,row.created_seconds-effects.time_seconds,row.lifetime_seconds,
                             low-effects.time_seconds,high-effects.time_seconds,*ink,opacity))
    drawn = set()
    for rows,start in reversed(list(zip(runs,starts))):
        for index in reversed(range(len(rows))):
            row = rows[index]
            if row.chevron:
                if row.strike_id in drawn:
                    continue
                drawn.add(row.strike_id)
                if controls[(start+index)*16+15] <= 0 or effects.opacity(row) <= 0:
                    continue
                profile = effects.profiles[row.energy_level-1]
                scale = effects.settings.get("thrust_visual_scale",1)
                reach = profile["reach_scale"]/effects.profiles[0]["reach_scale"]
                for target,width,strength in ((jobs,effects.settings.get("thrust_outer_half_width_pixels",2.5),.9),
                                              (cores,effects.settings.get("thrust_core_half_width_pixels",.8),1)):
                    for leg in range(2):
                        target.extend((start+index,start,len(rows),4+leg,width*reach*scale,strength,
                                       effects.settings.get("thrust_tail_opacity",.8),scale))
            else:
                parts = (2,1,0) if len(rows)>=3 else (3,)
                for part in parts:
                    jobs.extend((start+index,start,len(rows),part,0,0,0,0))
    return controls, array("f",jobs+cores)


class ComputeSwordTrail(BicubicSampler):
    def __init__(self,pico):
        self.buffers, self.capacities = [], [0,0,0]
        self.compute_program = 0
        self.last_job_count = self.upload_bytes = 0
        super().__init__(pico,None,vertex_shader=VERTEX_SHADER,fragment_shader=FRAGMENT_SHADER,
                         extra_uniforms=("transform","camera_offset","camera_zoom"))
        try:
            signatures = {
                "glGenBuffers": (None,[ct.c_int,ct.c_void_p]), "glDeleteBuffers": (None,[ct.c_int,ct.c_void_p]),
                "glBindBuffer": (None,[ct.c_uint,ct.c_uint]),
                "glBufferData": (None,[ct.c_uint,ct.c_ssize_t,ct.c_void_p,ct.c_uint]),
                "glBufferSubData": (None,[ct.c_uint,ct.c_ssize_t,ct.c_ssize_t,ct.c_void_p]),
                "glGetBufferSubData": (None,[ct.c_uint,ct.c_ssize_t,ct.c_ssize_t,ct.c_void_p]),
                "glBindBufferBase": (None,[ct.c_uint,ct.c_uint,ct.c_uint]),
                "glGetIntegeri_v": (None,[ct.c_uint,ct.c_uint,ct.c_void_p]),
                "glDispatchCompute": (None,[ct.c_uint,ct.c_uint,ct.c_uint]),
                "glMemoryBarrier": (None,[ct.c_uint]), "glUniform1ui": (None,[ct.c_int,ct.c_uint]),
                "glDrawArraysInstanced": (None,[ct.c_uint,ct.c_int,ct.c_int,ct.c_int]),
                "glGetProgramInfoLog": (None,[ct.c_uint,ct.c_int,ct.c_void_p,ct.c_void_p])}
            for name,(result,args) in signatures.items():
                setattr(self,name,bind_gl(pico,name,result,args))
            self.compute_program = self._compile_compute()
            self.compute_uniforms = {name:self.glGetUniformLocation(self.compute_program,name.encode()) for name in
                                     ("job_count","sample_seconds","inner_ratio")}
            names = (ct.c_uint*3)()
            self.glGenBuffers(3,names)
            self.buffers = list(names)
        except BaseException:
            self.close()
            raise

    def _compile_compute(self):
        shader,program = self.glCreateShader(0x91B9),0
        try:
            source = ct.c_char_p(COMPUTE_SHADER)
            self.glShaderSource(shader,1,ct.byref(source),None)
            self.glCompileShader(shader)
            status = ct.c_int()
            self.glGetShaderiv(shader,0x8B81,ct.byref(status))
            if not status.value:
                message = ct.create_string_buffer(4096)
                self.glGetShaderInfoLog(shader,4096,None,message)
                raise RuntimeError("Trail Compute 컴파일 실패: "+message.value.decode(errors="replace"))
            program = self.glCreateProgram()
            self.glAttachShader(program,shader)
            self.glLinkProgram(program)
            self.glGetProgramiv(program,0x8B82,ct.byref(status))
            if not status.value:
                message = ct.create_string_buffer(4096)
                self.glGetProgramInfoLog(program,4096,None,message)
                raise RuntimeError("Trail Compute 연결 실패: "+message.value.decode(errors="replace"))
            return program
        except BaseException:
            if program:
                self.glDeleteProgram(program)
            raise
        finally:
            self.glDeleteShader(shader)

    @contextmanager
    def state(self):
        generic,indexed = self.integer(SSBO_BINDING),[]
        for index in range(3):
            value = ct.c_int()
            self.glGetIntegeri_v(SSBO_BINDING,index,ct.byref(value))
            indexed.append(value.value)
        try:
            for index,name in enumerate(self.buffers):
                self.glBindBufferBase(SSBO,index,name)
            yield
        finally:
            for index,name in enumerate(indexed):
                self.glBindBufferBase(SSBO,index,name)
            self.glBindBuffer(SSBO,generic)

    def _reserve(self,index,size):
        self.glBindBuffer(SSBO,self.buffers[index])
        if size>self.capacities[index]:
            self.capacities[index] = max(1024,1<<(size-1).bit_length())
            self.glBufferData(SSBO,self.capacities[index],None,0x88E8)

    def generate(self,effects,color):
        controls,jobs = trail_inputs(effects,color)
        self._dispatch_inputs(controls,jobs,effects.settings)

    def _dispatch_inputs(self,controls,jobs,settings):
        self.last_job_count = len(jobs)//8
        self.upload_bytes = (len(controls)+len(jobs))*4
        if not self.last_job_count:
            return
        for index,values in enumerate((controls,jobs)):
            self._reserve(index,len(values)*4)
            self.glBufferSubData(SSBO,0,len(values)*4,ct.c_void_p(values.buffer_info()[0]))
        self._reserve(2,self.last_job_count*128)
        self.glUseProgram(self.compute_program)
        self.glUniform1ui(self.compute_uniforms["job_count"],self.last_job_count)
        self.glUniform1f(self.compute_uniforms["sample_seconds"],settings.get("sample_seconds",1/240))
        self.glUniform1f(self.compute_uniforms["inner_ratio"],settings.get("trail_inner_ratio",.62))
        self.glDispatchCompute(ceil(self.last_job_count/64),1,1)
        self.glMemoryBarrier(0x2000)

    def render(self,effects,camera,renderer,texture,color):
        with self.batch(),self.state():
            self.generate(effects,color)
            self._draw_generated(texture,camera.world_to_screen((0,0)),getattr(camera,"zoom",1))

    def _draw_generated(self,texture,camera_offset,camera_zoom=1):
        if not self.last_job_count:
            return
        self.glUseProgram(self.program)
        self.glUniform2f(self.uniforms["camera_offset"],*camera_offset)
        self.glUniform1f(self.uniforms["camera_zoom"],camera_zoom)
        sx,sy = ct.c_float(),ct.c_float()
        self.pico.SDL_RenderGetScale(self.pico.renderer,ct.byref(sx),ct.byref(sy))
        self.glUniform4f(self.uniforms["transform"],*self.viewport[:2],sx.value,sy.value)
        enabled = self.glIsEnabled(0x0DE1)
        try:
            if self.pico.SDL_GL_BindTexture(texture,None,None):
                raise RuntimeError("Trail 텍스처 연결 실패")
            self.glDrawArraysInstanced(0x0004,0,6,self.last_job_count)
        finally:
            self.pico.SDL_GL_UnbindTexture(texture)
            (self.glEnable if enabled else self.glDisable)(0x0DE1)

    def prepare(self,settings,texture):
        """로딩 중 버퍼 상한과 실제 Compute·그리기를 준비한다. 화면·게임 상태는 보존한다."""
        maximum = settings.get('max_sections',192)
        if type(maximum) is not int or maximum < 1:
            raise ValueError('Trail 구간 상한은 양의 정수여야 한다.')
        p = self.pico
        target = p.SDL_GetRenderTarget(p.renderer)
        scale_x,scale_y = ct.c_float(),ct.c_float()
        viewport,clip = p.SDL_Rect(),p.SDL_Rect()
        p.SDL_RenderGetScale(p.renderer,ct.byref(scale_x),ct.byref(scale_y))
        p.SDL_RenderGetViewport(p.renderer,ct.byref(viewport))
        p.SDL_RenderGetClipRect(p.renderer,ct.byref(clip))
        clipped = p.SDL_RenderIsClipEnabled(p.renderer)
        scratch = p.SDL_CreateTexture(p.renderer,p.SDL_PIXELFORMAT_RGBA8888,p.SDL_TEXTUREACCESS_TARGET,8,8)
        if not scratch:
            raise RuntimeError('Trail 사전 실행 대상 생성 실패')
        try:
            if p.SDL_SetRenderTarget(p.renderer,scratch):
                raise RuntimeError('Trail 사전 실행 대상 연결 실패')
            p.SDL_RenderSetScale(p.renderer,1,1)
            p.SDL_RenderSetViewport(p.renderer,None)
            p.SDL_RenderSetClipRect(p.renderer,None)
            with self.batch(),self.state():
                # 일반 곡선 3개·찌르기 4개 job/구간 중 더 큰 상한으로 예약한다.
                for index,size in enumerate((maximum*64,maximum*4*32,maximum*4*128)):
                    self._reserve(index,size)
                controls = array('f',(1,1,6,1,1,2,6,2,-.001,.26,-.004,0,1,1,1,.5))
                jobs = array('f',(0,0,1,3,0,0,0,0, 0,0,1,4,1,.9,.8,1, 0,0,1,5,1,1,.8,1))
                self._dispatch_inputs(controls,jobs,settings)
                self._draw_generated(texture,(0,0))
                bind_gl(p,'glFinish',None,[])()
        finally:
            p.SDL_SetRenderTarget(p.renderer,target)
            p.SDL_RenderSetScale(p.renderer,scale_x.value,scale_y.value)
            p.SDL_RenderSetViewport(p.renderer,ct.byref(viewport))
            p.SDL_RenderSetClipRect(p.renderer,ct.byref(clip) if clipped else None)
            p.SDL_DestroyTexture(scratch)
            self.last_job_count = self.upload_bytes = 0

    def close(self):
        for name in self.buffers:
            value = ct.c_uint(name)
            self.glDeleteBuffers(1,ct.byref(value))
        self.buffers.clear()
        if self.compute_program:
            self.glDeleteProgram(self.compute_program)
            self.compute_program = 0
        if self.program:
            self.glDeleteProgram(self.program)
            self.program = 0
