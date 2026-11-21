"""원거리 적이 공유하는 고정 크기 포즈 시트."""

from bisect import bisect_right
import ctypes as ct
import json
from struct import Struct
import zlib


CROWD_ATLAS_SIZE = 1024
CROWD_CELL_SIZE = 64
MAX_QUADS = 512
QUAD = Struct("=" + "ff4Bff" * 4)
CROWD_SHADOW_RECT = (CROWD_ATLAS_SIZE - CROWD_CELL_SIZE + 1,) * 2 + (CROWD_CELL_SIZE - 2,) * 2


class EnemyCrowdAtlas:
    def __init__(self, pico, source):
        self.pico = pico
        document = json.loads(source.read_bytes())
        if document.get("version") not in (1, 2) or document.get("size") != CROWD_ATLAS_SIZE:
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
        self.shadows = {(kind, direction): (p.SDL_Rect(*row[:4]), row[4:])
                        for kind, directions in document.get("shadows", {}).items()
                        for direction, row in directions.items()}
        self.destination = p.SDL_Rect()
        self.vertices = self.indices = None
        self.quad_count = 0
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

    @staticmethod
    def _scaled_rect(x, foot, bounds, scale):
        left, top, width, height = bounds
        return (round(x + left * scale), round(foot + top * scale),
                max(1, round(width * scale)), max(1, round(height * scale)))

    def _body_rect(self, kind, playback, x, foot, scale):
        motion, direction, seconds = playback
        clip = self.profiles[kind][motion]
        index = bisect_right(clip["starts"], seconds, lo=1) - 1
        source, bounds = clip["directions"][direction][index]
        return source, self._scaled_rect(x, foot, bounds, scale)

    def _shadow_rect(self, kind, direction, x, foot, scale, radius):
        tile = self.shadows.get((kind, direction))
        if tile is None:
            return self.shadow_source, (round(x - radius), round(foot - radius * .5), round(radius * 2), round(radius))
        source, bounds = tile
        return source, self._scaled_rect(x, foot, bounds, scale)

    def _copy(self, source, bounds):
        p, target = self.pico, self.destination
        target.x, target.y, target.w, target.h = bounds
        if p.SDL_RenderCopy(p.renderer, self.texture, source, target):
            raise RuntimeError("군집 아틀라스 개별 제출 실패")

    def draw(self, kind, playback, x, foot, scale):
        source, bounds = self._body_rect(kind, playback, x, foot, scale)
        self._copy(source, bounds)
        return bounds[1]

    def _draw_quads(self, quads, alpha):
        # 같은 텍스처와 블렌드를 사용한다. 인덱스 순서를 입력과 같게 유지한다.
        p = self.pico
        if self.vertices is None:
            self.vertices = (p.SDL_Vertex * (MAX_QUADS * 4))()
            self.indices = (ct.c_int * (MAX_QUADS * 6))(
                *(base + index for base in range(0, MAX_QUADS * 4, 4) for index in (0, 1, 2, 0, 2, 3)))
        try:
            for source, (x, y, w, h) in quads:
                if w <= 0 or h <= 0:
                    continue
                left, top = source.x / CROWD_ATLAS_SIZE, source.y / CROWD_ATLAS_SIZE
                right = (source.x + source.w) / CROWD_ATLAS_SIZE
                bottom = (source.y + source.h) / CROWD_ATLAS_SIZE
                QUAD.pack_into(self.vertices, self.quad_count * QUAD.size,
                               x, y, 255, 255, 255, alpha, left, top,
                               x + w, y, 255, 255, 255, alpha, right, top,
                               x + w, y + h, 255, 255, 255, alpha, right, bottom,
                               x, y + h, 255, 255, 255, alpha, left, bottom)
                self.quad_count += 1
                if self.quad_count == MAX_QUADS:
                    self._submit_quads()
            if self.quad_count:
                self._submit_quads()
        finally:
            self.quad_count = 0

    def _submit_quads(self):
        p, count = self.pico, self.quad_count
        if p.SDL_RenderGeometry(p.renderer, self.texture, self.vertices, count * 4, self.indices, count * 6):
            raise RuntimeError("군집 아틀라스 배치 제출 실패")
        self.quad_count = 0

    def draw_bodies(self, placements):
        self._draw_quads((self._body_rect(*row) for row in placements), 255)

    def draw_shadows(self, placements, opacity, *, batched=False):
        if not placements:
            return 0
        quads = (self._shadow_rect(*row) for row in placements)
        alpha = round(max(0, min(1, opacity)) * 255)
        if batched:
            self._draw_quads(quads, alpha)
            return len(placements)
        p = self.pico
        if p.SDL_SetTextureAlphaMod(self.texture, alpha):
            raise RuntimeError("군집 그림자 투명도 설정 실패")
        try:
            for source, bounds in quads:
                self._copy(source, bounds)
        finally:
            if p.SDL_SetTextureAlphaMod(self.texture, 255):
                raise RuntimeError("군집 그림자 투명도 복원 실패")
        return len(placements)

    def close(self):
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
        self.vertices = self.indices = None
