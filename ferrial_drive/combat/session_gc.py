"""교전과 종료 로딩을 기준으로 프로세스의 순환 GC 시점을 관리한다."""

import gc

from ..ui.loading import LoadingCancelled


class CombatCollection:
    def __init__(self, make_screen):
        self.make_screen = make_screen
        self.automatic = gc.isenabled()
        self.in_combat = False
        self.pending_collection = False

    def set_combat(self, active):
        if active == self.in_combat:
            return
        self.in_combat = active
        if active:
            gc.disable()
            self.pending_collection = True
        elif self.automatic:
            gc.enable()

    def finish(self):
        """닫힌 교전의 참조를 놓은 뒤, 로딩 화면을 표시하고 전체 수집한다."""
        if not self.pending_collection:
            return True
        self.pending_collection = False
        gc.disable()
        screen = None
        try:
            if self.make_screen is not None:
                screen = self.make_screen()
                try:
                    screen.show(0, "전투 메모리 정리 중")
                except LoadingCancelled:
                    return False
        finally:
            try:
                gc.collect(2)
            finally:
                if screen is not None:
                    screen.close()
        return True

    def restore(self):
        if self.automatic:
            gc.enable()
        else:
            gc.disable()
