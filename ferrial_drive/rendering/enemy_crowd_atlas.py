"""원거리 적이 공유하는 고정 크기 포즈 시트."""

from bisect import bisect_right
import ctypes as ct
import json
import zlib


CROWD_ATLAS_SIZE = 1024
CROWD_CELL_SIZE = 64
CROWD_SHADOW_RECT = (CROWD_ATLAS_SIZE - CROWD_CELL_SIZE + 1,) * 2 + (CROWD_CELL_SIZE - 2,) * 2


class EnemyCrowdAtlas:
    def __init__(self, pico, source):
        self.pico = pico
        document = json.loads(source.read_bytes())
        if document.get("version") != 1 or document.get("size") != CROWD_ATLAS_SIZE:
            raise ValueError("지원하지 않는 군집 아틀라스 형식이다.")
        self.profiles = document["profiles"]
        self.bytes = CROWD_ATLAS_SIZE ** 2 * 4
        data = zlib.decompress(source.with_suffix(".rgba.zlib").read_bytes())
        if len(data) != self.bytes:
            raise ValueError("군집 아틀라스의 픽셀 크기가 맞지 않는다.")
        p = self.pico
        for motions in self.profiles.values():
            for motion in motions.values():
                for direction, rows in motion["directions"].items():
                    motion["directions"][direction] = tuple((p.SDL_Rect(*row[:4]), row[4:]) for row in rows)
        self.destination = p.SDL_Rect()
        self.shadow_source = p.SDL_Rect(*CROWD_SHADOW_RECT)
        self.texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC,
                                           CROWD_ATLAS_SIZE, CROWD_ATLAS_SIZE)
        if not self.texture:
            raise RuntimeError("군집 아틀라스 텍스처 생성 실패")
        blend = p.SDL_ComposeCustomBlendMode(p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD, p.SDL_BLENDFACTOR_ONE, p.SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
                p.SDL_BLENDOPERATION_ADD)
        if (p.SDL_UpdateTexture(self.texture, None, ct.c_char_p(data), CROWD_ATLAS_SIZE * 4)
                or p.SDL_SetTextureBlendMode(self.texture, blend)
                or p.SDL_SetTextureScaleMode(self.texture, p.SDL_ScaleModeLinear)):
            self.close()
            raise RuntimeError("군집 아틀라스 업로드 또는 블렌딩 설정 실패")

    def supports(self, kind, playback):
        motion, direction, _ = playback
        clip = self.profiles.get(kind, {}).get(motion)
        return clip is not None and direction in clip["directions"]

    def draw(self, kind, playback, x, foot, scale):
        motion, direction, seconds = playback
        clip = self.profiles[kind][motion]
        index = bisect_right(clip["starts"], seconds, lo=1) - 1
        source, (left, top, width, height) = clip["directions"][direction][index]
        target = self.destination
        target.x, target.y = round(x + left * scale), round(foot + top * scale)
        target.w, target.h = max(1, round(width * scale)), max(1, round(height * scale))
        p = self.pico
        if p.SDL_RenderCopy(p.renderer, self.texture, source, target):
            raise RuntimeError("군집 아틀라스 포즈 그리기 실패")
        return target.y

    def draw_shadows(self, placements, opacity):
        if not placements:
            return 0
        p, target = self.pico, self.destination
        alpha = round(max(0, min(1, opacity)) * 255)
        if p.SDL_SetTextureAlphaMod(self.texture, alpha):
            raise RuntimeError("군집 그림자 투명도 설정 실패")
        try:
            for x, foot, radius in placements:
                target.x, target.y = round(x - radius), round(foot - radius * .5)
                target.w, target.h = round(radius * 2), round(radius)
                if p.SDL_RenderCopy(p.renderer, self.texture, self.shadow_source, target):
                    raise RuntimeError("군집 아틀라스 그림자 그리기 실패")
        finally:
            if p.SDL_SetTextureAlphaMod(self.texture, 255):
                raise RuntimeError("군집 아틀라스 투명도 복원 실패")
        return len(placements)

    def close(self):
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
