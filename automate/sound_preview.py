"""게임과 동일한 실시간 레이어 혼합 결과를 창 없이 WAV로 기록한다."""

import argparse
from array import array
from ctypes import string_at
import json
import os
from pathlib import Path
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]


def record(pico, player, path, schedule, duration_seconds):
    if player.bank.get("hit_metal", {}).get("replaces_hit") is True:
        metal_times = {time for time, kind, _ in schedule if kind == "hit_metal"}
        schedule = [row for row in schedule if not (row[1] == "hit" and row[0] in metal_times)]
    blocks = []
    captured_frames = 0

    @pico.mix_func
    def capture(_, stream, length):
        nonlocal captured_frames
        blocks.append(string_at(stream, length))
        captured_frames += length // 4

    player.reset()
    pico.Mix_SetPostMix(capture, None)
    previous, index = 0.0, 0
    try:
        # 기록한 샘플 시각을 사용해 부하가 커져도 청취 구간이 짧아지지 않게 한다.
        while (now := captured_frames/44100) < duration_seconds:
            player.update(now-previous)
            previous = now
            while index < len(schedule) and schedule[index][0] <= now:
                _, kind, options = schedule[index]
                if kind == "scrape_on":
                    player.set_loop("scrape", True)
                elif kind == "scrape_off":
                    player.set_loop("scrape", False)
                elif kind in ("loop_on", "loop_off"):
                    player.set_loop(options["event"], kind == "loop_on")
                else:
                    if options.get("fixed_variation"):
                        player.random.seed(31)
                        player.previous_choices.clear()
                        options = {key: value for key, value in options.items() if key != "fixed_variation"}
                    player.play(kind, **options)
                index += 1
            pico.SDL_Delay(2)
    finally:
        pico.Mix_SetPostMix(pico.mix_func(), None)
        player.stop()
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = b"".join(blocks)[:round(duration_seconds*44100)*4]
    with wave.open(str(path), "wb") as output:
        output.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        output.writeframes(pcm)
    samples = array("h", pcm)
    return {"file": str(path), "peak": max(map(abs, samples), default=0),
            "clipped_samples": sum(abs(value) >= 32767 for value in samples),
            "seconds": len(samples)/88200}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/runtime/audio/training_cc0_v1")
    parser.add_argument("--output", type=Path, default=ROOT / "output/audio/cc0_review")
    parser.add_argument("--only", choices=("all", "mobility", "boost", "attacks", "contact", "gun", "gun-contact", "gun-explosion"), default="all")
    parser.add_argument("--channels", type=int, default=24, help="효과음 동시 재생 채널 수")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pico2d.pico2d as pico
    from ferrial_drive.audio.effects import PicoSoundEffects

    pico.SDL_Init(pico.SDL_INIT_AUDIO)
    if pico.Mix_OpenAudio(44100, pico.AUDIO_S16SYS, 2, 1024) < 0:
        raise OSError("청취 파일용 믹서 초기화 실패")
    pico.audio_on = True
    player = PicoSoundEffects(pico, ROOT / "samples/sound_effects/sound_bank.json", args.directory, channels=args.channels,
                              user_bank=ROOT / "data/runtime/audio/user_audio/bank.json")
    try:
        if player.disabled_reason:
            raise OSError(player.disabled_reason)
        if args.only == "gun-explosion":
            if "gun_explosion" not in player.bank:
                raise ValueError("Overdrive 폭발음을 먼저 연결한다.")
            movement = json.loads((ROOT / "samples/sword_movement/movement_config.json").read_text(encoding="utf-8-sig"))
            player.set_rate_multiplier(movement.get("overdrive", {}).get("pitch_scale", 1.1))
            single = [(0.2, "gun_explosion", {})]
            schedule = []
            for index in range(30):
                time = .2 + index / 30
                schedule.extend([(time, "gun_fire", {}), (time + .03, "gun_explosion", {})])
            report = {"single": record(pico, player, args.output / "energy_explosion_single.wav", single, 2.4),
                      "overdrive": record(pico, player, args.output / "energy_explosion_overdrive.wav", schedule, 3.2)}
            report.update(play_counts=player.play_counts, layer_counts=player.layer_counts,
                          dropped_layers=player.dropped_layers, channels=args.channels)
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "gun-contact":
            if any(name not in player.bank for name in ("gun_fire", "gun_hit", "gun_hit_metal")):
                raise ValueError("총 발사음·기본 명중음·금속 명중음을 먼저 연결한다.")
            single = [(0.2, "gun_fire", {}), (.23, "gun_hit", {}),
                      (1.5, "gun_fire", {}), (1.53, "gun_hit", {}), (1.53, "gun_hit_metal", {})]
            report = {"single": record(pico, player, args.output / "gun_hit_materials.wav", single, 3.0)}
            for label, rpm in (("900rpm", 900), ("overdrive_1800rpm", 1800)):
                schedule = []
                for index in range(rpm // 60):
                    time = .2 + index * 60 / rpm
                    schedule.extend([(time, "gun_fire", {}), (time + .03, "gun_hit", {}),
                                     (time + .03, "gun_hit_metal", {})])
                report[label] = record(pico, player, args.output / f"gun_metal_hits_{label}.wav", schedule, 2.6)
            report.update(play_counts=player.play_counts, layer_counts=player.layer_counts,
                          dropped_layers=player.dropped_layers, channels=args.channels)
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "boost":
            report = {"boost": record(pico, player, args.output / "jet_boost_preview.wav",
                                      [(0.2, "boost", {})], 3.0),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "gun":
            if any(name not in player.bank for name in ("gun_fire", "gun_empty")):
                raise ValueError("총 발사음과 빈 탄창 음원을 sound-import로 먼저 연결한다.")
            report = {"single": record(pico, player, args.output / "gun_single.wav",
                                       [(0.2, "gun_fire", {})], 3.0),
                      "burst_900rpm": record(pico, player, args.output / "gun_burst_900rpm.wav",
                          [(0.2 + index / 15, "gun_fire", {}) for index in range(15)] +
                          [(2.0, "gun_empty", {}), (2.3, "gun_empty", {})], 4.0),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "contact":
            schedule = [(0.2, "swing_1", {}), (1.1, "hit", {}),
                        (2.0, "hit", {}), (2.0, "hit_metal", {}),
                        (3.0, "swing_3", {}), (3.13, "hit", {}), (3.13, "hit_metal", {})]
            report = {"contact": record(pico, player, args.output / "miss_stop_metal_thrust.wav", schedule, 4),
                      "metal_repeated": record(pico, player, args.output / "metal_hits_repeated.wav",
                          [(time, kind, {}) for time in (.2,.48,.76,1.04) for kind in ("hit", "hit_metal")], 2.6),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "attacks":
            motion = json.loads((ROOT / "samples/sound_effects/sound_bank.json").read_text(encoding="utf-8"))["motion"]
            schedule = []
            for index, time in enumerate((.3, 1.1, 1.9, 2.7), 1):
                if index == 4:
                    schedule.extend([(time, f"swing_{index}", {"energy_level": 1}),
                                     (time + .07, "step", {"gain": motion["attack_step_gain"]})])
                else:
                    schedule.extend([(time, "step", {"gain": motion["attack_step_gain"]}),
                                     (time + .07, f"swing_{index}", {"energy_level": 1})])
            report = {"attacks": record(pico, player, args.output / "attack_steps.wav", schedule, 3.8),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "boost":
            report = {"boost": record(pico, player, args.output / "boost.wav", [(0.2, "boost", {})], 1.4),
                      "repeated": record(pico, player, args.output / "boost_repeated.wav",
                          [(time, "boost", {}) for time in (0.2, 0.48, 0.76, 1.04)], 2.4),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        if args.only == "mobility":
            report = {"boost": record(pico, player, args.output / "boost.wav", [(0.2, "boost", {})], 1.4),
                      "slide": record(pico, player, args.output / "slide_continuous.wav",
                          [(0.1, "scrape_on", {}), (12.7, "scrape_off", {})], 13.0),
                      "dash_boost": record(pico, player, args.output / "dash_boost_comparison.wav",
                          [(0.2, "scrape_on", {}), (0.2, "dash_ignite", {}), (0.2, "loop_on", {"event":"dash_jet"}),
                           (5.1, "loop_off", {"event":"dash_jet"}), (5.1, "scrape_off", {}),
                           (5.9, "boost", {}), (7.0, "boost", {}), (7.28, "boost", {})], 8.7),
                      "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                      "dropped_layers": player.dropped_layers}
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        levels = []
        for level in (1, 2, 3):
            levels.extend([(0.3+(level-1)*1.8, "swing_1", {"energy_level": level, "fixed_variation": True}),
                           (1.0+(level-1)*1.8, "hit", {"energy_level": level, "fixed_variation": True})])
        movement = [(time, "step", {}) for time in (0.2, 0.55, 0.9, 1.25)]
        movement += [(1.7, "scrape_on", {})]
        movement += [(time, "pebble", {}) for time in (1.8, 1.97, 2.19, 2.35, 2.57, 2.73, 2.96)]
        movement += [(3.2, "scrape_off", {}), (3.9, "boost", {})]
        report = {"levels": record(pico, player, args.output / "levels_1_2_3.wav", levels, 5.8),
                  "combos": record(pico, player, args.output / "combos_1_2_3_4.wav",
                      [(time, f"swing_{index}", {"energy_level": 1})
                       for index, time in enumerate((0.25, 0.9, 1.8, 2.5), 1)], 3.3),
                  "movement": record(pico, player, args.output / "run_scrape_boost.wav", movement, 4.6),
                  "special": record(pico, player, args.output / "counter_ultimate.wav",
                      [(0.2, "counter", {}), (2.3, "ultimate", {})], 4.5) if "counter" in player.bank else None,
                  "play_counts": player.play_counts, "layer_counts": player.layer_counts,
                  "conversion_max_ms": player.conversion_max_ms, "dropped_layers": player.dropped_layers}
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        player.close()
        pico.Mix_CloseAudio()
        pico.SDL_QuitSubSystem(pico.SDL_INIT_AUDIO)


if __name__ == "__main__":
    main()
