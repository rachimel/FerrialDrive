"""파츠 아틀라스의 보간·깊이 합성과 GLSL 입력 제출."""

from contextlib import nullcontext
import ctypes as ct

from ferrial_drive.diagnostics.texture_metrics import bind_gl

from .atlas_texture_cache import bind_atlas_textures
from .gl_pass import TexturedQuadPass
from .part_motion_atlas import MAX_PARTS
from .part_pbr import PBR_FUNCTIONS, PBR_UNIFORMS


PART_SAMPLE_FIELDS = (("colorA", "color", "a", "color"), ("colorB", "color", "b", "color"),
                      ("forwardRects", "vector", "a", "forward"), ("backwardRects", "vector", "b", "backward"),
                      ("energyA", "energy", "a", "energy"), ("energyB", "energy", "b", "energy"),
                      ("depthA", "depth", "a", "depth"), ("depthB", "depth", "b", "depth"))
PBR_SAMPLE_FIELDS = (("materialA", "material", "a", "material"), ("materialB", "material", "b", "material"))
COAT_SAMPLE_FIELDS = (("coatA", "coat", "a", "coat"), ("coatB", "coat", "b", "coat"))


PART_SHADER = '''#version 120
#define PARTS PART_LIMIT
#ifdef ANGULAR
#define VIEWS (PARTS*2)
uniform vec4 angleMatrices[12], angleRects[PARTS], angleOrigin, angleWeights;
uniform float waistDepthShift;
#else
#define VIEWS PARTS
#endif
uniform vec4 bankData[BANKS];
uniform vec4 colorA[VIEWS], colorB[VIEWS], forwardRects[VIEWS], backwardRects[VIEWS];
uniform vec4 energyA[VIEWS], energyB[VIEWS], depthA[VIEWS], depthB[VIEWS], crops[VIEWS], shifts[VIEWS];
#ifdef PBR
uniform vec4 materialA[VIEWS], materialB[VIEWS];
uniform float depthOutput;
#endif
#ifdef COAT
uniform vec4 coatA[VIEWS], coatB[VIEWS];
#endif
uniform vec4 flowSteps[VIEWS];
#ifdef PART_PAGES
uniform vec4 energyPlacementA[VIEWS], energyPlacementB[VIEWS];
#endif
#ifdef FRAME_CROP
uniform vec4 colorPlacementA[VIEWS], colorPlacementB[VIEWS], depthPlacementA[VIEWS], depthPlacementB[VIEWS];
#endif
uniform vec4 energyTint, rimLight, modulation;
#ifdef DEFERRED_SURFACE
uniform float deferredProfile;
#define PART_OUTPUT gl_FragData[0]
#else
#define PART_OUTPUT gl_FragColor
#endif
#ifdef PART_INSTANCES
in float localPhase;
#else
uniform float localPhase;
#endif
uniform float partCount, effectOpacity, brightness, realtimeLight;
uniform vec4 colorMix;
varying vec2 texel;
#ifdef CACHE_KEYPOSE_SAMPLES
flat in ivec4 sampleTile;
flat in int sampleBase;
uniform vec4 sourceRect;
#ifdef KEYPOSE_SAMPLES_FP16
#define KEYPOSE_SAMPLE_TYPE uvec2
#else
#define KEYPOSE_SAMPLE_TYPE vec4
#endif
#ifdef DEPTH_COVERAGE
layout(std430,binding=KEYPOSE_BINDING) writeonly buffer KeyposeSamples { KEYPOSE_SAMPLE_TYPE samples[]; };
#else
layout(std430,binding=KEYPOSE_BINDING) readonly buffer KeyposeSamples { KEYPOSE_SAMPLE_TYPE samples[]; };
#endif
ivec2 samplePixel() {
    return ivec2(gl_FragCoord.xy)-sampleTile.xy;
}
int sampleIndex(int part) {
    ivec2 pixel=samplePixel();
    return sampleBase+(pixel.y*sampleTile.z+pixel.x)*PARTS+part;
}
#ifdef KEYPOSE_SAMPLES_FP16
vec4 decodeKeyposeSamples(uvec2 packedPoints) {
    return vec4(unpackHalf2x16(packedPoints.x),unpackHalf2x16(packedPoints.y));
}
#endif
#ifdef DEPTH_COVERAGE
vec4 storeKeyposeSamples(int part,vec4 points) {
#ifdef KEYPOSE_SAMPLES_FP16
    uvec2 packedPoints=uvec2(packHalf2x16(points.xy),packHalf2x16(points.zw));
    samples[sampleIndex(part)]=packedPoints;
    // 깊이 판정도 재질 패스와 같은 양자화 좌표로 한다.
    return decodeKeyposeSamples(packedPoints);
#else
    samples[sampleIndex(part)]=points;
    return points;
#endif
}
#else
vec4 loadKeyposeSamples(int part) {
#ifdef KEYPOSE_SAMPLES_FP16
    return decodeKeyposeSamples(samples[sampleIndex(part)]);
#else
    return samples[sampleIndex(part)];
#endif
}
#endif
vec2 sampleTexel() {
    if(sampleBase<0) return texel;
    return sourceRect.xy+(vec2(samplePixel())+vec2(0.5))*sourceRect.zw/vec2(sampleTile.zw);
}
#define SAMPLE_TEXEL sampleTexel()
#else
#define SAMPLE_TEXEL texel
#endif
#ifdef READ_SCREEN_DEPTH
uniform sampler2D screenDepth;
flat in vec3 screenPlacement;
bool obscured() {
    if(screenPlacement.z<=0.0) return false;
    ivec2 pixel=ivec2(floor(gl_FragCoord.xy)+screenPlacement.xy);
    return any(lessThan(pixel,ivec2(0)))||any(greaterThanEqual(pixel,textureSize(screenDepth,0)))||
           texelFetch(screenDepth,pixel,0).r<screenPlacement.z;
}
#endif
vec2 coord(vec2 p,vec4 rect,vec2 size) {
    return (rect.xy+clamp(p,vec2(0.5),rect.zw-0.5))/size;
}
PART_FIELD_ACCESS
PAGE_SAMPLERS
SURFACE_FUNCTIONS
vec4 colorAt(vec2 p,vec4 rect,float bank,vec2 size,int part,bool second) {
    if(p.x<0.5||p.y<0.5||p.x>size.x-0.5||p.y>size.y-0.5) return vec4(0.0);
    vec2 point=p*rect.zw/size;
#ifdef FRAME_CROP
    if(rect.z<=0.0) return vec4(0.0);
    vec4 placement=second?PART_FIELD(colorPlacementB,part):PART_FIELD(colorPlacementA,part);
    point=p*placement.zw-placement.xy;
    if(any(lessThan(point,vec2(0.0)))||any(greaterThan(point,rect.zw))) return vec4(0.0);
#endif
    return read_color(point,rect,bank);
}
vec2 flowAt(vec2 p,vec4 rect,float bank,vec2 size,vec2 stepSize) {
    if(rect.z<=0.0) return vec2(0.0);
    vec2 ratio=rect.zw/size;
    vec4 v=read_vector(p*ratio,rect,bank)*255.0;
    if(bankData[int(bank)].w>0.5) return (v.rg-128.0)*stepSize/ratio;
    return (vec2(v.r*256.0+v.g,v.b*256.0+v.a)-32768.0)/(64.0*ratio);
}
float depthAt(vec2 p,vec4 rect,float bank,vec2 size,int part,bool second) {
    if(p.x<0.5||p.y<0.5||p.x>size.x-0.5||p.y>size.y-0.5) return 0.0;
    vec2 point=p*rect.zw/size;
#ifdef FRAME_CROP
    if(rect.z<=0.0) return 0.0;
    vec4 placement=second?PART_FIELD(depthPlacementB,part):PART_FIELD(depthPlacementA,part);
    point=p*placement.zw-placement.xy;
    if(any(lessThan(point,vec2(0.0)))||any(greaterThan(point,rect.zw))) return 0.0;
#endif
    vec4 v=read_depth(point,rect,bank);
    if(v.a<0.000001) return 0.0;
    float encoded=dot(v.rgb,vec3(65536.0,256.0,1.0))*255.0/16777215.0/v.a;
    vec2 range=bankData[int(bank)].xy;
    return range.x+encoded*range.y;
}
vec4 surfaceAt(vec2 p,vec4 rect,vec4 maskRect,vec4 depthRect,float bank,vec2 size,int part,bool second,
               out float depth,out vec4 material,out vec3 properties,out vec2 coat) {
    vec4 c=colorAt(p,rect,bank,size,part,second);
    material=vec4(0.0);
    properties=vec3(0.0);
    coat=vec2(0.0);
    depth=0.0;
    if(c.a<0.000001) return vec4(0.0);
    depth=depthAt(p,depthRect,bank,size,part,second);
    if(depth<=0.0) return vec4(0.0);
#ifndef DEPTH_COVERAGE
#ifdef SURFACE
#ifdef PBR
    if(depthOutput>0.5) return c;
    vec4 packedRect=second?PART_FIELD(materialB,part):PART_FIELD(materialA,part);
    properties=read_material(p*packedRect.zw/size,packedRect,bank).rgb;
#ifdef COAT
    vec4 coatRect=second?PART_FIELD(coatB,part):PART_FIELD(coatA,part);
    coat=read_coat(p*coatRect.zw/size,coatRect,bank).rg;
#endif
#endif
    material=read_energy(p*maskRect.zw/size,maskRect,bank);
#else
    if(energyTint.a>0.0&&c.a>0.00001&&maskRect.z>0.0) {
        vec2 maskPoint=p*maskRect.zw/size;
#ifdef PART_PAGES
        vec4 placement=second?PART_FIELD(energyPlacementB,part):PART_FIELD(energyPlacementA,part);
        maskPoint=p*placement.zw-placement.xy;
        if(any(lessThan(maskPoint,vec2(0.0)))||any(greaterThan(maskPoint,maskRect.zw))) return c;
#endif
        vec4 mask=read_energy(maskPoint,maskRect,bank);
        float strength=mix(max(mask.r,max(mask.g,mask.b)),mask.a,bankData[int(bank)].z);
        float weight=clamp(strength/c.a*energyTint.a,0.0,1.0);
        c.rgb=mix(c.rgb,energyTint.rgb*max(c.r,max(c.g,c.b)),weight);
    }
#endif
#endif
    return c;
}
vec4 shadeSurface(vec4 c,vec4 field,vec3 properties,vec2 coat,vec2 pixel,float depth) {
#ifdef SURFACE
    if(c.a<0.0001) return c;
    vec3 normal=normalize(field.rgb/c.a*2.0-1.0+vec3(0.00001));
    vec3 position=worldAt(pixel,depth);
#ifdef PBR
    // 카메라 깊이에서 복원한 표면의 자기 그림자 오차를 노멀 방향으로 보정한다.
    float shadow=surfaceVisibilityAt(position+normal*4.0);
    vec3 base=srgbToLinear(clamp(c.rgb/c.a,0.0,1.0));
    vec3 attrs=clamp(properties/c.a,0.0,1.0);
    c.rgb=shadePbr(base,normal,position,attrs,clamp(coat/c.a,0.0,1.0),shadow,-cameraForward.xyz)*c.a;
#else
    float shadow=visibilityAt(position);
    float lambert=max(0.0,dot(normal,lightDirection.xyz));
    c.rgb*=pow(0.34+0.85*lambert*shadow,0.454545);
#endif
    vec3 emission=energyTint.a>0.0?energyTint.rgb:vec3(0.08,0.72,0.94);
    c.rgb=mix(c.rgb,emission*c.a,clamp(field.a*max(1.0,energyTint.a)/c.a,0.0,1.0));
#endif
    return c;
}
bool outsideSample(vec2 p,vec2 size) {
    return p.x<0.0||p.y<0.0||p.x>size.x||p.y>size.y;
}
vec4 keyposeSamplePoints(int i,vec2 p,vec2 size,float bank,float t) {
    vec2 a=p,b=p;
    if(t>0.0&&t<1.0) {
        for(int step=0;step<16;++step) {
            a=(a+p-t*flowAt(a,PART_FIELD(forwardRects,i),bank,size,PART_FIELD(flowSteps,i).xy))*0.5;
            b=(b+p-(1.0-t)*flowAt(b,PART_FIELD(backwardRects,i),bank,size,PART_FIELD(flowSteps,i).zw))*0.5;
        }
    }
    return vec4(a,b);
}
vec4 temporalSurface(int i,vec2 p,out float depth,out vec4 material,out vec3 properties,out vec2 coat) {
    vec2 size=PART_FIELD(crops,i).zw;
    float bank=PART_FIELD(shifts,i).w,t=localPhase;
    depth=0.0;
    material=vec4(0.0);
    properties=vec3(0.0);
    coat=vec2(0.0);
    if(outsideSample(p,size)) return vec4(0.0);
    vec4 points;
#if defined(CACHE_KEYPOSE_SAMPLES) && !defined(DEPTH_COVERAGE)
    if(sampleBase>=0) points=loadKeyposeSamples(i);
    else points=keyposeSamplePoints(i,p,size,bank,t);
#else
    points=keyposeSamplePoints(i,p,size,bank,t);
#ifdef CACHE_KEYPOSE_SAMPLES
    if(sampleBase>=0) points=storeKeyposeSamples(i,points);
#endif
#endif
    vec2 a=points.xy,b=points.zw;
    if(t<=0.0) return surfaceAt(a,PART_FIELD(colorA,i),PART_FIELD(energyA,i),PART_FIELD(depthA,i),bank,size,i,false,depth,material,properties,coat);
    if(t>=1.0) return surfaceAt(b,PART_FIELD(colorB,i),PART_FIELD(energyB,i),PART_FIELD(depthB,i),bank,size,i,true,depth,material,properties,coat);
    vec4 ma,mb;
    vec3 pa,pb;
    vec2 ka,kb;
    float da,db;
    vec4 ca=surfaceAt(a,PART_FIELD(colorA,i),PART_FIELD(energyA,i),PART_FIELD(depthA,i),bank,size,i,false,da,ma,pa,ka);
    vec4 cb=surfaceAt(b,PART_FIELD(colorB,i),PART_FIELD(energyB,i),PART_FIELD(depthB,i),bank,size,i,true,db,mb,pb,kb);
    vec4 c=mix(ca,cb,t);
    if(c.a>0.000001)
        depth=(da*ca.a*(1.0-t)+db*cb.a*t)/c.a;
    material=mix(ma,mb,t);
    properties=mix(pa,pb,t);
    coat=mix(ka,kb,t);
    return c;
}
#ifdef ANGULAR
#ifdef SURFACE
uniform vec4 normalYaw[4];
#endif
vec2 unprojectAngle(vec2 target,float depth,int matrixIndex,vec2 cropOrigin) {
    vec3 point=vec3(target,(depth-angleOrigin.z)*angleOrigin.w);
    return vec2(dot(angleMatrices[matrixIndex].xyz,point),
                dot(angleMatrices[matrixIndex+1].xyz,point))+angleOrigin.xy-cropOrigin;
}
vec4 angleSurface(int i,vec2 target,int matrixIndex,out float targetDepth,out vec4 material,out vec3 properties,out vec2 coat) {
    vec2 p=unprojectAngle(target,PART_FIELD(shifts,i).z,matrixIndex,PART_FIELD(crops,i).xy);
    bool second=localPhase>=0.5;
    vec4 depthRect=second?PART_FIELD(depthB,i):PART_FIELD(depthA,i);
    float bank=PART_FIELD(shifts,i).w;
    for(int step=0;step<5;++step) {
        float depth=depthAt(p,depthRect,bank,PART_FIELD(crops,i).zw,i,second);
        if(depth<=0.0) break;
        vec2 next=unprojectAngle(target,depth,matrixIndex,PART_FIELD(crops,i).xy);
        if(dot(next-p,next-p)<0.04) { p=next; break; }
        p=mix(p,next,0.75);
    }
    float depth;
    vec4 c=temporalSurface(i,p,depth,material,properties,coat);
#ifdef SURFACE
    vec2 rotation=normalYaw[matrixIndex/3].xy;
    vec2 n=material.xy*2.0-c.a;
    material.xy=(mat2(rotation.x,rotation.y,-rotation.y,rotation.x)*n+c.a)*0.5;
#endif
    targetDepth=angleOrigin.z+dot(angleMatrices[matrixIndex+2].xyz,
                                  vec3(p+PART_FIELD(crops,i).xy-angleOrigin.xy,(depth-angleOrigin.z)*angleOrigin.w))/angleOrigin.w;
    return c;
}
#endif
#ifdef DEPTH_COVERAGE
void main() {
    vec2 point=SAMPLE_TEXEL;
#ifdef CACHE_KEYPOSE_SAMPLES
    bool opaque=false;
#endif
    for(int i=0;i<PARTS;++i) {
        if(float(i)>=partCount) break;
        vec4 crop=PART_FIELD(crops,i), shift=PART_FIELD(shifts,i);
        vec2 p=point-crop.xy-shift.xy;
#ifdef CACHE_KEYPOSE_SAMPLES
        // 이미 가림이 확정된 픽셀의 나머지 파츠는 보간 좌표만 기록한다.
        if(opaque) {
            if(!outsideSample(p,crop.zw))
                storeKeyposeSamples(i,keyposeSamplePoints(i,p,crop.zw,shift.w,localPhase));
            continue;
        }
#endif
        float depth;
        vec4 material;
        vec3 properties;
        vec2 coat;
        if(temporalSurface(i,p,depth,material,properties,coat).a>=1.0) {
#ifdef CACHE_KEYPOSE_SAMPLES
            if(sampleBase>=0) { opaque=true; continue; }
#endif
            return;
        }
    }
#ifdef CACHE_KEYPOSE_SAMPLES
    if(opaque) return;
#endif
    discard;
}
#else
void main() {
#ifdef READ_SCREEN_DEPTH
    if(obscured()) discard;
#endif
    vec4 colors[PARTS];
    float depths[PARTS];
#ifdef PBR
    vec4 normalEnergy[PARTS];
    vec3 materialProperties[PARTS];
    vec2 coatProperties[PARTS];
#endif
    for(int i=0;i<PARTS;++i) {
        colors[i]=vec4(0.0); depths[i]=1.0e30;
#ifdef PBR
        normalEnergy[i]=vec4(0.0); materialProperties[i]=vec3(0.0); coatProperties[i]=vec2(0.0);
#endif
        if(float(i)>=partCount) continue;
        float depth=0.0;
        vec4 material;
        vec3 properties;
        vec2 coat;
#ifdef ANGULAR
        vec4 bounds=angleRects[i];
        if(any(lessThan(texel,bounds.xy))||any(greaterThan(texel,bounds.zw))) continue;
        int j=i*2;
        bool upper=PART_FIELD(shifts,j).x<0.5;
        int m=upper?0:6;
        vec2 target=texel-angleOrigin.xy-(upper?angleWeights.xy:vec2(0.0));
        float za,zb,w=upper?angleWeights.z:angleWeights.w;
        vec4 a=vec4(0.0),b=vec4(0.0);
        vec4 ma=vec4(0.0),mb=vec4(0.0);
        vec3 pa=vec3(0.0),pb=vec3(0.0);
        vec2 ka=vec2(0.0),kb=vec2(0.0);
        za=0.0; zb=0.0;
        if(w<1.0) a=angleSurface(j,target,m,za,ma,pa,ka);
        if(w>0.0) b=angleSurface(j+1,target,m+3,zb,mb,pb,kb);
        vec4 c=mix(a,b,w);
        material=mix(ma,mb,w);
        properties=mix(pa,pb,w);
        coat=mix(ka,kb,w);
        if(c.a>0.000001) {
            depth=mix(za*a.a,zb*b.a,w)/c.a+(upper?waistDepthShift:0.0);
            if(a.a>0.01&&b.a>0.01&&abs(za-zb)>18.0)
                depth=(za<zb?za:zb)+(upper?waistDepthShift:0.0);
        }
#else
        vec4 c=temporalSurface(i,SAMPLE_TEXEL-PART_FIELD(crops,i).xy-PART_FIELD(shifts,i).xy,depth,material,properties,coat);
        depth+=PART_FIELD(shifts,i).z;
#endif
#ifdef PBR
        colors[i]=c;
        normalEnergy[i]=material;
        materialProperties[i]=properties;
        coatProperties[i]=coat;
#else
        colors[i]=shadeSurface(c,material,properties,coat,texel,depth);
#endif
        if(c.a>0.000001) depths[i]=depth;
    }
#ifdef PBR
    if(depthOutput>0.5) {
        float nearest=1.0e30;
        for(int i=0;i<PARTS;++i) {
            if(colors[i].a>=0.5&&depths[i]>0.0) nearest=min(nearest,depths[i]);
        }
        if(nearest>=1.0e30) {
            PART_OUTPUT=vec4(0.0);
        } else {
            // 24비트 RGB에 0.25cm 단위의 깊이를 담는다.
            float encodedDepth=floor(clamp(nearest*4.0,1.0,16777215.0)+0.5);
            PART_OUTPUT=vec4(vec3(floor(encodedDepth/65536.0),mod(floor(encodedDepth/256.0),256.0),
                                   mod(encodedDepth,256.0))/255.0,1.0);
        }
        return;
    }
#endif
    for(int pass=0;pass<PARTS-1;++pass) {
        for(int j=0;j<PARTS-1;++j) {
            if(j>=PARTS-1-pass) continue;
            if(depths[j]>depths[j+1]) {
                float z=depths[j];depths[j]=depths[j+1];depths[j+1]=z;
                vec4 c=colors[j];colors[j]=colors[j+1];colors[j+1]=c;
#ifdef PBR
                vec4 n=normalEnergy[j];normalEnergy[j]=normalEnergy[j+1];normalEnergy[j+1]=n;
                vec3 p=materialProperties[j];materialProperties[j]=materialProperties[j+1];materialProperties[j+1]=p;
                vec2 k=coatProperties[j];coatProperties[j]=coatProperties[j+1];coatProperties[j+1]=k;
#endif
            }
        }
    }
#ifdef DEFERRED_SURFACE
    // 한 표면으로 표현할 수 없는 반투명 파츠 겹침은 기존 합성을 쓴다.
    int first=-1;
    bool overlaps=false;
    for(int i=0;i<PARTS;++i) {
        if(colors[i].a<=0.000001) continue;
        if(first<0) first=i;
        else { overlaps=true; break; }
    }
    if(first<0) discard;
    if(!overlaps || colors[first].a>=0.99999) {
        vec4 base=colors[first], field=normalEnergy[first];
        vec3 normal=normalize(field.rgb/base.a*2.0-1.0+vec3(0.00001));
        float emission=clamp(field.a*max(1.0,energyTint.a)/base.a,0.0,1.0);
        vec2 coat=clamp(coatProperties[first]/base.a,0.0,1.0);
        gl_FragData[0]=vec4(clamp(base.rgb/base.a,0.0,1.0),base.a);
        gl_FragData[1]=vec4(normal,emission);
        gl_FragData[2]=vec4(clamp(materialProperties[first]/base.a,0.0,1.0),coat.x);
        gl_FragData[3]=vec4(worldAt(texel,depths[first]),2.0*(deferredProfile+1.0)+coat.y);
        return;
    }
#endif
    vec4 c=vec4(0.0);
    for(int i=0;i<PARTS;++i) {
#ifdef PBR
        if(colors[i].a<=0.000001) continue;
        if(c.a>=0.99999) break;
        c+=(1.0-c.a)*shadeSurface(colors[i],normalEnergy[i],materialProperties[i],coatProperties[i],texel,depths[i]);
#else
        c+=(1.0-c.a)*colors[i];
#endif
    }
    vec3 rgb=c.a>0.00001?c.rgb/c.a:vec3(0.0);
    if(realtimeLight>0.0) {
        float z=c.a>0.00001?depths[0]:0.0;
        vec2 slope=clamp(vec2(dFdx(z),dFdy(z)),vec2(-2.0),vec2(2.0));
        vec3 normal=normalize(vec3(-slope,1.0));
        float diffuse=max(0.0,dot(normal,vec3(-0.48,0.36,0.8)));
        rgb*=mix(1.0,0.62+0.48*diffuse,realtimeLight*smoothstep(0.75,1.0,c.a));
    }
    rgb=mix(rgb,colorMix.rgb*max(dot(rgb,vec3(0.299,0.587,0.114)),0.25),colorMix.a);
    if(rimLight.a>0.0) {
        vec2 gradient=vec2(dFdx(c.a),dFdy(c.a));
        float edge=clamp(length(gradient)*4.5,0.0,1.0);
        float directional=0.3+0.7*max(0.0,dot(normalize(gradient+vec2(0.00001)),normalize(vec2(0.6,-0.8))));
        rgb=mix(rgb,rimLight.rgb,edge*directional*rimLight.a);
    }
    PART_OUTPUT=vec4(rgb*modulation.rgb*brightness,c.a*modulation.a*effectOpacity);
#ifdef DEFERRED_SURFACE
    gl_FragData[1]=vec4(0.0);
    gl_FragData[2]=vec4(0.0);
    gl_FragData[3]=vec4(0.0);
#endif
}
#endif
'''.encode("utf-8")


class PartPainter:
    PAGE_KINDS = ("color", "vector", "energy", "depth")
    ARRAYS = ("colorA", "colorB", "forwardRects", "backwardRects", "energyA", "energyB", "depthA", "depthB",
              "crops", "shifts", "flowSteps")

    def __init__(self, pico, *, angular=False, part_count=MAX_PARTS, paged=False, frame_crop=False, surface=False,
                 pbr=False, coat=False, instanced=False, deferred=False, depth_coverage=False,
                 screen_depth=False, instance_table=False, cache_keypose_samples=False, keypose_samples_fp16=False):
        self.pico = pico
        self.paged = paged
        self.frame_crop = frame_crop
        self.arrays = self.ARRAYS + (("energyPlacementA", "energyPlacementB") if paged else ())
        self.page_kinds = self.PAGE_KINDS
        self.sample_fields = PART_SAMPLE_FIELDS
        if pbr:
            self.arrays += ("materialA", "materialB")
            self.page_kinds += ("material",)
            self.sample_fields += PBR_SAMPLE_FIELDS
        if coat:
            self.arrays += ("coatA", "coatB")
            self.page_kinds += ("coat",)
            self.sample_fields += COAT_SAMPLE_FIELDS
        if frame_crop:
            self.arrays += ("colorPlacementA", "colorPlacementB", "depthPlacementA", "depthPlacementB")
        banks = 4 if angular else 2
        texture_banks = 1 if paged else banks
        input_kinds = ("color", "vector", "depth") if depth_coverage else self.page_kinds
        self.texture_names = {kind: tuple("artwork" if kind == "color" and bank == 0 else f"{kind}Page{bank}"
                                         for bank in range(texture_banks)) for kind in input_kinds}
        declarations, uniforms = [], []
        for kind, names in self.texture_names.items():
            samples = []
            for index, name in enumerate(names):
                size = name + "Size"
                declarations.extend((f"uniform sampler2D {name};", f"uniform vec2 {size};"))
                uniforms.extend((name, size))
                condition = f"if(bank<{index + .5}) " if index < texture_banks - 1 else ""
                samples.append(f"{condition}return texture2D({name},coord(p,rect,{size}));")
            declarations.append(f"vec4 read_{kind}(vec2 p,vec4 rect,float bank) {{ {' '.join(samples)} }}")
        defines = f"#version 120\n#define BANKS {banks}" + ("\n#define ANGULAR" if angular else "")
        if paged:
            defines += "\n#define PART_PAGES"
        if frame_crop:
            defines += "\n#define FRAME_CROP"
        if pbr:
            defines += "\n#define PBR"
        if coat:
            defines += "\n#define COAT"
        if deferred:
            defines += "\n#define DEFERRED_SURFACE"
            uniforms.append("deferredProfile")
        if depth_coverage:
            defines += "\n#define DEPTH_COVERAGE"
        if screen_depth:
            defines += "\n#define READ_SCREEN_DEPTH"
            uniforms.append("screenDepth")
        if cache_keypose_samples:
            from .keypose_sample_buffer import KEYPOSE_SAMPLE_BINDING
            defines += f"\n#define CACHE_KEYPOSE_SAMPLES\n#define KEYPOSE_BINDING {KEYPOSE_SAMPLE_BINDING}"
            if keypose_samples_fp16:
                defines += "\n#define KEYPOSE_SAMPLES_FP16"
        shader = PART_SHADER.replace(b"#version 120", defines.encode(), 1)
        shader = shader.replace(b"PART_LIMIT", str(part_count).encode())
        shader = shader.replace(b"PAGE_SAMPLERS", "\n".join(declarations).encode())
        shadow_uniforms = ()
        if surface and not depth_coverage:
            from .part_shadow_map import SHADOW_FUNCTIONS, SHADOW_UNIFORMS
            shader = shader.replace(b"SURFACE_FUNCTIONS", b"#define SURFACE\n" + SHADOW_FUNCTIONS + (PBR_FUNCTIONS if pbr else b""))
            shadow_uniforms = SHADOW_UNIFORMS + (PBR_UNIFORMS + ("depthOutput",) if pbr else ())
        else:
            shader = shader.replace(b"SURFACE_FUNCTIONS", b"")
        angular_uniforms = ("angleRects[0]", "angleMatrices[0]", "angleOrigin", "angleWeights", "waistDepthShift") if angular else ()
        if angular and surface:
            angular_uniforms += ("normalYaw[0]",)
        sampler_type = TexturedQuadPass
        if instanced:
            from .instanced_quads import InstancedQuads
            sampler_type = InstancedQuads
            shader = shader.replace(b"#define BANKS", b"#define PART_INSTANCES\n#define BANKS", 1)
            indices = [f"#define FIELD_{field} {index}" for index, field in enumerate(self.arrays)]
            access = "\n".join((*indices, "flat in int pairIndex; uniform sampler2D poseTable;",
                f"vec4 poseField(int part,int field){{return texelFetch(poseTable,ivec2(part*{len(indices)}+field,pairIndex),0);}}",
                "#define PART_FIELD(name,index) poseField(index,FIELD_##name)"))
            uniforms.append("poseTable")
        else:
            access = "#define PART_FIELD(name,index) name[index]"
        shader = shader.replace(b"PART_FIELD_ACCESS", access.encode())
        sampler_options = {"screen_depth": True} if depth_coverage or screen_depth else {}
        if instance_table:
            sampler_options.update(instance_table=True, coverage_instances=depth_coverage)
        if cache_keypose_samples:
            sampler_options["cache_keypose_samples"] = True
        self.sampler = sampler_type(pico, fragment_shader=shader, **sampler_options,
            extra_uniforms=tuple(name + "[0]" for name in self.arrays) +
            tuple(uniforms) + ("bankData[0]", "energyTint", "rimLight", "localPhase", "partCount", "effectOpacity",
                               "brightness", "colorMix", "realtimeLight", "modulation") + angular_uniforms + shadow_uniforms)
        self.uniform_array = bind_gl(pico, "glUniform4fv", None, [ct.c_int, ct.c_int, ct.c_void_p])

    def upload(self, name, values):
        self.uniform_array(self.sampler.uniforms[name + "[0]"], len(values) // 4, (ct.c_float * len(values))(*values))

    def frame_arrays(self, cache, resources, state):
        arrays = {name: [] for name in self.arrays}
        for part in state["parts"]:
            bank = part["bank"] if len(resources) > 1 else 0
            resource = resources[bank]
            frames = resource["data"]["frames"]
            for name, kind, end, field in self.sample_fields:
                tile = frames[kind][part[end][field]]
                arrays[name].extend(cache.rect(resource, kind, tile) if self.paged else tile["rect"])
                if self.paged and kind == "energy":
                    x, y, w, h = tile.get("mask_crop", (0, 0, 0, 0))
                    arrays["energyPlacement" + end.upper()].extend((x, y, w / part["crop"][2], h / part["crop"][3]))
                if self.frame_crop and kind in ("color", "depth"):
                    x, y, w, h = tile.get("frame_crop", (0, 0, 0, 0))
                    arrays[kind + "Placement" + end.upper()].extend((x, y, w / part["crop"][2], h / part["crop"][3]))
            vectors = frames["vector"]
            arrays["flowSteps"].extend(vectors[part["a"]["forward"]].get("flow_step", (0, 0)))
            arrays["flowSteps"].extend(vectors[part["b"]["backward"]].get("flow_step", (0, 0)))
            arrays["crops"].extend(part["crop"])
            arrays["shifts"].extend((*part["shift"], bank))
        return arrays

    def paint(self, cache, resources, state, destination, *, energy_color=None, energy_gain=1, rim=(0, 0, 0, 0),
              opacity=1, tint=(1, 1, 1), tint_mix=0, brightness=1, realtime_light=0, shadow_map=None, pbr_lighting=None,
              sample_shadow=True, depth_output=False, instances=None, pose_table=None,
              screen_depth=None, screen_placements=None, instance_texture=None, instance_range=None, depth_origin=(0, 0)):
        entries = (cache.bindings(self.page_kinds) if self.paged else
                   [resource["pages"][kind] for kind in self.texture_names for resource in resources])
        if pbr_lighting:
            entries.append(pbr_lighting["entry"])
            environment_unit = len(entries) - 1
        if pose_table is not None:
            pose_unit = len(entries)
            entries.append({"gl_texture": pose_table})
        if screen_depth is not None:
            depth_unit = len(entries)
            entries.append({"gl_texture": screen_depth})
        if instance_texture is not None:
            from .instance_texture_buffer import TEXTURE_BINDING_BUFFER, TEXTURE_BUFFER
            instance_unit = len(entries)
            entries.append({"gl_texture": instance_texture, "gl_target": TEXTURE_BUFFER,
                            "gl_binding": TEXTURE_BINDING_BUFFER})
        arrays = self.frame_arrays(cache, resources, state) if pose_table is None else {}
        sampler = self.sampler
        with sampler.batch(), bind_atlas_textures(sampler, cache, entries):
            if pose_table is not None:
                sampler.glUniform1i(sampler.uniforms["poseTable"], pose_unit)
            if screen_depth is not None:
                sampler.glUniform1i(sampler.uniforms["screenDepth"], depth_unit)
            if instance_texture is not None:
                sampler.glUniform1i(sampler.uniforms["instanceTable"], instance_unit)
            if pbr_lighting:
                sampler.glUniform1i(sampler.uniforms["pbrEnvironment"], environment_unit)
                for uniform, field in (("pbrEnvironmentSize", "environment_size"), ("pbrKeyPosition", "key_position"),
                                       ("pbrKeyColor", "key_color"), ("pbrKeyDirection", "key_direction")):
                    sampler.glUniform4f(sampler.uniforms[uniform], *pbr_lighting[field])
                sampler.glUniform1f(sampler.uniforms["pbrExposure"], pbr_lighting["exposure"])
                sampler.glUniform1f(sampler.uniforms["depthOutput"], float(depth_output))
            for index, names in enumerate(self.texture_names.values()):
                for bank, name in enumerate(names):
                    unit = index if self.paged else index * len(resources) + (bank if bank < len(resources) else 0)
                    sampler.glUniform1i(sampler.uniforms[name], unit)
                    entry = entries[unit]
                    sampler.glUniform2f(sampler.uniforms[name + "Size"], *entry.get("storage_size", entry["size"]))
            self.upload("bankData", [value for resource in resources for value in (
                *resource["data"]["clip"]["depth_range"],
                float(self.paged or resource["pages"]["energy"]["codec"] == "a8_zlib"),
                float(self.paged or resource["pages"]["vector"]["codec"] == "rg8_zlib"))])
            for name, values in arrays.items():
                self.upload(name, values)
            count = len(state["parts"])
            if "angle_matrices" in state:
                self.upload("angleRects", state["angle_rects"])
                self.upload("angleMatrices", state["angle_matrices"])
                sampler.glUniform4f(sampler.uniforms["angleOrigin"], *state["angle_origin"])
                sampler.glUniform4f(sampler.uniforms["angleWeights"], *state["angle_weights"])
                sampler.glUniform1f(sampler.uniforms["waistDepthShift"], state["waist_depth_shift"])
                if shadow_map is not None:
                    self.upload("normalYaw", state["normal_yaw"])
                count //= 2
            sampler.glUniform1f(sampler.uniforms["localPhase"], state["alpha"])
            sampler.glUniform1f(sampler.uniforms["partCount"], count)
            sampler.glUniform4f(sampler.uniforms["energyTint"], *(energy_color or (0, 0, 0)), energy_gain if energy_color else 0)
            sampler.glUniform4f(sampler.uniforms["rimLight"], *rim)
            sampler.glUniform4f(sampler.uniforms["colorMix"], *tint, tint_mix)
            sampler.glUniform1f(sampler.uniforms["brightness"], brightness)
            sampler.glUniform1f(sampler.uniforms["realtimeLight"], realtime_light)
            sampler.glUniform1f(sampler.uniforms["effectOpacity"], opacity)
            with shadow_map.bind(sampler, len(entries), sample_shadow=sample_shadow,
                                 surface=pbr_lighting is not None) if shadow_map else nullcontext():
                if instance_range is not None:
                    sampler.glUniform4f(sampler.uniforms["modulation"], 1, 1, 1, 1)
                    sampler.draw_instance_range(state["bounds"], *instance_range, depth_origin, screen_depth is not None)
                elif instances is None:
                    sampler.draw(entries[0].get("texture"), entries[0]["size"], self.pico.SDL_Rect(*state["bounds"]), destination)
                else:
                    sampler.glUniform4f(sampler.uniforms["modulation"], 1, 1, 1, 1)
                    sampler.draw_instances(state["bounds"], instances, screen_placements=screen_placements)

    def close(self):
        self.sampler.close()
