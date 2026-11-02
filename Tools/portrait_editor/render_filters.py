"""Editor-owned Cubism shader variants. Installed live2d-py is left intact."""
from pathlib import Path
import json
import live2d

FILTER_GLSL=r'''
// Catmull-Rom reconstruction at source texel centers, for magnification only.
vec4 sampleArtwork(sampler2D image, vec2 uv) {
    vec2 size = vec2(textureSize(image, 0));
    vec2 footprint = fwidth(uv) * size;
    if (max(footprint.x, footprint.y) > 1.0) return texture2D(image, uv);
    vec2 p = uv * size - 0.5;
    vec2 base = floor(p), f = fract(p);
    vec2 f2=f*f, f3=f2*f;
    vec4 wx=vec4(-0.5*f.x+f2.x-0.5*f3.x,1.0-2.5*f2.x+1.5*f3.x,
                  0.5*f.x+2.0*f2.x-1.5*f3.x,-0.5*f2.x+0.5*f3.x);
    vec4 wy=vec4(-0.5*f.y+f2.y-0.5*f3.y,1.0-2.5*f2.y+1.5*f3.y,
                  0.5*f.y+2.0*f2.y-1.5*f3.y,-0.5*f2.y+0.5*f3.y);
    vec4 result=vec4(0.0);
    for(int j=0;j<4;++j) for(int i=0;i<4;++i)
        result += textureLod(image,(base+vec2(float(i-1),float(j-1))+0.5)/size,0.0)*wx[i]*wy[j];
    // A mild detail boost; bound ringing to nearby source values.
    vec4 a=textureLod(image,(base+vec2(0.5,0.5))/size,0.0);
    vec4 b=textureLod(image,(base+vec2(1.5,0.5))/size,0.0);
    vec4 c=textureLod(image,(base+vec2(0.5,1.5))/size,0.0);
    vec4 d=textureLod(image,(base+vec2(1.5,1.5))/size,0.0);
    vec4 lo=min(min(a,b),min(c,d)), hi=max(max(a,b),max(c,d));
    result.rgb += 0.12*(result.rgb-(a.rgb+b.rgb+c.rgb+d.rgb)*0.25);
    result=clamp(result,lo,hi);
    return clamp(result,0.0,1.0);
}
// Small spatial mask filter, not an expression opacity fade.
vec4 sampleEyeMask(sampler2D image, vec2 uv) {
    vec2 d=0.45/vec2(textureSize(image,0));
    return (texture2D(image,uv)*4.0+
        texture2D(image,uv+vec2(d.x,0.0))+texture2D(image,uv-vec2(d.x,0.0))+
        texture2D(image,uv+vec2(0.0,d.y))+texture2D(image,uv-vec2(0.0,d.y)))/8.0;
}
'''

def prepare(runtime_root,mode='sharp'):
    runtime_root=Path(runtime_root)/('shader-runtime-'+mode)
    destination=runtime_root/'FrameworkShaders';destination.mkdir(parents=True,exist_ok=True)
    source=Path(live2d.__file__).parent/'FrameworkShaders'
    changed=[]
    for path in source.iterdir():
        if path.suffix not in {'.vert','.frag'}:continue
        text=path.read_text(encoding='utf-8')
        if mode=='sharp':
            text=text.replace('#version 120','#version 130')
            if path.suffix=='.frag' and path.name!='FragShaderSrcSetupMask.frag':
                uses_art='texture2D(s_texture0, v_texCoord)' in text
                uses_mask='texture2D(s_texture1, v_clipPos.xy / v_clipPos.w)' in text
                if uses_art or uses_mask:
                    text=text.replace('void main()',FILTER_GLSL+'\nvoid main()')
                    text=text.replace('texture2D(s_texture0, v_texCoord)','sampleArtwork(s_texture0, v_texCoord)')
                    text=text.replace('texture2D(s_texture1, v_clipPos.xy / v_clipPos.w)','sampleEyeMask(s_texture1, v_clipPos.xy / v_clipPos.w)')
                    if 'PremultipliedAlpha' in path.name:
                        text=text.replace('vec4 texColor = sampleArtwork(s_texture0, v_texCoord);','vec4 texColor = sampleArtwork(s_texture0, v_texCoord);\n    texColor.rgb = min(texColor.rgb, vec3(texColor.a));')
                    changed.append(path.name)
        (destination/path.name).write_text(text,encoding='utf-8')
    (runtime_root/'filter-info.json').write_text(json.dumps({'mode':mode,'modified_shader_variants':changed,'source':'Installed Live2D FrameworkShaders copied into this project; original copyright headers retained'},indent=2),encoding='utf-8')
    return runtime_root
