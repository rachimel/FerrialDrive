"""전투 수치 커널의 네이티브 의존성을 초기화한다."""

from os import environ
from sys import modules


OPENBLAS_THREAD_SETTINGS = ("OPENBLAS_NUM_THREADS", "OPENBLAS_DEFAULT_NUM_THREADS",
                            "GOTO_NUM_THREADS", "OMP_NUM_THREADS")


def configure_combat_blas():
    # 전투 Numba 커널은 BLAS 연산이 없어 작업 스레드의 초기 버퍼가 필요 없다.
    if "numpy" not in modules and not any(name in environ for name in OPENBLAS_THREAD_SETTINGS):
        environ.setdefault("OPENBLAS_NUM_THREADS", "1")
