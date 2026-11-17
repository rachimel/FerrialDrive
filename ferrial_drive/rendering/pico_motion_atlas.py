"""Pico2D 공유 아틀라스 보간·BC7 직접 적재. 기존 모션 재생기와 독립이다."""

from contextlib import closing, contextmanager
import ctypes as ct
import json
from math import isfinite
from pathlib import Path
from threading import get_ident

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.diagnostics.texture_metrics import bind_gl
from .bicubic import BicubicSampler
from .motion_vectors import EASING_CODES
from .texture_codecs import bc7_size, texture_payload_size
from .texture_page_work import DEFAULT_DECODE_WORKERS, TexturePageWork, decoded_pages


ATLAS_SHADER = b'''#version 120
uniform sampler2D artwork;
uniform sampler2D colorSecond;
uniform sampler2D vectorFirst;
uniform sampler2D vectorSecond;
uniform sampler2D energyFirst, energySecond;
uniform vec2 colorSize0, colorSize1, vectorSize0, vectorSize1;
uniform vec2 energySize0, energySize1;
uniform vec2 frameSize;
uniform vec4 aRects[32], bRects[32], fRects[32], rRects[32], pageIds[32];
uniform vec4 energyARects[32], energyBRects[32], energyPageIds[32];
uniform vec4 energyTint;
uniform vec2 atlasSize;
uniform vec4 frameBounds, modulation;
uniform float phase, pairCount, blurSpan, blurStrength;
uniform float effectOpacity;
uniform vec4 colorMix;
uniform vec4 rimLight;
uniform float brightness;
uniform int easing;
varying vec2 texel;
vec4 sampleRect(sampler2D image, vec2 p, vec4 rect, vec2 size) {
    return texture2D(image,(rect.xy+clamp(p,vec2(0.5),rect.zw-0.5))/size);
}
vec4 colorAt(vec2 p, vec4 rect, float page) {
    if (p.x<0.0 || p.y<0.0 || p.x>frameSize.x || p.y>frameSize.y) return vec4(0.0);
    if (page<0.5) return sampleRect(artwork,p,rect,colorSize0);
    return sampleRect(colorSecond,p,rect,colorSize1);
}
vec2 flowAt(vec2 p, vec4 rect, float page) {
    vec4 v;
    if (page<0.5) v=sampleRect(vectorFirst,p,rect,vectorSize0)*255.0;
    else v=sampleRect(vectorSecond,p,rect,vectorSize1)*255.0;
    return (vec2(v.r*256.0+v.g,v.b*256.0+v.a)-32768.0)/64.0;
}
vec4 surfaceAt(vec2 p, vec4 rect, float page, vec4 maskRect, float maskPage) {
    vec4 c=colorAt(p,rect,page);
    if (energyTint.a>0.0 && c.a>0.00001) {
        vec4 mask;
        if (maskPage<0.5) mask=sampleRect(energyFirst,p,maskRect,energySize0);
        else mask=sampleRect(energySecond,p,maskRect,energySize1);
        float weight=clamp(max(mask.r,max(mask.g,mask.b))/c.a*energyTint.a,0.0,1.0);
        float light=max(c.r,max(c.g,c.b));
        c.rgb=mix(c.rgb,energyTint.rgb*light,weight);
    }
    return c;
}
vec4 evaluate(float value) {
    float goal=clamp(value,0.0,1.0);
    if (easing==1) goal=smoothstep(0.0,1.0,goal);
    else if (easing==2) goal=goal*goal*goal*(2.0-goal);
    else if (easing==3) goal=goal*goal*goal*goal*goal;
    int index=int(min(floor(goal*pairCount),pairCount-1.0));
    float t=goal*pairCount-float(index);
    vec4 pages=pageIds[index];
    vec4 masks=energyPageIds[index];
    if (t<=0.0) return surfaceAt(texel,aRects[index],pages.x,energyARects[index],masks.x);
    if (t>=1.0) return surfaceAt(texel,bRects[index],pages.y,energyBRects[index],masks.y);
    vec2 a=texel,b=texel;
    for (int i=0;i<16;++i) {
        a=mix(a,texel-t*flowAt(a,fRects[index],pages.z),0.5);
        b=mix(b,texel-(1.0-t)*flowAt(b,rRects[index],pages.w),0.5);
    }
    return mix(surfaceAt(a,aRects[index],pages.x,energyARects[index],masks.x),
               surfaceAt(b,bRects[index],pages.y,energyBRects[index],masks.y),t);
}
void main() {
    vec4 c=evaluate(phase);
    if (blurSpan>0.0 && blurStrength>0.0) {
        vec4 sum=vec4(0.0);
        for (int i=0;i<9;++i) sum+=evaluate(phase+(float(i)/8.0-1.0)*blurSpan)/9.0;
        c=mix(c,sum,blurStrength);
    }
    vec3 rgb=c.a>0.00001 ? c.rgb/c.a : vec3(0.0);
    vec3 tinted=colorMix.rgb*max(dot(rgb,vec3(0.299,0.587,0.114)),0.25);
    rgb=mix(rgb,tinted,colorMix.a);

    if (rimLight.a > 0.0) {
        vec2 gradient=vec2(dFdx(c.a),dFdy(c.a));
        float edge=clamp(length(gradient)*4.5,0.0,1.0);
        float directional=0.3+0.7*max(0.0,dot(normalize(gradient+vec2(0.00001)),normalize(vec2(0.6,-0.8))));
        rgb=mix(rgb,rimLight.rgb,edge*directional*rimLight.a);
    }
    gl_FragColor=vec4(rgb*modulation.rgb*brightness,c.a*modulation.a*effectOpacity);
}
'''


class AtlasTextureCache:
    """명시적인 렌더러 수명의 캐시. 같은 파일은 후보·클립·인스턴스가 함께 사용한다."""

    def __init__(self, pico, sampler, *, timings=None, ktx_library=None):
        self.pico, self.sampler = pico, sampler
        self.timings = timings or TimingRecorder(enabled=False)
        self.ktx_library = ktx_library
        self.owner_thread_id = get_ident()
        self.entries, self.hits = {}, 0
        self.finish = bind_gl(pico, "glFinish", None, [])
        self.compressed_upload = bind_gl(pico, "glCompressedTexImage2D", None,
                                         [ct.c_uint, ct.c_int, ct.c_uint, ct.c_int, ct.c_int,
                                          ct.c_int, ct.c_int, ct.c_void_p])
        self.query_level = bind_gl(pico, "glGetTexLevelParameteriv", None,
                                   [ct.c_uint, ct.c_int, ct.c_uint, ct.c_void_p])
        self.get_error = bind_gl(pico, "glGetError", ct.c_uint, [])
        self.upload_raw = bind_gl(pico, "glTexImage2D", None,
            [ct.c_uint,ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_uint,ct.c_uint,ct.c_void_p])
        self.parameter = bind_gl(pico, "glTexParameteri", None, [ct.c_uint,ct.c_uint,ct.c_int])
        self.pixel_store = bind_gl(pico, "glPixelStorei", None, [ct.c_uint,ct.c_int])
        self.bind_buffer = bind_gl(pico, "glBindBuffer", None, [ct.c_uint,ct.c_uint])

    def _upload_compact(self, texture, page, buffer):
        """RGB8와 알파 전용 R8을 적재하고 픽셀 전송 상태를 복원한다."""
        s = self.sampler
        with s.batch():
            self._bind(texture)
            keys = (0x0CF5,0x0CF2,0x0CF3,0x0CF4)
            old_unpack = tuple(s.integer(key) for key in keys)
            old_buffer = s.integer(0x88EF)
            try:
                self.bind_buffer(0x88EC,0)
                for key,value in zip(keys,(1,0,0,0)):
                    self.pixel_store(key,value)
                alpha = page["codec"] == "a8_zlib"
                self.upload_raw(0x0DE1,0,0x8229 if alpha else 0x8051,page["width"],page["height"],0,
                                0x1903 if alpha else 0x1907,0x1401,buffer)
                if alpha:
                    for channel in (0x8E42,0x8E43,0x8E44):
                        self.parameter(0x0DE1,channel,0)
                    self.parameter(0x0DE1,0x8E45,0x1903)
                error = self.get_error()
                if error:
                    raise RuntimeError(f"단축 채널 아틀라스 업로드 실패: GL {error:#x}")
            finally:
                for key,value in zip(keys,old_unpack):
                    self.pixel_store(key,value)
                self.bind_buffer(0x88EC,old_buffer)

    @staticmethod
    def page_key(page, directory):
        return ((Path(directory) / page["file"]).resolve(), page["sha256"])

    def _assert_owner(self):
        if get_ident() != self.owner_thread_id:
            raise RuntimeError("GPU 텍스처는 렌더러를 생성한 스레드에서만 적재·해제한다.")

    def acquire(self, page, directory, *, prepared=None):
        self._assert_owner()
        path = (Path(directory) / page["file"]).resolve()
        key = (path, page["sha256"])
        if key in self.entries:
            self.hits += 1
            self.entries[key]["references"] += 1
            return key, self.entries[key]
        width, height = page["width"], page["height"]
        if min(width, height) < 1 or max(width, height) > self.sampler.integer(0x0D33):
            raise ValueError("GPU 페이지 크기 제한을 초과했다.")
        if prepared is None:
            work = TexturePageWork(page, directory, timings=self.timings, ktx_library=self.ktx_library)
            work.run()
            prepared = work.take_result()
        if prepared.key != key or prepared.size != (width, height) or prepared.codec != page["codec"]:
            raise ValueError("준비된 페이지와 GPU 적재 요청이 다르다.")
        payload, compressed = prepared.pixels, prepared.compressed
        p, s = self.pico, self.sampler
        texture = None
        try:
            # 완료 대기를 포함한 CPU 경과 시간이다. GPU 프레임 질의와 구분한다.
            self.finish()
            with self.timings.scope("load.upload_complete"):
                texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32,
                                             p.SDL_TEXTUREACCESS_STATIC, width, height)
                if not texture:
                    raise RuntimeError("아틀라스 텍스처 생성 실패")
                buffer = ct.create_string_buffer(payload)
                if compressed:
                    with s.batch():
                        self._bind(texture)
                        self.compressed_upload(0x0DE1, 0, 0x8E8C, width, height, 0, len(payload), buffer)
                        error = self.get_error()
                        if error:
                            raise RuntimeError(f"BC7 업로드 실패: GL {error:#x}")
                elif page["codec"] in ("a8_zlib","rgb8_zlib"):
                    self._upload_compact(texture,page,buffer)
                elif p.SDL_UpdateTexture(texture, None, buffer, width * 4):
                    raise RuntimeError("RGBA 아틀라스 전송 실패")
                p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
                p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_NONE)
                self.finish()
            with s.batch():
                self._bind(texture)
                values = {}
                for name, enum in (("internal_format", 0x1003), ("compressed", 0x86A1),
                                    ("width", 0x1000), ("height", 0x1001)):
                    value = ct.c_int()
                    self.query_level(0x0DE1, 0, enum, ct.byref(value))
                    values[name] = value.value
                if compressed:
                    storage = ct.c_int()
                    self.query_level(0x0DE1, 0, 0x86A0, ct.byref(storage))
                    if not values["compressed"] or values["internal_format"] != 0x8E8C or storage.value != bc7_size(width, height):
                        raise RuntimeError("실제 GPU 저장 형식이 예상 BC7과 다르다.")
                    values["storage_bytes"] = storage.value
                else:
                    expected_format = {"a8_zlib":0x8229,"rgb8_zlib":0x8051}.get(page["codec"])
                    if expected_format is not None and values["internal_format"] != expected_format:
                        raise RuntimeError("단축 채널 텍스처의 실제 GL 저장 형식이 다르다.")
                    values["storage_bytes"] = texture_payload_size(page["codec"],width,height)
                    values["storage_semantics"] = "GL 저장 형식의 논리 페이로드. 드라이버 정렬·물리 할당량과 다르다."
            entry = {"texture": texture, "size": (width, height), "references": 1,
                     "disk_bytes": prepared.disk_bytes, "gpu": values, "codec": page["codec"]}
            self.entries[key] = entry
            return key, entry
        except BaseException:
            if texture:
                p.SDL_DestroyTexture(texture)
            raise

    def _bind(self, texture):
        w, h = ct.c_float(), ct.c_float()
        if self.pico.SDL_GL_BindTexture(texture, ct.byref(w), ct.byref(h)):
            raise RuntimeError("SDL/OpenGL 아틀라스 연결 실패")

    def release(self, key):
        self._assert_owner()
        entry = self.entries[key]
        entry["references"] -= 1
        if not entry["references"]:
            self.pico.SDL_DestroyTexture(entry["texture"])
            del self.entries[key]

    def report(self):
        return {"unique_textures": len(self.entries), "cache_hits": self.hits,
                "gpu_storage_bytes": sum(row["gpu"]["storage_bytes"] for row in self.entries.values()),
                "textures": [dict(path=str(key[0]), codec=row["codec"], **row["gpu"]) for key, row in self.entries.items()]}


class PicoMotionAtlas:
    def __init__(self, pico, source, cache, *, progress=None, decode_workers=DEFAULT_DECODE_WORKERS):
        if type(decode_workers) is not int or decode_workers < 1:
            raise ValueError("페이지 작업자 수는 양수 정수여야 한다.")
        self.pico, self.source, self.cache = pico, Path(source).resolve(), cache
        self.data = json.loads(self.source.read_text(encoding="utf-8"))
        if self.data.get("version") != 1:
            raise ValueError("지원하지 않는 모션 아틀라스 규격이다.")
        if self.data.get("color_alpha_mode", "premultiplied") != "premultiplied":
            raise ValueError("모션 아틀라스는 제작 시 알파 사전 곱셈한 색상만 허용한다.")
        if self.data.get("vector_encoding", "signed16_rgba_x64") != "signed16_rgba_x64":
            raise ValueError("모션 아틀라스 벡터 인코딩 오류")
        self.keys, self.pages = [], {"color": [], "vector": []}
        if "energy" in self.data["pages"]:
            self.pages["energy"] = []
        requests = [(kind, page) for kind in self.pages for page in self.data["pages"][kind]]
        total = len(requests)
        try:
            cache._assert_owner()
            missing, scheduled = [], set()
            max_side = cache.sampler.integer(0x0D33)
            for _, page in requests:
                if min(page["width"], page["height"]) < 1 or max(page["width"], page["height"]) > max_side:
                    raise ValueError("GPU 페이지 크기 제한을 초과했다.")
                key = cache.page_key(page, self.source.parent)
                if key not in cache.entries and key not in scheduled:
                    missing.append(page)
                    scheduled.add(key)
            with closing(decoded_pages(missing, self.source.parent, workers=decode_workers,
                                       timings=cache.timings, ktx_library=cache.ktx_library)) as prepared_pages:
                for kind, page in requests:
                    prepared = None
                    if cache.page_key(page, self.source.parent) not in cache.entries:
                        with cache.timings.scope("load.wait_prepared"):
                            prepared = next(prepared_pages)
                    key, entry = cache.acquire(page, self.source.parent, prepared=prepared)
                    del prepared
                    self.keys.append(key)
                    self.pages[kind].append(entry)
                    if progress is not None:
                        progress(len(self.keys) / max(1, total))
        except BaseException:
            self.close()
            raise

    def close(self):
        for key in self.keys:
            self.cache.release(key)
        self.keys.clear()


class AtlasPainter:
    def __init__(self, pico):
        self.pico = pico
        self.sampler = BicubicSampler(pico, None, fragment_shader=ATLAS_SHADER,
                                      extra_uniforms=("colorSecond", "vectorFirst", "vectorSecond", "colorSize0",
                                      "colorSize1", "vectorSize0", "vectorSize1", "frameSize", "aRects[0]",
                                      "bRects[0]", "fRects[0]", "rRects[0]", "pageIds[0]", "phase", "pairCount",
                                      "blurSpan", "blurStrength", "easing", "effectOpacity", "colorMix", "rimLight", "brightness",
                                      "energyFirst", "energySecond", "energySize0", "energySize1", "energyTint",
                                      "energyARects[0]", "energyBRects[0]", "energyPageIds[0]"))
        self.uniform_array = bind_gl(pico, "glUniform4fv", None, [ct.c_int, ct.c_int, ct.c_void_p])

    @contextmanager
    def _textures(self, cache, entries):
        s, previous = self.sampler, []
        try:
            for unit, entry in enumerate(entries):
                s.glActiveTexture(0x84C0 + unit)
                previous.append(s.integer(0x8069))
                cache._bind(entry["texture"])
            s.glActiveTexture(0x84C0)
            yield
        finally:
            for unit, texture in enumerate(previous):
                s.glActiveTexture(0x84C0 + unit)
                s.glBindTexture(0x0DE1, texture)
            s.glActiveTexture(0x84C0)

    def draw(self, resource, clip_name, phase, destination, *, blur=False, smoothstep=False,
             shutter_seconds=0.008, blur_strength=0.2, easing=None, opacity=1, tint=(1, 1, 1), tint_mix=0, rim_light=(0, 0, 0, 0), brightness=1,
             energy_color=None, energy_mask_gain=1):
        if len(tint) != 3 or any(not isfinite(v) or not 0 <= v <= 1 for v in (*tint, tint_mix)):
            raise ValueError("혼합 색상과 비율은 0~1의 유한값이어야 한다.")
        if not isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("아틀라스 불투명도는 0~1의 유한값이어야 한다.")
        if not isfinite(phase) or not 0 <= phase <= 1:
            raise ValueError("위상은 0~1이다.")
        easing = easing if easing is not None else ("smoothstep" if smoothstep else "linear")
        if easing not in EASING_CODES:
            raise ValueError("지원하지 않는 위상 곡선이다.")
        data, clip = resource.data, resource.data["clips"][clip_name]
        pairs = clip["pairs"]
        if not 1 <= len(pairs) <= 32:
            raise ValueError("아틀라스 보간은 최대 32구간을 지원한다.")
        if any(len(pair) not in (4, 6) or len(pair) != len(pairs[0]) for pair in pairs):
            raise ValueError("색상·벡터 쌍에 같은 규격의 선택 Energy Mask 쌍이 필요하다.")
        if energy_color is not None and (len(energy_color) != 3 or any(not isfinite(v) or not 0 <= v <= 1 for v in energy_color)):
            raise ValueError("Energy Mask 색상은 0~1 RGB다.")
        if not isfinite(energy_mask_gain) or energy_mask_gain <= 0:
            raise ValueError("Energy Mask 표시 강도는 양수 유한값이다.")
        has_energy = len(pairs[0]) == 6
        frames = data["frames"]
        banks = {kind: sorted({frames[kind][pair[field]]["page"] for pair in pairs for field in fields})
                 for kind, fields in (("color", (0, 1)), ("vector", (2, 3)))}
        if has_energy:
            banks["energy"] = sorted({frames["energy"][pair[field]]["page"] for pair in pairs for field in (4, 5)})
        if any(len(pages) > 2 for pages in banks.values()):
            raise ValueError("한 클립이 3페이지 이상에 흩어졌다. 더 큰 페이지로 다시 준비한다.")
        entries = []
        for kind in ("color", "vector"):
            selected = [resource.pages[kind][index] for index in banks[kind]]
            entries.extend((selected + selected[:1])[:2])
        selected = [resource.pages["energy"][index] for index in banks["energy"]] if has_energy else entries[:2]
        entries.extend((selected + selected[:1])[:2])
        arrays = [[] for _ in range(5)]
        energy_arrays = [[] for _ in range(3)]
        for pair in pairs:
            ids = []
            for field, index in enumerate(pair[:4]):
                kind = "color" if field < 2 else "vector"
                frame = frames[kind][index]
                arrays[field].extend(frame["rect"])
                ids.append(banks[kind].index(frame["page"]))
            arrays[4].extend(ids)
            mask_ids = []
            for field in (4, 5):
                frame = frames["energy"][pair[field]] if has_energy else {"rect": [0, 0, 1, 1], "page": 0}
                energy_arrays[field - 4].extend(frame["rect"])
                mask_ids.append(banks["energy"].index(frame["page"]) if has_energy else 0)
            energy_arrays[2].extend(mask_ids + [0, 0])
        s = self.sampler
        with s.batch(), self._textures(resource.cache, entries):
            for name, unit in (("colorSecond", 1), ("vectorFirst", 2), ("vectorSecond", 3)):
                s.glUniform1i(s.uniforms[name], unit)
            s.glUniform1i(s.uniforms["energyFirst"], 4)
            s.glUniform1i(s.uniforms["energySecond"], 5)
            for name, entry in zip(("colorSize0", "colorSize1", "vectorSize0", "vectorSize1", "energySize0", "energySize1"), entries):
                s.glUniform2f(s.uniforms[name], *entry["size"])
            for name, values in zip(("aRects[0]", "bRects[0]", "fRects[0]", "rRects[0]", "pageIds[0]"), arrays):
                self.uniform_array(s.uniforms[name], len(pairs), (ct.c_float * len(values))(*values))
            for name, values in zip(("energyARects[0]", "energyBRects[0]", "energyPageIds[0]"), energy_arrays):
                self.uniform_array(s.uniforms[name], len(pairs), (ct.c_float * len(values))(*values))
            s.glUniform4f(s.uniforms["energyTint"], *(energy_color or (0, 0, 0)),
                          energy_mask_gain if has_energy and energy_color is not None else 0)
            s.glUniform2f(s.uniforms["frameSize"], *clip["size"])
            s.glUniform1f(s.uniforms["phase"], phase)
            s.glUniform1f(s.uniforms["pairCount"], len(pairs))
            s.glUniform1f(s.uniforms["blurSpan"], shutter_seconds/(clip["interval_seconds"]*len(pairs)) if blur else 0)
            s.glUniform1f(s.uniforms["blurStrength"], blur_strength if blur else 0)
            s.glUniform1i(s.uniforms["easing"], EASING_CODES[easing])
            s.glUniform1f(s.uniforms["effectOpacity"], opacity)
            s.glUniform4f(s.uniforms["colorMix"], *tint, tint_mix)
            s.glUniform4f(s.uniforms["rimLight"], *rim_light)
            s.glUniform1f(s.uniforms["brightness"], brightness)
            width, height = clip["size"]
            s.draw(entries[0]["texture"], entries[0]["size"], self.pico.SDL_Rect(0, 0, width, height), destination)

    def close(self):
        if self.sampler:
            self.sampler.glDeleteProgram(self.sampler.program)
            self.sampler = None


class PicoAtlasSprite:
    """게임 재생 시간·중심 좌표를 품질별 공유 아틀라스에 연결한다."""

    def __init__(self, pico, source, *, timings=None, shutter_seconds=0.008, blur_strength=0.2, progress=None,
                 decode_workers=DEFAULT_DECODE_WORKERS):
        self.pico = pico
        self.rim_light = (0, 0, 0, 0)
        self.energy_color = None
        self.energy_mask_gain = 1
        self.painter = AtlasPainter(pico)
        self.cache = AtlasTextureCache(pico, self.painter.sampler, timings=timings)
        self.resource = None
        self.shutter_seconds, self.blur_strength = shutter_seconds, blur_strength
        try:
            self.resource = PicoMotionAtlas(pico, source, self.cache, progress=progress, decode_workers=decode_workers)
        except BaseException:
            self.painter.close()
            raise
        self.estimated_bytes = self.cache.report()["gpu_storage_bytes"]
        self.cached_clip_count = len(self.resource.data["clips"])

    def draw(self, clip_name, elapsed_seconds, x, y, *, scale=1, opacity=1, easing="linear", playback_speed=1,
             tint=(1, 1, 1), tint_mix=0, blur=True, brightness=1):
        clip = self.resource.data["clips"][clip_name]
        duration = clip["interval_seconds"]*len(clip["pairs"])
        phase = elapsed_seconds/duration
        phase = phase % 1 if clip["loop"] else min(1, max(0, phase))
        self._draw_phase(clip_name, phase, x, y, scale, easing=easing,
                         shutter_seconds=self.shutter_seconds*playback_speed if blur else 0,
                         opacity=opacity, tint=tint, tint_mix=tint_mix, brightness=brightness)

    def draw_frame(self, clip_name, frame_index, x, y, *, scale=1, opacity=1, tint=(1, 1, 1), tint_mix=0, brightness=1):
        clip = self.resource.data["clips"][clip_name]
        phase = min(frame_index, len(clip["pairs"]))/len(clip["pairs"])
        self._draw_phase(clip_name, phase, x, y, scale, shutter_seconds=0, opacity=opacity, tint=tint, tint_mix=tint_mix, brightness=brightness)

    def _draw_phase(self, clip_name, phase, x, y, scale, *, easing="linear", shutter_seconds=0, opacity=1,
                    tint=(1, 1, 1), tint_mix=0, brightness=1):
        clip = self.resource.data["clips"][clip_name]
        width, height = clip["source_size"]
        factor = scale*clip["pixel_scale"]
        destination = self.pico.SDL_Rect(round(x-clip["pivot"][0]*factor), round(y-clip["pivot"][1]*factor),
                                         round(width*factor), round(height*factor))
        self.painter.draw(self.resource, clip_name, phase, destination, easing=easing,
                          blur=shutter_seconds > 0, shutter_seconds=shutter_seconds, blur_strength=self.blur_strength,
                          opacity=opacity, tint=tint, tint_mix=tint_mix, rim_light=self.rim_light, brightness=brightness,
                          energy_color=self.energy_color, energy_mask_gain=self.energy_mask_gain)

    def close(self):
        if self.resource is not None:
            self.resource.close()
            self.resource = None
        self.painter.close()
