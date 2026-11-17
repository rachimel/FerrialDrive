"""훈련장 탄환·총구 섬광·명중 표현. 탄환의 진행·명중 판정을 소유하지 않는다."""

from ctypes import byref, c_int
from math import cos, exp, isfinite, pi, sin, tau
from random import Random

from ferrial_drive.combat.geometry import Vec2


CONTACT_CIRCLE = tuple((cos(tau * step / 24), sin(tau * step / 24)) for step in range(24))
IMPACT_CIRCLE = tuple((cos(tau * step / 16), sin(tau * step / 16)) for step in range(16))


def tracer_pixels(tail_color, core_color, width=64, height=16):
    """오른쪽 탄두·왼쪽 꼬리의 RGBA 텍스처를 한 번 굽는다."""
    tail = tuple(int(tail_color[i:i + 2], 16) for i in (1, 3, 5))
    core = tuple(int(core_color[i:i + 2], 16) for i in (1, 3, 5))
    pixels = bytearray()
    for y in range(height):
        across = (y + 0.5) / height * 2 - 1
        for x in range(width):
            along = (x + 0.5) / width
            radius = 0.18 + 0.82 * along
            edge = max(0, 1 - (across / radius) ** 2)
            alpha = edge ** 2 * along ** 0.65 * min(1, (1 - along) * 12)
            hot = exp(-((across / 0.24) ** 2)) * along
            pixels.extend((*[round(a + (b - a) * hot) for a, b in zip(tail, core)], round(alpha * 255)))
    return bytes(pixels)


def muzzle_flash_pixels(width=96, height=64):
    """총구를 왼쪽 7%에 둔 화염·곁불의 RGBA를 로딩 중 생성한다."""
    pixels = bytearray()
    for y in range(height):
        across = (y + .5) / height * 2 - 1
        for x in range(width):
            along = (x + .5) / width - .07
            flame = 0.0
            for length, slope, radius in ((.86, 0, .30), (.57, .42, .18), (.65, -.34, .17)):
                t = along / length
                if 0 < t < 1:
                    span = radius * sin(pi * t) ** .65
                    edge = max(0, 1 - ((across - slope * t) / span) ** 2)
                    flame = max(flame, edge ** 1.4 * min(1, t * 16) * (1 - t) ** .35)
            heat = exp(-((across / .16) ** 2) - ((along - .18) / .34) ** 2)
            brightness = round(170 + 85 * heat)
            pixels.extend((brightness, brightness, brightness, round(255 * flame)))
    return bytes(pixels)


class PicoGunEffects:
    def __init__(self, renderer, settings=None):
        self.renderer = renderer
        settings = settings or {}
        self.length_pixels = settings.get("length_pixels", 36)
        self.width_pixels = settings.get("width_pixels", 6)
        self.length_scales_by_energy_level = tuple(settings.get("length_scales_by_energy_level", (1, 1.25, 1.5)))
        if any(not isfinite(v) or v <= 0 for v in (self.length_pixels, self.width_pixels)):
            raise ValueError("총탄 표시 길이·폭은 양수 픽셀 값이어야 한다.")
        if (len(self.length_scales_by_energy_level) != 3
                or any(not isfinite(v) or v <= 0 for v in self.length_scales_by_energy_level)):
            raise ValueError("총탄 Trail 길이 배율은 에너지 1~3단계별 양수 유한값이어야 한다.")
        flash = settings.get("muzzle_flash", {})
        self.flash_length_pixels = flash.get("length_pixels", 84)
        self.flash_width_pixels = flash.get("width_pixels", 90)
        self.flash_lifetime_seconds = flash.get("lifetime_seconds", .045)
        self.flash_size_scale_range = tuple(flash.get("size_scale_range", (.8, 1.2)))
        if any(not isfinite(v) or v <= 0 for v in
               (self.flash_length_pixels, self.flash_width_pixels, self.flash_lifetime_seconds)):
            raise ValueError("총구 화염의 길이·폭·표시 시간은 양수 유한값이어야 한다.")
        if (len(self.flash_size_scale_range) != 2
                or any(not isfinite(v) or v <= 0 for v in self.flash_size_scale_range)
                or self.flash_size_scale_range[0] > self.flash_size_scale_range[1]):
            raise ValueError("총구 화염 크기 변주는 양수 최소·최대 배율이어야 한다.")
        self.flash_random = Random(0)
        self.flash_shot_key = None
        self.flash_size_scale = 1
        self.texture = self.flash_texture = None
        self.contact_vertices = None
        self.contact_vertex_views = []
        self.default_color = settings.get("tail_color", "#FFB843")
        p = renderer.pico
        # 색상은 정점으로 공급하고 텍스처는 Trail의 알파 형상만 공유한다.
        pixels = tracer_pixels("#FFFFFF", "#FFFFFF")
        self.texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC, 64, 16)
        if not self.texture:
            raise RuntimeError("총탄 텍스처 생성 실패")
        try:
            if p.SDL_UpdateTexture(self.texture, None, pixels, 64 * 4) != 0:
                raise RuntimeError("총탄 텍스처 전송 실패")
            if p.SDL_SetTextureBlendMode(self.texture, p.SDL_BLENDMODE_BLEND) != 0:
                raise RuntimeError("총탄 알파 혼합 설정 실패")
            if p.SDL_SetTextureScaleMode(self.texture, p.SDL_ScaleModeLinear) != 0:
                raise RuntimeError("총탄 필터 설정 실패")
            self.flash_texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32,
                                                    p.SDL_TEXTUREACCESS_STATIC, 96, 64)
            if not self.flash_texture:
                raise RuntimeError("총구 화염 텍스처 생성 실패")
            if p.SDL_UpdateTexture(self.flash_texture, None, muzzle_flash_pixels(), 96 * 4) != 0:
                raise RuntimeError("총구 화염 텍스처 전송 실패")
            if p.SDL_SetTextureBlendMode(self.flash_texture, p.SDL_BLENDMODE_ADD) != 0:
                raise RuntimeError("총구 화염 가산 혼합 설정 실패")
            if p.SDL_SetTextureScaleMode(self.flash_texture, p.SDL_ScaleModeLinear) != 0:
                raise RuntimeError("총구 화염 필터 설정 실패")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.contact_vertices = None
        self.contact_vertex_views.clear()
        for name in ("texture", "flash_texture"):
            texture = getattr(self, name, None)
            if texture:
                self.renderer.pico.SDL_DestroyTexture(texture)
                setattr(self, name, None)

    def draw(self, camera, guns, *, active_gun=None, muzzle=None, color=None, contact=None, energy_level=1):
        if type(energy_level) is not int or not 1 <= energy_level <= 3:
            raise ValueError("총탄 Trail 에너지 레벨은 1~3 정수여야 한다.")
        renderer, p, zoom = self.renderer, self.renderer.pico, camera.zoom
        trail_length = self.length_pixels * self.length_scales_by_energy_level[energy_level - 1]
        vertices, indices = [], []
        rgb = renderer.rgba(color or self.default_color)[:3]

        def add_tracer(start, end, width, ink, opacity=1):
            direction = (end - start).normalized()
            if direction.length < 1e-9:
                return
            a = camera.world_to_screen((start.x, start.y))
            b = camera.world_to_screen((end.x, end.y))
            normal = (-direction.y * width * zoom / 2, direction.x * width * zoom / 2)
            base = len(vertices)
            for point, sign, uv in ((a, -1, (0, 0)), (b, -1, (1, 0)),
                                    (b, 1, (1, 1)), (a, 1, (0, 1))):
                vertices.append(p.SDL_Vertex(p.SDL_FPoint(point[0] + sign * normal[0], point[1] + sign * normal[1]),
                                             p.SDL_Color(*ink, round(255 * opacity)), p.SDL_FPoint(*uv)))
            indices.extend(base + i for i in (0, 1, 2, 0, 2, 3))

        for gun in guns:
            for bullet in gun.projectiles:
                # 총구 뒤로 뻗지 않도록 실제 누적 이동 거리까지만 꼬리를 늘린다.
                length = min(trail_length, bullet.traveled_pixels)
                if length <= 1e-9:
                    continue
                start = bullet.position - bullet.direction * length
                add_tracer(start, bullet.position, self.width_pixels, rgb)
        if vertices:
            renderer.flush_batch()
            mesh = (p.SDL_Vertex * len(vertices))(*vertices)
            faces = (c_int * len(indices))(*indices)
            if p.SDL_RenderGeometry(p.renderer, self.texture, mesh, len(mesh), faces, len(faces)) != 0:
                raise RuntimeError("총탄 텍스처 표시 실패")
        if contact is not None:
            self.draw_contacts(camera, contact, rgb)
        if active_gun is not None and muzzle is not None:
            self.draw_muzzle(camera, active_gun, muzzle, rgb)

    def draw_muzzle(self, camera, gun, muzzle, rgb):
        """실제 발사 직후에만 미리 만든 화염을 탄도 방향으로 표시한다."""
        age = gun.shot_age_seconds
        if not 0 <= age < self.flash_lifetime_seconds:
            return
        renderer, p = self.renderer, self.renderer.pico
        shot_key = (gun, gun.shots_fired, gun.last_shot_seconds)
        if shot_key != self.flash_shot_key:
            self.flash_shot_key = shot_key
            self.flash_size_scale = self.flash_random.uniform(*self.flash_size_scale_range)
        progress = age / self.flash_lifetime_seconds
        scale = self.flash_size_scale * (1 - .3 * progress)
        direction = gun.shot_direction.normalized(Vec2(1, 0))
        side = Vec2(-direction.y, direction.x) * (self.flash_width_pixels * scale / 2)
        length = self.flash_length_pixels * scale
        start, end = muzzle - direction * (length * .07), muzzle + direction * (length * .93)
        vertices = []
        for point, uv in ((start - side, (0, 0)), (end - side, (1, 0)),
                          (end + side, (1, 1)), (start + side, (0, 1))):
            x, y = camera.world_to_screen((point.x, point.y))
            vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y),
                p.SDL_Color(*rgb, round(255 * (1 - progress))), p.SDL_FPoint(*uv)))
        renderer.flush_batch()
        mesh = (p.SDL_Vertex * 4)(*vertices)
        faces = (c_int * 6)(0, 1, 2, 0, 2, 3)
        if p.SDL_RenderGeometry(p.renderer, self.flash_texture, mesh, 4, faces, 6) != 0:
            raise RuntimeError("총구 화염 표시 실패")

    def draw_contacts(self, camera, contact, energy_rgb):
        """명중점의 에너지 섬광과 금속 불똥을 한 묶음으로 가산 합성한다."""
        renderer, p = self.renderer, self.renderer.pico
        # 형태별 정점 수의 상한만 확보한다. SDL 정점·하위 구조체는 프레임 사이 재사용한다.
        required = (len(contact.impacts) * 105
                    + len(contact.explosions) * (271 + contact.explosion_rays * 8)
                    + len(contact.sparks) * 8)
        if not required:
            return
        if required > len(self.contact_vertex_views):
            capacity = max(required, 1024, len(self.contact_vertex_views) * 2)
            self.contact_vertices = (p.SDL_Vertex * capacity)()
            self.contact_vertex_views = [(v.position, v.color) for v in self.contact_vertices]
        vertices = self.contact_vertex_views
        vertex_count, indices = 0, []
        # 이 카메라의 월드→화면 변환은 공통 배율과 평행이동이다.
        zoom = camera.zoom
        screen_x, screen_y = camera.world_to_screen((0, 0))

        def vertex(x, y, ink, alpha):
            nonlocal vertex_count
            position, color = vertices[vertex_count]
            position.x, position.y = x * zoom + screen_x, y * zoom + screen_y
            color.r, color.g, color.b, color.a = *ink, alpha
            vertex_count += 1

        def diamond(start, end, half_width, ink, opacity):
            direction = (end - start).normalized()
            normal = Vec2(-direction.y, direction.x) * half_width
            center = (start + end) * .5
            base = vertex_count
            alpha = round(255 * opacity)
            for point in (start, center + normal, end, center - normal):
                vertex(point.x, point.y, ink, alpha)
            indices.extend(base + i for i in (0, 1, 2, 0, 2, 3))

        def glow(origin, radii, ink, opacity):
            base, segments = vertex_count, len(CONTACT_CIRCLE)
            vertex(origin.x, origin.y, ink, round(255 * max(0, min(1, opacity))))
            for step, (x, y) in enumerate(CONTACT_CIRCLE):
                vertex(origin.x + x * radii.x, origin.y + y * radii.y, ink, 0)
                indices.extend((base, base + 1 + step, base + 1 + (step + 1) % segments))

        def ring(origin, radii, ink, opacity, thickness=.08):
            base, segments = vertex_count, len(CONTACT_CIRCLE)
            alpha = round(255 * max(0, min(1, opacity)))
            for x, y in CONTACT_CIRCLE:
                dx, dy = x * radii.x, y * radii.y
                vertex(origin.x + dx * (1 - thickness), origin.y + dy * (1 - thickness), ink, alpha)
                vertex(origin.x + dx, origin.y + dy, ink, 0)
            for step in range(segments):
                a, b = base + step * 2, base + ((step + 1) % segments) * 2
                indices.extend((a, b, b + 1, a, b + 1, a + 1))

        for impact in contact.impacts:
            age = contact.time_seconds - impact.created_seconds
            if not 0 <= age < impact.lifetime_seconds:
                continue
            progress = age / impact.lifetime_seconds
            opacity = (1 - progress) ** 1.5
            radius = impact.radius_pixels * (.65 + .35 * progress)
            rgb = energy_rgb
            origin, axis = impact.origin, impact.direction
            side = Vec2(-axis.y, axis.x)
            # 중심에서 투명 가장자리까지 보간하는 작은 광륜. 추가 텍스처는 만들지 않는다.
            base = vertex_count
            vertex(origin.x, origin.y, rgb, round(170 * opacity))
            segments = len(IMPACT_CIRCLE)
            for step, (x, y) in enumerate(IMPACT_CIRCLE):
                vertex(origin.x + x * radius, origin.y + y * radius, rgb, 0)
                indices.extend((base, base + 1 + step, base + 1 + (step + 1) % segments))
            # 탄도 축과 그 수직축으로 짧고 날카로운 빛을 더한다.
            for direction, scale in ((axis, 1), (side, .7)):
                extent = direction * (radius * scale)
                diamond(origin - extent, origin + extent, radius * .17, rgb, opacity)
                diamond(origin - extent * .4, origin + extent * .4,
                        radius * .07, (255, 250, 240), opacity)
            ring(origin, Vec2(radius, radius * .65) * (.45 + progress), rgb, opacity * .85)
            # 짧은 방사 파편은 금속 불꽃과 별도로 에너지색을 따른다.
            for ray in range(6):
                angle = tau * ray / 6 + impact.direction.x
                direction = Vec2(cos(angle), sin(angle))
                distance = radius * (.3 + progress * 1.25)
                diamond(origin + direction * distance * .6, origin + direction * distance,
                        radius * .035, rgb, opacity)

        for blast in contact.explosions:
            age = contact.time_seconds - blast.created_seconds
            if not 0 <= age < blast.lifetime_seconds:
                continue
            progress = age / blast.lifetime_seconds
            opacity = (1 - progress) ** 1.4
            radius = blast.radii_pixels
            origin = blast.origin
            expansion = .25 + .75 * (1 - (1 - progress) ** 3)
            # 실제 3m 지면 반경의 타원 충격파와 위로 부푸는 발광 구름을 분리한다.
            ring(origin, radius * expansion, energy_rgb, opacity, .13)
            ring(origin, radius * (expansion * .7), (220, 246, 255), opacity * .7, .06)
            glow(origin, radius * (.55 + progress * .6), energy_rgb, opacity * .9)
            for lobe in range(5):
                angle = tau * lobe / 5 + blast.seed * 2.39996
                offset = Vec2(cos(angle) * radius.x * .28, sin(angle) * radius.y * .28)
                offset = offset * expansion + Vec2(0, -radius.x * progress * .2)
                glow(origin + offset, Vec2(radius.x * .48, radius.x * .38) * (.4 + progress),
                     energy_rgb, opacity * .6)
            hot = max(0, 1 - progress * 3)
            glow(origin, Vec2(radius.x, radius.x) * (.18 + progress * .25), (255, 250, 240), hot)
            for ray in range(contact.explosion_rays):
                angle = tau * ray / contact.explosion_rays + blast.seed * 2.39996
                direction = Vec2(cos(angle), sin(angle) * .65)
                end = origin + direction * radius.x * (.25 + progress * .95)
                start = end - direction * radius.x * (.12 + .15 * (1 - progress))
                diamond(start, end, 1.8 * (1 - progress), energy_rgb, opacity)
                diamond(start, end, .65 * (1 - progress), (255, 250, 240), opacity)

        for spark in contact.sparks:
            age = contact.time_seconds - spark.created_seconds
            if not 0 <= age < spark.lifetime_seconds:
                continue
            opacity = (1 - age / spark.lifetime_seconds) ** .65
            end = spark.origin + spark.velocity * age
            # 총탄용 소프트 알파를 축소하지 않아 가는 불똥의 중심이 흐려지지 않는다.
            start = end - spark.velocity * .028
            diamond(start, end, spark.width_pixels / 2, (255, 174, 55), opacity)
            diamond(start, end, spark.width_pixels * .2, (255, 248, 224), opacity)
        if not vertex_count:
            return
        renderer.flush_batch()
        previous = c_int()
        p.SDL_GetRenderDrawBlendMode(p.renderer, byref(previous))
        p.SDL_SetRenderDrawBlendMode(p.renderer, p.SDL_BLENDMODE_ADD)
        try:
            faces = (c_int * len(indices))(*indices)
            if p.SDL_RenderGeometry(p.renderer, None, self.contact_vertices, vertex_count, faces, len(faces)) != 0:
                raise RuntimeError("총 에너지 명중·금속 불똥 표시 실패")
        finally:
            p.SDL_SetRenderDrawBlendMode(p.renderer, previous.value)
