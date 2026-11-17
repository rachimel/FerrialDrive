"""사용자가 선택한 음원을 검사하고 원본·출처를 보존해 게임용 WAV로 연결한다."""

import argparse
from array import array
from ctypes import string_at
from hashlib import sha256
from math import isfinite
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from automate.sound_effects import SAMPLE_RATE, write_wav


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--kind", choices=("swing", "counter", "ultimate", "boost", "hit_metal", "gun_fire", "gun_empty", "gun_explosion"))
    parser.add_argument("--preserve-source", action="store_true", help="구간·음량을 가공하지 않고 원본을 직접 연결한다.")
    parser.add_argument("--trim-only", action="store_true", help="정규화·끝 페이드 없이 선택 구간을 추출하고 앞 3ms만 페이드한다.")
    parser.add_argument("--event-volume", type=float, default=.9, help="단일 사건 음량 배율 0~1. 휘두르기 교체에는 사용하지 않는다.")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--inspect-output", type=Path, help="검사용 원본 PCM WAV 출력")
    parser.add_argument("--processing", type=Path, help="선택 음원 가공 설정 JSON")
    parser.add_argument("--split", action="store_true", help="휘두르기 묶음을 무음 구간으로 분리")
    parser.add_argument("--regions", type=Path, help="초 단위 [시작, 끝] 목록 JSON으로 여러 샘플을 준비한다.")
    parser.add_argument("--attack-index", type=int, choices=(1, 2, 3, 4),
                        help="해당 콤보 타수에 편집 원본을 직접 지정")
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--end-seconds", type=float)
    args = parser.parse_args()
    if not isfinite(args.event_volume) or not 0 <= args.event_volume <= 1:
        parser.error("사건 음량 배율은 0~1의 유한값이어야 한다.")
    if args.kind == "swing" and args.event_volume != .9:
        parser.error("휘두르기 교체의 음량은 타수별 bank에서 설정한다.")
    if args.preserve_source and (args.split or args.start_seconds != 0 or args.end_seconds is not None
                                 or args.processing is not None or args.attack_index is not None or args.regions or args.trim_only):
        parser.error("원본 직접 연결은 분리·구간 지정·가공·타수 지정과 함께 사용하지 않는다.")
    if args.trim_only and (args.processing is not None or args.attack_index is not None):
        parser.error("구간 단순 추출은 가공 설정·타수 직접 지정과 함께 사용하지 않는다.")
    if args.regions and (args.split or args.start_seconds != 0 or args.end_seconds is not None
                         or args.attack_index is not None):
        parser.error("구간 목록은 자동 분리·단일 구간·타수 지정과 함께 사용하지 않는다.")
    if not args.inspect and not args.kind:
        parser.error("저장할 음원의 --kind가 필요하다.")
    if args.attack_index is not None and (args.kind != "swing" or args.split or
            args.start_seconds != 0 or args.end_seconds is not None or args.processing is not None):
        parser.error("타수 지정은 swing 원본에만 사용하며 분리·구간 지정과 함께 사용하지 않는다.")
    source = args.source.resolve()
    payload = source.read_bytes()
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pico2d.pico2d as pico
    pico.SDL_Init(pico.SDL_INIT_AUDIO)
    pico.Mix_Init(pico.MIX_INIT_MP3 | pico.MIX_INIT_OGG)
    if pico.Mix_OpenAudio(SAMPLE_RATE, pico.AUDIO_S16SYS, 1, 1024) < 0:
        raise OSError("음원 변환기 초기화 실패")
    pico.audio_on = True
    try:
        sound = pico.load_wav(str(source))
        pcm = array("h", string_at(sound.wav.contents.abuf, sound.wav.contents.alen))
        del sound
    finally:
        pico.Mix_CloseAudio()
        pico.SDL_QuitSubSystem(pico.SDL_INIT_AUDIO)
    if sys.byteorder != "little":
        pcm.byteswap()
    duration = len(pcm)/SAMPLE_RATE
    if args.inspect:
        if args.inspect_output:
            write_wav(args.inspect_output, [value/32768 for value in pcm])
        hop = round(SAMPLE_RATE*0.1)
        print(json.dumps({"file": source.name, "duration_seconds": duration,
            "sha256": sha256(payload).hexdigest(),
            "rms_100ms": [round((sum(v*v for v in pcm[i:i+hop])/len(pcm[i:i+hop]))**0.5)
                           for i in range(0, len(pcm), hop)]}, indent=2))
        return
    end = args.end_seconds if args.end_seconds is not None else duration
    if not 0 <= args.start_seconds < end <= duration+0.001:
        parser.error("구간은 원본의 초 단위 범위 안에 있어야 한다.")
    if args.split and args.kind != "swing":
        parser.error("무음 분리는 휘두르기 묶음에만 사용한다.")
    if args.split and (args.start_seconds != 0 or args.end_seconds is not None):
        parser.error("무음 분리와 구간 지정은 함께 사용하지 않는다.")
    regions = [(args.start_seconds, end)]
    if args.regions:
        regions = json.loads(args.regions.read_text(encoding="utf-8-sig"))
        if not isinstance(regions, list) or not regions:
            parser.error("구간 목록은 비어 있지 않은 배열이어야 한다.")
        previous_end = 0
        for region in regions:
            if (not isinstance(region, list) or len(region) != 2
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not isfinite(value) for value in region)
                    or not previous_end <= region[0] < region[1] <= duration + .001):
                parser.error("구간은 원본 범위 안에서 겹치지 않는 오름차순 [시작, 끝]이어야 한다.")
            previous_end = region[1]
    if args.split:
        hop = round(SAMPLE_RATE*0.01)
        energies = [(sum(v*v for v in pcm[i:i+hop])/len(pcm[i:i+hop]))**0.5 for i in range(0,len(pcm),hop)]
        active = [i for i,value in enumerate(energies) if value > max(energies)*0.04]
        if not active:
            raise ValueError("원본이 무음이다.")
        groups = [[active[0]]]
        for value in active[1:]:
            if value-groups[-1][-1] > 7:
                groups.append([])
            groups[-1].append(value)
        regions = [(max(0, group[0]*0.01-0.015), min(duration, (group[-1]+1)*0.01+0.055))
                   for group in groups if len(group) >= 3]
    directory = ROOT / "data/runtime/audio/user_audio"
    original = directory / "originals" / source.name
    original.parent.mkdir(parents=True, exist_ok=True)
    if original.exists() and original.read_bytes() != payload:
        raise ValueError("같은 이름의 다른 원본이 있다. 기존 파일을 보존한다.")
    if source != original.resolve():
        shutil.copy2(source, original)
    names = []
    processing = json.loads(args.processing.read_text(encoding="utf-8")) if args.processing else None
    if args.attack_index is not None:
        names.append(f"user_swing_combo_{args.attack_index}{source.suffix.lower()}")
    if args.preserve_source:
        names.append(f"user_{args.kind}{source.suffix.lower()}")
    for index, (start, stop) in enumerate(regions if args.attack_index is None and not args.preserve_source else []):
        samples = [value/(32767 if args.trim_only else 32768)
                   for value in pcm[round(start*SAMPLE_RATE):round(stop*SAMPLE_RATE)]]
        if processing:
            from ferrial_drive.audio.processing import focused_whoosh
            if processing["processor"] != "focused_whoosh":
                raise ValueError("지원하지 않는 선택 음원 가공 방식")
            samples = focused_whoosh(samples, SAMPLE_RATE, processing)
        peak = max(abs(value) for value in samples)
        if peak == 0:
            raise ValueError("선택 구간이 무음이다.")
        if args.trim_only:
            samples = [value * min(1, i/(SAMPLE_RATE*0.003)) for i, value in enumerate(samples)]
        elif not processing:
            samples = [value*0.58/peak * min(1, i/(SAMPLE_RATE*0.003)) *
                       min(1, (len(samples)-1-i)/(SAMPLE_RATE*0.015)) for i, value in enumerate(samples)]
        name = f"user_{args.kind}_{index+1:02}.wav" if args.split or args.regions else f"user_{args.kind}.wav"
        write_wav(directory / name, samples)
        names.append(name)
    selection = json.loads((ROOT / "samples/sound_effects/user_selected_sources.json").read_text(encoding="utf-8"))
    provenance = dict(selection["sounds"][args.kind], license=selection["license"], license_url=selection["license_url"],
                      original_file=source.name, sha256=sha256(payload).hexdigest(),
                      regions_seconds=regions, prepared_files=names)
    chosen = selection["sounds"][args.kind]
    provenance.update(license=chosen.get("license", selection["license"]),
                      license_url=chosen.get("license_url", selection["license_url"]))
    if processing:
        provenance.update(processing=processing, processed_seconds=len(samples)/SAMPLE_RATE)
    if args.preserve_source:
        provenance.update(preparation="원본 직접 적재. 구간·음량·시작/끝 유지.")
    if args.trim_only:
        provenance.update(preparation="선택 구간 단순 추출. 앞 3ms 페이드, 정규화·끝 페이드·피치 변경 없음.")
    if args.kind != "swing":
        provenance["event_volume"] = args.event_volume
    record_name = args.kind
    if args.attack_index is not None:
        record_name = f"swing_combo_{args.attack_index}"
        provenance.update(attack_index=args.attack_index, preparation="편집 원본 직접 적재. 구간·음량·시작/끝 유지.")
    (directory / f"{record_name}_source.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    bank_path = directory / "bank.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8")) if bank_path.is_file() else {"files": {}, "replace_files": {}, "events": {}}
    bank["files"].update({name: f"originals/{source.name}" if args.attack_index is not None or args.preserve_source else name for name in names})
    if args.attack_index is not None:
        event = f"swing_{args.attack_index}"
        base = json.loads((ROOT / "samples/sound_effects/sound_bank.json").read_text(encoding="utf-8"))
        row = base["events"][event]
        row["layers"][0].update(files=names, rate=1, rate_jitter=0)
        bank["events"][event] = row
    elif args.kind == "swing":
        bank["replace_files"].update({"swing_air.wav": names, "swing_thrust.wav": names})
    else:
        bank["events"][args.kind] = {"cooldown_seconds":.06 if args.kind in ("gun_explosion", "hit_metal") else 0 if args.kind.startswith("gun_") else 0.08,
                                    "layers":[{"files":names,"volume":args.event_volume}]}
        if args.kind == "hit_metal":
            bank["events"][args.kind]["replaces_hit"] = True
        if args.kind == "gun_explosion":
            bank["events"][args.kind]["follow_rate_multiplier"] = False
    bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"선택 음원 연결 준비: {args.kind} ({len(names)} files, {regions})")


if __name__ == "__main__":
    main()
