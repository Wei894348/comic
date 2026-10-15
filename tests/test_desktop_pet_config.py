from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DesktopPetConfigTest(unittest.TestCase):
    @staticmethod
    def _isolated_pet_import():
        pet_root = Path(__file__).resolve().parents[1] / "src" / "desktop_pet"
        original_path = list(sys.path)
        original_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "src" or name.startswith("src.")
        }
        for name in original_modules:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(pet_root))
        return original_path, original_modules

    @staticmethod
    def _restore_import_state(original_path, original_modules):
        for name in list(sys.modules):
            if name == "src" or name.startswith("src."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)
        sys.path[:] = original_path

    def test_legacy_non_secret_config_moves_to_comic18_user_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_root = root / "legacy-appdata"
            legacy_root.mkdir()
            (legacy_root / "ameath_config.json").write_text(
                json.dumps({"scale_index": 5, "ai_enabled": True}), encoding="utf-8"
            )
            user_data = root / "user-data"
            original_path, original_modules = self._isolated_pet_import()
            try:
                with patch.dict(
                    os.environ,
                    {
                        "COMIC18_DATA_DIR": str(user_data),
                        "APPDATA": str(legacy_root),
                    },
                ):
                    config_module = importlib.import_module("src.config")
                    config = config_module.load_config(force_refresh=True)
                    constants = importlib.import_module("src.constants")
                    self.assertEqual(config["scale_index"], 5)
                    self.assertTrue(constants.CONFIG_FILE.exists())
                    persisted = json.loads(
                        constants.CONFIG_FILE.read_text(encoding="utf-8")
                    )
                    self.assertNotIn("ai_api_key", persisted)
            finally:
                self._restore_import_state(original_path, original_modules)

    def test_empty_data_override_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            local_app_data = Path(directory) / "local-app-data"
            original_path, original_modules = self._isolated_pet_import()
            try:
                with patch.dict(
                    os.environ,
                    {
                        "COMIC18_DATA_DIR": "",
                        "LOCALAPPDATA": str(local_app_data),
                    },
                ):
                    constants = importlib.import_module("src.constants")
                    self.assertEqual(
                        constants.CONFIG_FILE,
                        local_app_data / "comic18" / "desktop_pet.json",
                    )
            finally:
                self._restore_import_state(original_path, original_modules)


if __name__ == "__main__":
    unittest.main()
