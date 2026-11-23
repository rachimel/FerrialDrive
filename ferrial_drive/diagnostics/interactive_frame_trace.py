"""직접 조작의 프레임에 실제 전투 이벤트와 함수별 경과 시간을 연결한다."""

from collections import Counter


DIALOGUE_SCOPE = "hud.draw.dialogue"
DIALOGUE_PHASES = {
    "renderer.text": "text",
    "renderer.rich_text": "text",
    "renderer.filtered_polygons": "filtered_polygons",
    "hud.draw.panel_scanlines": "scanlines",
}


class InteractiveFrameTrace:
    def __init__(self, probe, canvas):
        self.probe, self.canvas = probe, canvas
        self.app = probe.app
        self.recording = False
        self.times, self.events = {}, []
        self.live_combat_root = f"{type(self.app).__name__}.draw_live_combat_motion"
        self.live_combat_stacks = Counter()
        self.dialogue_ns = Counter()

    def begin(self):
        self.times.clear()
        self.events.clear()
        self.live_combat_stacks.clear()
        self.dialogue_ns.clear()
        self.recording = self.probe.active = True

    def timing(self, path, elapsed, own):
        if self.recording:
            scope = path[-1]
            row = self.times.get(scope)
            if row is None:
                self.times[scope] = [1, elapsed, own]
            else:
                row[0] += 1
                row[1] += elapsed
                row[2] += own
            if self.live_combat_root in path:
                self.live_combat_stacks[path[path.index(self.live_combat_root):]] += own
            if DIALOGUE_SCOPE in path:
                children = path[path.index(DIALOGUE_SCOPE) + 1:]
                phase = next((DIALOGUE_PHASES[label] for label in children if label in DIALOGUE_PHASES), "other")
                self.dialogue_ns[phase] += own

    def stop(self):
        self.recording = self.probe.active = False

    def finish(self, row, budget_ms):
        if row["work_ms"] > budget_ms:
            hud = self.app.hud.state.hud
            slide = getattr(getattr(self.app.hud, "loadout_slide", None), "visual", None)
            row["combat_events"] = list(self.events)
            row["combat_state"] = {
                "loadout": hud.active_loadout_index + 1,
                "weapon_kind": hud.active_weapon_kind,
                "loadout_transition": getattr(self.app, "loadout_fade_seconds", 0) > 0 or getattr(slide, "moving", False),
            }
            row["function_timings_ns"] = dict(self.times)
            if any(phase != "other" for phase in self.dialogue_ns):
                row["dialogue_timings_ns"] = dict(self.dialogue_ns)
            if any(self.live_combat_stacks.values()):
                row["flamegraph_order"] = "first_call"
                row["live_combat_stacks"] = [{"stack": list(path), "self_wall_ns": own}
                                             for path, own in self.live_combat_stacks.items()]
        self.stop()

    def install(self):
        from ferrial_drive.rendering.atlas_texture_cache import AtlasTextureCache
        from ferrial_drive.rendering.part_atlas_residency import PartAtlasResidency
        from ferrial_drive.rendering.part_painter import PartPainter
        from ferrial_drive.rendering.part_shadow_map import PartShadowMap
        from ferrial_drive.rendering.pico_part_motion import PicoPartMotion

        app, probe = self.app, self.probe
        probe.frame_trace = self
        probe.install_dialogue()
        groups = (
            (app, ("handle_event", "draw", "draw_scene", "draw_targets", "update_guns",
                   "update_back_weapon", "update_loadout_fade", "draw_back_weapon", "draw_missiles",
                   "draw_missile_smoke", "draw_live_combat_motion")),
            (getattr(app, "encounter_view", None), ("draw",)),
            (PicoPartMotion, ("prepare_frame", "draw")),
            (PartAtlasResidency, ("stream", "_prepare_prefetch")),
            (AtlasTextureCache, ("_upload_gl",)),
            (PartPainter, ("paint",)),
            (getattr(app, "gun_renderer", None), ("draw",)),
            (getattr(app, "sword_renderer", None), ("draw_contacts",)),
            (app.hud.view, ("weapons", "resources", "radar")),
            (self.canvas, ("present",)),
            (self.canvas.pico, ("SDL_RenderFlush", "SDL_SetRenderTarget")),
        )
        for target, names in groups:
            for name in names:
                if callable(getattr(target, name, None)):
                    owner = target if isinstance(target, type) else type(target)
                    label = name if target is self.canvas.pico else f"{owner.__name__}.{name}"
                    if label == "SDL_RenderFlush" and getattr(self.canvas.pico, "fdrive_native_gl", None) is not None:
                        label = "NativeGlRenderer.flush"
                    probe.method(target, name, label)
        if callable(getattr(app, "draw_live_combat_motion", None)):
            phases = (
                ("pose_prepare", app, ("live_part_selection", "part_render_angles")),
                ("pose_prepare", PicoPartMotion, ("prepare_frame", "prepare_draw", "anchor_offset")),
                ("shadow_prepare", PicoPartMotion, ("shadow_frame", "prepare_shadow", "prepare_surface")),
                ("shadow_submit", PartShadowMap, ("render_depth", "render_surfaces", "draw_ground_many")),
                ("parts_compose", PicoPartMotion, ("draw",)),
            )
            for phase, target, names in phases:
                for name in names:
                    if callable(getattr(target, name, None)):
                        self._watch_live_combat_phase(target, name, phase)
        for index, gun in enumerate(app.guns, 1):
            for method in ("update", "fire_followup"):
                if callable(getattr(gun, method, None)):
                    self._watch_gun(gun, index, method)
        swap = getattr(app, "swap_actions", None)
        if callable(getattr(swap, "launch", None)):
            self._watch_launch(swap)
        if callable(getattr(app, "perform_hud_action", None)):
            self._watch_loadout_action()
        self._watch_loadout_apply()
        return self

    def _watch_live_combat_phase(self, target, name, phase):
        owner = target if isinstance(target, type) else type(target)
        function = f"{owner.__name__}.{name}"
        scope = f"live_combat.{phase}.{function}"
        probe = self.probe
        probe.scope_functions[scope] = function

        def wrap(original):
            def call(*args, **kwargs):
                if self.recording and probe.stack and self.live_combat_root in probe.stack[-1][3]:
                    with probe.scope(scope):
                        return original(*args, **kwargs)
                return original(*args, **kwargs)
            return call
        probe.replace(target, name, wrap)

    def _watch_gun(self, gun, slot, method):
        scope = f"RangedCombat.{method}"

        def wrap(original):
            def call(*args, **kwargs):
                if not self.recording:
                    return original(*args, **kwargs)
                before = gun.shots_fired
                with self.probe.scope(scope):
                    result = original(*args, **kwargs)
                shots = gun.shots_fired - before
                if shots > 0:
                    self.events.append({"type": "gun_fire", "gun_slot": slot, "count": shots,
                                        "followup": method == "fire_followup"})
                return result
            return call

        self.probe.replace(gun, method, wrap)

    def _watch_launch(self, swap):
        def wrap(original):
            def launch(*args, **kwargs):
                if not self.recording:
                    return original(*args, **kwargs)
                with self.probe.scope("SwapActions.launch"):
                    launched = original(*args, **kwargs)
                if launched:
                    self.events.append({"type": "back_weapon_fire", "count": len(launched)})
                return launched
            return launch

        self.probe.replace(swap, "launch", wrap)

    def _watch_loadout_action(self):
        def wrap(original):
            def action(name, *args, **kwargs):
                if not self.recording or name != "loadout":
                    return original(name, *args, **kwargs)
                before = getattr(self.app, "loadout_fade_seconds", 0)
                with self.probe.scope("MovementApplication.perform_hud_action"):
                    result = original(name, *args, **kwargs)
                if before <= 0 < getattr(self.app, "loadout_fade_seconds", 0):
                    self.events.append({"type": "loadout_transition_start"})
                return result
            return action

        self.probe.replace(self.app, "perform_hud_action", wrap)

    def _watch_loadout_apply(self):
        hud = self.app.hud
        if not callable(getattr(hud, "perform", None)):
            return

        def wrap(original):
            def perform(action, *args, **kwargs):
                if not self.recording or action != "loadout":
                    return original(action, *args, **kwargs)
                before = hud.state.hud.active_loadout_index
                with self.probe.scope("MovementHud.perform(loadout)"):
                    result = original(action, *args, **kwargs)
                after = hud.state.hud.active_loadout_index
                if after != before:
                    self.events.append({"type": "loadout_changed", "from": before + 1, "to": after + 1})
                return result
            return perform

        self.probe.replace(hud, "perform", wrap)
