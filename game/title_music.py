"""타이틀 믹서에서 로컬 Atlas를 스트리밍한다."""

import ctypes as ct
from pathlib import Path
import warnings


MUSIC = Path(__file__).resolve().parents[1] / "data/source/audio/sources/bgm/credit/Atlas.mp3"


class TitleMusic:
    def __init__(self):
        self.handle = None
        self.lib = None

    def start(self, mixer):
        if mixer is None or not MUSIC.is_file() or self.handle:
            return
        self.lib = mixer.lib
        try:
            open_music = self.lib.fd_music_open
            close_music = self.lib.fd_music_close
        except AttributeError:
            warnings.warn("타이틀 음악을 사용하려면 audio-engine을 다시 빌드해야 한다.")
            return
        open_music.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_float]
        open_music.restype = ct.c_void_p
        close_music.argtypes = [ct.c_void_p]
        close_music.restype = None
        self.handle = open_music(mixer.engine, str(MUSIC), .28)
        if not self.handle:
            warnings.warn("Atlas 음악을 열 수 없다.")

    def close(self):
        if self.handle:
            self.lib.fd_music_close(self.handle)
            self.handle = None
