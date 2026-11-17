"""독립 페이지 Work의 병렬 실행·결과 소유권·실패 정리·대기열 제한을 검사한다."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
from threading import Barrier, Event, Lock, get_ident
import tempfile
import unittest
from unittest.mock import patch
import zlib

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.rendering.texture_page_work import TexturePageWork, decoded_pages


class TexturePageWorkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def page(self, index=0):
        data = zlib.compress(bytes([index]) * 64)
        (self.root / f"page_{index}.zlib").write_bytes(data)
        return {"file": f"page_{index}.zlib", "sha256": hashlib.sha256(data).hexdigest(),
                "width": 4, "height": 4, "codec": "rgba_zlib"}

    def test_work_publishes_exact_payload_once_and_releases_ownership(self):
        page = self.page(7)
        work = TexturePageWork(page, self.root)
        self.assertEqual(work.state, "pending")
        with self.assertRaises(RuntimeError):
            work.take_result()
        work.run()
        self.assertEqual(work.state, "ready")
        result = work.take_result()
        self.assertEqual(result.pixels, bytes([7]) * 64)
        self.assertFalse(result.compressed)
        self.assertEqual(work.state, "consumed")
        with self.assertRaises(RuntimeError):
            work.take_result()
        with self.assertRaises(RuntimeError):
            work.run()

    def test_same_work_is_claimed_only_once_under_competing_threads(self):
        work = TexturePageWork(self.page(), self.root)
        gate = Barrier(2)

        def run():
            gate.wait(timeout=5)
            try:
                work.run()
                return True
            except RuntimeError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            self.assertEqual(sorted(future.result(timeout=5) for future in futures), [False, True])
        self.assertEqual(work.take_result().pixels, bytes(64))

    def test_decompression_overlaps_without_holding_the_work_lock(self):
        from ferrial_drive.rendering.texture_codecs import unpack_payload
        gate = Barrier(2)
        threads = set()
        lock = Lock()
        owner = get_ident()

        def decode(*args, **kwargs):
            with lock:
                threads.add(get_ident())
            gate.wait(timeout=5)
            return unpack_payload(*args, **kwargs)

        with patch("ferrial_drive.rendering.texture_page_work.unpack_payload", side_effect=decode):
            values = list(decoded_pages([self.page(1), self.page(2)], self.root, workers=2))
        self.assertEqual([row.pixels[0] for row in values], [1, 2])
        self.assertEqual(len(threads), 2)
        self.assertNotIn(owner, threads)

    def test_completed_work_stays_within_window_until_consumer_advances(self):
        original = TexturePageWork.run
        completed = Event()
        lock = Lock()
        count = 0

        def run(work):
            nonlocal count
            original(work)
            with lock:
                count += 1
                if count == 2:
                    completed.set()

        pages = [self.page(index) for index in range(6)]
        with patch.object(TexturePageWork, "run", run), closing(decoded_pages(pages, self.root, workers=2)) as iterator:
            self.assertEqual(next(iterator).pixels[0], 0)
            self.assertTrue(completed.wait(timeout=5))
            self.assertEqual(count, 2)
        self.assertEqual(count, 2)

    def test_worker_failure_propagates_and_remaining_work_is_drained(self):
        first, second = self.page(1), self.page(2)
        first["sha256"] = "0" * 64
        started = []
        original = TexturePageWork.run

        def run(work):
            try:
                original(work)
            finally:
                started.append(work)

        with patch.object(TexturePageWork, "run", run), closing(decoded_pages([first, second], self.root, workers=2)) as iterator:
            with self.assertRaisesRegex(ValueError, "해시"):
                next(iterator)
        self.assertTrue(started)
        self.assertTrue(all(work.state in ("failed", "ready") for work in started))

    def test_corrupt_payload_is_failed_after_valid_file_hash(self):
        page = self.page()
        data = zlib.compress(bytes(65))
        (self.root / page["file"]).write_bytes(data)
        page["sha256"] = hashlib.sha256(data).hexdigest()
        work = TexturePageWork(page, self.root)
        with self.assertRaises(ValueError):
            work.run()
        self.assertEqual(work.state, "failed")

    def test_parallel_timing_reports_completed_calls_from_every_worker(self):
        timings = TimingRecorder(enabled=True)
        values = list(decoded_pages([self.page(index) for index in range(8)], self.root, workers=4, timings=timings))
        self.assertEqual(len(values), 8)
        rows = {row["name"]: row for row in timings.snapshot()["measurements"]}
        self.assertEqual(rows["load.decode"]["calls"], 8)
        self.assertEqual(rows["load.integrity"]["failures"], 0)

    def test_invalid_worker_count_is_rejected(self):
        for count in (0, -1, True, 1.5):
            with self.subTest(workers=count), self.assertRaises(ValueError):
                next(decoded_pages([], self.root, workers=count))

    def test_gpu_cache_rejects_calls_from_a_worker_before_touching_gl(self):
        from ferrial_drive.rendering.pico_motion_atlas import AtlasTextureCache
        cache = AtlasTextureCache.__new__(AtlasTextureCache)
        cache.owner_thread_id = get_ident()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaisesRegex(RuntimeError, "스레드"):
                executor.submit(cache.acquire, self.page(), self.root).result(timeout=5)
            with self.assertRaisesRegex(RuntimeError, "스레드"):
                executor.submit(cache.release, None).result(timeout=5)

    def test_main_thread_consumer_preserves_order_and_releases_cache_on_failure(self):
        from types import SimpleNamespace
        from ferrial_drive.rendering.pico_motion_atlas import PicoMotionAtlas

        pages = [self.page(index) for index in range(3)]
        source = self.root / "atlas.json"
        source.write_text(json.dumps({"version": 1, "pages": {"color": pages, "vector": [pages[0]]}}))
        owner = get_ident()
        released = []

        class Cache:
            entries = {}
            timings = TimingRecorder(enabled=False)
            ktx_library = None
            sampler = SimpleNamespace(integer=lambda key: 2048)

            @staticmethod
            def page_key(page, directory):
                return ((directory / page["file"]).resolve(), page["sha256"])

            def acquire(self, page, directory, *, prepared=None):
                self.assert_owner()
                key = self.page_key(page, directory)
                if key not in self.entries:
                    if prepared.pixels[0] == 2:
                        raise RuntimeError("전송 실패")
                    self.entries[key] = prepared
                return key, self.entries[key]

            def assert_owner(self):
                if get_ident() != owner:
                    raise AssertionError("GPU 소비 스레드 변경")

            _assert_owner = assert_owner

            def release(self, key):
                self.assert_owner()
                released.append(key)
                del self.entries[key]

        cache = Cache()
        with self.assertRaisesRegex(RuntimeError, "전송 실패"):
            PicoMotionAtlas(None, source, cache, decode_workers=2)
        self.assertEqual(cache.entries, {})
        self.assertEqual([key[0].name for key in released], ["page_0.zlib", "page_1.zlib"])


if __name__ == "__main__":
    unittest.main()
