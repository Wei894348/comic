from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from desktop_pet.src import credential_store


class DesktopPetCredentialStoreTest(unittest.TestCase):
    def test_dpapi_round_trip_writes_only_ciphertext(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"LOCALAPPDATA": directory}
        ):
            self.assertTrue(credential_store.save_secret("ai_api_key", "secret-value"))
            path = credential_store.credential_file()
            payload = path.read_text(encoding="utf-8")

            self.assertNotIn("secret-value", payload)
            self.assertEqual(
                credential_store.load_secret("ai_api_key"), "secret-value"
            )

    def test_empty_value_removes_secret_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"LOCALAPPDATA": directory}
        ):
            self.assertTrue(credential_store.save_secret("ai_api_key", "secret-value"))
            self.assertTrue(credential_store.save_secret("ai_api_key", ""))
            self.assertFalse(credential_store.credential_file().exists())


if __name__ == "__main__":
    unittest.main()
