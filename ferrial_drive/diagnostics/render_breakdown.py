"""훈련장 HUD·월드의 선택적 계측과 진단용 표시 생략. 정상 표현은 수정하지 않는다."""

from collections import Counter, defaultdict
from contextlib import contextmanager, nullcontext
import sys
from time import perf_counter_ns

from .timing import TimingRecorder


VARIANTS = ("baseline", "no_hud", "no_world", "no_ui_blur", "no_camera_blur", "no_actor_blur",
            "no_auxiliary", "no_body_wind", "no_trail", "no_echoes", "no_ground_effects", "no_shadow",
            "no_radar", "no_dialogue", "no_resources", "no_rings", "cpu_trail", "compute_trail", "no_hud_batch",
            "collision_polygon", "collision_capsule", "ground_individual", "ground_batched", "individual_enemy_parts", "individual_enemy_shadows", "no_enemy_labels", "debug_enemy_labels")


class RenderBreakdown:
    def __init__(self, app, *, detailed=False, variant="baseline"):
        if variant not in VARIANTS:
            raise ValueError("지원하지 않는 진단 조건이다.")
        self.app, self.detailed, self.variant = app, detailed, variant
        self.recorder = TimingRecorder(enabled=True, session="render-breakdown")
        self.active, self.frames = False, 0
        self.stack, self.originals = [], []
        self.calls = defaultdict(Counter)
        self.self_ns = Counter()
        self.blur_requests = Counter()
        self.latest_ms = {}
        self.hooked = set()
        self.collision_checks = self.collision_hits = 0
        self.combat_samples = Counter()
        self.combat_peaks = Counter()
        self.combat_alive_min = None
        self.ground_counts = Counter()

    def step(self, measuring):
        self.active = measuring
        self.frames += int(measuring)

    @contextmanager
    def scope(self, name):
        if not self.active:
            self.stack.append([name, 0, 0])
            try:
                yield
            finally:
                self.stack.pop()
            return
        entry = [name, perf_counter_ns(), 0]
        self.stack.append(entry)
        try:
            with self.recorder.scope(name):
                yield
        finally:
            elapsed = perf_counter_ns() - entry[1]
            self.stack.pop()
            self.latest_ms[name] = elapsed/1e6
            self.self_ns[name] += max(0, elapsed-entry[2])
            if self.stack:
                self.stack[-1][2] += elapsed

    def replace(self, target, name, function):
        original = getattr(target, name)
        own = hasattr(target, "__dict__") and name in target.__dict__
        self.originals.append((target, name, original, own))
        setattr(target, name, function(original))

    def method(self, target, name, label, *, skip=None, hud_phase=False):
        key = id(target), name
        if key in self.hooked:
            return
        self.hooked.add(key)
        def wrap(original):
            def measured(*args, **kwargs):
                if self.variant == skip:
                    return None
                actual = label
                if hud_phase:
                    phase = "probe" if self.app.hud.view._panel_probe is not None else "draw"
                    actual = "hud." + phase + "." + label
                if self.detailed or label in ("world.total", "hud.total", "update.total"):
                    with self.scope(actual):
                        result = original(*args, **kwargs)
                else:
                    result = original(*args, **kwargs)
                if self.active and label == "world.ground_effects":
                    self.ground_counts.update(getattr(target, "stats", {}))
                return result
            return measured
        self.replace(target, name, wrap)

    def install(self):
        app = self.app
        if self.variant in ("no_enemy_labels", "debug_enemy_labels"):
            view = getattr(app, "encounter_view", None)
            if view is None:
                raise ValueError("적 이름표·체력 막대 대조에는 교전 장면이 필요하다.")
            self.replace(view, "show_enemy_labels", lambda old: self.variant == "debug_enemy_labels")
        if self.variant in ("individual_enemy_parts", "individual_enemy_shadows"):
            view = getattr(app, "encounter_view", None)
            if view is None:
                raise ValueError("적 묶음 제출 대조에는 교전 장면이 필요하다.")
            self.replace(view, "batch_enemy_shadows", lambda old: False)
            if self.variant == "individual_enemy_parts":
                self.replace(view, "batch_enemy_parts", lambda old: False)
        if self.variant in ("ground_individual", "ground_batched") and app.ground_effect_renderer is not None:
            self.replace(app.ground_effect_renderer, "backend", lambda old: self.variant.removeprefix("ground_"))
        self.method(app, "update", "update.total")
        for name, label in (("bind_hud_world", "update.targets"), ("update_guns", "update.guns"),
                            ("update_hud", "update.hud"), ("advance_encounter", "update.encounter")):
            if self.detailed and hasattr(app, name):
                self.method(app, name, label)
        encounter = getattr(app, "encounter", None)
        if encounter is not None:
            for name in ("advance", "_think", "_move", "advance_reactions"):
                if self.detailed:
                    self.method(encounter, name, "update.enemies." + name)
            def sample_update(original):
                def update(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if self.active:
                        alive = sum(enemy.alive for enemy in encounter.enemies.values())
                        self.combat_alive_min = alive if self.combat_alive_min is None else min(self.combat_alive_min, alive)
                        values = {"alive_enemies": alive, "enemy_projectiles": len(encounter.projectiles),
                                  "player_projectiles": sum(len(gun.projectiles) for gun in app.guns)}
                        self.combat_samples["frames"] += 1
                        for key, value in values.items():
                            self.combat_samples[key] += value
                            self.combat_peaks[key] = max(self.combat_peaks[key], value)
                        self.combat_samples["running_frames"] += encounter.result == "running"
                        self.combat_samples["overdrive_frames"] += bool(app.hud.state.overdrive)
                        self.combat_samples["paused_frames"] += bool(getattr(app, "paused", False) or getattr(app.hud, "blocking", False))
                        self.combat_samples["ranged_frames"] += app.hud.state.hud.active_weapon_kind == "ranged"
                    return result
                return update
            self.replace(app, "update", sample_update)
            if self.detailed and app.encounter_view is not None:
                self.method(app.encounter_view, "draw", "world.enemies")
        if self.detailed and getattr(app, "gun_renderer", None) is not None:
            self.method(app.gun_renderer, "draw", "world.gun_effects")
        if self.variant in ("collision_polygon","collision_capsule"):
            self.replace(app.sword_effects,"hitbox_type",lambda old:self.variant.removeprefix("collision_"))
        if app.sword_effects is not None:
            def update_wrapper(original):
                def update(*a,**kw):
                    with self.scope("update.sword_effects"):
                        result = original(*a,**kw)
                    if self.active:
                        self.collision_checks += app.sword_effects.last_collision_checks
                        self.collision_hits += len(app.sword_effects.hits)
                    return result
                return update
            self.replace(app.sword_effects,"update",update_wrapper)
        if self.variant == 'no_hud_batch':
            self.replace(app.hud.renderer.batch_queue, 'enabled', lambda old: False)
        if self.variant in ("cpu_trail", "compute_trail"):
            self.replace(app.sword_renderer,"trail_backend",lambda old: self.variant.removesuffix("_trail"))
        self.method(app, "draw_world", "world.total")
        self.method(app.hud, "draw", "hud.total", skip="no_hud")
        if self.variant == "no_world":
            self.replace(app, "draw_world", lambda original: lambda: app.camera.world_to_screen(
                app.projection.project(app.controller.position_m)))
        if self.variant in ("no_world", "no_camera_blur"):
            self.replace(app.hud.view, "world_motion_blur", lambda original: lambda *a, **kw: nullcontext())
        if self.variant == "no_actor_blur":
            for sprite in (app.attack_sprite, app.motion_sprite):
                if sprite is not None:
                    self.replace(sprite, "shutter_seconds", lambda original: 0)

        world = [(app.ground, "draw", "world.ground", None),
                 (app.shadow_blend, "draw", "world.shadow", "no_shadow"),
                 (app.ground_effect_renderer, "draw", "world.ground_effects", "no_ground_effects"),
                 (app.sword_renderer, "draw_echoes", "world.echoes", "no_echoes"),
                 (app.sword_renderer, "draw_trail", "world.trail", "no_trail"),
                 (app.sword_renderer, "draw_body_wind", "world.body_wind", "no_body_wind")]
        for sprite in (app.attack_sprite, app.motion_sprite):
            world.extend([(sprite, "draw", "world.actor", None), (sprite, "draw_frame", "world.actor_static", None)])
        for target, name, label, skip in world:
            if target is not None and hasattr(target, name):
                self.method(target, name, label, skip=skip)

        if self.detailed or self.variant in ("no_auxiliary", "no_ui_blur"):
            from ferrial_drive.ui_v2 import weapon_card
            self.method(weapon_card, "draw_auxiliary_slot", "auxiliary", skip="no_auxiliary", hud_phase=True)
        for name in ("radar", "dialogue", "resources"):
            if self.variant == "no_" + name and not self.detailed:
                self.method(app.hud.view, name, name, skip=self.variant, hud_phase=True)
        if self.variant == "no_rings" and not self.detailed:
            self.method(app.hud.renderer, "ring", "renderer.ring", skip=self.variant)
        if self.detailed:
            view = app.hud.view
            self.method(view, "prepare_panel_effects", "hud.prepare")
            for name in ("weapons", "resources", "minimap", "radar", "target", "dialogue", "absorption",
                         "perspective_counter", "player_health", "ultimate_icon", "panel_scanlines"):
                self.method(view, name, name, skip="no_"+name, hud_phase=True)
            for name in ("film_grain", "scanline_layer", "filtered_polygons", "ring", "neon_text", "text"):
                self.method(app.hud.renderer, name, "renderer." + name, skip="no_rings" if name == "ring" else None)
            self._install_sdl_counts(app.pico)
        self._install_blur(app.hud.renderer)
        return self

    def _install_sdl_counts(self, pico):
        for name in ("SDL_RenderGeometry", "SDL_RenderCopy", "SDL_RenderCopyEx", "SDL_RenderCopyF",
                     "SDL_RenderCopyExF", "SDL_RenderDrawLine", "SDL_RenderDrawLines", "SDL_RenderFillRect", "SDL_RenderFillRects",
                     "SDL_SetRenderTarget", "SDL_RenderFlush", "SDL_CreateTexture", "SDL_CreateTextureFromSurface"):
            if not hasattr(pico, name):
                continue

            def wrapper(original, api=name):
                def counted(*args):
                    if self.active:
                        owner = self.stack[-1][0] if self.stack else "outside"
                        domain = next((entry[0] for entry in self.stack if entry[0] in ("hud.total", "world.total")), "outside")
                        self.calls[domain][api] += 1
                        if owner != domain:
                            self.calls[owner][api] += 1
                    return original(*args)
                return counted
            self.replace(pico, name, wrapper)

    def _install_blur(self, renderer):
        def wrapper(original):
            @contextmanager
            def blur(*args, **kwargs):
                domain = "hud" if any(entry[0] == "hud.total" for entry in self.stack) else "world"
                # 가벼운 계측에서도 바깥 HUD 범위로 카메라와 UI 필터를 구분한다.
                if self.variant == "no_ui_blur" and domain == "hud":
                    yield
                    return
                if self.active:
                    self.blur_requests[domain] += 1
                context = original(*args, **kwargs)
                if not self.detailed or not self.active:
                    with context:
                        yield
                    return
                with self.scope(domain + ".blur.setup"):
                    context.__enter__()
                try:
                    yield
                except BaseException:
                    with self.scope(domain + ".blur.composite"):
                        suppress = context.__exit__(*sys.exc_info())
                    if not suppress:
                        raise
                else:
                    with self.scope(domain + ".blur.composite"):
                        context.__exit__(None, None, None)
            return blur
        self.replace(renderer, "directional_blur", wrapper)

    def report(self):
        snapshot = self.recorder.snapshot()
        renderer = getattr(getattr(self.app, 'hud', None), 'renderer', None)
        queue = getattr(renderer, 'batch_queue', None)
        encounter = getattr(self.app, "encounter", None)
        view = getattr(self.app, "encounter_view", None)
        combat_frames = self.combat_samples["frames"]
        combat = None if encounter is None else {
            "sampled_frames": combat_frames, "sampling": "측정 구간 update 직후. 준비 프레임 제외.",
            "initial_enemies": len(encounter.enemies), "alive_min": self.combat_alive_min,
            "mean": {key: self.combat_samples[key] / combat_frames if combat_frames else None
                     for key in ("alive_enemies", "enemy_projectiles", "player_projectiles")},
            "peak": dict(self.combat_peaks), "running_frames": self.combat_samples["running_frames"],
            "overdrive_frames": self.combat_samples["overdrive_frames"],
            "paused_frames": self.combat_samples["paused_frames"],
            "ranged_frames": self.combat_samples["ranged_frames"],
            "final_result": encounter.result,
            "enemy_rendering_last": dict(view.primitives.stats) if view is not None else None}
        return {"detailed": self.detailed, "variant": self.variant, "frames": self.frames,
                "ground_effects_backend": getattr(getattr(self.app, "ground_effect_renderer", None), "backend", None),
                "ground_effects_per_frame": {key: value / max(1, self.frames) for key, value in self.ground_counts.items()},
                "combat_activity": combat,
                "hud_batch_enabled": queue.enabled if queue is not None else False,
                "hud_batch_last": dict(queue.stats) if queue is not None and queue.enabled else None,
                "timings": snapshot,
                "self_ms_per_frame": {k: v / max(1, self.frames) / 1e6 for k, v in self.self_ns.items()},
                "sdl_calls_per_frame": {k: {api: count/max(1, self.frames) for api, count in counts.items()}
                                        for k, counts in self.calls.items()},
                "blur_requests_per_frame": {k: v/max(1, self.frames) for k, v in self.blur_requests.items()},
                "collision_checks_per_frame":self.collision_checks/max(1,self.frames),
                "collision_hits":self.collision_hits,
                "semantics": "중첩 wall 시간. 부모/자식·호출 수는 중복되어 합산하지 않는다. 상세 계측 오버헤드 미보정."}

    def close(self):
        for target, name, original, own in reversed(self.originals):
            if own:
                setattr(target, name, original)
            else:
                delattr(target, name)
        self.originals.clear()
        self.hooked.clear()
