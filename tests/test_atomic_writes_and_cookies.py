from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_pet.src import atomic_write as desktop_pet_atomic_write
from jm_app.backend import atomic_write, cookie_store, credential_store


def _acquire_path_lock(path: str, ready, acquired) -> None:
    ready.set()
    with atomic_write.exclusive_path_lock(Path(path)):
        acquired.set()


class AtomicWriteTest(unittest.TestCase):
    def test_concurrent_writers_use_distinct_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "config.json"
            barrier = threading.Barrier(2)
            sources = []
            errors = []
            real_replace = os.replace

            def delayed_replace(source, target):
                sources.append(Path(source))
                time.sleep(0.02)
                real_replace(source, target)

            def write(payload):
                try:
                    barrier.wait(timeout=5)
                    atomic_write.atomic_write_json(destination, payload, indent=2)
                except Exception as exc:  # Captured for an assertion in the main thread.
                    errors.append(exc)

            with patch.object(atomic_write.os, "replace", side_effect=delayed_replace):
                threads = [
                    threading.Thread(target=write, args=({"writer": writer},))
                    for writer in ("first", "second")
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)

            self.assertFalse(errors)
            self.assertEqual(len(set(sources)), 2)
            self.assertIn(json.loads(destination.read_text(encoding="utf-8"))["writer"], {"first", "second"})
            self.assertEqual(list(destination.parent.glob(f".{destination.name}.*.tmp")), [])

    def test_failed_replace_cleans_unique_temporary_file(self):
        for module in (atomic_write, desktop_pet_atomic_write):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / "settings.json"
                destination.write_text("old", encoding="utf-8")

                with patch.object(module.os, "replace", side_effect=PermissionError("locked")):
                    with self.assertRaises(PermissionError):
                        module.atomic_write_json(destination, {"value": "new"})

                self.assertEqual(destination.read_text(encoding="utf-8"), "old")
                self.assertEqual(
                    list(destination.parent.glob(f".{destination.name}.*.tmp")), []
                )

    def test_path_lock_serializes_a_spawned_process(self):
        if os.name != "nt":
            self.skipTest("exercises the Windows msvcrt lock implementation")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "credentials.json"
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            acquired = context.Event()
            process = context.Process(
                target=_acquire_path_lock,
                args=(str(destination), ready, acquired),
            )

            with atomic_write.exclusive_path_lock(destination):
                process.start()
                self.assertTrue(ready.wait(timeout=5))
                self.assertFalse(acquired.wait(timeout=0.3))
            self.assertTrue(acquired.wait(timeout=5))
            process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)


class CookieStoreTest(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            self.skipTest("requires Windows DPAPI support")

    def test_cookie_is_dpapi_protected_and_plaintext_file_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_file = root / "session" / "cookies.json"
            with (
                patch.object(credential_store, "app_data_dir", return_value=root),
                patch.object(cookie_store, "COOKIE_FILE", legacy_file),
            ):
                cookie_store.save_cookie_dict({"AVS": "sensitive-cookie"})

                self.assertEqual(cookie_store.load_cookie_dict(), {"AVS": "sensitive-cookie"})
                self.assertFalse(legacy_file.exists())
                encrypted_payload = (root / "credentials.json").read_text(encoding="utf-8")
                self.assertNotIn("AVS", encrypted_payload)
                self.assertNotIn("sensitive-cookie", encrypted_payload)

    def test_concurrent_credential_updates_preserve_every_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_atomic_write = credential_store.atomic_write_json

            def slow_atomic_write(*args, **kwargs):
                time.sleep(0.02)
                real_atomic_write(*args, **kwargs)

            with (
                patch.object(credential_store, "app_data_dir", return_value=root),
                patch.object(credential_store, "_protect", side_effect=lambda value: f"encrypted-{value}"),
                patch.object(credential_store, "atomic_write_json", side_effect=slow_atomic_write),
            ):
                threads = [
                    threading.Thread(
                        target=credential_store.set_secret,
                        args=(f"key-{index}", f"value-{index}"),
                    )
                    for index in range(8)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)

            stored = json.loads((root / "credentials.json").read_text(encoding="utf-8"))
            self.assertEqual(set(stored), {f"key-{index}" for index in range(8)})

    def test_plaintext_cookie_file_is_migrated_on_first_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_file = root / "session" / "cookies.json"
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_text(
                json.dumps({"AVS": "legacy-cookie"}), encoding="utf-8"
            )
            with (
                patch.object(credential_store, "app_data_dir", return_value=root),
                patch.object(cookie_store, "COOKIE_FILE", legacy_file),
            ):
                self.assertEqual(cookie_store.load_cookie_dict(), {"AVS": "legacy-cookie"})
                self.assertFalse(legacy_file.exists())
                self.assertEqual(cookie_store.load_cookie_dict(), {"AVS": "legacy-cookie"})

    def test_protected_cookie_read_retries_lingering_plaintext_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_file = Path(directory) / "cookies.json"
            legacy_file.write_text('{"AVS": "legacy-cookie"}', encoding="utf-8")
            with (
                patch.object(cookie_store, "COOKIE_FILE", legacy_file),
                patch.object(
                    cookie_store,
                    "get_secret",
                    return_value='{"AVS": "protected-cookie"}',
                ),
            ):
                self.assertEqual(
                    cookie_store.load_cookie_dict(), {"AVS": "protected-cookie"}
                )
                self.assertFalse(legacy_file.exists())

    def test_plaintext_cookie_is_kept_when_dpapi_migration_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_file = Path(directory) / "cookies.json"
            legacy_file.write_text('{"AVS": "legacy-cookie"}', encoding="utf-8")
            with (
                patch.object(cookie_store, "COOKIE_FILE", legacy_file),
                patch.object(cookie_store, "get_secret", return_value=""),
                patch.object(cookie_store, "set_secret", side_effect=OSError("DPAPI unavailable")),
            ):
                self.assertEqual(cookie_store.load_cookie_dict(), {"AVS": "legacy-cookie"})
                self.assertTrue(legacy_file.exists())


if __name__ == "__main__":
    unittest.main()
