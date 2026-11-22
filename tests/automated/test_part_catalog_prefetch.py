"""방향 메타데이터 선조회와 렌더 스레드의 페이지 소유권을 검사한다."""

from collections import OrderedDict
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from ferrial_drive.rendering.part_atlas_residency import AtlasFrameBudget, DirectionPrefetch, PartAtlasResidency
from ferrial_drive.rendering.part_motion_catalog import PartMotionCatalog


class PartCatalogPrefetchTests(unittest.TestCase):
    def make_residency(self):
        catalog = PartMotionCatalog.__new__(PartMotionCatalog)
        catalog.source = Path("catalog.json")
        catalog.paged = False
        catalog.records = OrderedDict()
        catalog.max_records = 2
        catalog.data = {"motions": {"idle": {"0": "idle.json"}},
                        "part_spaces": {"idle": {"body": "lower"}}}
        page = {"file": "color", "codec": "rgba_zlib", "width": 4, "height": 4}
        payload = {"pages": {"color": [page]}, "clip": {"parts": {"body": {"space": "upper"}}}}
        cache = SimpleNamespace(entries={("color",): {"gl_texture": 1}}, page_key=lambda *args: ("color",))
        cache.acquire = Mock()
        cache.release = Mock()
        r = PartAtlasResidency(catalog, cache, None, max_directions=2, budget_bytes=None)
        self.addCleanup(r.close)
        return r, catalog, payload

    def test_combat_stream_polls_worker_and_publishes_only_on_owner(self):
        r, catalog, payload = self.make_residency()
        started, release = Event(), Event()
        self.addCleanup(release.set)
        owner = get_ident()
        read_threads = []

        def read(relative, path):
            read_threads.append(get_ident())
            started.set()
            if not release.wait(timeout=3):
                raise RuntimeError("렌더 스레드가 방향 준비를 기다렸다.")
            return payload

        catalog._read_direction = read
        key = "idle", "0"
        budget = AtlasFrameBudget()
        r.stream((key,), (), budget)
        self.assertTrue(started.wait(timeout=3))
        self.assertEqual(len(read_threads), 1)
        self.assertNotEqual(read_threads[0], owner)
        self.assertFalse(r.prefetch.metadata.done())
        r.stream((key,), (), budget)
        self.assertFalse(catalog.records)
        self.assertFalse(r.resources)
        r.cache.acquire.assert_not_called()

        pending = r.prefetch.metadata
        release.set()
        self.assertIs(pending.result(timeout=3), payload)
        self.assertFalse(catalog.records)
        self.assertFalse(r.resources)
        r.stream((key,), (), budget)
        self.assertEqual(len(read_threads), 1)
        self.assertIs(catalog.records["idle.json"], payload)
        self.assertEqual(payload["clip"]["parts"]["body"]["space"], "upper")
        self.assertEqual(r.resources[key]["data"]["clip"]["parts"]["body"]["space"], "lower")
        r.cache.acquire.assert_called_once()

    def test_cancelled_metadata_never_changes_catalog_records(self):
        r, catalog, payload = self.make_residency()
        started, release = Event(), Event()
        self.addCleanup(release.set)

        def read(relative, path):
            started.set()
            if not release.wait(timeout=3):
                raise RuntimeError("취소까지 워커가 기다리지 못했다.")
            return payload

        catalog._read_direction = read
        r.stream((("idle", "0"),), (), AtlasFrameBudget())
        self.assertTrue(started.wait(timeout=3))
        pending = r.prefetch.metadata
        r.clear()
        release.set()
        self.assertIs(pending.result(timeout=3), payload)
        self.assertIsNone(r.prefetch)
        self.assertFalse(catalog.records)
        self.assertFalse(r.resources)
        r.cache.acquire.assert_not_called()

    def test_waiting_direction_prepares_metadata_ahead_of_page_uploads(self):
        r, catalog, payload = self.make_residency()
        catalog.data["motions"]["idle"]["1"] = "idle_next.json"
        release = Event()
        self.addCleanup(release.set)
        pending_reads = []

        def read(relative, path):
            pending_reads.append(relative)
            if relative == "idle.json" and not release.wait(timeout=3):
                raise RuntimeError("첫 방향 준비가 완료되지 않았다.")
            return payload

        catalog._read_direction = read
        first, second = ("idle", "0"), ("idle", "1")
        budget = AtlasFrameBudget()
        r.stream((first, second), (), budget)
        ahead = r.metadata_jobs[second]
        self.assertIs(ahead.result(timeout=3), payload)
        self.assertFalse(r.prefetch.metadata.done())
        self.assertFalse(r.resources)
        self.assertFalse(catalog.records)
        release.set()
        r.prefetch.metadata.result(timeout=3)
        r.stream((first, second), (), budget)
        self.assertIn(first, r.resources)
        r.stream((first, second), (), budget)
        self.assertIn(second, r.resources)
        self.assertCountEqual(pending_reads, ["idle.json", "idle_next.json"])

    def test_required_direction_finishes_small_page_without_duplicate_acquire(self):
        r, _, _ = self.make_residency()
        r.cache.entries.clear()
        key = "idle", "0"
        page_key = ("color",)
        request = {"file": "color", "codec": "rgba_zlib", "width": 4, "height": 4}
        stage = r.prefetch = DirectionPrefetch(key, {"pages": {"color": page_key}}, {page_key: request})
        events = []

        def steps():
            events.append("read")
            yield
            events.append("decode")

        work = SimpleNamespace(take_result=lambda: "prepared")
        pending = steps()
        next(pending)
        stage.small_jobs[page_key] = work, pending

        def acquire(page, directory, *, prepared=None):
            self.assertEqual(prepared, "prepared")
            r.cache.entries[page_key] = {"gl_texture": 1}

        r.cache.acquire.side_effect = acquire
        r.require((key,))
        self.assertEqual(events, ["read", "decode"])
        self.assertEqual(r.loads, 1)
        self.assertIsNone(r.prefetch)
        self.assertIn(key, r.resources)
        r.cache.acquire.assert_called_once()
