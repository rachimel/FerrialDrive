"""공통·사용자 선택 샘플을 독립 채널에서 혼합하고 SDL로 피치·속도를 변환한다."""

from ctypes import POINTER, byref, c_int, c_uint16, cast, create_string_buffer, memmove, string_at
import json
from math import isfinite
from pathlib import Path
from random import Random
from time import perf_counter
import warnings


def convert_playback_rate(pico, pcm, rate, frequency, sample_format, channel_count):
    """동일 PCM의 재생률을 메모리에서 변환한다. 피치와 속도가 함께 변한다."""
    if not isfinite(rate) or not 0.5 <= rate <= 2:
        raise ValueError("재생률은 0.5~2의 유한값이어야 한다.")
    conversion = pico.SDL_AudioCVT()
    result = pico.SDL_BuildAudioCVT(byref(conversion), sample_format, channel_count,
        round(frequency * rate), sample_format, channel_count, frequency)
    if result < 0:
        raise OSError("효과음 재생률 변환 준비 실패")
    conversion.len = len(pcm)
    memory = create_string_buffer(len(pcm) * max(1, conversion.len_mult))
    memmove(memory, pcm, len(pcm))
    conversion.buf = cast(memory, POINTER(pico.Uint8))
    if pico.SDL_ConvertAudio(byref(conversion)) < 0:
        raise OSError("효과음 재생률 변환 실패")
    return memory, conversion.len_cvt if result else len(pcm)


class PicoSoundEffects:
    def __init__(self, pico, bank_path, directory, *, volume=0.4, channels=24, seed=31, user_bank=None):
        self.pico = pico
        self.sounds = {}
        self.pcm = {}
        self.voices = {}
        self.channels = ()
        self.random = Random(seed)
        self.previous_choices = {}
        self.time_seconds = 0.0
        self.last_played = {}
        self.play_counts = {}
        self.layer_counts = {}
        self.dropped_layers = 0
        self.conversion_max_ms = 0
        self.disabled_reason = None
        self.volume = volume
        self.rate_multiplier = 1.0
        self.bank = json.loads(Path(bank_path).read_text(encoding="utf-8"))["events"]
        user_files = {}
        if user_bank is not None and Path(user_bank).is_file():
            selected = json.loads(Path(user_bank).read_text(encoding="utf-8"))
            self.bank.update(selected.get("events", {}))
            replacements = selected.get("replace_files", {})
            for row in self.bank.values():
                for layer in row["layers"]:
                    files = []
                    for name in layer["files"]:
                        replacement = replacements.get(name, name)
                        files.extend(replacement if isinstance(replacement, list) else [replacement])
                    layer["files"] = list(dict.fromkeys(files))
            user_files = {name: Path(user_bank).parent / value for name, value in selected.get("files", {}).items()}
        if not 0 <= volume <= 1 or type(channels) is not int or channels < 1:
            raise ValueError("음량은 0~1, 채널 수는 양수 정수여야 한다.")
        if not pico.audio_on:
            self.disabled_reason = "오디오 장치를 사용할 수 없다."
            warnings.warn(self.disabled_reason, RuntimeWarning)
            return
        try:
            frequency, sample_format, channel_count = c_int(), c_uint16(), c_int()
            if not pico.Mix_QuerySpec(byref(frequency), byref(sample_format), byref(channel_count)):
                raise OSError("오디오 장치 형식 조회 실패")
            self.format = (frequency.value, sample_format.value, channel_count.value)
            files = {name for row in self.bank.values() for layer in row["layers"] for name in layer["files"]}
            for name in sorted(files):
                path = user_files.get(name, Path(directory) / name)
                if not path.is_file():
                    raise FileNotFoundError(f"효과음이 없다: {path}. sound-effects 준비 명령을 실행한다.")
                sound = pico.load_wav(str(path))
                self.sounds[name] = sound
                self.pcm[name] = string_at(sound.wav.contents.abuf, sound.wav.contents.alen)
            start = pico.Mix_AllocateChannels(-1)
            total = pico.Mix_AllocateChannels(start + channels)
            if total < start + channels:
                raise OSError("효과음 채널을 확보하지 못했다.")
            self.channels = tuple(range(start, total))
        except (OSError, IOError) as error:
            self.sounds.clear()
            self.pcm.clear()
            self.disabled_reason = f"효과음을 비활성화한다: {error}"
            warnings.warn(self.disabled_reason, RuntimeWarning)

    def update(self, delta_seconds):
        if not isfinite(delta_seconds) or delta_seconds < 0:
            raise ValueError("갱신 시간은 0 이상의 유한한 초 단위다.")
        self.time_seconds += delta_seconds
        self._collect()

    def _collect(self):
        for channel, voice in list(self.voices.items()):
            if not self.pico.Mix_Playing(channel):
                if voice["chunk"] is not None:
                    self.pico.Mix_FreeChunk(voice["chunk"])
                del self.voices[channel]

    def play(self, name, *, energy_level=1, gain=1, rate=1, loop=False):
        if type(energy_level) is not int or not 1 <= energy_level <= 3:
            raise ValueError("에너지 레벨은 1~3 정수다.")
        if not isfinite(gain) or not 0 <= gain <= 1 or not isfinite(rate) or not 0.5 <= rate <= 2:
            raise ValueError("음량은 0~1, 재생률은 0.5~2의 유한값이다.")
        if not self.sounds or name not in self.bank or gain == 0:
            return False
        self._collect()
        cooldown = self.bank[name].get("cooldown_seconds", 0)
        if self.time_seconds - self.last_played.get(name, -float("inf")) < cooldown:
            return False
        played = False
        for index, layer in enumerate(self.bank[name]["layers"]):
            key = (name, index)
            layer_cooldown = layer.get("cooldown_seconds", 0)
            if layer_cooldown and self.time_seconds - self.last_played.get(key, -float("inf")) < layer_cooldown:
                continue
            layer_gain = layer.get("volume", 1) * layer.get("volume_by_level", [1, 1, 1])[energy_level-1]
            if layer_gain <= 0:
                continue
            channel = next((value for value in self.channels if value not in self.voices), None)
            if channel is None:
                self.dropped_layers += 1
                continue
            choices = [item for item in layer["files"] if item != self.previous_choices.get(key)] or layer["files"]
            selected = self.random.choice(choices)
            self.previous_choices[key] = selected
            jitter = layer.get("rate_jitter", 0)
            playback_rate = rate * layer.get("rate", 1) * layer.get("rate_by_level", [1, 1, 1])[energy_level-1]
            multiplier = self.rate_multiplier if self.bank[name].get("follow_rate_multiplier", True) else 1
            playback_rate *= self.random.uniform(1-jitter, 1+jitter) * multiplier
            playback_rate = min(2, max(.5, playback_rate))
            chunk, memory = None, None
            source = self.sounds[selected].wav
            if abs(playback_rate-1) > 0.001:
                started = perf_counter()
                memory, length = convert_playback_rate(self.pico, self.pcm[selected], playback_rate, *self.format)
                chunk = self.pico.Mix_QuickLoad_RAW(cast(memory, POINTER(self.pico.Uint8)), length)
                if not chunk:
                    raise OSError("변환 효과음 생성 실패")
                source = chunk
                self.conversion_max_ms = max(self.conversion_max_ms, (perf_counter()-started)*1000)
            self.pico.Mix_Volume(channel, round(128 * self.volume * gain * layer_gain))
            if loop:
                fade_ms = round(self.bank[name].get("fade_in_seconds", 0.04)*1000)
                result = self.pico.Mix_FadeInChannel(channel, source, -1, fade_ms)
            else:
                result = self.pico.Mix_PlayChannel(channel, source, 0)
            if result < 0:
                if chunk is not None:
                    self.pico.Mix_FreeChunk(chunk)
                self.dropped_layers += 1
                continue
            self.voices[channel] = {"event": name, "loop": loop, "gain": layer_gain,
                                    "chunk": chunk, "memory": memory}
            if layer_cooldown:
                self.last_played[key] = self.time_seconds
            self.layer_counts[selected] = self.layer_counts.get(selected, 0) + 1
            played = True
        if played:
            self.last_played[name] = self.time_seconds
            self.play_counts[name] = self.play_counts.get(name, 0) + 1
        return played

    def set_rate_multiplier(self, rate):
        """신규 효과음과 지속음의 재생률을 전환한다. 지속음은 다음 갱신에 재시작한다."""
        if not isfinite(rate) or not .5 <= rate <= 2:
            raise ValueError("효과음 재생률 배율은 0.5~2여야 한다.")
        if rate != self.rate_multiplier:
            for channel, voice in list(self.voices.items()):
                if voice["loop"]:
                    self.pico.Mix_HaltChannel(channel)
            self._collect()
            self.rate_multiplier = rate

    def set_loop(self, name, enabled, *, gain=1):
        active = [(channel, voice) for channel, voice in self.voices.items()
                  if voice["event"] == name and voice["loop"]]
        if not enabled:
            for channel, voice in active:
                self.pico.Mix_FadeOutChannel(channel, round(self.bank[name].get("fade_out_seconds", 0.07)*1000))
                voice["loop"] = False
        elif not active:
            self.play(name, gain=gain, loop=True)
        else:
            for channel, voice in active:
                self.pico.Mix_Volume(channel, round(128 * self.volume * gain * voice["gain"]))

    def stop(self):
        for channel in self.channels:
            self.pico.Mix_HaltChannel(channel)
        self._collect()

    def reset(self):
        self.stop()
        self.last_played.clear()

    def close(self):
        self.stop()
        if self.channels and self.pico.Mix_AllocateChannels(-1) == self.channels[-1]+1:
            self.pico.Mix_AllocateChannels(self.channels[0])
        self.channels = ()
        # Pico2D Wav 소멸자는 Mix_FreeChunk를 호출한다. 캔버스 종료 전에 해제한다.
        self.sounds.clear()
        self.pcm.clear()
