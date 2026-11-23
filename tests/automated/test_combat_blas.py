"""전투 수치 커널이 OpenBLAS의 시작 설정과 외부 재정의를 존중하는지 확인한다."""

from unittest import TestCase
from unittest.mock import patch

from ferrial_drive.combat import numeric_runtime


class CombatBlasTests(TestCase):
    def test_default_is_set_before_numpy_starts(self):
        options = {}
        with patch.object(numeric_runtime, "environ", options), patch.object(numeric_runtime, "modules", {}):
            numeric_runtime.configure_combat_blas()
        self.assertEqual(options, {"OPENBLAS_NUM_THREADS": "1"})

    def test_explicit_thread_settings_take_priority(self):
        for name in numeric_runtime.OPENBLAS_THREAD_SETTINGS:
            with self.subTest(name=name):
                options = {name: "4"}
                with patch.object(numeric_runtime, "environ", options), patch.object(numeric_runtime, "modules", {}):
                    numeric_runtime.configure_combat_blas()
                self.assertEqual(options, {name: "4"})

    def test_embedded_numpy_does_not_change_the_environment(self):
        options = {}
        with patch.object(numeric_runtime, "environ", options), patch.object(numeric_runtime, "modules", {"numpy": object()}):
            numeric_runtime.configure_combat_blas()
        self.assertEqual(options, {})
