"""파츠 표면의 GGX 직접광과 HDR 환경 반사를 계산한다."""

PBR_UNIFORMS = ("pbrEnvironment", "pbrEnvironmentSize", "pbrKeyPosition", "pbrKeyColor", "pbrKeyDirection", "pbrExposure")
COAT_CHANNELS = ("CoatWeight", "CoatRoughness")

PBR_FUNCTIONS = """
uniform sampler2D pbrEnvironment;
uniform vec4 pbrEnvironmentSize;
uniform vec4 pbrKeyPosition, pbrKeyColor, pbrKeyDirection;
uniform float pbrExposure;
const float PI=3.14159265359;

vec3 srgbToLinear(vec3 srgb) {
    return mix(srgb/12.92,pow((srgb+0.055)/1.055,vec3(2.4)),step(vec3(0.04045),srgb));
}
vec3 linearToSrgb(vec3 linear) {
    linear=max(linear,vec3(0.0));
    return mix(linear*12.92,1.055*pow(linear,vec3(1.0/2.4))-0.055,step(vec3(0.0031308),linear));
}
vec3 sampleEnvironment(vec3 vector, float band) {
    float longitude=fract(atan(vector.y,vector.x)/(2.0*PI)+0.5);
    float latitude=acos(clamp(vector.z,-1.0,1.0))/PI;
    vec2 size=pbrEnvironmentSize.xy;
    // 가로 양끝과 각 밴드의 위아래에 한 픽셀 여백을 둔다.
    vec2 uv=(vec2(1.0)+vec2(longitude,latitude)*size+vec2(0.0,band*(size.y+2.0)))
            /vec2(size.x+2.0,pbrEnvironmentSize.z);
    vec3 encoded=texture2D(pbrEnvironment,uv).rgb;
    return encoded*encoded*pbrEnvironmentSize.w;
}
float ggxReflection(float alpha,float nl,float nv,float nh) {
    float a2=alpha*alpha;
    float denominator=max(1.0+nh*nh*(a2-1.0),0.0001);
    float distribution=a2/(PI*denominator*denominator);
    float visibility=0.5/max(nl*sqrt(nv*nv*(1.0-a2)+a2)+nv*sqrt(nl*nl*(1.0-a2)+a2),0.001);
    return distribution*visibility;
}
vec3 environmentReflection(vec3 reflection,float roughness,vec3 f0,float nv) {
    float band=roughness*5.0;
    vec3 radiance=mix(sampleEnvironment(reflection,floor(band)),sampleEnvironment(reflection,ceil(band)),fract(band));
    // 환경 반사의 방향별 프레넬과 마스킹을 거칠기·시선각에 따라 보정한다.
    float slope=1.0-roughness;
    float gain=min(slope*slope,exp2(-9.28*nv))*slope+0.0425-0.0275*roughness;
    vec2 envBrdf=vec2(1.04-0.572*roughness,-0.04+0.022*roughness)+vec2(-1.04,1.04)*gain;
    return radiance*max(f0*envBrdf.x+envBrdf.y,vec3(0.0));
}
vec3 shadePbr(vec3 base, vec3 normal, vec3 position, vec3 attributes, vec2 coat, float shadow, vec3 viewDirection) {
    float metal=attributes.r;
    float roughness=clamp(attributes.g,0.045,1.0);
    vec3 f0=mix(vec3(0.08*attributes.b),base,metal);
    float nv=max(dot(normal,viewDirection),0.001);
    vec3 toLight=(pbrKeyPosition.xyz-position)*0.01;
    float distanceSquared=max(dot(toLight,toLight),0.01);
    vec3 light=toLight*inversesqrt(distanceSquared);
    vec3 halfVector=normalize(light+viewDirection+vec3(0.00001));
    float nl=max(dot(normal,light),0.0);
    float nh=max(dot(normal,halfVector),0.0);
    float vh=max(dot(viewDirection,halfVector),0.0);
    vec3 fresnel=f0+(1.0-f0)*exp2((-5.55473*vh-6.98316)*vh);

    // 면광원이 차지하는 각도를 거칠기에 반영한다.
    float spread=min(1.0,pbrKeyPosition.w*inversesqrt(distanceSquared));
    float alpha=clamp(roughness*roughness+spread,0.002,1.0);
    vec3 diffuse=base*(1.0-metal);
    float attenuation=max(1.0-distanceSquared*pbrKeyDirection.w,0.0);
    float sourceNormal=max(dot(pbrKeyDirection.xyz,-light),0.0);
    vec3 irradiance=pbrKeyColor.rgb*(pbrKeyColor.w/distanceSquared*nl*shadow*sourceNormal*attenuation*attenuation);
    vec3 direct=(diffuse*(1.0-fresnel)/PI+ggxReflection(alpha,nl,nv,nh)*fresnel)*irradiance;

    vec3 reflection=reflect(-viewDirection,normal);
    float edge=pow(1.0-nv,5.0);
    vec3 roughFresnel=f0+(max(vec3(1.0-roughness),f0)-f0)*edge;
    vec3 ambientDiffuse=sampleEnvironment(normal,6.0)*diffuse*(1.0-roughFresnel);
    vec3 ambient=ambientDiffuse+environmentReflection(reflection,roughness,f0,nv);
#ifdef COAT
    if(coat.x>0.0) {
        // 유전체 코팅의 별도 GGX 반사와 아래 재질로 통과하는 광량을 계산한다.
        float coatRoughness=clamp(coat.y,0.02,1.0);
        float coatAlpha=clamp(coatRoughness*coatRoughness+spread,0.002,1.0);
        float coatFresnel=0.04+0.96*exp2((-5.55473*vh-6.98316)*vh);
        float directTransmission=(1.0-coatFresnel)*(1.0-coatFresnel);
        float ambientTransmission=1.0-(0.04+0.96*edge);
        direct=direct*mix(1.0,directTransmission,coat.x)+
               irradiance*(coat.x*ggxReflection(coatAlpha,nl,nv,nh)*coatFresnel);
        ambient=ambient*mix(1.0,ambientTransmission*ambientTransmission,coat.x)+
                coat.x*environmentReflection(reflection,coatRoughness,vec3(0.04),nv);
    }
#endif
    return linearToSrgb((direct+ambient)*pbrExposure);
}
""".encode("utf-8")
