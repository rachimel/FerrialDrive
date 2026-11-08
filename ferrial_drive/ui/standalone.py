"""기존 미리보기 호출 호환. 실제 실행은 FDrive 공통 실행부를 사용한다."""

from ferrial_drive.runtime import poll_events as _events, run_application as run_preview

__all__ = ['run_preview']
