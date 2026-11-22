"""하한 사양 기능·자원 제한 벤치마크
Windows 자식 프로세스에 CPU·커밋 메모리 제한을 적용하고 FHD 최소 60FPS·권장 165FPS 예산을 측정한다.
기본은 직접 조작이며 --scenario combat으로 다수 적 교전을 측정한다. UHD 630 처리량을 에뮬레이션하지 않는다.
Runner에서 Combat·Movement를 선택하고 창을 닫으면 성능 보고서를 저장한다.
"""

from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[1]
UNIT_TEST_ENTRYPOINT = "standalone"
UNIT_TEST_SUPPORTS_MUTE = True
UNIT_TEST_PRESETS = (
    {"id": "combat", "label": "Combat · 2 GiB 제한", "args": ["--scenario", "combat", "--detail"]},
    {"id": "movement", "label": "Movement · 이동·검 훈련장", "args": ["--scenario", "sword", "--detail"]},
    {"id": "combat_native", "label": "Combat · 실기 제한 없음",
     "args": ["--scenario", "combat", "--detail", "--gpu-profile", "none", "--no-resource-limits"]},
    {"id": "crowd_1000", "label": "Combat · 1,000기 · HP 10만",
     "args": ["--scenario", "combat", "--enemy-count", "1000", "--enemy-spacing-m", "24", "--player-hp", "100000",
              "--gpu-profile", "none", "--no-resource-limits"]},
)


def prepare_auto_cycle(program, *, weapon="sword", overdrive=False, dash=False):
    """게임의 초기화·무장 전환·강제 발동 경로로 반복 입력을 준비한다."""
    program.reset()
    program.set_energy_level(3)
    if weapon == "smg":
        program.perform_hud_action("swap")
    if overdrive:
        program.perform_hud_action("overdrive")
    program.mouse = (program.window_size[0] * .8, program.window_size[1] * .5)
    program.attack_held = True
    if dash:
        program.keys.update(("d", "left_shift"))


def aim_at_enemy(program):
    """실제 살아 있는 적 중 가장 가까운 적을 마우스 조준점으로 선택한다."""
    encounter = getattr(program, "encounter", None)
    if encounter is None:
        return
    alive = [enemy for enemy in encounter.enemies.values() if enemy.alive]
    if alive:
        px, py = program.controller.position_m
        enemy = min(alive, key=lambda row: (row.position_m.x - px)**2 + (row.position_m.y - py)**2)
        x, y = program.projection.project((enemy.position_m.x, enemy.position_m.y))
        program.mouse = program.camera.world_to_screen((x, y - enemy.profile.height_pixels))


def run_worker(args, applied, profile):
    # 부모가 제한 적용을 확인한 뒤에만 게임·Pico2D 모듈을 가져온다.
    from contextlib import nullcontext
    import ctypes as ct
    from dataclasses import asdict, replace
    from time import perf_counter
    from ferrial_drive.combat.movement_application import MovementApplication
    from ferrial_drive.combat.encounter_application import EncounterApplication
    from ferrial_drive.diagnostics.render_breakdown import RenderBreakdown
    from ferrial_drive.diagnostics.frame_benchmark import benchmark_program
    from ferrial_drive.diagnostics.gpu_profile import Uhd630Profile
    from ferrial_drive.diagnostics.texture_metrics import ProcessGpuMemory, bind_gl, process_memory
    from ferrial_drive.rendering import PicoCanvas
    from ferrial_drive.settings import GameSettingsStore

    args.output.mkdir(parents=True, exist_ok=True)
    # 저장된 설정을 격리 복사한다. 품질 이름을 특정 해상도로 가정하지 않는다.
    settings_path = args.output / "settings.json"
    initial_settings = GameSettingsStore().load()
    if args.quality is not None:
        initial_settings = replace(initial_settings, texture_quality=args.quality)
    GameSettingsStore(settings_path).save(initial_settings)
    application_type = EncounterApplication if args.scenario == "combat" else MovementApplication
    encounter_options = (dict(encounter_path=args.encounter, enemy_count=args.enemy_count,
                              enemy_spacing_m=args.enemy_spacing_m, player_hp=args.player_hp,
                              crowd_atlas_enabled=not args.legacy_enemy_render) if args.scenario == "combat" else {})
    app = application_type(args.config, demo=args.demo or args.scenario == "demo", settings_file=settings_path,
                           profile=args.output / "timings.json", movement_speed_multiplier=args.movement_speed_multiplier,
                           mute=args.mute, player_pipeline=args.player_pipeline, **encounter_options)
    if list(app.window_size) != profile["resolution"]:
        raise ValueError("프로필과 훈련장 설정의 출력 해상도가 다르다.")
    gpu_memory = ProcessGpuMemory()
    result = {"status": "error", "scenario": args.scenario, "profile": profile, "resources_applied": applied,
              "python": sys.version, "resolution": app.window_size, "input_mode": "auto" if args.auto else "interactive",
              "measured_at": datetime.now().astimezone().isoformat(),
              "audio_muted": args.mute, "player_pipeline": app.player_pipeline, "command": sys.argv[1:], "movement_speed_multiplier": args.movement_speed_multiplier,
              "demo": app.demo,
              "instrumentation": {"detailed": args.detail, "call_profile": args.call_profile},
              "auto_input": {"weapon": args.auto_weapon, "overdrive": args.auto_overdrive, "dash": args.auto_dash,
                             "reset_seconds": 2, "aim": "nearest_alive" if args.scenario == "combat" else "fixed"}
                            if args.auto else None,
              "host": {"platform": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count()},
              "limitations": "실기 성능 보정 없음. 현재 설정의 적 수만 측정하며 UHD 630 처리량·메모리 대역폭 재현 없음."}
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            result["host"]["processor_name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    try:
        with PicoCanvas(*app.window_size, "Ferrial Drive | Hardware benchmark", vsync=False) as canvas:
            guard = None if args.gpu_profile == "none" else Uhd630Profile(canvas.pico)
            with guard if guard else nullcontext():
                query = bind_gl(canvas.pico, "glGetString", ct.c_char_p, [ct.c_uint])
                result["actual_gl"] = {name: query(enum).decode(errors="replace") for name, enum in
                                       (("vendor", 0x1F00), ("renderer", 0x1F01), ("version", 0x1F02))}
                result["renderer"] = asdict(canvas.info)
                enemy_samples = []

                def sample_enemy_textures(frame, phase):
                    view = getattr(app, "encounter_view", None)
                    if view is None:
                        return
                    sprites = view.sprites.values()
                    caches = [sprite.resource.cache for sprite in sprites if sprite.part_counts]
                    enemy_samples.append({"frame": frame, "phase": phase,
                        "enemy_pbr_gpu_allocated_bytes": sum(cache.gpu_storage_bytes + cache.pooled_bytes for cache in caches),
                        "enemy_pbr_uploaded_bytes": sum(cache.uploaded_bytes for cache in caches),
                        "enemy_pose_cache_bytes": sum(sprite.pose_cache.bytes for sprite in sprites if sprite.pose_cache),
                        "enemy_crowd_atlas_bytes": view.crowd_atlas.bytes if view.crowd_atlas else 0})

                commit_limit = applied.get("process_memory_limit_bytes", 0)
                reserve = min(128 * 1024**2, commit_limit // 16)

                def within_commit_budget(frame):
                    committed = process_memory().get("private_bytes")
                    if committed is None or committed < commit_limit - reserve:
                        return True
                    result["memory_stop"] = {"frame": frame, "commit_bytes": committed,
                                             "limit_bytes": commit_limit, "reserve_bytes": reserve}
                    return False

                started = perf_counter()
                probe = call_profile = None
                collection = app.prepare_combat_collection() if args.scenario == "combat" else None
                try:
                    app.enter()
                    width, height = ct.c_int(), ct.c_int()
                    if canvas.pico.SDL_GetRendererOutputSize(canvas.pico.renderer, ct.byref(width), ct.byref(height)) != 0:
                        raise RuntimeError("실제 출력 해상도 조회 실패")
                    result["logical_resolution"] = list(app.window_size)
                    result["resolution"] = [width.value, height.value]
                    result["resolution_initial"] = list(result["resolution"])
                    result["load_seconds"] = perf_counter() - started
                    result["process_after_load"] = process_memory()
                    sample_enemy_textures(None, "after_load")
                    result["settings"] = asdict(app.game_settings)
                    result["baked_shadow_texture_bytes"] = sum(
                        width * height for resource in app.sprites if "shadow" in resource.alpha_layers
                        for width, height in (resource.texture_sizes["shadow"],))
                    player_sheets = set(app.clip_resources.values()) | set(app.attack_resources.values())
                    result["player_sheet_texture_bytes"] = sum(resource.estimated_bytes for resource in player_sheets)
                    result["player_auxiliary_sheet_texture_bytes"] = sum(
                        resource.estimated_bytes for resource in app.sprites if resource not in player_sheets)
                    if app.pbr_enabled and any("body" in resource.texture_sizes for resource in player_sheets):
                        raise RuntimeError("PBR 시험에서 기존 플레이어 시트가 적재됐다.")
                    result["config_snapshot"] = json.loads(json.dumps({"movement": app.config, "hud": app.hud.config.data}))
                    if args.scenario == "combat":
                        result["player_health_initial"] = asdict(app.controller.health)
                        result["config_snapshot"]["encounter"] = app.encounter.settings
                        result["enemy_atlas_sources"] = {
                            kind: str(sprite.resource.source) for kind, sprite in app.encounter_view.sprites.items()
                            if sprite.part_counts
                        }
                    result["atlas_divisor_after_load"] = (app.motion_sprite.resource.data.get("divisor")
                        if app.motion_sprite is not None and hasattr(app.motion_sprite, "resource") else None)
                    if not app.demo and app.part_sprite is None:
                        raise RuntimeError("실제 검 이동 아틀라스가 연결되지 않았다.")
                    if args.call_profile:
                        import cProfile
                        call_profile = cProfile.Profile()

                    def step(program, index, measurement_start):
                        probe.active = False
                        if index % 30 == 0:
                            sample_enemy_textures(index, "warmup" if index < args.warmup else "measurement")
                        if measurement_start and call_profile:
                            call_profile.enable()
                        if args.auto and (index == 0 or measurement_start or
                                (index > args.warmup and (index-args.warmup) % round(2*args.target_fps) == 0)):
                            prepare_auto_cycle(program, weapon=args.auto_weapon, overdrive=args.auto_overdrive, dash=args.auto_dash)
                        if args.auto:
                            aim_at_enemy(program)
                        # 초기화·조준은 events_ms에 포함하고 update 구간 계측에서는 제외한다.
                        probe.step(index >= args.warmup)

                    def status(values=None):
                        mode = "자동 측정" if args.auto else "직접 조작"
                        title = ["Ferrial Drive", mode]
                        if values is not None:
                            title.append(f"{values['fps']:.1f}/{args.target_fps:g} FPS")
                        resource_samples = result.get("resource_samples")
                        sample = (resource_samples[-1] if resource_samples else
                                  {"ram": process_memory(), "vram": gpu_memory.sample(), "dxgi": {}})
                        ram = sample["ram"].get("working_set_bytes")
                        title.append(f"RAM {ram / 2**20:.0f} MiB" if ram is not None else "RAM 미측정")
                        dedicated = sample["vram"].get("dedicated_bytes")
                        shared = sample["vram"].get("shared_bytes")
                        local = sample["dxgi"].get("local_bytes")
                        if dedicated is not None:
                            title.append(f"GPU 전용 {dedicated / 2**20:.0f} MiB")
                        if shared is not None:
                            title.append(f"GPU 공유 {shared / 2**20:.0f} MiB")
                        if dedicated is None and shared is None:
                            title.append(f"GPU 로컬 {local / 2**20:.0f} MiB" if local is not None else "GPU 메모리 미측정")
                        if values is not None:
                            title.extend((f"HUD {probe.latest_ms.get('hud.total', 0):.2f}ms",
                                          f"World {probe.latest_ms.get('world.total', 0):.2f}ms"))
                        if values is None or values["warming_up"]:
                            title.append("준비 중")
                        canvas.pico.SDL_SetWindowTitle(canvas.pico.window, " | ".join(title).encode("utf-8"))

                    status()
                    comparisons = []
                    ground_random = getattr(app.ground_effects, "random", None)
                    ground_random_state = ground_random.getstate() if ground_random is not None else None
                    variants = args.compare or [args.variant]
                    rounds = args.rounds if args.compare else 1
                    for repeat in range(rounds):
                        order = list(reversed(variants)) if repeat % 2 else variants
                        for variant in order:
                            probe = RenderBreakdown(app, detailed=args.detail, variant=variant)
                            try:
                                probe.install()
                                if args.auto:
                                    app.paused = False
                                    if ground_random is not None:
                                        ground_random.setstate(ground_random_state)
                                result["benchmark"] = benchmark_program(app, canvas, target_fps=args.target_fps,
                                    frames=args.frames, warmup=args.warmup, paced=not args.unpaced, before_step=step,
                                    interactive=not args.auto, on_status=status,
                                    should_continue=within_commit_budget if commit_limit else None)
                                if "memory_stop" in result:
                                    result["benchmark"].update(completed=False, target_met=False, all_work_within_budget=False)
                                if app.sword_renderer:
                                    result["trail_backend_requested"] = app.sword_renderer.trail_backend
                                    result["trail_backend"] = app.sword_renderer.last_trail_backend
                                    result["trail_fallback"] = app.sword_renderer.compute_unavailable
                                if app.sword_effects:
                                    result["hitbox_type"] = app.sword_effects.hitbox_type
                            finally:
                                if call_profile:
                                    call_profile.disable()
                                probe.active = False
                                result["draw_breakdown"] = probe.report()
                                probe.close()
                                probe = None
                            if args.compare:
                                row = {"round": repeat+1, "variant": variant, "benchmark": result["benchmark"],
                                       "hitbox_type":result.get("hitbox_type"),
                                       "draw_breakdown": result["draw_breakdown"],
                                       "trail_backend": ("disabled" if variant=="no_trail" else app.sword_renderer.last_trail_backend)
                                           if app.sword_renderer else None,
                                       "trail_fallback": app.sword_renderer.compute_unavailable if app.sword_renderer else None}
                                comparisons.append(row)
                                with (args.output / "progress.jsonl").open("a", encoding="utf-8") as stream:
                                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                                print(json.dumps({"round": repeat+1, "variant": variant,
                                    "work_ms": result["benchmark"]["work_ms"]}, ensure_ascii=False), flush=True)
                            if not result["benchmark"]["completed"]:
                                break
                        if not result["benchmark"]["completed"]:
                            break
                    if args.compare:
                        result["comparisons"] = comparisons
                    result["gpu_memory"] = gpu_memory.sample()
                    sample_enemy_textures(None, "after_benchmark")
                    if enemy_samples:
                        result["enemy_texture_samples"] = enemy_samples
                    result["settings_final"] = asdict(app.game_settings)
                    if canvas.pico.SDL_GetRendererOutputSize(canvas.pico.renderer, ct.byref(width), ct.byref(height)) != 0:
                        raise RuntimeError("최종 출력 해상도 조회 실패")
                    result["resolution"] = [width.value, height.value]
                    result["resolution_changed"] = result["resolution"] != result["resolution_initial"]
                    result["status"] = "completed" if result["benchmark"]["completed"] else "interrupted"
                    if "memory_stop" in result:
                        result["status"] = "memory_limit"
                finally:
                    if call_profile:
                        call_profile.disable()
                        call_profile.dump_stats(str(args.output / "calls.prof"))
                    if probe:
                        probe.active = False
                        result["draw_breakdown"] = probe.report()
                        probe.close()
                    try:
                        try:
                            app.exit()
                        finally:
                            app = surface = None
                        if collection:
                            collection.finish()
                    finally:
                        if collection:
                            collection.restore()
                    if guard:
                        result["gpu_profile"] = guard.report()
                        if guard.violations:
                            result["status"] = "feature_violation"
                            if "benchmark" in result:
                                result["benchmark"]["target_met"] = False
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        gpu_memory.close()
        (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {"status": result["status"], "report": str(args.output / "report.json"),
               **{key: result["benchmark"][key] for key in
                  ("observed_fps", "work_ms", "deadline_miss_percent", "target_met")}}
    print(json.dumps(compact, ensure_ascii=False), flush=True)
    if result["status"] == "memory_limit":
        stop = result["memory_stop"]
        print(f"커밋 메모리 상한에 가까워 측정을 중단했다. "
              f"{stop['commit_bytes'] / 2**20:.0f}/{stop['limit_bytes'] / 2**20:.0f} MiB · 보고서 저장 완료", flush=True)
    return 0 if result["status"] == "completed" else 2


def main():
    sys.path.insert(0, str(ROOT))
    from ferrial_drive.diagnostics.resource_limits import ResourceLimits, run_gated_child, wait_for_limits
    from ferrial_drive.diagnostics.render_breakdown import VARIANTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "samples/hardware_profile_benchmark/profile.json")
    parser.add_argument("--config", type=Path, default=ROOT / "samples/sword_movement/movement_config.json")
    parser.add_argument("--scenario", choices=("demo", "sword", "combat"), default="sword")
    parser.add_argument("--mute", action="store_true", help="효과음 없이 실행")
    parser.add_argument("--player-pipeline", choices=("baked", "pbr"))
    parser.add_argument("--enemy-count", type=int, help="플레이어 주위에 배치할 교전 부하 시험 적 수")
    parser.add_argument("--legacy-enemy-render", action="store_true", help="고정 군집 아틀라스 이전 경로로 교전한다.")
    parser.add_argument("--enemy-spacing-m", type=float, default=12, help="부하 시험 격자의 중심 간격(m)")
    parser.add_argument("--player-hp", type=int, help="부하 시험 중 조기 패배를 방지할 시작 HP")
    parser.add_argument("--encounter", type=Path, default=ROOT / "samples/combat_test_v1_5/encounter.json",
                        help="combat test의 적 종류·배치·전투 설정")
    parser.add_argument("--demo", action="store_true", help="combat에서도 플레이어를 공개 도형으로 시연")
    parser.add_argument("--movement-speed-multiplier", type=float, default=1, help="3배속 combat test는 3 지정")
    parser.add_argument("--quality", choices=("low", "medium", "high"), help="생략하면 현재 저장 설정을 격리 복사")
    parser.add_argument("--auto", action="store_true", help="고정 입력 반복 공격. 생략하면 직접 조작")
    parser.add_argument("--auto-weapon", choices=("sword", "smg"), default="sword")
    parser.add_argument("--auto-overdrive", action="store_true", help="자동 반복마다 Overdrive 강제 발동")
    parser.add_argument("--auto-dash", action="store_true", help="자동 반복에 오른쪽 대시를 유지해 지면 효과 부하 재현")
    parser.add_argument("--frames", type=int, help="측정 프레임 수. 직접 조작은 생략하면 창을 닫을 때까지 실행")
    parser.add_argument("--detail", action="store_true", help="HUD·월드 세부 구간과 SDL 호출 수 계측")
    parser.add_argument("--variant", choices=VARIANTS, default="baseline", help="진단 프로세스에만 적용하는 표시 생략 대조")
    parser.add_argument("--compare", choices=VARIANTS, nargs="+", help="한 번 불러온 같은 장면에서 조건별 자동 대조")
    parser.add_argument("--rounds", type=int, default=2, help="조건 대조 반복 횟수. 회차마다 역순으로 실행")
    parser.add_argument("--call-profile", action="store_true", help="측정 구간 Python 호출을 calls.prof로 저장")
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--target-fps", type=float)
    parser.add_argument("--cpu-percent", type=float)
    parser.add_argument("--logical-cpus", type=int)
    parser.add_argument("--memory-mib", type=int)
    parser.add_argument("--gpu-profile", choices=("none", "uhd630_gl45_conservative"))
    parser.add_argument("--no-resource-limits", action="store_true")
    parser.add_argument("--unpaced", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from math import isfinite
    if args.enemy_count is not None and (args.scenario != "combat" or args.enemy_count < 1):
        parser.error("--enemy-count에는 combat 장면과 양수 적 수가 필요하다.")
    if not isfinite(args.enemy_spacing_m) or args.enemy_spacing_m <= 0:
        parser.error("--enemy-spacing-m는 양수 유한 거리여야 한다.")
    if args.player_hp is not None and (args.scenario != "combat" or args.player_hp < 1):
        parser.error("--player-hp에는 combat 장면과 양수 HP가 필요하다.")
    if not isfinite(args.movement_speed_multiplier) or args.movement_speed_multiplier <= 0:
        parser.error("이동 배율은 양수 유한값이어야 한다.")
    if not args.auto and (args.auto_weapon != "sword" or args.auto_overdrive or args.auto_dash):
        parser.error("--auto-weapon과 --auto-overdrive에는 --auto가 필요하다.")
    if args.compare and (not args.auto or args.call_profile or args.rounds < 1):
        parser.error("--compare는 --auto와 양수 --rounds가 필요하며 --call-profile과 분리한다.")
    applied = wait_for_limits() if args.worker else None
    if args.auto and args.frames is None:
        args.frames = 600
    profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
    args.target_fps = profile["target_fps"] if args.target_fps is None else args.target_fps
    args.gpu_profile = profile["gpu_profile"] if args.gpu_profile is None else args.gpu_profile
    if args.gpu_profile not in ("none", "uhd630_gl45_conservative"):
        parser.error("지원하지 않는 GPU 프로필")
    values = dict(profile["resource_limits"])
    for key in ("cpu_percent", "logical_cpus", "memory_mib"):
        if getattr(args, key) is not None:
            values[key] = getattr(args, key)
    limits = None if args.no_resource_limits else ResourceLimits(**values)
    profile.update(resource_limits=values, resource_limits_enabled=not args.no_resource_limits,
                   target_fps=args.target_fps, gpu_profile=args.gpu_profile)
    if args.worker:
        return run_worker(args, applied, profile)
    if (args.frames is not None and args.frames < 1) or args.warmup < 0 or not 0 < args.target_fps <= 10000:
        parser.error("프레임 수·목표 FPS 범위 오류")
    args.output = (args.output or ROOT / "output/performance/hardware_profile" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")).resolve()
    # 기존 결과가 있으면 덮어쓰지 않는다.
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker", "--output", str(args.output)]
    code, final = run_gated_child(command, cwd=ROOT, limits=limits, timeout_seconds=300 if args.auto else None)
    (args.output / "limits_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (args.output / "report.json").is_file():
        (args.output / "report.json").write_text(json.dumps({"status": "error", "child_exit_code": code,
            "error": "측정을 시작하기 전에 자식 실행이 실패했다. 콘솔 오류를 확인한다."}, ensure_ascii=False, indent=2), encoding="utf-8")
    from ferrial_drive.diagnostics.benchmark_report import write_report
    write_report(args.output / "report.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
