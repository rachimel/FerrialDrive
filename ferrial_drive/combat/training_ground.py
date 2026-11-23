"""흙바닥 반복·미터 눈금과 평면 투영. 이동 규칙과 독립인 훈련장 표현이다."""

from contextlib import nullcontext
from ctypes import byref
from math import ceil, floor
import os

from ferrial_drive.rendering.hud_text_atlas import HudTextAtlas
from ferrial_drive.ui.components import Rect


class GroundProjection:
    def __init__(self, pixels_per_meter, y_scale):
        if pixels_per_meter <= 0 or not 0 < y_scale <= 1:
            raise ValueError("표시 배율과 평면 투영 비율이 유효하지 않다.")
        self.pixels_per_meter = pixels_per_meter
        self.y_scale = y_scale

    def project(self, point_m):
        return point_m[0] * self.pixels_per_meter, point_m[1] * self.pixels_per_meter * self.y_scale

    def unproject(self, point_pixels):
        return point_pixels[0] / self.pixels_per_meter, point_pixels[1] / self.pixels_per_meter / self.y_scale


class GroundTextureColors:
    """반복 바닥의 발생 지점 주변 색을 읽는다. 화면 캡처·GPU 읽기를 하지 않는다."""
    def __init__(self, width, height, rgba, projection, tile_m):
        if min(width, height) < 1 or len(rgba) != width * height * 4 or tile_m <= 0:
            raise ValueError("바닥 색상 입력 크기·타일 간격 오류")
        self.width, self.height, self.rgba = width, height, rgba
        self.projection, self.tile_m = projection, tile_m

    def color_at(self, point_pixels, *, blend):
        if not 0 <= blend <= 1:
            raise ValueError("바닥 색 합성 비율은 0~1이어야 한다.")
        x, y = self.projection.unproject(point_pixels)
        x, y = int((x / self.tile_m % 1) * self.width), int((y / self.tile_m % 1) * self.height)
        radius = max(1, min(self.width, self.height) // 32)
        samples = [(row % self.height * self.width + column % self.width) * 4
                   for row in (y - radius, y, y + radius) for column in (x - radius, x, x + radius)]
        color = [round(255 * (1 - blend) + sum(self.rgba[index + channel] for index in samples) / 9 * blend)
                 for channel in range(3)]
        return "#" + "".join(f"{value:02X}" for value in color)


class TrainingGroundView:
    def __init__(self, renderer, projection, settings, texture_path=None, *, sample_colors=False):
        self.renderer, self.projection, self.settings = renderer, projection, settings
        self.pico = renderer.pico
        self.native = getattr(self.pico, "fdrive_native_gl", None)
        self.grid_atlas = None
        if (self.native is not None and getattr(renderer, "batch_queue", None) is not None
                and os.environ.get("FDRIVE_GROUND_GRID_SUBMISSION") != "legacy"):
            self.grid_atlas = HudTextAtlas(self.pico, renderer.flush_batch, size=512, solid_texel=True)
        self.texture = None
        self.colors = None
        if texture_path is not None:
            self.texture = self.pico.IMG_LoadTexture(self.pico.renderer, str(texture_path).encode("utf-8"))
            if not self.texture:
                raise OSError(f"흙 텍스처를 열 수 없다: {texture_path}")
            self.pico.SDL_SetTextureScaleMode(self.texture, self.pico.SDL_ScaleModeLinear)
            if sample_colors:
                from ferrial_drive.rendering.pico_interpolation import read_rgba_image
                width, height, pixels = read_rgba_image(self.pico, texture_path)
                self.colors = GroundTextureColors(width, height, pixels, projection, settings["tile_m"])

    def color_at(self, point_pixels, *, blend):
        return self.colors.color_at(point_pixels, blend=blend) if self.colors else "#FFFFFF"

    def draw(self, camera, window_size, map_size_m, *, grid=True):
        r, p = self.renderer, self.projection
        width, height = window_size
        r.clear("#101517")
        left, top = camera.world_to_screen(p.project((0, 0)))
        right, bottom = camera.world_to_screen(p.project((map_size_m, map_size_m)))
        visible = Rect(max(0, left), max(0, top), max(0, min(width, right) - max(0, left)),
                       max(0, min(height, bottom) - max(0, top)))
        minimum = p.unproject(camera.screen_to_world((0, 0)))
        maximum = p.unproject(camera.screen_to_world((width, height)))
        with r.clip(visible):
            if self.texture:
                tile_m = self.settings["tile_m"]
                tile_w, tile_h = p.project((tile_m, tile_m))
                tile_w, tile_h = tile_w * camera.zoom, tile_h * camera.zoom
                tiles = []
                for row in range(max(0, floor(minimum[1] / tile_m)), min(ceil(map_size_m / tile_m), ceil(maximum[1] / tile_m))):
                    for column in range(max(0, floor(minimum[0] / tile_m)), min(ceil(map_size_m / tile_m), ceil(maximum[0] / tile_m))):
                        x, y = camera.world_to_screen(p.project((column * tile_m, row * tile_m)))
                        # 같은 경계에서 반올림해 소수점 배율의 타일 틈을 방지한다.
                        tiles.append((round(x), round(y), round(x + tile_w), round(y + tile_h)))
                if self.native is not None:
                    self.native.copy_tiles(self.texture, tiles)
                else:
                    for x, y, right, bottom in tiles:
                        target = self.pico.SDL_Rect(x, y, right - x, bottom - y)
                        self.pico.SDL_RenderCopy(self.pico.renderer, self.texture, None, byref(target))
            else:
                r.rect(visible, "#554A37")
            if grid:
                self.draw_grid(camera, window_size, map_size_m, (left, top, right, bottom), minimum, maximum)
        r.rect(Rect(left, top, right - left, bottom - top), "#E8CC8F", filled=False)

    def draw_grid(self, camera, window_size, map_size_m, bounds, minimum, maximum):
        r, projection = self.renderer, self.projection
        width, height = window_size
        left, top, right, bottom = bounds
        spacing, major = self.settings["grid_m"], self.settings["major_grid_m"]
        atlas = self.grid_atlas
        queue = getattr(r, "batch_queue", None)
        use_batch = (atlas is not None and queue is not None and queue.enabled and queue.unit_scale()
                     and self.native.draw_blend == self.pico.SDL_BLENDMODE_BLEND)
        with r.hud_batch(text_atlas=atlas) if use_batch else nullcontext():
            solid = (atlas.solid_uv(),) * 4 if use_batch else None
            for axis in range(2):
                first = max(0, ceil(minimum[axis] / spacing))
                last = min(floor(map_size_m / spacing), floor(maximum[axis] / spacing))
                for index in range(first, last + 1):
                    meters = index * spacing
                    strong = abs(meters / major - round(meters / major)) < 1e-7
                    position = projection.project((meters, 0) if axis == 0 else (0, meters))
                    x, y = camera.world_to_screen(position)
                    color, opacity = ("#D7C39C", 0.55) if strong else ("#CABEA4", 0.2)
                    if axis == 0:
                        line = x, max(0, top), x, min(height, bottom)
                        label = x + 4, height - 26
                    else:
                        line = max(0, left), y, min(width, right), y
                        label = 6, y + 3
                    if use_batch:
                        x1, y1, x2, y2 = map(round, line)
                        # 단위 배율에서 축 정렬 선이 덮는 1픽셀 폭을 사각형으로 옮긴다.
                        if axis == 0:
                            x2 += 1
                        else:
                            y2 += 1
                        if x2 > x1 and y2 > y1:
                            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                            queue.texture_quad(points, r.rgba(color, opacity), atlas.texture, solid)
                    else:
                        r.line(*line, color, opacity)
                    r.text(f"{meters:g}m", *label, "small", color, 0.85)

    def close(self):
        self.colors = None
        if self.grid_atlas is not None:
            self.grid_atlas.close()
        if self.texture:
            self.pico.SDL_DestroyTexture(self.texture)
            self.texture = None
