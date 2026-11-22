"""검 판정 면과 같은 Trail·현재 기체와 분리된 공격 잔상의 Pico2D 표현."""

from math import exp, isfinite
import ctypes as ct

from ferrial_drive.rendering.motion_vectors import target_phase
from ferrial_drive.assets.pico_opacity import texture_tint
from .sword_trail_geometry import curved_trail_sections, ribbon_edges, sweep_runs
from ferrial_drive.combat.geometry import Vec2
from .slash_rim import slash_rim_color


def body_wind_tint(settings, ground_color=None):
    color = settings.get("color", "#B8B8B8")
    gray = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    if ground_color is None:
        return gray
    blend = settings.get("ground_color_blend", 0.45)
    if not isfinite(blend) or not 0 <= blend <= 1:
        raise ValueError("검풍의 바닥 색 합성 비율은 0~1이어야 한다.")
    ground = tuple(int(ground_color[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(round(a * (1 - blend) + b * blend) for a, b in zip(gray, ground))


class PicoSwordEffects:
    def __init__(self, renderer, *, trail_backend="cpu", flow_directory=None):
        if trail_backend not in ("cpu", "compute"):
            raise ValueError("Trail 백엔드는 cpu 또는 compute다.")
        self.renderer = renderer
        self.flow_texture = None
        self.flow_key = None
        self.flow_directory = flow_directory
        self.trail_backend = trail_backend
        self.last_trail_backend = None
        self.compute_trail = None
        self.compute_unavailable = None
        self.prepared = False

    def prepare_flow(self, settings):
        from ferrial_drive.assets.trail_flow import load_flow_texture

        key = (settings.get("flow_strands", 18), settings.get("flow_softness", 0.018))
        if self.flow_key == key:
            return
        p = self.renderer.pico
        recipe,pixels = load_flow_texture(settings,self.flow_directory)
        width,height = recipe['width'],recipe['height']
        texture = p.SDL_CreateTexture(p.renderer, p.SDL_PIXELFORMAT_RGBA32, p.SDL_TEXTUREACCESS_STATIC, width, height)
        if not texture:
            raise RuntimeError("검 Trail 결 텍스처 생성 실패")
        try:
            if p.SDL_UpdateTexture(texture, None, pixels, width * 4) != 0:
                raise RuntimeError("검 Trail 결 텍스처 전송 실패")
            p.SDL_SetTextureBlendMode(texture, p.SDL_BLENDMODE_BLEND)
            p.SDL_SetTextureScaleMode(texture, p.SDL_ScaleModeLinear)
        except BaseException:
            p.SDL_DestroyTexture(texture)
            raise
        self.close()
        self.flow_texture, self.flow_key = texture, key

    def close(self):
        self.prepared = False
        if self.compute_trail is not None:
            self.compute_trail.close()
            self.compute_trail = None
        if self.flow_texture:
            self.renderer.pico.SDL_DestroyTexture(self.flow_texture)
        self.flow_texture = self.flow_key = None

    def prepare(self,settings):
        """미리 만든 결과 셰이더·버퍼·첫 실제 실행을 로딩에서 준비한다."""
        self.prepare_flow(settings)
        if self.prepared:
            return
        if self.trail_backend == "compute" and self.compute_unavailable is None:
            from ferrial_drive.rendering.bicubic import renderer_name
            from ferrial_drive.diagnostics.gpu_profile import bind_gl
            pico = self.renderer.pico
            if self.compute_trail is None:
                if renderer_name(pico) != "opengl":
                    self.compute_unavailable = "OpenGL 렌더러가 아니다."
                else:
                    query = bind_gl(pico,"glGetString",ct.c_char_p,[ct.c_uint])
                    version = query(0x1F02).decode().split()[0].split(".")
                    if tuple(map(int,version[:2])) < (4,3):
                        self.compute_unavailable = "OpenGL 4.3 미지원"
            if self.compute_unavailable is None:
                if self.compute_trail is None:
                    from .compute_sword_trail import ComputeSwordTrail
                    self.compute_trail = ComputeSwordTrail(pico)
                try:
                    self.compute_trail.prepare(settings,self.flow_texture)
                except BaseException:
                    self.compute_trail.close()
                    self.compute_trail = None
                    raise
        self.prepared = True

    def draw_trail(self, effects, camera, color):
        if not effects.sections:
            return
        self.prepare(effects.settings)
        if self.trail_backend == "compute" and self.compute_unavailable is None:
            self.compute_trail.render(effects,camera,self.renderer,self.flow_texture,color)
            self.last_trail_backend = "compute"
            return
        self.last_trail_backend = "cpu"
        self.draw_trail_cpu(effects,camera,color)

    def draw_trail_cpu(self, effects, camera, color):
        r = self.renderer
        p = r.pico
        if not effects.sections:
            return
        self.prepare_flow(effects.settings)
        vertices, indices = [], []
        core_vertices, core_indices = [], []
        drawn_thrusts = set()
        sample_seconds = effects.settings.get("sample_seconds", 1 / 240)
        runs = [curved_trail_sections(run, sample_seconds) for run in
                sweep_runs(effects.sections, effects.settings.get("trail_min_sweep_ratio", 0.12))]
        sections = [section for run in runs for section in run]
        starts, ranges = {}, {}
        for run in runs:
            low, high = run[0].created_seconds - sample_seconds, run[-1].created_seconds
            previous = low
            for section in run:
                starts[id(section)] = previous
                ranges[id(section)] = low, high
                previous = section.created_seconds
        for section in reversed(sections):
            profile = effects.profiles[section.energy_level - 1]
            opacity = effects.opacity(section) ** 2
            section_color = getattr(section, "color", None) or profile.get("color", color)
            rgb = tuple(int(section_color[i:i + 2], 16) for i in (1, 3, 5))
            if section.chevron:
                if section.strike_id in drawn_thrusts:
                    continue
                drawn_thrusts.add(section.strike_id)
                next_start = min((row.created_seconds for row in effects.sections
                                  if row.strike_id > section.strike_id), default=None)
                if next_start is not None:
                    opacity *= max(0, 1 - (effects.time_seconds - next_start) /
                                   effects.settings.get("thrust_transition_fade_seconds", 0.08))
                if opacity <= 0:
                    continue
                left, tip, right = section.chevron
                visual_scale = effects.settings.get("thrust_visual_scale", 1)
                left = tip + (left - tip) * visual_scale
                right = tip + (right - tip) * visual_scale
                level_scale = profile["reach_scale"] / effects.profiles[0]["reach_scale"]
                layers = ((vertices, indices, effects.settings.get("thrust_outer_half_width_pixels", 2.5), 0.9),
                          (core_vertices, core_indices, effects.settings.get("thrust_core_half_width_pixels", 0.8), 1))
                for mesh, faces, half_width, alpha_scale in layers:
                    edges = ribbon_edges((left, tip, right), (half_width * level_scale * visual_scale,) * 3)
                    for index in range(2):
                        offset = len(mesh)
                        tail = effects.settings.get("thrust_tail_opacity", 0.8)
                        ua, ub = index / 2, (index + 1) / 2
                        for point, strength, uv in ((edges[index][0], tail if index == 0 else 1, (ua, 0)),
                                                    (edges[index][1], tail if index == 0 else 1, (ua, 1)),
                                                    (edges[index + 1][1], tail if index == 1 else 1, (ub, 1)),
                                                    (edges[index + 1][0], tail if index == 1 else 1, (ub, 0))):
                            x, y = camera.world_to_screen((point.x, point.y))
                            alpha = round(255 * opacity * strength * alpha_scale * profile.get("trail_opacity", 0.3))
                            mesh.append(p.SDL_Vertex(p.SDL_FPoint(x, y), p.SDL_Color(*rgb, alpha), p.SDL_FPoint(*uv)))
                        faces.extend(offset + index for index in (0, 1, 2, 0, 2, 3))
                continue
            offset = len(vertices)
            low, high = ranges[id(section)]
            duration = max(1e-9, high - low)
            ua = max(0, min(1, (starts[id(section)] - low) / duration))
            ub = max(0, min(1, (section.created_seconds - low) / duration))
            inner = effects.settings.get("trail_inner_ratio", 0.62)
            inner_a = section.root_a + (section.tip_a - section.root_a) * inner
            inner_b = section.root_b + (section.tip_b - section.root_b) * inner
            for point, strength, uv in ((inner_a, 1, (ua, 0)), (section.tip_a, 1, (ua, 1)),
                                        (section.tip_b, 1, (ub, 1)), (inner_b, 1, (ub, 0))):
                x, y = camera.world_to_screen((point.x, point.y))
                alpha = round(255 * opacity * profile.get("trail_opacity", 0.3) * strength)
                vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y), p.SDL_Color(*rgb, alpha), p.SDL_FPoint(*uv)))
            indices.extend(offset + index for index in (0, 1, 2, 0, 2, 3))
        for mesh, faces in ((vertices, indices), (core_vertices, core_indices)):
            if not mesh:
                continue
            points = (p.SDL_Vertex * len(mesh))(*mesh)
            triangles = (ct.c_int * len(faces))(*faces)
            if p.SDL_RenderGeometry(p.renderer, self.flow_texture, points, len(points), triangles, len(triangles)):
                raise RuntimeError("검 Trail 그리기 실패")

    def draw_contacts(self, effects, camera):
        """실제 Trail의 좁은 리본과 속도축을 향한 화면 평면 입자를 한 번에 그린다."""
        contact = effects.contact_effects
        if contact is None or not (contact.slashes or contact.sparks):
            return
        p = self.renderer.pico
        vertices, indices = [], []
        camera_x, camera_y = camera.position
        screen_x, screen_y = camera.screen_center
        shake_x, shake_y = camera.feedback_offset_pixels
        zoom = camera.zoom

        def quad(points, rgb, alpha):
            offset = len(vertices)
            for point in points:
                x = (point.x - camera_x) * zoom + screen_x + shake_x
                y = (point.y - camera_y) * zoom + screen_y + shake_y
                vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y), p.SDL_Color(*rgb, round(255 * alpha)),
                                             p.SDL_FPoint(0, 0)))
            indices.extend(offset + i for i in (0, 1, 2, 0, 2, 3))

        settings = contact.settings
        rim_palettes = {}
        for mark in contact.slashes:
            points, width_scale, opacity = contact.slash_visual(mark)
            if len(mark.points) < 2:
                continue
            # 둥근 단면의 가상 법선에 따라 한 리본의 가장자리만 림으로 밝힌다.
            width = settings["slash_width_pixels"]
            fractions = (.04,settings.get("slash_center_width_ratio",.35),1,.04)
            knots = (0,.5,settings.get("slash_front_peak_ratio",.825),1)
            axis = points[-1]-points[0]
            normal = Vec2(-axis.y,axis.x).normalized(Vec2(0,1))
            segments = settings.get("slash_segments",24)
            bands = (-1,-.96,-.88,-.72,-.5,0,.5,.72,.88,.96,1)
            if mark.material not in rim_palettes:
                rim_palettes[mark.material] = tuple(slash_rim_color(position,mark.material,
                    settings.get("rim_lighting",{}),1) for position in bands)
            palette = rim_palettes[mark.material]
            offset = len(vertices)
            for row in range(segments+1):
                along = row/segments
                interval = next((i for i in range(3) if along <= knots[i+1]),2)
                fraction = (along-knots[interval])/(knots[interval+1]-knots[interval])
                half_width = fractions[interval]+(fractions[interval+1]-fractions[interval])*fraction
                center = points[0]+axis*along
                visibility = contact.slash_visibility(mark,along)
                side = normal*(width*width_scale*half_width*contact.slash_width_scale(visibility))
                for position,color in zip(bands,palette):
                    point = center + side * position
                    x = (point.x - camera_x) * zoom + screen_x + shake_x
                    y = (point.y - camera_y) * zoom + screen_y + shake_y
                    rgba = (*color[:3],round(color[3]*opacity*visibility*.95))
                    vertices.append(p.SDL_Vertex(p.SDL_FPoint(x,y),p.SDL_Color(*rgba),p.SDL_FPoint(0,0)))
            columns = len(bands)
            for row in range(segments):
                for column in range(columns-1):
                    a = offset + row * columns + column
                    indices.extend((a,a+1,a+columns+1,a,a+columns+1,a+columns))
        for spark in contact.sparks:
            age = contact.time_seconds - spark.created_seconds
            progress = age / spark.lifetime_seconds
            drag = 5
            # 지수 감속의 적분으로 프레임률과 무관한 이동을 계산한다.
            center = spark.origin + spark.velocity * ((1 - exp(-drag * age)) / drag) + Vec2(0, 70 * age * age)
            tangent = (spark.velocity * exp(-drag * age) + Vec2(0, 140 * age)).normalized(Vec2(1, 0))
            side = Vec2(-tangent.y, tangent.x) * spark.width_pixels * (1 - progress * 0.6)
            extent = tangent * ((3 + 13 * (1 - progress)) * spark.size_scale)
            quad((center - extent, center + side, center + extent * 0.4, center - side),
                 (255, 222, 156) if progress < 0.4 else (247, 145, 58), (1 - progress) ** 1.4)
        if vertices:
            previous = ct.c_int()
            p.SDL_GetRenderDrawBlendMode(p.renderer, ct.byref(previous))
            p.SDL_SetRenderDrawBlendMode(p.renderer, p.SDL_BLENDMODE_ADD)
            try:
                mesh = (p.SDL_Vertex * len(vertices))(*vertices)
                faces = (ct.c_int * len(indices))(*indices)
                if p.SDL_RenderGeometry(p.renderer, None, mesh, len(mesh), faces, len(faces)):
                    raise RuntimeError("검 베임선·금속 입자 그리기 실패")
            finally:
                p.SDL_SetRenderDrawBlendMode(p.renderer, previous.value)

    def draw_echoes(self, effects, camera, projection, sprite, resources, *, scale, interpolate, easing, pose_sprite=None):
        pending = []
        draw_batch = getattr(pose_sprite, "draw_echo_batch", None)

        def draw_pending():
            if pending and (draw_batch is None or not draw_batch(pending, scale=scale, easing=easing)):
                for name, seconds, x, y, opacity, tint, mix, brightness in pending:
                    pose_sprite.draw_echo(name, seconds, x, y, scale=scale, easing=easing,
                                          opacity=opacity, tint=tint, tint_mix=mix, brightness=brightness)
            pending.clear()

        for echo in effects.echoes:
            remaining = effects.opacity(echo)
            opacity = echo.opacity * remaining ** 1.1
            brightness = 0.16 + 0.84 * remaining
            if not isfinite(opacity) or opacity <= 0:
                continue
            x, y = camera.world_to_screen(projection.project(echo.position_m))
            if pose_sprite is not None and echo.pose_clip_name is not None:
                pending.append((echo.pose_clip_name, echo.elapsed_seconds, x, y, opacity,
                                echo.tint, echo.tint_mix, brightness))
                continue
            draw_pending()
            resource = resources[echo.clip_name]
            if sprite is not None and interpolate:
                sprite.draw(echo.clip_name, echo.elapsed_seconds, x, y, scale=scale,
                            opacity=opacity, easing=easing, blur=False, tint=echo.tint, tint_mix=echo.tint_mix, brightness=brightness)
            else:
                clip = resource.clips[echo.clip_name]
                duration = clip.duration_ms / 1000
                phase = target_phase(min(1, echo.elapsed_seconds / duration), easing=easing)
                frame = min(int(phase * len(clip.frames)), len(clip.frames) - 1)
                if sprite is not None and hasattr(sprite, "draw_frame"):
                    sprite.draw_frame(echo.clip_name, frame, x, y, scale=scale, opacity=opacity,
                                      tint=echo.tint, tint_mix=echo.tint_mix, brightness=brightness)
                else:
                    with resource.opacity(opacity), texture_tint(self.renderer.pico, resource.textures.values(),
                                                               echo.tint, echo.tint_mix, brightness):
                        resource.draw(echo.clip_name, frame, x, self.renderer.pico.get_canvas_height() - y,
                                      scale=scale, part_visibility={"shadow": False})
        draw_pending()

    def draw_body_wind(self, effects, camera, *, ground_color=None):
        """몸을 감아 도는 고정 반경의 짧은 궤적. 방사형 채움이나 팽창은 사용하지 않는다."""
        if not effects.body_winds:
            return
        self.prepare_flow(effects.settings)
        p = self.renderer.pico
        vertices, indices = [], []
        settings = effects.settings.get("body_wind", {})
        for wind in effects.body_winds:
            alpha = settings.get("opacity", 0.28)
            width = wind.band_width_pixels / wind.radius_pixels
            # 판정의 내부를 채우지 않고 같은 외주를 따라 힘이 감겨 흐르는 얇은 띠만 그린다.
            for index, (first, second) in enumerate(zip(wind.arc, wind.arc[1:])):
                u1, u2 = index / (len(wind.arc) - 1), (index + 1) / (len(wind.arc) - 1)
                offset = len(vertices)
                for edge, fraction, u in ((first, 1 - width, u1), (first, 1, u1),
                                          (second, 1, u2), (second, 1 - width, u2)):
                    point = wind.center + (edge - wind.center) * fraction
                    sampled = ground_color((point.x, point.y)) if ground_color else None
                    rgb = body_wind_tint(settings, sampled)
                    x, y = camera.world_to_screen((point.x, point.y))
                    uv = (u, (fraction - (1 - width)) / width)
                    vertices.append(p.SDL_Vertex(p.SDL_FPoint(x, y), p.SDL_Color(*rgb, round(255 * alpha)), p.SDL_FPoint(*uv)))
                indices.extend(offset + i for i in (0, 1, 2, 0, 2, 3))
        if vertices:
            mesh = (p.SDL_Vertex * len(vertices))(*vertices)
            faces = (ct.c_int * len(indices))(*indices)
            if p.SDL_RenderGeometry(p.renderer, self.flow_texture, mesh, len(mesh), faces, len(faces)):
                raise RuntimeError("몸 주변 검풍 그리기 실패")
