from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jm_app.backend.jm_endpoints import API_DOMAINS, IMAGE_DOMAINS
from jm_app.frontend.state_persistence import StatePersistenceMixin


class _HistoryStore:
    def load_history(self):
        return []

    def replace_history(self, _history):
        raise AssertionError("empty history should not be migrated")


class _PersistenceHarness:
    load_local_cache = StatePersistenceMixin.load_local_cache
    _log_local_state_warning = StatePersistenceMixin._log_local_state_warning

    def __init__(self, root: Path):
        self.cache_file = root / "cache.json"
        self.settings_file = root / "config.json"
        self.api_domain_pool = list(API_DOMAINS)
        self.cover_domain_pool = list(IMAGE_DOMAINS)
        self.history_store = _HistoryStore()
        self.warnings = []

    @staticmethod
    def normalize_history_records(records):
        return list(records)

    def log(self, message: str):
        self.warnings.append(message)


class StatePersistenceTest(unittest.TestCase):
    def test_invalid_failure_counter_does_not_discard_valid_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = _PersistenceHarness(root)
            harness.cache_file.write_text(
                json.dumps({"cover_domain_failures": {"bad": "not-an-int"}}),
                encoding="utf-8",
            )
            expected_settings = {"theme_dark": True, "settings_version": 3}
            harness.settings_file.write_text(
                json.dumps(expected_settings), encoding="utf-8"
            )

            harness.load_local_cache()

        self.assertEqual(harness.settings_cache, expected_settings)
        self.assertEqual(harness.cover_domain_failures, {})
        self.assertTrue(any("封面域名失败次数无效" in warning for warning in harness.warnings))


if __name__ == "__main__":
    unittest.main()
