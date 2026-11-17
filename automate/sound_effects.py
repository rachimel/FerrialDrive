"""보존 음원을 편집한다. 공개 라이선스·사용자 제공 음원은 출처별 명세로 분리한다."""

import argparse
from array import array
from ctypes import string_at
import json
from math import exp, isfinite, pi, tanh
from pathlib import Path
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SAMPLE_RATE = 44100
RECIPE = ROOT / "samples/sound_effects/processing.json"


def process_samples(samples, recipe):
    """무음·구간 편집, 길이 조정, 대역 제한과 짧은 페이드를 적용한다."""
    threshold = max(abs(value) for value in samples) * 0.012
    active = [index for index, value in enumerate(samples) if abs(value) > threshold]
    if not active:
        raise ValueError("음원이 무음이다.")
    padding = round(SAMPLE_RATE * 0.005)
    samples = samples[max(0, active[0]-padding):min(len(samples), active[-1]+padding+1)]
    window = round(recipe.get("window_seconds", len(samples)/SAMPLE_RATE) * SAMPLE_RATE)
    if window < len(samples):
        hop = round(SAMPLE_RATE * 0.01)
        energies = [sum(value*value for value in samples[start:start+hop]) for start in range(0, len(samples), hop)]
        count = max(1, window//hop)
        start = max(range(max(1, len(energies)-count+1)), key=lambda index: sum(energies[index:index+count])) * hop
        samples = samples[start:start+window]
    length = round(recipe["duration_seconds"] * SAMPLE_RATE)
    ratio = (len(samples)-1) / max(1, length-1)
    resized = []
    for index in range(length):
        position = index * ratio
        left = min(len(samples)-2, int(position))
        resized.append(samples[left] + (samples[left+1]-samples[left]) * (position-left))
    low, dc, output = 0.0, 0.0, []
    hp = 1-exp(-2*pi*recipe.get("highpass_hz", 45)/SAMPLE_RATE)
    lp = 1-exp(-2*pi*recipe.get("lowpass_hz", 10000)/SAMPLE_RATE)
    drive = recipe.get("drive", 1)
    for index, value in enumerate(resized):
        dc += hp * (value-dc)
        low += lp * (value-dc-low)
        value = tanh(low * drive)
        if recipe.get("envelope"):
            progress = index / max(1, length-1)
            value *= (progress * (1-progress) * 4) ** 0.65
        output.append(value)
    peak = max(abs(value) for value in output)
    output = [value * 0.58 / max(peak, 1e-8) for value in output]
    if recipe.get("loop"):
        overlap = min(round(SAMPLE_RATE * 0.06), len(output)//4)
        joined = [output[-overlap+i]*(1-i/overlap) + output[i]*(i/overlap) for i in range(overlap)]
        return joined + output[overlap:-overlap]
    fade_in, fade_out = SAMPLE_RATE*0.004, SAMPLE_RATE*0.035
    return [value * min(1, i/fade_in) * min(1, (len(output)-1-i)/fade_out) for i, value in enumerate(output)]


def extract_region(samples, recipe):
    """원본 구간의 길이·피치를 보존하고 짧은 페이드와 피크 보정만 적용한다."""
    start, end = recipe["start_seconds"], recipe["end_seconds"]
    peak = recipe.get("peak", 0.58)
    fade_in = recipe.get("fade_in_seconds", 0.0005)
    fade_out = recipe.get("fade_out_seconds", 0.008)
    if (not all(isfinite(value) for value in (start, end, peak, fade_in, fade_out))
            or not 0 <= start < end <= len(samples) / SAMPLE_RATE
            or not 0 < peak < 1 or fade_in <= 0 or fade_out <= 0):
        raise ValueError("추출 구간·피크·페이드 범위 오류")
    selected = samples[round(start * SAMPLE_RATE):round(end * SAMPLE_RATE)]
    if len(selected) < 2:
        raise ValueError("추출 구간이 너무 짧다.")
    if (fade_in + fade_out) * SAMPLE_RATE > len(selected):
        raise ValueError("페이드 합계가 추출 구간보다 길다.")
    output = [value * min(1, index / (SAMPLE_RATE * fade_in))
              * min(1, (len(selected) - 1 - index) / (SAMPLE_RATE * fade_out))
              for index, value in enumerate(selected)]
    source_peak = max(map(abs, output))
    if source_peak <= 1e-10:
        raise ValueError("추출 구간이 무음이다.")
    return [value * peak / source_peak for value in output]


def write_wav(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array("h", (round(max(-1, min(1, sample)) * 32767) for sample in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        output.writeframes(pcm.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="독립 시연 폴더에 출력")
    parser.add_argument("--recipe", type=Path, default=RECIPE, help="기본 CC0 또는 별도 선택 음원 가공 명세")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preview", type=Path, help="각 소리 사이에 무음을 둔 연속 청취 파일")
    parser.add_argument("--only", action="append", help="지정한 공통 음원만 준비한다. 반복 지정 가능")
    args = parser.parse_args()
    directory = args.output or ROOT / ("samples/sound_effects/generated" if args.demo else "data/runtime/audio/training_cc0_v1")
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    unknown = set(args.only or ()) - recipe.keys()
    if unknown:
        parser.error(f"지원하지 않는 음원: {', '.join(sorted(unknown))}")
    selected = recipe if not args.only else {name: recipe[name] for name in dict.fromkeys(args.only)}
    import os
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pico2d.pico2d as pico
    pico.SDL_Init(pico.SDL_INIT_AUDIO)
    if pico.Mix_OpenAudio(SAMPLE_RATE, pico.AUDIO_S16SYS, 1, 1024) < 0:
        raise OSError("음원 변환기 초기화 실패")
    pico.audio_on = True
    preview = []
    try:
        for name, row in selected.items():
            inputs = []
            for value in row.get("sources", [row.get("source")]):
                source = ROOT / "data/source/audio/sources" / value
                source_group = ROOT / "data/source/audio/sources" / Path(value).parts[0]
                record = json.loads((source_group / "source.json").read_text(encoding="utf-8"))
                user_provided = record.get("license") == "USER-PROVIDED" and record.get("source_type") == "user_provided"
                if (record["license"] not in ("CC0-1.0","CC-BY-4.0") and not user_provided) or (
                        record["license"] == "CC-BY-4.0" and not record.get("attribution")):
                    raise ValueError(f"지원 라이선스·출처 문구가 없는 원본이다: {source}")
                sound = pico.load_wav(str(source))
                pcm = array("h", string_at(sound.wav.contents.abuf, sound.wav.contents.alen))
                if sys.byteorder != "little":
                    pcm.byteswap()
                del sound
                inputs.append([value/32768 for value in pcm])
            if row.get("processor") == "extract_region":
                samples = extract_region(inputs[0], row)
            elif row.get("processor") == "continuous_friction":
                from ferrial_drive.audio.processing import continuous_friction
                samples = continuous_friction(inputs, SAMPLE_RATE, row)
            elif row.get("processor") == "layered_burst":
                from ferrial_drive.audio.processing import layered_burst
                samples = layered_burst(inputs, SAMPLE_RATE, row)
            else:
                samples = process_samples(inputs[0], row)
            write_wav(directory / f"{name}.wav", samples)
            preview.extend(samples)
            preview.extend([0] * round(SAMPLE_RATE * 0.4))
        (directory / "processing.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        pico.Mix_CloseAudio()
        pico.SDL_QuitSubSystem(pico.SDL_INIT_AUDIO)
    if args.preview:
        write_wav(args.preview, preview)
    print(f"가공 음원 {len(selected)}개 준비: {directory}")


if __name__ == "__main__":
    main()
