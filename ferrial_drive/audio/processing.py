"""샘플 기반 부스트 정리와 끊김 없는 마찰 재료의 오프라인 가공."""

from math import cos, exp, isfinite, pi, sin, sqrt
from random import Random


def biquad(samples, sample_rate, kind, frequency, *, end_frequency=None, q=0.70710678):
    """RBJ/W3C Audio EQ Cookbook의 LPF·HPF·0dB BPF 수식 사용.

    출처: https://www.w3.org/TR/audio-eq-cookbook/
    """
    end_frequency = frequency if end_frequency is None else end_frequency
    if sample_rate <= 0 or q <= 0 or not all(isfinite(f) and 0 < f < sample_rate/2 for f in (frequency, end_frequency)):
        raise ValueError("필터 주파수와 Q의 범위 오류")
    z1 = z2 = 0.0
    output = []
    for index, value in enumerate(samples):
        if index % 64 == 0:
            f = frequency + (end_frequency-frequency) * index / max(1, len(samples)-1)
            omega = 2*pi*f/sample_rate
            c, alpha = cos(omega), sin(omega)/(2*q)
            a0, a1, a2 = 1+alpha, -2*c, 1-alpha
            if kind == "lowpass":
                b0, b1, b2 = (1-c)/2, 1-c, (1-c)/2
            elif kind == "highpass":
                b0, b1, b2 = (1+c)/2, -(1+c), (1+c)/2
            elif kind == "bandpass":
                b0, b1, b2 = alpha, 0.0, -alpha
            else:
                raise ValueError("지원하지 않는 필터 종류")
            b0, b1, b2, a1, a2 = (v/a0 for v in (b0, b1, b2, a1, a2))
        y = b0*value + z1
        z1, z2 = b1*value - a1*y + z2, b2*value - a2*y
        output.append(y)
    return output


def diffuse_tail(samples, sample_rate, recipe):
    """원음의 시작을 보존하고 감쇠하는 불규칙 반사를 잔향으로 더한다."""
    tail = recipe["duration_seconds"]
    pre_delay = recipe.get("pre_delay_seconds", 0.018)
    taps = recipe.get("taps", 40)
    wet = recipe["wet"]
    if not 0 < pre_delay < tail or type(taps) is not int or taps < 4 or not 0 <= wet <= 1:
        raise ValueError("잔향 시간·반사 수·혼합 값 오류")
    random = Random(recipe.get("seed", 83))
    reflections = []
    for index in range(taps):
        delay = pre_delay + (tail-pre_delay)*(index+random.random())/taps
        gain = exp(-recipe.get("decay_exponent", 3)*delay/tail) * random.choice((-1, 1))
        reflections.append((round(delay*sample_rate), gain))
    norm = sqrt(sum(gain*gain for _, gain in reflections))
    reverberation = [0.0]*(len(samples)+round(tail*sample_rate))
    for delay, gain in reflections:
        for index, value in enumerate(samples):
            reverberation[index+delay] += value*gain/norm
    reverberation = biquad(reverberation, sample_rate, "lowpass", recipe["damping_hz"])
    output = [value*wet for value in reverberation]
    for index, value in enumerate(samples):
        output[index] += value
    fade = sample_rate*0.025
    return [value*min(1, (len(output)-1-index)/fade) for index, value in enumerate(output)]


def focused_whoosh(samples, sample_rate, recipe):
    """원음의 이동 대역을 남기고 잡음 꼬리를 줄인 뒤 선택 잔향을 더한다."""
    start, end = recipe["start_seconds"], recipe["end_seconds"]
    if not 0 <= start < end <= len(samples)/sample_rate:
        raise ValueError("부스트 편집 구간 오류")
    source = samples[round(start*sample_rate):round(end*sample_rate)]
    focused = biquad(source, sample_rate, "bandpass", recipe["focus_start_hz"],
                     end_frequency=recipe["focus_end_hz"], q=recipe["focus_q"])
    body = biquad(source, sample_rate, "lowpass", recipe["body_lowpass_hz"])
    body = biquad(body, sample_rate, "highpass", recipe.get("body_highpass_hz", 100))
    mixed = [center + low*recipe["body_gain"] + raw*recipe["broadband_gain"]
             for center, low, raw in zip(focused, body, source)]
    if recipe.get("hiss_lowpass_hz"):
        mixed = biquad(mixed, sample_rate, "lowpass", recipe["hiss_lowpass_hz"])
    output = []
    for index, value in enumerate(mixed):
        t = index/sample_rate
        envelope = min(1, t/recipe["attack_seconds"])
        envelope *= exp(-max(0, t-recipe["hold_seconds"])/recipe["decay_seconds"])
        envelope *= min(1, (len(source)-1-index)/(sample_rate*recipe["fade_out_seconds"]))
        output.append(value * envelope)
    if recipe.get("reverb"):
        output = diffuse_tail(output, sample_rate, recipe["reverb"])
    peak = max(map(abs, output), default=0)
    if peak <= 1e-10:
        raise ValueError("부스트 편집 결과가 무음이다.")
    return [value*recipe.get("peak", 0.58)/peak for value in output]


def layered_burst(sources, sample_rate, recipe):
    """서로 독립된 녹음의 충격·분사·감쇠층을 조립한다."""
    duration = recipe["duration_seconds"]
    peak = recipe.get("peak", 0.72)
    if (not isfinite(duration) or duration <= 0 or not 0 < peak < 1
            or sample_rate <= 0 or not recipe["layers"]):
        raise ValueError("분사음 길이·최대 진폭·레이어 오류")
    output = [0.0] * round(duration * sample_rate)
    for layer in recipe["layers"]:
        source = sources[layer["source_index"]]
        start, end = layer["source_start_seconds"], layer["source_end_seconds"]
        length = round(layer["duration_seconds"] * sample_rate)
        offset = round(layer.get("offset_seconds", 0) * sample_rate)
        attack, hold, decay = (layer[key] for key in ("attack_seconds", "hold_seconds", "decay_seconds"))
        if (not 0 <= start < end <= len(source) / sample_rate or length < 2 or offset < 0
                or offset + length > len(output) or min(attack, decay) <= 0 or hold < 0
                or not isfinite(layer["gain"]) or layer["gain"] < 0):
            raise ValueError("분사음 레이어 구간·시간·음량 오류")
        source = source[round(start * sample_rate):round(end * sample_rate)]
        if len(source) < 2:
            raise ValueError("분사음 원본 구간이 너무 짧다.")
        mean = sum(source) / len(source)
        source = [value - mean for value in source]
        rate_start, rate_end = layer.get("rate_start", 1), layer.get("rate_end", 1)
        if not all(isfinite(rate) and rate > 0 for rate in (rate_start, rate_end)):
            raise ValueError("분사음 재생률 곡선은 유한한 양수여야 한다.")
        resized = []
        for index in range(length):
            progress = index / (length - 1)
            # 속도를 적분한 좌표를 사용해 피치가 뛰지 않고 연속적으로 가속한다.
            position = (rate_start * progress + (rate_end - rate_start) * progress**2 / 2)
            position *= (len(source) - 1) / ((rate_start + rate_end) / 2)
            position = min(len(source) - 1, position)
            left = min(len(source) - 2, int(position))
            resized.append(source[left] + (source[left + 1] - source[left]) * (position - left))
        signal = biquad(resized, sample_rate, "highpass", layer["highpass_hz"])
        signal = biquad(signal, sample_rate, "lowpass", layer["lowpass_hz"])
        if "focus_start_hz" in layer:
            focused = biquad(signal, sample_rate, "bandpass", layer["focus_start_hz"],
                             end_frequency=layer["focus_end_hz"], q=layer.get("focus_q", 0.7))
            focus_mix = layer.get("focus_mix", 0.5)
            signal = [a * (1 - focus_mix) + b * focus_mix for a, b in zip(signal, focused)]
        source_peak = max(map(abs, signal), default=0)
        if source_peak <= 1e-10:
            raise ValueError("분사음 레이어가 무음이다.")
        fade = max(1, sample_rate * layer.get("fade_out_seconds", 0.035))
        for index, value in enumerate(signal):
            t = index / sample_rate
            envelope = min(1, t / attack) * exp(-max(0, t - hold) / decay)
            envelope *= min(1, (length - 1 - index) / fade)
            output[offset + index] += value / source_peak * layer["gain"] * envelope
    if recipe.get("reverb"):
        output = diffuse_tail(output, sample_rate, recipe["reverb"])
    output_peak = max(map(abs, output), default=0)
    if output_peak <= 1e-10:
        raise ValueError("분사음 합성이 무음이다.")
    return [value * peak / output_peak for value in output]


def continuous_friction(sources, sample_rate, recipe):
    """실제 마찰 조각을 원형 overlap-add로 겹친다. 지속음을 재시작하지 않는다."""
    length = round(recipe["duration_seconds"]*sample_rate)
    grain = round(recipe["grain_seconds"]*sample_rate)
    hop = round(recipe["hop_seconds"]*sample_rate)
    trimmed = []
    for source in sources:
        threshold = max(map(abs, source), default=0)*0.015
        active = [index for index, value in enumerate(source) if abs(value) > threshold]
        if active:
            trimmed.append(source[active[0]:active[-1]+1])
    sources = trimmed
    if not sources or not 0 < hop < grain <= length or any(len(source) < grain+2 for source in sources):
        raise ValueError("마찰 조각·겹침·원본 길이 오류")
    random = Random(recipe.get("seed", 71))
    output, weights = [0.0]*length, [0.0]*length
    window = [0.5-0.5*cos(2*pi*i/(grain-1)) for i in range(grain)]
    for start in range(0, length, hop):
        source = random.choice(sources)
        offset = random.randrange(len(source)-grain)
        piece = source[offset:offset+grain]
        rms = sqrt(sum(v*v for v in piece)/grain)
        gain = min(8, 0.13/max(rms, 0.01))
        for index, (value, weight) in enumerate(zip(piece, window)):
            position = (start+index) % length
            output[position] += value*gain*weight
            weights[position] += weight
    output = [value/max(weight, 1e-8) for value, weight in zip(output, weights)]
    # 순환 필터의 시작 상태가 안정화되도록 이전 한 주기를 먼저 통과시킨다.
    extended = output + output
    extended = biquad(extended, sample_rate, "highpass", recipe["highpass_hz"])
    extended = biquad(extended, sample_rate, "lowpass", recipe["lowpass_hz"])
    output = extended[-length:]
    # 원형 RMS 보정으로 짧은 원본의 규칙적인 음량 출렁임을 줄인다.
    block = round(sample_rate*0.04)
    rms_values = [sqrt(sum(v*v for v in output[i:i+block])/len(output[i:i+block]))
                  for i in range(0, length, block)]
    gains = [min(3, 0.1/max(value, 0.015)) for value in rms_values]
    for index in range(length):
        position = index/block
        left = int(position) % len(gains)
        gain = gains[left] + (gains[(left+1)%len(gains)]-gains[left]) * (position-int(position))
        output[index] *= gain
    peak = max(map(abs, output), default=1)
    return [value*0.58/max(peak, 1e-8) for value in output]
