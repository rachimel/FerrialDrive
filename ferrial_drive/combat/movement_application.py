"""이동·전투 훈련장의 입력·표현 연결. 실행 루프는 호출자가 소유한다."""

from ctypes import byref, memmove
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict, replace
import json
from math import atan2, cos, degrees, floor, isfinite, radians, sin, tau
from pathlib import Path
from time import perf_counter

from ferrial_drive.assets.catalog import AssetCatalog, read_document
from ferrial_drive.assets.directional import SCREEN_DIRECTIONS
from ferrial_drive.assets.pico_assets import PicoAssetBackend
from ferrial_drive.assets.sprites import SpriteClip, SpriteFrame
from ferrial_drive.combat.camera import LookAheadCamera
from ferrial_drive.combat.camera_impact import CameraImpact
from ferrial_drive.combat.aim_follow import AimFollow, AimFollowSettings, interpolate_angles
from ferrial_drive.combat.locomotion import LocomotionController, LocomotionPlayback, LocomotionSettings, unit_vector
from ferrial_drive.combat.movement_combat import MovementCombat
from ferrial_drive.combat.overdrive import OverdriveSettings
from ferrial_drive.combat.energy import EnergySettings
from ferrial_drive.combat.config import CombatConfig
from ferrial_drive.combat.ranged_combat import RangedCombat, explosion_targets
from ferrial_drive.combat.entity_storage import EntityRegistry
from ferrial_drive.combat.projectile_storage import projectile_storage
from ferrial_drive.combat.gun_contact import GunContactEffects
from ferrial_drive.combat.weapon_animation import HELD_GUN_MOTIONS, WeaponAnimation
from ferrial_drive.combat.muzzle_tracks import MuzzleTracks
from ferrial_drive.combat.training_ground import GroundProjection, TrainingGroundView
from ferrial_drive.combat.ground_effects import ground_effect_mode, trail_in_front
from ferrial_drive.combat.sword_effects import BladeTrajectory, SwordEffects, SwordTarget
from ferrial_drive.combat.geometry import Vec2
from ferrial_drive.rendering.pico_sword_effects import PicoSwordEffects
from ferrial_drive.rendering.pico_gun_effects import PicoGunEffects
from ferrial_drive.rendering.rim_light import standby_rim
from ferrial_drive.rendering.overdrive_palette import rainbow_color
from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.rendering.motion_vectors import target_phase
from ferrial_drive.rendering.part_atlas_residency import AtlasFrameBudget
from ferrial_drive.settings import GameSettingsStore
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui.pico_renderer import PicoRenderer
from ferrial_drive.ui_v2.movement_hud import MovementHud


class MovementApplication:
    parts_only = False
    pbr_enabled = False
    retired_player_motions = frozenset()
    hud_type = MovementHud
    debug_controls = True

    def __init__(self, config_path, *, demo=False, capture=None, capture_frame=1, report=None, script=None, profile=None,
                 record_directory=None, record_step=2, settings_file=None, movement_speed_multiplier=1, mute=False, theme_file=None,
                 preview_frame=None, preview_control=None, preview_hidden=False, overdrive_rainbow=False,
                 part_catalog=None, part_mixed=False, part_step_directions=False, part_color_codec=None,
                 player_pipeline=None):
        self.config_path = Path(config_path).resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        self.part_stream_budget = AtlasFrameBudget()
        self.overdrive_settings = OverdriveSettings(**self.config.get("overdrive", {}))
        self.energy_settings = EnergySettings(**self.config.get("energy", {}))
        self.standby_trail_tint_ratio = self.config.get("sword_effects", {}).get("standby_tint_ratio", .65)
        if not isfinite(self.standby_trail_tint_ratio) or not 0 <= self.standby_trail_tint_ratio <= 1:
            raise ValueError("Standby Trail의 붉은색 혼합 비율은 0~1이어야 한다.")
        self.overdrive_rainbow = overdrive_rainbow
        self.rainbow_cycle_seconds = self.config.get("overdrive_rainbow", {}).get("cycle_seconds", 3)
        rainbow_color(0, self.rainbow_cycle_seconds)
        self.overdrive_color = None
        self.sword_damage_by_energy_level = tuple(self.config.get("combat", {}).get("damage_by_energy_level", (60, 80, 100)))
        if (len(self.sword_damage_by_energy_level) != 3
                or any(type(amount) is not int or amount <= 0 for amount in self.sword_damage_by_energy_level)):
            raise ValueError("검 피해량은 에너지 1~3단계별 양수 정수여야 한다.")
        if not isfinite(movement_speed_multiplier) or movement_speed_multiplier <= 0:
            raise ValueError("이동 속도 배율은 양수 유한값이어야 한다.")
        self.movement_speed_multiplier = movement_speed_multiplier
        movement = asdict(LocomotionSettings(**self.config["movement"]))
        self.config["movement"] = {name: value * movement_speed_multiplier if name.endswith("_speed_mps") else value
                                   for name, value in movement.items()}
        self.style = self.config["presentation"]
        self.weapons_enabled = self.config.get("weapons", {}).get("enabled", False)
        weapon_settings = self.config.get("weapons", {})
        self.gun_damage_by_energy_level = tuple(weapon_settings.get("damage_by_energy_level", (15, 20, 25)))
        self.gun_overdrive_damage = weapon_settings.get("overdrive_damage", 25)
        if (len(self.gun_damage_by_energy_level) != 3 or any(type(v) is not int or v <= 0
                for v in (*self.gun_damage_by_energy_level, self.gun_overdrive_damage))):
            raise ValueError("기관단총 피해량은 레벨별 3개와 Overdrive의 양수 정수다.")
        effects = weapon_settings.get("effects", {})
        explosion = weapon_settings.get("overdrive_explosion", {})
        self.gun_explosion_radius_m = explosion.get("radius_m", 3)
        self.gun_explosion_damage = explosion.get("damage", 13)
        if (not isfinite(self.gun_explosion_radius_m) or self.gun_explosion_radius_m <= 0
                or type(self.gun_explosion_damage) is not int or self.gun_explosion_damage <= 0):
            raise ValueError("Overdrive 폭발은 양수 미터 반경·정수 피해가 필요하다.")
        self.gun_recoil = CameraImpact(**effects.get("fire_recoil", {
            "amplitude_pixels": 2, "duration_seconds": .09, "frequency_hz": 18, "damping": 2}))
        self.gun_hit_camera_pixels = effects.get("hit_camera_pixels", 6)
        self.gun_overdrive_hit_camera_pixels = effects.get("overdrive_hit_camera_pixels", 8)
        if not all(isfinite(v) and v >= 0 for v in (self.gun_hit_camera_pixels, self.gun_overdrive_hit_camera_pixels)):
            raise ValueError("기관단총 카메라 피드백은 0 이상의 유한한 픽셀 값이다.")
        self.gun_contact = GunContactEffects(weapon_settings.get("contact_effects"))
        gun_settings = CombatConfig(**self.config.get("weapons", {}).get("gun", {}))
        self.weapon_animation = WeaponAnimation(swap_speed=self.config.get("weapons", {}).get("swap_speed", 1),
                                               aim_speed=self.config.get("weapons", {}).get("aim_speed", 1))
        self.weapon_durations = {}
        self.muzzle_tracks = None
        self.single_shot_requested = False
        self.settings_store = GameSettingsStore(settings_file)
        self.game_settings = self.settings_store.load()
        self.theme_file = theme_file
        self.preview_frame_path = Path(preview_frame) if preview_frame else None
        self.preview_control_path = Path(preview_control) if preview_control else None
        self.preview_hidden = preview_hidden
        self.preview_control_signature = None
        self.next_preview_frame = 0
        self.window_size = (self.config["window"]["width"], self.config["window"]["height"])
        self.entities = EntityRegistry()
        self.projectile_storage = projectile_storage(self.entities)
        self.controller = LocomotionController(LocomotionSettings(**self.config["movement"]), registry=self.entities)
        split = self.config.get("upper_lower", {})
        self.aim_follow = (AimFollow(AimFollowSettings(**split["follow"]), yaw_degrees=45)
                           if split.get("enabled", False) else None)
        self.pose_catalog = self.pose_tracks = self.pose_sprite = None
        self.player_pipeline = player_pipeline or ("baked" if part_catalog or part_color_codec else split.get("player_pipeline", "mixed"))
        if self.player_pipeline not in ("baked", "mixed", "pbr"):
            raise ValueError("플레이어 렌더 경로는 baked·mixed·pbr 중 하나여야 한다.")
        self.pbr_enabled = self.player_pipeline == "pbr" and not demo
        self.retired_player_motions = frozenset(split.get("retired_motions", ())) if self.pbr_enabled else frozenset()
        configured_parts = self.relative_path(split["part_catalog"]) if split.get("part_catalog") else None
        self.part_catalog_path = (Path(part_catalog).resolve() if part_catalog else
                                  configured_parts if configured_parts and configured_parts.is_file() else None)
        profile_key = "part_ktx_catalog_profiles" if part_color_codec == "ktx" else "part_catalog_profiles"
        if self.pbr_enabled:
            profile_key = "pbr_catalog_profiles"
        self.part_catalog_profiles = split.get(profile_key, {})
        surface_key = "surface_ktx_catalog_profiles" if part_color_codec == "ktx" else "surface_catalog_profiles"
        self.surface_catalog_profiles = split.get(surface_key, {}) if self.player_pipeline == "mixed" else {}
        if part_color_codec == "ktx" and not self.part_catalog_profiles:
            raise ValueError("KTX2 파츠 품질 프로필 설정이 필요하다.")
        self.part_profile_override = Path(part_catalog).resolve() if part_catalog else None
        self.parts_only = False
        self.part_mixed, self.part_sprite = part_mixed, None
        self.part_step_directions = part_step_directions
        self.part_angle_remainder_seconds, self.part_angles, self.previous_part_angles = 0, None, None
        self.projection = GroundProjection(self.style["pixels_per_meter"], self.style["projection_y_scale"])
        self.guns = [RangedCombat(gun_settings, seed=index, range_m=weapon_settings.get("range_m", 75),
                                 projection=self.projection, penetration_count=weapon_settings.get("penetration_count", 1),
                                 projectiles=self.projectile_storage, owner_eid=self.controller.eid)
                     for index in range(2)]
        self.camera = LookAheadCamera(*self.window_size, max_offset_units=100,
                                      response_seconds=0.15 / movement_speed_multiplier,
                                      zoom_transition_seconds=self.config.get("camera_zoom", {}).get("transition_seconds", 0.2))
        self.camera.reset(self.projection.project(self.controller.position_m))
        self.camera_impact = CameraImpact(**self.config.get("camera_impact", {}))
        self.timings = TimingRecorder(enabled=profile is not None)
        self.profile_path = Path(profile) if profile else None
        self.demo, self.running, self.paused, self.grid = demo, True, False, True
        self.show_shadow = True
        self.interpolation_enabled = self.config.get("interpolation", {}).get("enabled", False)
        self.keys = set()
        self.attack_held = False
        self.mouse = (self.window_size[0] * 0.7, self.window_size[1] * 0.65)
        self.capture_path = Path(capture) if capture else None
        self.capture_frame = capture_frame
        self.report_path = Path(report) if report else None
        self.script = json.loads(Path(script).read_text(encoding="utf-8-sig")) if script else []
        self.frame = 0
        self.trace = []
        self.frame_times = []
        self.renderer = self.ground = self.playback = None
        self.sprites = []
        self.clip_resources = {}
        self.combat = self.hud = self.motion_sprite = self.attack_sprite = self.shadow_blend = None
        self.attack_resources = {}
        self.pending_capture = None
        self.ground_effects = self.ground_effect_renderer = None
        self.sword_effects = self.sword_renderer = None
        self.gun_renderer = None
        self.energy_level = self.config.get("sword_effects", {}).get("energy_level", 1)
        self.rim_elapsed_seconds = 0
        self.sword_targets = []
        self.target_hits, self.target_flash = {}, {}
        self.effect_mode = None
        self.loading = None
        self.loading_trace = []
        self.sound_player = self.sound_cues = None
        self.mute = mute
        self.record_directory = Path(record_directory) if record_directory else None
        if type(record_step) is not int or record_step < 1:
            raise ValueError("기록 간격은 양수 프레임 수여야 한다.")
        self.record_step = record_step

    def relative_path(self, value):
        return (self.config_path.parent / value).resolve()

    def load_sprites(self, source, *, layers=None, progress=None):
        clips, resources = {}, {}
        definitions = list(AssetCatalog.load(source).definitions.values())
        for index, definition in enumerate(definitions):
            document = read_document(definition)
            if not document.mech or (not self.pbr_enabled and "shadow" not in document.mech.sheets):
                raise ValueError("검 이동 에셋에 그림자 시트가 없다. 그림자 포함 카탈로그를 지정한다.")
            alpha_shadow = not self.pbr_enabled and self.parts_only
            shadow_scale = self.game_settings.shadow_scale
            sprite = PicoAssetBackend(filtering="linear" if self.pbr_enabled else "bicubic", layers=layers,
                                       alpha_layers=("shadow",) if alpha_shadow else (),
                                       alpha_scale=shadow_scale if alpha_shadow else None).load(document)
            self.sprites.append(sprite)
            selected = {name: clip for name, clip in sprite.clips.items()
                        if name.split("/")[0] not in self.retired_player_motions}
            if clips.keys() & selected.keys():
                raise ValueError("분리 시트의 클립 이름이 중복됐다.")
            clips.update(selected)
            resources.update({name: sprite for name in selected})
            if progress is not None:
                progress((index + 1) / len(definitions))
        return clips, resources

    def path(self, name):
        return (self.config_path.parent / self.style[name]).resolve()

    def enter(self):
        from ferrial_drive.ui.loading import LoadingScreen, LoadingCancelled
        from ferrial_drive.rendering.canvas import apply_output_resolution
        import pico2d.pico2d as pico
        self.pico = pico
        apply_output_resolution(self.game_settings.screen_resolution, self.window_size)
        self.load_started_seconds = perf_counter()
        settings = self.config.get("loading")
        if settings:
            logo = self.relative_path(settings["logo"])
            self.loading = LoadingScreen(pico, self.window_size, self.path("font"), settings,
                                         logo if logo.is_file() else None)
        try:
            self.loading_progress(0, "준비 중")
            self._enter_resources()
            self.loading_progress(1, "준비 완료")
        except LoadingCancelled:
            self.running = False
        finally:
            if self.loading is not None:
                self.loading.close()
                self.loading = None

    def loading_progress(self, progress, label):
        if self.loading is None:
            return
        capture = (lambda: self.capture(self.report_path.parent / "loading" / f"{int(progress * 100):03d}.png")) if self.report_path and progress in (0, 1) else None
        self.loading.show(progress, label, before_present=capture)
        self.loading_trace.append({"progress": progress, "stage": label,
                                   "elapsed_seconds": perf_counter() - self.load_started_seconds})

    def _enter_resources(self):
        import pico2d.pico2d as pico
        self.pico = pico
        font = self.path("font")
        if not font.is_file():
            raise FileNotFoundError(f"훈련장 글꼴이 없다: {font}")
        hud = self.config.get("hud")
        self.loading_progress(0.03, "화면 준비")
        if hud:
            self.hud = self.hud_type(self.relative_path(hud["config"]), self.relative_path(hud["preset"]),
                                   camera_motion_blur=hud.get("camera_motion_blur"), settings_store=self.settings_store,
                                   theme_file=self.theme_file, overdrive_settings=self.overdrive_settings,
                                   energy_settings=self.energy_settings, targeting=self.config.get("targeting"),
                                   player=self.controller)
            levels = self.config.get("sword_effects", {}).get("levels")
            if levels:
                self.hud.config.data["v2"]["style"]["energy_level_colors"] = [level["color"] for level in levels]
            if not self.demo and hud.get("icon_manifest"):
                self.hud.load_icon_manifest(self.relative_path(hud["icon_manifest"]))
            self.hud.enter()
            self.hud.graphics_settings.prepare_apply = self.prepare_settings
            self.renderer = self.hud.renderer
        else:
            self.renderer = PicoRenderer({"body": font, "small": font}, {"body": 20, "small": 15})
        if self.weapons_enabled:
            self.loading_progress(0.10, "총탄·총구 화염 준비")
            with self.timings.scope('loading.projectile_contacts.prepare'):
                self.guns[0].warm_collision()
            with self.timings.scope('loading.gun_effects.prepare'):
                self.gun_renderer = PicoGunEffects(self.renderer, self.config.get("weapons", {}).get("effects", {}))
        if self.demo:
            frames = tuple(SpriteFrame((0, 0, 1, 1), (0, 0)) for _ in range(8))
            clips = {f"{state}_loop/{direction}": SpriteClip(12, frames)
                     for state in ("idle", "dash", "boost")
                     for direction in ("s", "sw", "w", "nw", "n", "ne", "e", "se")}
            attack_clips = {f"combo_{index:02}/{direction}": SpriteClip(12, frames[:count])
                            for index, count in enumerate((6, 6, 6, 8), 1)
                            for direction in ("s", "sw", "w", "nw", "n", "ne", "e", "se")}
            if self.weapons_enabled:
                for motion, count in self.config["weapons"]["motion_frames"].items():
                    for direction in ("s", "sw", "w", "nw", "n", "ne", "e", "se"):
                        clips[f"{motion}/{direction}"] = SpriteClip(12, tuple(frames[0] for _ in range(count)))
            self.combat = MovementCombat(self.controller, attack_clips,
                                          speed=self.config.get("combat", {}).get("playback_speed", 1.25),
                                          acceleration=self.config.get("combat", {}).get("acceleration", "smoothstep"))
        else:
            source = self.path("asset")
            if not source.is_file():
                raise FileNotFoundError(f"검 이동 8방향 에셋이 없다: {source}. 기본 도형은 --demo로 실행한다.")
            from ferrial_drive.rendering.canvas import renderer_name
            opengl = renderer_name(pico) == "opengl"
            if self.pbr_enabled and (not opengl or not self.part_catalog_profiles):
                raise RuntimeError("PBR 플레이어 실행에는 OpenGL과 품질별 전체 PBR 카탈로그가 필요하다.")
            self.parts_only = bool(self.part_catalog_profiles and opengl)
            layers = () if self.pbr_enabled else ("shadow",) if self.parts_only else None
            clips, self.clip_resources = self.load_sprites(source, layers=layers,
                progress=lambda value: self.loading_progress(0.12 + 0.24 * value, "기체 준비"))
            settings = self.config.get("combat")
            if settings:
                attack_clips, self.attack_resources = self.load_sprites(self.relative_path(settings["asset"]), layers=layers,
                    progress=lambda value: self.loading_progress(0.36 + 0.09 * value, "전투 준비"))
                self.combat = MovementCombat(self.controller, attack_clips, speed=settings["playback_speed"],
                                              acceleration=settings.get("acceleration", "smoothstep"))
            if renderer_name(pico) == "opengl":
                from ferrial_drive.rendering.pico_motion_sprite import PicoMotionSprite
                from ferrial_drive.rendering.pico_shadow_blend import PicoShadowBlend
                interpolation = self.config.get("interpolation", {})
                if self.parts_only:
                    if not self.pbr_enabled:
                        self.shadow_blend = PicoShadowBlend(pico, softness_pixels=self.style.get("shadow_softness_pixels", 5),
                                                           contact_radius_pixels=self.style.get("shadow_contact_radius_pixels", 56))
                elif interpolation.get("enabled"):
                    options = {key: interpolation[key] for key in ("easing", "shutter_seconds", "blur_direction", "blur_strength", "cache_capacity") if key in interpolation}
                    self.motion_sprite = PicoMotionSprite(pico, self.relative_path(interpolation["source"]), **options)
                    self.shadow_blend = PicoShadowBlend(pico, softness_pixels=self.style.get("shadow_softness_pixels", 5),
                                                       contact_radius_pixels=self.style.get("shadow_contact_radius_pixels", 56))
                    if settings:
                        self.attack_sprite = PicoMotionSprite(pico, self.relative_path(settings["interpolation"]), **options)
                effects = self.config.get("ground_effects")
                self.loading_progress(0.87, "효과 준비")
                if effects and effects.get("enabled", True):
                    from ferrial_drive.combat.ground_effects import GroundEffects
                    from ferrial_drive.rendering.pico_ground_effects import PicoGroundEffects
                    self.ground_effects = GroundEffects(self.relative_path(effects["anchors"]),
                        appearance=effects["appearance"], capacity=effects.get("capacity", 128),
                        emission_seconds=effects.get("emission_seconds", 0.04), near_front_pixels=effects["near_emitter_front_pixels"])
                    self.ground_effect_renderer = PicoGroundEffects(pico, self.relative_path(effects["atlas"]))
        sword_settings = self.config.get("sword_effects")
        if sword_settings and sword_settings.get("enabled", True):
            trajectory = BladeTrajectory.load(self.relative_path(sword_settings["demo_trajectory"] if self.demo
                                                                else sword_settings["trajectory"]))
            self.sword_effects = SwordEffects(trajectory, sword_settings, scale=self.style["sprite_scale"],
                project=self.projection.project, easing=self.config["combat"].get("easing", "accelerate"),
                y_pixels_per_meter=self.projection.pixels_per_meter * self.projection.y_scale,
                hitbox_type=sword_settings.get("hitbox_type","capsule"))
            flow_field = 'demo_flow_texture_directory' if self.demo else 'flow_texture_directory'
            flow_directory = (self.relative_path(sword_settings[flow_field]) if flow_field in sword_settings else None)
            self.sword_renderer = PicoSwordEffects(self.renderer, trail_backend=sword_settings.get("trail_renderer", "compute"),
                                                  flow_directory=flow_directory)
            self.loading_progress(0.90,"Trail 준비")
            with self.timings.scope('loading.sword_trail.prepare'):
                self.sword_renderer.prepare(sword_settings)
            self.sword_targets = [SwordTarget(row["id"],
                Vec2(*self.projection.project(row["position_m"])) + Vec2(0, -row["height_pixels"]),
                row["radius_pixels"], row.get("material", "generic"), tuple(row["position_m"]))
                for row in sword_settings.get("targets", [])]
            self.target_hits = {target.target_id: 0 for target in self.sword_targets}
        self.bind_hud_world()
        self.playback = LocomotionPlayback(clips, transition_seconds=self.style["transition_seconds"])
        self.weapon_durations = {name.rsplit("/", 1)[0]: clip.duration_ms / 1000 for name, clip in clips.items()}
        if self.weapons_enabled and not self.demo:
            self.muzzle_tracks = MuzzleTracks.load(self.relative_path(self.config["weapons"]["muzzle_tracks"]))
        if not self.demo and (self.aim_follow or self.parts_only):
            from ferrial_drive.combat.upper_lower import UpperLowerCatalog, PoseAttachments, PoseBladeTrajectory
            from ferrial_drive.rendering.pico_pose_table import PicoPoseTable
            self.pose_catalog = UpperLowerCatalog.load(self.relative_path(self.config["upper_lower"]["catalog"]))
            self.pose_tracks = PoseAttachments(self.pose_catalog, smooth=self.parts_only)
            self.pose_tracks.easing = self.config.get("combat", {}).get("easing", "linear")
            if self.sword_effects:
                self.sword_effects.trajectory = PoseBladeTrajectory(self.pose_tracks, self.sword_effects.trajectory)
            with ExitStack() as pending:
                surface = None
                if self.parts_only:
                    surface = self.load_surface_profile(self.game_settings)
                    if surface is not None:
                        pending.callback(surface.close)
                    self.part_sprite = self.load_part_profile(self.game_settings, surface=surface)
                elif self.part_catalog_path and opengl:
                    from ferrial_drive.rendering.pico_part_motion import PicoPartMotion
                    self.part_sprite = PicoPartMotion(pico, self.part_catalog_path, timings=self.timings,
                                                      mixed_directions=self.part_mixed, direction_warp=not self.part_step_directions,
                                                      upscale_aa=self.game_settings.upscale_aa)
                if opengl:
                    self.pose_sprite = PicoPoseTable(pico, self.pose_catalog, self.game_settings.texture_quality,
                        parts=self.part_sprite, surface_parts=surface, parts_only=self.parts_only,
                        progress=lambda value: self.loading_progress(.905+.02*value, "상·하체 준비"), timings=self.timings)
                    pending.pop_all()
        self.loading_progress(0.93, "훈련장 준비")
        self.ground = TrainingGroundView(self.renderer, self.projection, self.style,
                                        None if self.demo else self.path("ground"),
                                        sample_colors=self.ground_effects is not None or bool(self.sword_effects))
        audio = self.config.get("audio", {})
        if audio.get("enabled", False) and not self.mute:
            from ferrial_drive.audio.effects import PicoSoundEffects
            from ferrial_drive.combat.movement_audio import MovementSoundCues
            self.loading_progress(0.98, "효과음 준비")
            self.sound_player = PicoSoundEffects(pico, self.relative_path(audio["bank"]),
                self.relative_path(audio["demo_directory" if self.demo else "directory"]),
                volume=audio.get("volume", 0.4), channels=audio.get("channels", 24),
                user_bank=self.relative_path(audio["user_bank"]) if audio.get("user_bank") else None)
            windows = self.config.get("sword_effects", {}).get("active_phase_windows", [[0, 1]] * 4)
            self.sound_cues = MovementSoundCues(self.sound_player, windows,
                easing=self.config.get("combat", {}).get("easing", "accelerate"),
                motion=json.loads(self.relative_path(audio["bank"]).read_text(encoding="utf-8"))["motion"])
        self.update = self.timings.wrap(self.update, name="movement.update")
        self.draw = self.timings.wrap(self.draw, name="movement.draw")

    def required_part_motions(self):
        return {name.split("/")[0] for name in (*self.clip_resources, *self.attack_resources)}

    def load_surface_profile(self, settings):
        profiles = self.surface_catalog_profiles
        if self.part_profile_override or self.pico is None or settings.texture_quality not in profiles:
            return None
        source = self.relative_path(profiles[settings.texture_quality])
        if not source.is_file():
            return None
        import ctypes as ct
        from ferrial_drive.diagnostics.gpu_profile import bind_gl
        from ferrial_drive.rendering.pico_part_motion import PicoPartMotion

        units = ct.c_int()
        bind_gl(self.pico, "glGetIntegerv", None, [ct.c_uint, ct.c_void_p])(0x8872, ct.byref(units))
        if units.value < 17:
            return None
        sprite = PicoPartMotion(self.pico, source, timings=self.timings, mixed_directions=True,
                                max_directions=16, cache_budget_bytes=64 * 1024**2,
                                direction_warp=not self.part_step_directions, upscale_aa=settings.upscale_aa)
        if sprite.shadow_map is None or sprite.data["quality"] != settings.texture_quality:
            sprite.close()
            raise ValueError("선택 품질에 맞는 실시간 조명 카탈로그가 필요하다.")
        return sprite

    def load_part_profile(self, settings, *, surface=None):
        from ferrial_drive.assets.alpha_data import alpha_dimensions
        from ferrial_drive.rendering.pico_part_motion import PicoPartMotion

        if settings.texture_quality == "high" and self.part_profile_override:
            source = self.part_profile_override
        else:
            profile = self.part_catalog_profiles[settings.texture_quality]
            candidates = (profile,) if isinstance(profile, str) else profile
            paths = [self.relative_path(candidate) for candidate in candidates]
            source = next((path for path in paths if path.is_file()), paths[-1])
        shadow_bytes = 0
        for resource in self.sprites:
            if "shadow" not in resource.alpha_layers:
                continue
            width, height = alpha_dimensions(resource.sizes["shadow"], settings.shadow_scale)
            shadow_bytes += width * height
        surface_bytes = surface.cache_budget_bytes + surface.shadow_map.storage_bytes if surface else 0
        part_budget_bytes = max(0, 256 * 1024**2 - shadow_bytes - surface_bytes)
        split = self.config["upper_lower"]
        lighting = self.relative_path(split["pbr_lighting"]) if self.pbr_enabled else None
        part_spaces = None
        if self.pbr_enabled:
            part_spaces = {name: {"gun": "upper"} for name in HELD_GUN_MOTIONS}
        sprite = PicoPartMotion(self.pico, source, timings=self.timings, mixed_directions=True, max_directions=32,
                                cache_budget_bytes=part_budget_bytes, direction_warp=not self.part_step_directions,
                                pbr_lighting=lighting, part_spaces=part_spaces, upscale_aa=settings.upscale_aa)
        try:
            required = self.required_part_motions()
            if missing := required - sprite.data["motions"].keys():
                raise ValueError("파츠 아틀라스 누락: " + ", ".join(sorted(missing)))
            if self.pbr_enabled:
                if (not sprite.pbr_lighting or sprite.data.get("sample_fps") != 24
                        or any(set(sprite.data["motions"][name]) != set("01234567") for name in required)
                        or not required <= sprite.shadow_map.tracks.keys()
                        or (not self.part_step_directions and not required <= sprite.correspondence.keys())):
                    raise ValueError("모든 플레이어 모션에 24fps·8방향 PBR 데이터와 그림자 포즈가 필요하다.")
                sprite.cache_budget_bytes = max(0, part_budget_bytes - sprite.shadow_map.storage_bytes)
                sprite.enable_streaming(self.part_stream_budget, "idle_loop", "gun_ready")
            if sprite.direction_sample_fps is not None:
                sprite.direction_sample_fps = split.get("direction_sample_fps", sprite.direction_sample_fps)
        except BaseException:
            sprite.close()
            raise
        return sprite

    @contextmanager
    def prepare_settings(self, settings):
        """기체·그림자를 준비하고 저장 성공 때 함께 교체한다. 게임 진행 상태는 보존한다."""
        installed = False
        candidate_pose, previous_pose = None, None
        candidate_parts, previous_parts = None, None
        candidate_surface = None
        with ExitStack() as pending_changes:
            changes = []
            try:
                if settings.shadow_scale != self.game_settings.shadow_scale and self.parts_only:
                    for resource in self.sprites:
                        if resource.alpha_layers:
                            changes.append(pending_changes.enter_context(resource.prepare_alpha_scale(settings.shadow_scale)))
                if settings.texture_quality != self.game_settings.texture_quality and self.pose_sprite:
                    from ferrial_drive.rendering.pico_pose_table import PicoPoseTable
                    if self.parts_only:
                        candidate_surface = self.load_surface_profile(settings)
                        candidate_parts = self.load_part_profile(settings, surface=candidate_surface)
                        candidate_parts.direction_enabled = self.part_sprite.direction_enabled
                    candidate_pose = PicoPoseTable(self.pico,self.pose_catalog,settings.texture_quality,
                        progress=lambda value:self.draw_settings_progress(),timings=self.timings,
                        parts=candidate_parts or self.part_sprite, surface_parts=candidate_surface, parts_only=self.parts_only)
                    candidate_surface = None
                if settings.upscale_aa != self.game_settings.upscale_aa:
                    current_surface = self.pose_sprite.surface_parts if self.pose_sprite and candidate_pose is None else None
                    current_parts = self.part_sprite if candidate_parts is None else None
                    for sprite in (current_parts, current_surface):
                        if sprite and sprite.upscaler and sprite.data.get("upscale_filter") == "bounded_bicubic":
                            change = pending_changes.enter_context(sprite.upscaler.prepare_aa(settings.upscale_aa))
                            if change is not None:
                                changes.append(change)

                def apply():
                    nonlocal installed, previous_pose, previous_parts
                    for change in changes:
                        change()
                    if candidate_pose is not None:
                        previous_pose,self.pose_sprite = self.pose_sprite,candidate_pose
                    if candidate_parts is not None:
                        previous_parts,self.part_sprite = self.part_sprite,candidate_parts
                    self.game_settings = settings
                    installed = True

                yield apply
            finally:
                if installed:
                    if previous_pose is not None:
                        previous_pose.close()
                    if previous_parts is not None:
                        previous_parts.close()
                if not installed and candidate_pose is not None:
                    candidate_pose.close()
                if not installed and candidate_parts is not None:
                    candidate_parts.close()
                if candidate_surface is not None:
                    candidate_surface.close()

    def draw_settings_progress(self):
        self.draw()
        self.pico.SDL_RenderPresent(self.pico.renderer)

    def reset(self):
        self.weapon_animation.reset()
        self.gun_contact.reset()
        self.gun_recoil.reset()
        for gun in self.guns:
            gun.reset()
        self.single_shot_requested = False
        if self.sound_cues:
            self.sound_cues.reset()
        self.rim_elapsed_seconds = 0
        self.controller.reset()
        if self.aim_follow:
            self.aim_follow.reset(45)
        self.part_angle_remainder_seconds, self.part_angles, self.previous_part_angles = 0, None, None
        self.playback.reset()
        if self.combat:
            self.combat.combo.reset()
        self.camera.reset(self.projection.project(self.controller.position_m))
        self.camera_impact.reset()
        self.keys.clear()
        self.release_attack()
        if self.ground_effects:
            self.ground_effects.reset()

        if self.sword_effects:
            self.sword_effects.reset()
        self.target_hits = dict.fromkeys(self.target_hits, 0)
        self.target_flash.clear()
        if self.hud:
            self.hud.reset_training()
            self.bind_hud_world()
            self.set_energy_level(self.config.get("sword_effects", {}).get("energy_level", 1))
        self.sync_overdrive_palette()

    def set_energy_level(self, level):
        if type(level) is not int or not 1 <= level <= 3:
            raise ValueError("에너지 레벨은 1~3 정수여야 한다.")
        self.energy_level = level
        if self.hud:
            from ferrial_drive.ui.energy import EnergyCharge
            self.hud.set_energy_charge(EnergyCharge(level - 1))

    def movement(self):
        horizontal = int("d" in self.keys) - int("a" in self.keys)
        vertical = int("s" in self.keys) - int("w" in self.keys)
        return unit_vector((horizontal, vertical))

    def locked_target_position(self):
        if self.hud and self.hud.targets_enabled:
            target = self.hud.enemies.get(self.hud.selected_target_id)
            if target and target["health"].current > 0:
                return Vec2(*target["position"])
        return None

    def ranged_aim_position(self):
        locked = self.locked_target_position()
        return locked if locked is not None else Vec2(*self.camera.screen_to_world(self.mouse, include_feedback=False))

    def aim(self):
        ranged = self.weapons_enabled and self.weapon_animation.kind == "ranged"
        target = self.ranged_aim_position() if ranged else Vec2(*self.camera.screen_to_world(self.mouse, include_feedback=False))
        root = Vec2(*self.projection.project(self.controller.position_m))
        if ranged:
            if self.demo:
                root += Vec2(0, -48)
            elif self.muzzle_tracks is not None:
                selection = self.current_weapon_motion()
                if self.pose_tracks and selection.name in self.pose_catalog.motions:
                    offset = self.pose_tracks.aim_plane_offset(selection.name, selection.elapsed_seconds)
                else:
                    offset = self.muzzle_tracks.aim_plane_offset(selection.name, selection.elapsed_seconds, loop=selection.loop)
                root += offset * self.style["sprite_scale"]
        delta = target - root
        return self.projection.unproject((delta.x, delta.y))

    def find_sword_target(self, target_id):
        return next((target for target in self.sword_targets if target.target_id == target_id), None)

    def trigger_camera_hit(self, strike_id, target_id):
        """표적 가까이의 실제 검끝 이동 방향을 화면 충격으로 전달한다."""
        target = self.find_sword_target(target_id)
        if target is None:
            return
        if self.hud and self.hud.enemies[target_id]["health"].current <= 0:
            return
        sections = [section for section in getattr(self.sword_effects, "sections", ())
                    if section.strike_id == strike_id]
        direction = self.projection.project(self.controller.facing)
        if sections:
            section = min(sections, key=lambda item: ((item.tip_a + item.tip_b) * 0.5 - target.center).length)
            movement = section.tip_b - section.tip_a
            if movement.length > 1e-6:
                direction = (movement.x, movement.y)
        self.camera_impact.trigger(strike_id, direction, overdrive=bool(self.hud and self.hud.state.overdrive))
        self.camera.feedback_offset_pixels = self.camera_impact.offset_pixels

    def on_sword_hit(self, strike_id, target_id):
        """검 명중 사건을 표현·교전에 전달한다. 피해 적용은 기존 흐름에서 수행한다."""
        self.trigger_camera_hit(strike_id, target_id)

    def on_gun_hit(self, target_id, impact):
        """실제 총탄 명중을 교전에 전달한다. 정지 표적에는 추가 이동 반응이 없다."""

    def release_attack(self, *, discard_requested=True):
        self.attack_held = False
        if discard_requested:
            self.single_shot_requested = False
        if self.combat:
            self.combat.stop_auto_swing()

    @property
    def gun(self):
        index = self.hud.state.hud.active_loadout_index if self.hud else 0
        return self.guns[index]

    def request_primary_attack(self):
        if self.encounter_finished():
            return False
        if self.weapons_enabled:
            if self.weapon_animation.switching:
                return False
            if self.weapon_animation.kind == "ranged":
                self.single_shot_requested = True
                return True
        if not self.combat:
            return False
        started = not self.combat.active
        accepted = self.combat.request_attack(self.aim())
        if accepted and started:
            self.playback.reset()
        return accepted

    def current_weapon_motion(self, *, predict_fire=False):
        if not self.weapons_enabled:
            return None
        state = "boost" if self.controller.boost_preparing else self.controller.state
        selection = self.weapon_animation.select(state,
            shot_age_seconds=0 if predict_fire else self.gun.shot_age_seconds,
            shot_interval_seconds=self.gun.interval_seconds, durations=self.weapon_durations)
        return replace(selection, direction=self.controller.direction) if selection else None

    def update_guns(self, seconds, previous_root):
        overdrive = bool(self.hud and self.hud.state.overdrive)
        fire_rate = self.overdrive_settings.cooldown_speed if overdrive else 1
        damage = self.gun_overdrive_damage if overdrive else self.gun_damage_by_energy_level[self.energy_level - 1]
        self.gun_contact.update(seconds)
        firing = (self.attack_held or self.single_shot_requested) and self.weapon_animation.kind == "ranged" and not self.weapon_animation.switching
        selection = self.current_weapon_motion(predict_fire=firing and (self.gun.ammo > 0 or overdrive))
        root = Vec2(*self.projection.project(self.controller.position_m))
        previous = Vec2(*previous_root)
        def muzzle_at(offset):
            position = previous + (root - previous) * (offset / seconds if seconds else 1)
            time = max(0, selection.elapsed_seconds - (seconds-offset) * selection.playback_speed)
            return self.muzzle_position(selection, position, time)
        targets = [t for t in self.sword_targets if not self.hud or self.hud.enemies[t.target_id]["health"].current > 0]
        for gun in self.guns:
            previous_shots = gun.shots_fired
            gun.update(seconds, muzzle_at, self.ranged_aim_position(), targets,
                       firing=firing and gun is self.gun, aiming=bool(self.hud and self.hud.aiming), rate=fire_rate,
                       damage=damage, consume_ammo=not overdrive,
                       explosion_radius_m=self.gun_explosion_radius_m if overdrive else 0,
                       explosion_damage=self.gun_explosion_damage if overdrive else 0,
                       max_shots=1 if self.single_shot_requested and not self.attack_held else None)
            if gun.shots_fired != previous_shots:
                self.gun_recoil.trigger((self.guns.index(gun), gun.shots_fired),
                                       (-gun.shot_direction.x, -gun.shot_direction.y))
            if self.sound_player:
                for event in gun.trigger_events:
                    self.sound_player.play("gun_fire" if event == "shot" else "gun_empty")
            for shot_id, target_id, impact in gun.impact_events:
                # 관통마다 독립 명중점을 보존하며 이미 생성된 폭발은 직격 적 사망 뒤에도 처리한다.
                if self.hud and self.hud.enemies[target_id]["health"].current <= 0 and not impact.explosion_damage:
                    continue
                self.target_hits[target_id] += 1
                self.target_flash[target_id] = 0.18
                target = self.find_sword_target(target_id)
                self.gun_contact.emit(impact.position, impact.direction, target.material, seed=shot_id)
                if self.sound_player and not impact.explosion_damage:
                    self.sound_player.play("gun_hit")
                    if target.material in ("metal", "steel"):
                        self.sound_player.play("gun_hit_metal")
                self.on_gun_hit(target_id, impact)
                self.camera_impact.trigger(("gun", self.guns.index(gun), shot_id),
                    (impact.direction.x, impact.direction.y), amplitude_pixels=(self.gun_overdrive_hit_camera_pixels
                    if overdrive else self.gun_hit_camera_pixels))
                if self.hud:
                    self.hud.damage_target(target_id, impact.damage)
                if impact.explosion_damage:
                    self.gun_contact.emit_explosion(impact.position,
                        self.projection.project((impact.explosion_radius_m, impact.explosion_radius_m)), seed=shot_id)
                    if self.sound_player:
                        self.sound_player.play("gun_explosion")
                    for nearby in explosion_targets(impact, target, targets, self.projection):
                        if self.hud and self.hud.enemies[nearby.target_id]["health"].current > 0:
                            self.target_flash[nearby.target_id] = .18
                            self.target_hits[nearby.target_id] += 1
                            self.hud.damage_target(nearby.target_id, impact.explosion_damage)
        self.single_shot_requested = False
        if self.hud:
            loadouts = tuple(replace(loadout, ranged=replace(loadout.ranged, rounds=self.guns[i].ammo))
                             for i, loadout in enumerate(self.hud.state.hud.loadouts))
            if loadouts != self.hud.state.hud.loadouts:
                self.hud.set_hud(loadouts=loadouts)

    def muzzle_position(self, selection, root, source_seconds=None):
        if self.demo:
            facing = Vec2(*self.projection.project(self.controller.facing)).normalized(Vec2(1, 0))
            return root + facing * 65 + Vec2(0, -48)
        if selection is None or self.muzzle_tracks is None:
            raise ValueError("실제 총구 추적과 선택한 총 모션이 필요하다.")
        time = selection.elapsed_seconds if source_seconds is None else source_seconds
        if self.pose_tracks and selection.name in self.pose_tracks.tracks:
            return root + self.pose_tracks.projected(selection.name, time, "muzzle") * self.style["sprite_scale"]
        return root + self.muzzle_tracks.sample(selection.clip_name, time, loop=selection.loop) * self.style["sprite_scale"]

    def upper_lower_angles(self):
        if self.aim_follow:
            return self.aim_follow.upper_yaw_degrees, self.aim_follow.lower_yaw_degrees
        yaw = degrees(atan2(self.controller.facing[1], self.controller.facing[0]))
        return yaw, yaw

    def update_part_angles(self, previous_angles, delta_seconds):
        fps = self.part_sprite.direction_sample_fps if self.part_sprite else None
        if not fps or delta_seconds <= 0:
            return
        total = self.part_angle_remainder_seconds + delta_seconds
        ticks = floor(total * fps + 1e-9)
        self.part_angle_remainder_seconds = max(0, total - ticks / fps)
        if self.part_angles is None:
            self.previous_part_angles = self.part_angles = previous_angles
        if ticks:
            angles = self.upper_lower_angles()
            weight = 1 - self.part_angle_remainder_seconds / delta_seconds
            self.previous_part_angles = (self.part_angles if ticks == 1 else
                                         interpolate_angles(previous_angles, angles, weight - 1 / (fps * delta_seconds)))
            self.part_angles = interpolate_angles(previous_angles, angles, weight)

    def part_render_angles(self, motion=None):
        parts = self.part_sprite
        if (self.part_angles is not None and parts is not None and parts.enabled and self.interpolation_enabled
                and parts.direction_enabled and self.pose_sprite.quality == parts.data["quality"]
                and (motion is None or motion in parts.data["motions"])):
            phase = self.part_angle_remainder_seconds * parts.direction_sample_fps
            return interpolate_angles(self.previous_part_angles, self.part_angles, phase)
        return self.upper_lower_angles()

    def current_pose(self, *, rendering=False):
        """게임의 동작 위상과 두 방향을 함께 평가한 출력만 선택한다."""
        if self.pose_catalog is None or self.parts_only:
            return None
        custom = self.current_weapon_motion()
        attacking = self.combat and self.combat.active and custom is None
        playback = custom or (self.combat.combo if attacking else self.playback)
        motion = playback.clip_name.split("/")[0]
        if motion not in self.pose_catalog.motions:
            return None
        elapsed = playback.elapsed_seconds
        loop = custom.loop if custom else not attacking and playback.motion.endswith("_loop")
        if attacking:
            duration = self.pose_catalog.motions[motion]["source_frame_count"] / 12
            elapsed = (0 if playback.waiting_for_input else
                       target_phase(min(1, elapsed/duration), easing=self.config["combat"].get("easing", "linear"))*duration)
        self.pose_source_seconds = elapsed
        angles = self.part_render_angles(motion) if rendering else self.upper_lower_angles()
        return self.pose_catalog.select(motion, elapsed, *angles, loop=loop)

    def independent_part_pose(self, motion):
        if self.pose_sprite is None or self.part_sprite is None or (not self.parts_only and not self.interpolation_enabled):
            return None
        from ferrial_drive.combat.upper_lower import direction_index
        angles = self.part_render_angles(motion)
        upper, lower = (direction_index(angle) for angle in angles)
        name = f"{motion}/u{upper}l{lower}"
        quality = self.pose_sprite.quality
        if self.parts_only and not self.interpolation_enabled:
            return name, None
        if self.part_sprite.angular_span(name, angles, quality) is not None:
            return name, angles
        if self.part_sprite.supports(name, quality):
            return name, angles
        name = f"{motion}/u{upper}l{upper}"
        if self.part_sprite.supports(name, quality):
            return name, angles
        return None

    def perform_hud_action(self, action):
        """시연 동작이 실제로 발동한 경우에만 카운터·필살기 소리를 낸다."""
        counter_before = self.hud.state.counter
        ultimate_before = self.hud.state.ultimate_cooldown_seconds
        audible = not self.paused and not self.hud.blocking
        if self.weapons_enabled and action in ("swap", "loadout"):
            if self.weapon_animation.switching or (self.combat and self.combat.active and not self.combat.boosting):
                return
            if self.combat:
                self.combat.combo.reset()
                self.combat.attack_steps = []
                self.combat.stop_auto_swing()
        self.hud.perform(action)
        if self.weapons_enabled and action in ("swap", "loadout"):
            self.weapon_animation.request(self.hud.state.hud.active_weapon_kind, force=action == "loadout")
        self.sync_overdrive_palette()
        if not self.sound_player or not audible:
            return
        if action == "counter" and not counter_before and self.hud.state.counter:
            self.sound_player.play("counter")
        elif action == "ultimate" and ultimate_before == 0 and self.hud.state.ultimate_cooldown_seconds > 0:
            self.sound_player.play("ultimate")

    def handle_event(self, event):
        p = self.pico
        if not self.script and event.type == p.SDL_MOUSEBUTTONUP and event.button == p.SDL_BUTTON_LEFT:
            self.release_attack(discard_requested=False)
        if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_F10:
            self.running = False
            return
        if self.hud and self.hud.graphics_settings.opened:
            if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_ESCAPE:
                self.hud.graphics_settings.cancel()
            else:
                self.hud.pointer(event, p, self.paused)
            return
        if self.script:
            # 지정 입력의 조준·상태가 실제 데스크톱 입력에 덮이지 않게 한다.
            if event.type == p.SDL_KEYDOWN and event.key == p.SDLK_F10:
                self.running = False
            return
        if self.hud:
            action = self.hud.pointer(event, p, self.paused)
            if action == "settings_opened":
                self.keys.clear()
                self.release_attack()
                self.hud.aiming = False
                return
            if action == "quit":
                self.running = False
            elif action == "continue":
                self.hud.perform(action)
                self.paused = False
                self.keys.clear()
                self.release_attack()
                return
            elif action == "new_game":
                self.perform_hud_action(action)
                return
            elif action in ("resume", "show_hud"):
                self.paused = False
                self.hud.scene = "combat"
            elif action == "show_menu":
                self.paused = False
                self.keys.clear()
                self.hud.scene = "menu"
            if action in ("resume", "show_hud", "show_menu"):
                self.release_attack()
                return
            if self.hud.scene == "menu" or self.hud.transition.active:
                self.keys.clear()
                self.release_attack()
                return
        if event.type == p.SDL_WINDOWEVENT and event.window_event == p.SDL_WINDOWEVENT_FOCUS_LOST:
            self.keys.clear()
            self.release_attack()
            self.paused = True
            if self.hud:
                self.hud.aiming = False
        elif event.type == p.SDL_MOUSEMOTION:
            self.mouse = (event.x, event.y)
        elif event.type in (p.SDL_KEYDOWN, p.SDL_KEYUP):
            if getattr(event, "repeat", False):
                return
            if self.hud and not self.paused and not self.hud.blocking and event.type == p.SDL_KEYDOWN:
                if event.key == p.SDLK_q:
                    self.bind_hud_world()
                    self.hud.mouse = self.mouse
                    self.hud.select_mouse_target()
                    return
                actions = {p.SDLK_r: "activate_overdrive", p.SDLK_v: "ultimate",
                           p.SDLK_e: "swap", p.SDLK_f: "loadout"}
                if self.debug_controls:
                    actions.update({p.SDLK_F1: "damage_target", p.SDLK_F2: "damage_player",
                                    p.SDLK_F3: "energy_down", p.SDLK_F4: "energy_up",
                                    p.SDLK_F6: "overdrive", p.SDLK_F7: "target_size",
                                    p.SDLK_F8: "absorb", p.SDLK_F9: "dash", p.SDLK_c: "counter",
                                    p.SDLK_t: "toggle_target", p.SDLK_b: "dialogue", p.SDLK_4: "level"})
                if event.key in actions:
                    self.perform_hud_action(actions[event.key])
                    self.energy_level = self.hud.state.energy_level
                    return
            down = event.type == p.SDL_KEYDOWN
            key = {p.SDLK_w: "w", p.SDLK_a: "a", p.SDLK_s: "s", p.SDLK_d: "d",
                   p.SDLK_LSHIFT: "left_shift", p.SDLK_RSHIFT: "right_shift"}.get(event.key)
            if key:
                if down and not self.paused:
                    self.keys.add(key)
                else:
                    self.keys.discard(key)
            if down:
                if event.key == p.SDLK_F10:
                    self.running = False
                elif self.debug_controls and event.key == p.SDLK_F12 and self.part_sprite is not None:
                    if self.parts_only:
                        self.part_sprite.direction_enabled = not self.part_sprite.direction_enabled
                        label = "방향 보간 ON" if self.part_sprite.direction_enabled else "8방향"
                    else:
                        self.part_sprite.enabled = not self.part_sprite.enabled
                        label = "파츠 ON" if self.part_sprite.enabled else "기존 경로"
                    p.SDL_SetWindowTitle(p.window, ("Ferrial Drive | 독립 파츠 비교 | " + label + " | F12 전환").encode("utf-8"))
                elif event.key == p.SDLK_ESCAPE:
                    self.paused = not self.paused
                    self.keys.clear()
                    self.release_attack()
                    if self.hud:
                        self.hud.aiming = False
                elif event.key == p.SDLK_F5:
                    self.reset()
                elif self.debug_controls and event.key == p.SDLK_g:
                    self.grid = not self.grid
                elif self.debug_controls and event.key == p.SDLK_h:
                    self.show_shadow = not self.show_shadow
                elif self.debug_controls and event.key == p.SDLK_i:
                    self.interpolation_enabled = not self.interpolation_enabled
                elif self.debug_controls and event.key in (p.SDLK_1, p.SDLK_2, p.SDLK_3) and not self.paused:
                    self.set_energy_level(event.key - p.SDLK_1 + 1)
                elif event.key == p.SDLK_SPACE and not self.paused and not (self.hud and self.hud.blocking):
                    if self.hud:
                        self.hud.dash_override = None
                    if self.combat:
                        self.combat.request_boost(self.movement(), self.aim())
                    else:
                        self.controller.request_boost(self.movement(), self.aim())
        elif event.type == p.SDL_MOUSEBUTTONDOWN and event.button == p.SDL_BUTTON_LEFT and not self.paused and not (self.hud and self.hud.blocking) and self.combat:
            self.attack_held = True
            self.request_primary_attack()

    def update(self, delta_seconds):
        self.apply_preview_control()
        self.frame += 1
        for entry in self.script:
            if entry["frame"] == self.frame:
                if entry.get("reset"):
                    self.reset()
                if "keys" in entry:
                    self.keys = set(entry["keys"])
                if "mouse" in entry:
                    self.mouse = tuple(entry["mouse"])
                if "paused" in entry:
                    self.paused = entry["paused"]
                    self.keys.clear()
                    self.release_attack()
                if "interpolation" in entry:
                    self.interpolation_enabled = entry["interpolation"]
                if "part_renderer" in entry and self.part_sprite is not None:
                    if self.parts_only:
                        self.part_sprite.direction_enabled = bool(entry["part_renderer"])
                    else:
                        self.part_sprite.enabled = bool(entry["part_renderer"])
                if self.hud and "ui_action" in entry:
                    self.perform_hud_action(entry["ui_action"])
                if self.hud and "scene" in entry:
                    self.hud.scene = entry["scene"]
                    self.keys.clear()
                    self.release_attack()
                if "energy_level" in entry:
                    self.set_energy_level(entry["energy_level"])
                if self.hud and "aiming" in entry:
                    self.hud.aiming = bool(entry["aiming"])
                if entry.get("capture"):
                    name = entry["capture"]
                    if not self.report_path or Path(name).name != name:
                        raise ValueError("검토 캡처에는 --report와 파일 이름이 필요하다.")
                    self.pending_capture = self.report_path.parent / "frames" / name
                if "attack_held" in entry:
                    self.attack_held = entry["attack_held"]
                    if not self.attack_held:
                        self.release_attack()
                if entry.get("boost") and not self.paused:
                    (self.combat or self.controller).request_boost(self.movement(), self.aim())
                if entry.get("attack") and not self.paused and not (self.hud and self.hud.blocking) and self.combat:
                    self.request_primary_attack()
        # 사전 지정 입력 검증은 렌더 속도와 독립된 60Hz다. 일반 조작은 실제 경과 시간을 쓴다.
        dt = 1 / 60 if self.script else min(delta_seconds, 0.1)
        if self.paused or (self.hud and self.hud.blocking) or self.encounter_finished():
            if self.sound_player:
                self.sound_player.stop()
            self.update_hud(dt)
            return
        previous_position_m = self.controller.position_m
        previous_angles = self.upper_lower_angles()
        previous_draw_angles = self.part_render_angles() if self.parts_only else previous_angles
        if self.hud:
            # 첫 획득·유효성은 사격 전에 확인하고 교체 대기 시간은 HUD 갱신에서 한 번만 더한다.
            self.bind_hud_player()
            self.hud.update_world_view(0, update_markers=False)
        previous_position = self.projection.project(previous_position_m)
        overdrive = bool(self.hud and self.hud.state.overdrive)
        animation_speed = self.sync_overdrive_modifiers()
        prepare_before_seconds = self.controller.boost_prepare_remaining_seconds
        options = {"dash": bool({"left_shift", "right_shift"} & self.keys)}
        if self.combat:
            options["auto_swing"] = self.attack_held
        if self.weapons_enabled and (self.weapon_animation.kind == "ranged" or self.weapon_animation.switching):
            if self.combat:
                self.combat.attack_steps = []
            self.controller.update(dt, self.movement(), self.aim(), dash=options["dash"], face_movement=False)
        else:
            (self.combat or self.controller).update(dt, self.movement(), self.aim(), **options)
        if self.aim_follow:
            target = self.aim()
            yaw = degrees(atan2(target[1],target[0])) if any(target) else self.aim_follow.upper_yaw_degrees
            self.aim_follow.update(dt,yaw)
            upper = radians(self.aim_follow.upper_yaw_degrees)
            self.controller.facing = (cos(upper), sin(upper))
        self.update_part_angles(previous_angles, dt)
        if self.pose_tracks:
            self.pose_tracks.smooth = self.parts_only and self.interpolation_enabled and self.part_sprite.direction_enabled
            self.pose_tracks.begin_frame(previous_draw_angles, self.part_render_angles() if self.parts_only else self.upper_lower_angles(),
                                         self.combat.attack_steps if self.combat else [], dt)
        self.advance_encounter(dt, previous_position_m)
        if self.weapons_enabled:
            self.weapon_animation.update(dt, self.weapon_durations, aiming=bool(self.hud and self.hud.aiming),
                                         state=self.controller.state, animation_speed=animation_speed)
            self.update_guns(dt, previous_position)
        zoom = self.config.get("camera_zoom", {}).get("scale_by_state", {}).get(self.controller.presentation_state, 1)
        focus = self.locked_target_position()
        self.camera.update(self.projection.project(self.controller.position_m), self.mouse, dt, target_zoom=zoom,
                           focus_world=(focus.x, focus.y) if focus is not None else None)
        self.camera_impact.update(dt)
        self.gun_recoil.update(dt)
        self.camera.feedback_offset_pixels = tuple(a + b for a, b in
            zip(self.camera_impact.offset_pixels, self.gun_recoil.offset_pixels))
        if self.sword_effects:
            steps = self.combat.attack_steps if self.combat else []
            # 공격 위상은 가속된 steps를 따르고, 효과의 생성 시각·수명은 실제 초를 쓴다.
            self.sword_effects.update(dt, steps,
                                      self.energy_level, self.sword_targets, energy_color=self.current_energy_color(),
                                      trail_color=self.current_trail_color(),
                                      reach_multiplier=self.overdrive_settings.trail_scale if overdrive else 1)
            self.target_flash = {name: max(0, value - dt) for name, value in self.target_flash.items()}
            for strike_id, target_id in self.sword_effects.hits:
                self.target_hits[target_id] += 1
                self.target_flash[target_id] = 0.18
                self.on_sword_hit(strike_id, target_id)
                if self.hud:
                    damage = self.overdrive_settings.sword_damage if overdrive else self.sword_damage_by_energy_level[self.energy_level - 1]
                    self.hud.damage_target(target_id, damage)
        if not self.combat or not self.combat.active:
            self.playback.update("boost" if self.controller.boost_preparing else self.controller.state,
                                 self.controller.direction, dt * animation_speed)
        if self.sound_cues:
            attacking = bool(self.combat and self.combat.active)
            mode = ground_effect_mode(self.controller.state,
                attack_index=self.combat.combo.attack_index if attacking else None,
                waiting=self.combat.combo.waiting_for_input if attacking else False, dash=options["dash"])
            self.sound_cues.update(dt, self.controller,
                self.combat.attack_steps if self.combat else [],
                self.sword_effects.hits if self.sword_effects else [],
                prepare_before_seconds=prepare_before_seconds, energy_level=self.energy_level,
                scraping=mode is not None and self.controller.speed_mps > 0.05,
                dashing=mode in ("dash", "dash_attack") and self.controller.speed_mps > 0.05,
                hit_materials={target.target_id: target.material for target in self.sword_targets})
        self.update_hud(dt, targets_current=True)
        if self.ground_effects:
            self.update_ground_effects(dt, previous_position)
        if self.report_path:
            self.trace.append({"frame": self.frame, "position_m": self.controller.position_m,
                               "state": self.controller.state, "direction": self.controller.direction,
                               "motion": self.playback.motion, "speed_mps": self.controller.speed_mps,
                               "movement_speed_mps": self.controller.movement_speed_mps})
            self.trace[-1]["boost_preparing"] = self.controller.boost_preparing
            self.trace[-1]["boost_remaining_seconds"] = self.controller.boost_remaining_seconds
            self.trace[-1]["camera_zoom"] = self.camera.zoom
            self.trace[-1]["camera_impact_offset_pixels"] = self.camera.feedback_offset_pixels
            self.trace[-1]["overdrive_color"] = self.overdrive_color
            if self.aim_follow:
                pose = self.current_pose()
                self.trace[-1].update(upper_yaw_degrees=self.aim_follow.upper_yaw_degrees,
                    lower_yaw_degrees=self.aim_follow.lower_yaw_degrees,
                    lower_following=self.aim_follow.lower_following,
                    pose_clip=pose.clip_name if pose else None, pose_frame=pose.frame_index if pose else None)
            if self.hud:
                self.trace[-1].update(radar_scale=self.hud.state.radar_scale,
                                     radar_solid_ratio=self.hud.state.radar_solid_ratio,
                                     lock_target_id=self.hud.selected_target_id,
                                     lock_pending_id=self.hud.auto_target.pending_id,
                                     lock_pending_seconds=self.hud.auto_target.pending_seconds)
            if self.combat and self.combat.active:
                self.trace[-1].update(motion=self.combat.combo.clip_name, state="attack",
                    attack_index=self.combat.combo.attack_index, attack_elapsed_seconds=self.combat.combo.elapsed_seconds,
                    attack_strike_id=self.combat.strike_id, attack_queued=self.combat.combo.queued)
            self.trace[-1]["attack_held"] = self.attack_held
            if self.weapons_enabled:
                selection = self.current_weapon_motion()
                self.trace[-1].update(weapon_kind=self.weapon_animation.kind, weapon_switching=self.weapon_animation.switching,
                    gun_aiming=self.weapon_animation.aiming, gun_ammo=self.gun.ammo,
                    gun_muzzle=(self.gun.muzzle.x, self.gun.muzzle.y),
                    gun_shot_direction=(self.gun.shot_direction.x, self.gun.shot_direction.y),
                    gun_shots=sum(g.shots_fired for g in self.guns), gun_hits=[hit for g in self.guns for hit in g.hits],
                    weapon_motion=selection.clip_name if selection else None, energy_mask_color=self.current_energy_color())
            if self.sword_effects:
                self.trace[-1].update(energy_level=self.energy_level, sword_sections=len(self.sword_effects.sections),
                    attack_echoes=len(self.sword_effects.echoes), sword_hits=self.sword_effects.hits[:],
                    target_hits=self.target_hits.copy())
            if self.ground_effects:
                self.trace[-1]["ground_particles"] = len(self.ground_effects.particles)
                self.trace[-1]["ground_effect_mode"] = self.effect_mode

    def encounter_finished(self):
        return False

    def advance_encounter(self, seconds, previous_position_m):
        """독립 교전 실행부가 적을 갱신하는 연결점. 기본 훈련장은 정지 표적을 유지한다."""

    def current_energy_color(self):
        if self.hud:
            state = self.hud.state
            if state.overdrive and self.overdrive_color is not None:
                return self.overdrive_color
            return self.hud.view.level_energy_color(state.energy_level,
                                                   1 if state.overdrive else state.overdrive_charge_ratio * self.overdrive_settings.standby_tint_ratio)
        return "#9DDFEA"

    def current_trail_color(self):
        """Standby의 검 Trail만 더 붉게 표시한다. UI·기체 마스크·잔상색은 유지한다."""
        color = self.current_energy_color()
        if not self.hud or self.hud.state.overdrive or not self.hud.state.overdrive_ready:
            return color
        from ferrial_drive.ui.energy import energy_color
        return energy_color(color, self.hud.view.style["overdrive_red"], self.standby_trail_tint_ratio)

    def sync_energy_mask(self):
        """HUD와 같은 표시색을 공유하고 원본 기체 텍스처는 보존한다."""
        color = self.current_energy_color()
        rgb = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
        for sprite in (self.motion_sprite, self.attack_sprite, self.pose_sprite):
            if sprite is not None:
                sprite.energy_color = rgb if self.style.get("energy_mask_enabled", True) else None
                sprite.energy_mask_gain = self.style.get("energy_mask_gain", 4)

    def current_rim_light(self):
        rim = self.config.get("overdrive_rim", {})
        active = bool(self.hud and self.hud.state.overdrive)
        ready = bool(self.hud and self.hud.state.overdrive_ready)
        if active and self.overdrive_color is not None:
            rim = {**rim, "color": self.overdrive_color}
        if ready:
            rim = {**rim, "strength": rim.get("strength", 1) * self.overdrive_settings.standby_rim_strength}
        return standby_rim(rim, self.rim_elapsed_seconds, active or ready)

    def sync_overdrive_palette(self):
        active = bool(self.hud and self.hud.state.overdrive)
        elapsed = (max(0, self.overdrive_settings.duration_seconds - self.hud.state.overdrive_remaining_seconds)
                   if active else 0)
        self.overdrive_color = (rainbow_color(elapsed, self.rainbow_cycle_seconds)
                               if active and self.overdrive_rainbow else None)
        if self.hud and self.hud.view is not None:
            self.hud.view.overdrive_color = self.overdrive_color

    def update_ground_effects(self, delta_seconds, previous_position):
        if delta_seconds <= 0:
            return
        custom = self.current_weapon_motion()
        attacking = self.combat and self.combat.active and custom is None
        playback = self.combat.combo if attacking else self.playback
        clip_name = custom.clip_name if custom else playback.clip_name
        loop = custom.loop if custom else not attacking and playback.motion.endswith("_loop")
        elapsed = custom.elapsed_seconds if custom else playback.elapsed_seconds
        if attacking:
            clip = self.attack_resources[playback.clip_name].clips[playback.clip_name]
            duration = clip.duration_ms / 1000
            elapsed = target_phase(min(1, elapsed / duration), easing=self.config.get("combat", {}).get("easing", "accelerate")) * duration
        elif not loop and custom is None:
            clip = self.clip_resources[playback.clip_name].clips[playback.clip_name]
            elapsed = min(1, elapsed / playback.transition_seconds) * clip.duration_ms / 1000
        motion = clip_name.split("/")[0]
        if self.pose_tracks and motion in self.pose_tracks.tracks:
            offsets = self.pose_tracks.ground_offsets(motion, elapsed, self.style["sprite_scale"])
        else:
            offsets = self.ground_effects.attachment_offsets(clip_name, elapsed, loop=loop,
                                                            scale=self.style["sprite_scale"])
        center = self.projection.project(self.controller.position_m)
        velocity = tuple((a - b) / delta_seconds for a, b in zip(center, previous_position))
        color = self.current_energy_color()
        mode = ground_effect_mode(self.controller.state,
            attack_index=playback.attack_index if attacking else None,
            waiting=playback.waiting_for_input if attacking else False,
            dash=bool({"left_shift", "right_shift"} & self.keys))
        self.effect_mode = mode
        lower = radians(self.upper_lower_angles()[1])
        foot_facing = (cos(lower),sin(lower)) if self.parts_only or self.current_pose() else self.controller.facing
        strength = self.config["ground_effects"]["strength_by_mode"].get(mode, 1)
        effect_opacity = None
        if mode == "dash":
            strength *= self.controller.dash_output
            effect_opacity = strength * self.controller.dash_output
        self.ground_effects.update(delta_seconds, center=center, velocity=velocity, offsets=offsets,
            active=mode is not None, strength=strength,
            material=self.config["ground_effects"]["material"], energy_color=color,
            foot_contact=mode in ("dash", "boost", "dash_attack"),
            foot_facing_x=foot_facing[0],
            boost_active=self.controller.boost_remaining_seconds > 0,
            effect_opacity=effect_opacity,
            reverse_motion=sum(v * f for v, f in zip(self.projection.unproject(velocity), foot_facing)) < 0,
            ground_color=lambda point: self.ground.color_at(point, blend=self.config["ground_effects"]["ground_color_blend"]))

    def bind_hud_world(self):
        if self.hud:
            self.hud.bind_world(self.camera, self.projection, self.controller, self.sword_targets, self.mouse,
                                player_bounds=self.player_world_bounds())

    def bind_hud_player(self):
        self.hud.bind_player(self.camera, self.projection, self.controller, self.mouse,
                             player_bounds=self.player_world_bounds())

    def player_world_bounds(self):
        """그림자·잔상을 제외한 플레이어 표시 영역. 가시성 검사로 GPU 적재를 유발하지 않는다."""
        x, y = self.projection.project(self.controller.position_m)
        pose = self.current_pose()
        if pose is not None and self.pose_sprite is not None:
            left, top, width, height = self.pose_sprite.clip_bounds[pose.clip_name]
            scale = self.style["sprite_scale"]
            return x + left * scale, y + top * scale, width * scale, height * scale
        if self.sprites and self.playback is not None:
            custom = self.current_weapon_motion()
            attacking = self.combat and self.combat.active and custom is None
            playback = custom or (self.combat.combo if attacking else self.playback)
            resource = (self.attack_resources if attacking else self.clip_resources)[playback.clip_name]
            frames = resource.clips[playback.clip_name].frames
            scale = self.style["sprite_scale"] * self.style.get("atlas_pixel_scale", 1)
            left = min(-frame.pivot[0] for frame in frames)
            top = min(frame.pivot[1] - frame.rect[3] for frame in frames)
            right = max(frame.rect[2] - frame.pivot[0] for frame in frames)
            bottom = max(frame.pivot[1] for frame in frames)
            return x + left * scale, y + top * scale, (right - left) * scale, (bottom - top) * scale
        return x - 38, y - 105, 76, 110

    def sync_overdrive_modifiers(self):
        self.sync_overdrive_palette()
        active = bool(self.hud and self.hud.state.overdrive)
        animation_speed = self.overdrive_settings.animation_speed if active else 1
        self.controller.speed_multiplier = self.overdrive_settings.movement_speed if active else 1
        if self.combat:
            self.combat.speed = self.config.get("combat", {}).get("playback_speed", 1.25) * animation_speed
        if self.sound_player:
            self.sound_player.set_rate_multiplier(self.overdrive_settings.pitch_scale if active else 1)
        return animation_speed

    def update_hud(self, delta_seconds, *, targets_current=False):
        if self.hud:
            if targets_current:
                self.bind_hud_player()
            else:
                self.bind_hud_world()
            self.hud.update(self.controller, delta_seconds, paused=self.paused,
                            interpolation=bool(self.interpolation_enabled and self.motion_sprite and self.current_pose() is None),
                            attack=self.combat.combo if self.combat and self.combat.active else None,
                            training_hits=sum(self.target_hits.values()))
            self.energy_level = self.hud.state.energy_level
            if not (self.hud.state.overdrive or self.hud.state.overdrive_ready):
                self.rim_elapsed_seconds = 0
            elif not self.paused and not self.hud.blocking:
                self.rim_elapsed_seconds += delta_seconds
        self.sync_overdrive_modifiers()

    def draw_demo(self, x, y):
        r, state = self.renderer, self.controller.state
        phase = self.playback.elapsed_seconds * 1.5 * tau
        bob = abs(sin(phase)) * 5 if state == "run" else 0
        zoom = self.camera.zoom
        r.rect(Rect(x - 24 * zoom, y - (95 + bob) * zoom, 48 * zoom, 62 * zoom), "#83969D")
        r.rect(Rect(x - 12 * zoom, y - (80 + bob) * zoom, 24 * zoom, 4 * zoom), self.current_energy_color())
        for side in (-1, 1):
            step = sin(phase) * side * 12 if state == "run" else 0
            r.rect(Rect(x + (side * 14 - 6) * zoom, y + (-34 + step) * zoom, 12 * zoom, 32 * zoom), "#566D76")
        direction = self.controller.facing
        length = max(1e-8, (direction[0] ** 2 + direction[1] ** 2) ** 0.5)
        dx, dy = direction[0] / length, direction[1] / length
        selection = self.current_weapon_motion()
        if selection and selection.name.startswith("gun_"):
            root = Vec2(*self.projection.project(self.controller.position_m))
            muzzle = self.muzzle_position(selection, root)
            point = self.camera.world_to_screen((muzzle.x, muzzle.y))
            r.line(x + dx * 18 * zoom, y + (-48 + dy * 18) * zoom, *point, "#E4E9EC")
            return
        if self.combat and self.combat.active:
            from math import atan2, cos
            clip = self.combat.combo.clips[self.combat.combo.clip_name]
            phase = self.combat.combo.elapsed_seconds / (clip.duration_ms / 1000)
            phase = target_phase(phase, easing=self.config.get("combat", {}).get("easing", "accelerate"))
            angle = atan2(dy, dx) - tau / 4 + phase * tau * 0.6
            dx, dy = cos(angle), sin(angle)
        r.line(x + 27 * zoom, y - 48 * zoom, x + (27 + dx * 75) * zoom,
               y + (-48 + dy * 40) * zoom, "#80D6F0")

    def draw_targets(self):
        r, zoom = self.renderer, self.camera.zoom
        for target in self.sword_targets:
            if self.hud and target.target_id in self.hud.enemies and self.hud.enemies[target.target_id]["health"].current <= 0:
                continue
            tx, ty = self.camera.world_to_screen((target.center.x, target.center.y))
            color = "#FFFFFF" if self.target_flash.get(target.target_id, 0) > 0 else "#D6AD76"
            r.circle(tx, ty, target.radius_pixels * zoom, color, 0.8)
            r.line(tx - 7 * zoom, ty, tx + 7 * zoom, ty, color, 0.8)
            r.line(tx, ty - 7 * zoom, tx, ty + 7 * zoom, color, 0.8)
            r.text(f"{target.target_id} · {self.target_hits[target.target_id]}", tx, ty - (target.radius_pixels + 16) * zoom,
                   "small", color, align="center")

    def draw_world(self):
        self.part_stream_budget.reset()
        self.sync_energy_mask()
        animation_speed = self.overdrive_settings.animation_speed if self.hud and self.hud.state.overdrive else 1
        r, c = self.renderer, self.controller
        zoom = self.camera.zoom
        sprite_scale = self.style["sprite_scale"] * zoom
        width, height = self.window_size
        self.ground.draw(self.camera, self.window_size, c.settings.map_size_m, grid=self.grid)
        x, y = self.camera.world_to_screen(self.projection.project(c.position_m))
        pose = self.current_pose(rendering=True) if self.pose_sprite else None
        weapon_motion = self.current_weapon_motion() if self.sprites and pose is None else None
        playback = weapon_motion or (self.combat.combo if self.combat and self.combat.active else self.playback)
        part_only_pose = self.independent_part_pose(playback.clip_name.split("/")[0]) if self.sprites and pose is None else None
        if self.pose_sprite:
            pose_clips = [pose.clip_name] if pose else []
            if self.sword_effects:
                pose_clips.extend(echo.pose_clip_name for echo in self.sword_effects.echoes if echo.pose_clip_name)
            if pose and self.part_sprite and self.interpolation_enabled:
                self.pose_sprite.prepare_frame(pose_clips, angular_pose=(pose.clip_name,
                                                                         self.part_render_angles(pose.clip_name.split("/")[0])))
            elif part_only_pose:
                self.pose_sprite.prepare_frame(pose_clips, part_only_pose=part_only_pose)
            else:
                self.pose_sprite.prepare_frame(pose_clips)
        self.draw_targets()
        if self.sword_effects:
            if self.sprites:
                self.sword_renderer.draw_echoes(self.sword_effects, self.camera, self.projection,
                    self.attack_sprite, self.attack_resources,
                    scale=sprite_scale if self.pose_sprite else sprite_scale * self.style.get("atlas_pixel_scale", 1),
                    interpolate=self.interpolation_enabled, easing=self.config["combat"].get("easing", "accelerate"),
                    pose_sprite=self.pose_sprite)
            self.sword_renderer.draw_trail(self.sword_effects, self.camera, "#9DDFEA")
            self.sword_renderer.draw_body_wind(self.sword_effects, self.camera,
                ground_color=(lambda point: self.ground.color_at(point, blend=1)) if self.ground.colors else None)
        if self.sprites and pose is not None:
            self.draw_pose(pose,x,y,sprite_scale)
        elif self.sprites:
            attacking = self.combat and self.combat.active
            playback = weapon_motion or (self.combat.combo if attacking else self.playback)
            resource = (self.attack_resources if attacking else self.clip_resources)[playback.clip_name]
            clip = resource.clips[playback.clip_name]
            if weapon_motion:
                elapsed = weapon_motion.elapsed_seconds
                frame_position = elapsed * clip.fps
                endpoint = None
            elif attacking:
                elapsed = playback.elapsed_seconds
                phase = min(1, elapsed / (clip.duration_ms / 1000))
                attack_easing = self.config.get("combat", {}).get("easing", "accelerate")
                frame_position = len(clip.frames) * target_phase(phase, easing=attack_easing)
                endpoint = (f"combo_{playback.attack_index + 2:02}/{playback.direction}"
                            if not playback.waiting_for_input and playback.attack_index < 3 else None)
                if playback.waiting_for_input:
                    elapsed = frame_position = 0
            else:
                elapsed = playback.elapsed_seconds
                if not playback.motion.endswith("_loop"):
                    elapsed = min(1, elapsed / playback.transition_seconds) * clip.duration_ms / 1000
                frame_position = elapsed * clip.fps
                endpoint = (f"{playback.state}_loop/{playback.direction}"
                            if not playback.motion.endswith("_loop") else None)
            frame_index = ((int(frame_position) % len(clip.frames) if weapon_motion.loop else min(int(frame_position), len(clip.frames)-1))
                           if weapon_motion else min(int(frame_position), len(clip.frames)-1) if attacking else playback.frame_index)
            interpolator = self.attack_sprite if attacking else self.motion_sprite
            interpolate = self.interpolation_enabled and (interpolator is not None or part_only_pose is not None)
            if interpolator is not None:
                interpolator.rim_light = self.current_rim_light()
            sheet_scale = sprite_scale * self.style.get("atlas_pixel_scale", 1)
            direction = SCREEN_DIRECTIONS[int(part_only_pose[0][-1])] if self.parts_only else playback.direction
            part_seconds = frame_position / clip.fps
            if part_only_pose and self.parts_only and not self.interpolation_enabled:
                fps = self.part_sprite.data.get("sample_fps") or clip.fps
                part_seconds = floor(part_seconds * fps + 1e-8) / fps
            active_parts, active_span = self.pose_sprite.select_parts(*part_only_pose) if part_only_pose else (None, None)
            part_shadow = getattr(active_parts, "shadow_map", None)
            before_body = None
            if self.show_shadow and part_shadow and active_parts.prepare_shadow(part_only_pose[0], part_seconds, active_span):
                if self.pbr_enabled:
                    def before_body():
                        with self.timings.scope("parts.shadow_ground"):
                            part_shadow.draw_ground(x, y, sprite_scale, self.style["shadow_opacity"],
                                                    softness_pixels=self.style.get("shadow_softness_pixels", 5))
                        if self.ground_effect_renderer:
                            self.ground_effect_renderer.draw(self.ground_effects, self.camera,
                                                            trail_in_front=trail_in_front(direction))
                else:
                    with self.timings.scope("parts.shadow_ground"):
                        part_shadow.draw_ground(x, y, sprite_scale, self.style["shadow_opacity"])
            elif self.show_shadow and not self.pbr_enabled and "shadow" in resource.mech.layer_rows:
                resources = self.attack_resources if attacking else self.clip_resources
                shadow_name = playback.clip_name.rsplit("/", 1)[0] + "/" + direction
                shadow_resource = resources[shadow_name]
                if endpoint is not None and self.parts_only:
                    endpoint = endpoint.rsplit("/", 1)[0] + "/" + direction
                if self.shadow_blend:
                    self.shadow_blend.draw(shadow_resource, shadow_name, frame_position if interpolate else frame_index, x, height - y,
                                           scale=sheet_scale, opacity=self.style["shadow_opacity"], endpoint=endpoint,
                                           endpoint_resource=resources.get(endpoint),
                                           loop=weapon_motion.loop if weapon_motion else not attacking and playback.motion.endswith("_loop"))
                else:
                    with resource.opacity(self.style["shadow_opacity"]):
                        resource.draw(playback.clip_name, frame_index, x, height - y,
                                      scale=sheet_scale, part_visibility={"body": False})
            if self.ground_effect_renderer and before_body is None:
                self.ground_effect_renderer.draw(self.ground_effects, self.camera,
                                                trail_in_front=trail_in_front(direction))
            if part_only_pose:
                name, angles = part_only_pose
                self.pose_sprite.rim_light = self.current_rim_light()
                self.pose_sprite.draw_motion(name, part_seconds, x, y, scale=sprite_scale, yaw_degrees=angles,
                                             sample_shadow=self.show_shadow, before_body=before_body)
                if self.trace and self.trace[-1]["frame"] == self.frame:
                    self.trace[-1].update(part_clip=name, part_angles_degrees=angles, part_seconds=part_seconds,
                                          part_lighting="pbr" if self.pbr_enabled else "surface" if part_shadow else "baked")
            elif interpolate:
                if weapon_motion:
                    source_speed = weapon_motion.playback_speed
                elif attacking:
                    source_speed = self.combat.speed
                elif not playback.motion.endswith("_loop"):
                    source_speed = clip.duration_ms / 1000 / playback.transition_seconds
                else:
                    source_speed = 1
                interpolator.draw(playback.clip_name, elapsed, x, y, scale=sprite_scale,
                                  easing=attack_easing if attacking else "linear",
                                  playback_speed=source_speed * (animation_speed if not attacking and not weapon_motion else 1))
            else:
                resource.draw(playback.clip_name, frame_index, x, height - y,
                              scale=sheet_scale, part_visibility={"shadow": False})
            if self.ground_effect_renderer:
                self.ground_effect_renderer.draw(self.ground_effects, self.camera, foreground=True,
                                                trail_in_front=trail_in_front(direction))
        else:
            self.draw_demo(x, y)
        if self.weapons_enabled and self.gun_renderer is not None:
            selection = self.current_weapon_motion()
            muzzle = (self.muzzle_position(selection, Vec2(*self.projection.project(self.controller.position_m)))
                      if self.weapon_animation.kind == "ranged" and not self.weapon_animation.switching else None)
            self.gun_renderer.draw(self.camera, self.guns, active_gun=self.gun, muzzle=muzzle,
                                   color=self.current_energy_color(), contact=self.gun_contact,
                                   energy_level=self.energy_level)
        if self.sword_effects:
            self.sword_renderer.draw_contacts(self.sword_effects, self.camera)
        return x, y

    def draw_pose(self,pose,x,y,scale):
        sprite = self.pose_sprite
        sprite.rim_light = self.current_rim_light()
        if self.show_shadow:
            sprite.draw_frame(pose.clip_name,pose.frame_index,x,y,scale=scale,shadow=True,
                              opacity=self.style["shadow_opacity"])
        direction = SCREEN_DIRECTIONS[pose.lower]
        if self.ground_effect_renderer:
            self.ground_effect_renderer.draw(self.ground_effects,self.camera,trail_in_front=trail_in_front(direction))
        seconds = getattr(self, "pose_source_seconds", pose.frame_index / 12)
        if (not self.interpolation_enabled or getattr(self, "part_sprite", None) is None
                or not sprite.draw_motion(pose.clip_name, seconds, x, y, scale=scale,
                                          yaw_degrees=self.part_render_angles(pose.clip_name.split("/")[0]))):
            sprite.draw_frame(pose.clip_name,pose.frame_index,x,y,scale=scale)
        if self.ground_effect_renderer:
            self.ground_effect_renderer.draw(self.ground_effects,self.camera,foreground=True,trail_in_front=trail_in_front(direction))
    def draw(self):
        start = perf_counter() if self.report_path else None
        preview_due = self.preview_frame_path and perf_counter() >= self.next_preview_frame
        width, height = self.window_size
        world_filter = (self.hud.view.world_motion_blur(self.camera.velocity_pixels_per_second,
                                                       enabled=not self.paused and self.hud.scene == "combat")
                        if self.hud else nullcontext())
        with world_filter:
            x, y = self.draw_world()
        if self.hud:
            if preview_due:
                from ferrial_drive.diagnostics.theme_preview import ThemePreviewRenderer
                view = self.hud.view
                original = view.renderer
                preview_renderer = ThemePreviewRenderer(original)
                view.renderer, view.theme_preview_active = preview_renderer, True
                try:
                    self.hud.draw(self.mouse, (x, y))
                finally:
                    view.renderer, view.theme_preview_active = original, False
            else:
                self.hud.draw(self.mouse, (x, y))
        elif self.paused:
            self.renderer.rect(Rect(0, 0, width, height), "#0A1016", 0.5)
            self.renderer.text("일시정지 · Esc 재개", width / 2, height / 2, "body", "#FFFFFF", align="center")
        if start is not None:
            self.frame_times.append(perf_counter() - start)
            if len(self.frame_times) > 3600:
                self.frame_times.pop(0)
        if self.capture_path and self.frame >= self.capture_frame:
            self.capture(self.capture_path)
            self.capture_path = None
        if self.pending_capture:
            self.capture(self.pending_capture)
            self.pending_capture = None
        if preview_due:
            self.next_preview_frame = perf_counter() + .2
            temporary = self.preview_frame_path.with_name(self.preview_frame_path.stem + ".writing.png")
            self.capture(temporary)
            try:
                temporary.replace(self.preview_frame_path)
                metadata = {"image_signature": self.preview_frame_path.stat().st_mtime_ns,
                            "size": list(self.window_size), "scene": self.hud.scene if self.hud else "combat",
                            "paused": self.paused,
                            "regions": preview_renderer.export() if self.hud else []}
                metadata_path = self.preview_frame_path.with_suffix(".json")
                metadata_temporary = metadata_path.with_suffix(".tmp")
                metadata_temporary.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
                metadata_temporary.replace(metadata_path)
            except PermissionError:
                pass
        if self.record_directory and self.frame % self.record_step == 0:
            area = self.pico.SDL_Rect(max(0, min(width - 440, round(x) - 220)),
                                      max(0, min(height - 340, round(y) - 260)), 440, 340)
            self.capture(self.record_directory / f"{self.frame:05d}.png", area=area)

    def apply_preview_control(self):
        """외부 테마 편집기의 제한된 시연 상태 요청만 처리한다."""
        if self.preview_control_path is None or self.hud is None:
            return
        try:
            signature = self.preview_control_path.stat().st_mtime_ns
            if signature == self.preview_control_signature:
                return
            request = json.loads(self.preview_control_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.preview_control_signature = signature
        if not isinstance(request, dict):
            return
        if request.get("scene") in ("menu", "combat"):
            self.paused = False
            self.hud.scene = request["scene"]
        if type(request.get("paused")) is bool:
            self.paused = request["paused"]
        action = request.get("action")
        if action == "reset":
            self.reset()
        elif action in ("damage_target", "damage_player", "overdrive", "activate_overdrive", "swap", "loadout", "dialogue", "absorb", "ultimate", "energy_up", "energy_down"):
            self.perform_hud_action(action)

    def capture(self, path, area=None, *, output_size=None):
        p = self.pico
        surface = p.SDL_CreateRGBSurfaceWithFormat(0, *self.window_size, 32, p.SDL_PIXELFORMAT_RGBA32)
        cropped = None
        if not surface:
            raise RuntimeError("화면 저장 표면 생성 실패")
        try:
            p.SDL_RenderFlush(p.renderer)
            if p.SDL_RenderReadPixels(p.renderer, None, p.SDL_PIXELFORMAT_RGBA32,
                                     surface.contents.pixels, surface.contents.pitch) != 0:
                raise RuntimeError("화면 픽셀 읽기 실패")
            if area is not None:
                if area.x < 0 or area.y < 0 or area.w <= 0 or area.h <= 0 or (
                        area.x + area.w > self.window_size[0] or area.y + area.h > self.window_size[1]):
                    raise ValueError("캡처 영역은 창 내부의 양수 크기여야 한다.")
                cropped = p.SDL_CreateRGBSurfaceWithFormat(0, area.w, area.h, 32, p.SDL_PIXELFORMAT_RGBA32)
                if not cropped:
                    raise RuntimeError("부분 캡처 표면 생성 실패")
                for row in range(area.h):
                    memmove(cropped.contents.pixels + row * cropped.contents.pitch,
                            surface.contents.pixels + (area.y + row) * surface.contents.pitch + area.x * 4,
                            area.w * 4)
            elif output_size is not None:
                cropped = p.SDL_CreateRGBSurfaceWithFormat(0, *output_size, 32, p.SDL_PIXELFORMAT_RGBA32)
                if not cropped or p.SDL_BlitScaled(surface, None, cropped, None) != 0:
                    raise RuntimeError("미리보기 축소 실패")
            path.parent.mkdir(parents=True, exist_ok=True)
            if p.IMG_SavePNG(cropped if cropped is not None else surface, str(path).encode("utf-8")) != 0:
                raise RuntimeError("화면 PNG 저장 실패")
        finally:
            if cropped is not None:
                p.SDL_FreeSurface(cropped)
            p.SDL_FreeSurface(surface)

    def exit(self):
        if self.report_path and self.playback:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            info = self.pico.SDL_RendererInfo()
            self.pico.SDL_GetRendererInfo(self.pico.renderer, byref(info))
            self.report_path.write_text(json.dumps({"renderer": info.name.decode(), "frames": self.frame,
                "movement_speed_multiplier": self.movement_speed_multiplier,
                "movement": self.config["movement"],
                "draw_cpu_mean_ms": sum(self.frame_times) / max(1, len(self.frame_times)) * 1000,
                "draw_cpu_max_ms": max(self.frame_times, default=0) * 1000,
                "asset_bytes": sum(sprite.estimated_bytes for sprite in self.sprites),
                "interpolation_bytes": sum(sprite.estimated_bytes for sprite in dict.fromkeys((self.motion_sprite, self.attack_sprite)) if sprite),
                "upper_lower_bytes": self.pose_sprite.estimated_bytes if self.pose_sprite else 0,
                "part_renderer": self.part_sprite.report() if self.part_sprite else None,
                "player_pipeline": self.player_pipeline,
                "surface_renderer": self.pose_sprite.surface_parts.report()
                                    if self.pose_sprite and self.pose_sprite.surface_parts else None,
                "upper_lower": self.config.get("upper_lower"),
                "texture_quality": self.game_settings.texture_quality,
                "shadow_scale": self.game_settings.shadow_scale,
                "upscale_aa": self.game_settings.upscale_aa,
                "sword_effects": self.config.get("sword_effects"), "target_hits": self.target_hits,
                "camera_impact": self.config.get("camera_impact", {}),
                "overdrive_rainbow": self.overdrive_rainbow,
                "rainbow_cycle_seconds": self.rainbow_cycle_seconds,
                "loading": self.loading_trace,
                "audio": {"play_counts": self.sound_player.play_counts,
                          "layer_counts": self.sound_player.layer_counts,
                          "dropped_layers": self.sound_player.dropped_layers,
                          "conversion_max_ms": self.sound_player.conversion_max_ms,
                          "disabled_reason": self.sound_player.disabled_reason} if self.sound_player else None,
                "gpu_cached_clips": [(sprite.cached_clip_count if hasattr(sprite, "cached_clip_count") else len(sprite.interpolator.clip_cache))
                                     for sprite in dict.fromkeys((self.motion_sprite, self.attack_sprite)) if sprite],
                "trace": self.trace}, ensure_ascii=False, indent=2), encoding="utf-8")
        for resource in (self.sound_player, self.gun_renderer, self.sword_renderer, self.ground_effect_renderer, self.motion_sprite, self.attack_sprite, self.pose_sprite, self.part_sprite, self.shadow_blend, self.ground, *self.sprites, self.hud or self.renderer):
            if resource is not None:
                resource.close()
        if self.profile_path:
            self.timings.write_json(self.profile_path)
