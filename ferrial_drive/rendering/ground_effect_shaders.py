"""지면 효과의 공통 음영 계산과 개별·인스턴스 입력 선언."""

VERTEX_SHADER = b'''#version 120
uniform vec2 outputSize;
uniform float targetFlip;
uniform vec2 quadCenter;
uniform vec2 rotation;
uniform float mirrorX;
varying vec2 texel;
varying vec2 screenPoint;
void main() {
    vec2 p=gl_Vertex.xy-quadCenter;
    p.x*=mirrorX;
    p=quadCenter+vec2(rotation.x*p.x-rotation.y*p.y,rotation.y*p.x+rotation.x*p.y);
    p/=outputSize;
    gl_Position=vec4(p.x*2.0-1.0,(1.0-p.y*2.0)*targetFlip,0.0,1.0);
    screenPoint=p*outputSize;
    texel=gl_MultiTexCoord0.xy;
}
'''

PARTICLE_FIELDS = (('vec4', 'frameBounds'), ('vec4', 'ink'), ('float', 'fade'), ('float', 'cutoff'), ('float', 'detail'), ('float', 'roundness'), ('int', 'mode'), ('int', 'depthMode'), ('vec2', 'emitterOrigin'), ('float', 'nearRadius'), ('float', 'headFeather'))

FRAGMENT_BODY = b'''void main() {
    float nearWeight=1.0-smoothstep(nearRadius-3.0,nearRadius+3.0,distance(screenPoint,emitterOrigin));
    float depthWeight=depthMode==1 ? 1.0-nearWeight : (depthMode==2 ? nearWeight : 1.0);
    if(depthWeight<0.001) discard;
    vec2 uv=(texel-frameBounds.xy)/(frameBounds.zw-frameBounds.xy);
    if(mode==3) {
        float radius=length((uv-0.5)*2.0);
        float a=(1.0-smoothstep(0.4,1.0,radius))*fade*ink.a*depthWeight;
        if(a<0.02) discard;
        vec3 rgb=mix(ink.rgb,vec3(1.0),(1.0-smoothstep(0.0,0.45,radius))*0.65);
        fragmentColor=vec4(rgb,a);
    } else if(mode==2 || mode==4) {
        float across=uv.y-0.5;
        float streak=1.0;
        if(mode==4) {
            float tail=1.0-uv.x;
            across+=tail*tail*(0.025*sin(uv.x*10.0)+0.012*sin(uv.x*23.0));
            across/=mix(0.4,1.0,smoothstep(0.0,0.7,uv.x));
            streak-=0.12*tail*(0.5+0.5*sin(across*110.0+uv.x*4.0));
        }
        float a=pow(uv.x,0.6)*exp(-pow(across*4.0,2.0))*streak*fade*ink.a*depthWeight;
        a*=smoothstep(0.0,headFeather,1.0-uv.x);
        if(a<0.02) discard;
        float core=mode==4 ? (1.0-smoothstep(0.015,0.09,abs(across)))*smoothstep(0.0,0.3,uv.x) : 0.0;
        fragmentColor=vec4(mix(ink.rgb,vec3(1.0),core),a);
    } else {
        vec4 color=sample_artwork(clamp(texel,frameBounds.xy+0.5,frameBounds.zw-0.5)/atlasSize);
        color.rgb=mix(vec3(0.72),color.rgb,detail);
        float circle=1.0-smoothstep(0.24,0.5,length(uv-0.5));
        color.a=mix(color.a,circle,roundness);
        if(mode==0) {
            float noise=fract(sin(dot(floor(gl_FragCoord.xy),vec2(12.9898,78.233)))*43758.5453);
            if(color.a<cutoff || noise>fade) discard;
            fragmentColor=vec4(color.rgb*ink.rgb,1.0);
        } else {
            float edge=smoothstep(0.0,0.08,min(min(uv.x,1.0-uv.x),min(uv.y,1.0-uv.y)));
            float a=color.a*fade*ink.a*edge*depthWeight;
            if(a<0.02) discard;
            fragmentColor=vec4(color.rgb*ink.rgb,a);
        }
    }
}
'''

def fragment_shader(*, instanced=False):
    version = "#version 330\n" if instanced else "#version 120\n"
    qualifier = "flat in" if instanced else "uniform"
    declarations = "\n".join(f"{qualifier} {kind} {name};" for kind, name in PARTICLE_FIELDS)
    varying = "in" if instanced else "varying"
    output = "out vec4 fragmentColor;" if instanced else "#define fragmentColor gl_FragColor"
    sample = "texture" if instanced else "texture2D"
    header = (version + "uniform sampler2D artwork;\nuniform vec2 atlasSize;\n" + declarations
              + f"\n{varying} vec2 texel;\n{varying} vec2 screenPoint;\n{output}\n"
              + f"vec4 sample_artwork(vec2 uv) {{ return {sample}(artwork, uv); }}\n")
    return header.encode() + FRAGMENT_BODY


FRAGMENT_SHADER = fragment_shader()
INSTANCED_FRAGMENT_SHADER = fragment_shader(instanced=True)
