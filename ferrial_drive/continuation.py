"""타이틀의 테스트 복귀와 본편 마지막 세이브 로더 연결. 저장 형식은 소유하지 않는다."""


class ContinueSession:
    def __init__(self, *, mode="test", has_last_save=None, load_last_save=None):
        if mode not in ("test", "game"):
            raise ValueError("재개 모드는 test 또는 game이어야 한다.")
        if (has_last_save is None) != (load_last_save is None):
            raise ValueError("마지막 세이브 확인·불러오기 함수를 함께 지정한다.")
        if has_last_save is not None and (not callable(has_last_save) or not callable(load_last_save)):
            raise ValueError("마지막 세이브 연결은 호출 가능한 함수여야 한다.")
        if mode == "test" and has_last_save is not None:
            raise ValueError("테스트 복귀에는 본편 세이브 로더를 연결하지 않는다.")
        self.mode = mode
        self.has_last_save = has_last_save
        self.load_last_save = load_last_save

    @property
    def available(self):
        return self.mode == "test" or (self.has_last_save is not None and bool(self.has_last_save()))

    def resume(self):
        """본편 로더가 상태 복원을 완료하고 True를 반환해야 화면을 전환한다."""
        if not self.available:
            return False
        return self.mode == "test" or self.load_last_save() is True
