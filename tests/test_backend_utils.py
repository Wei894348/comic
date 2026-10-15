from __future__ import annotations

import unittest

from jm_app.backend.utils import dedupe_domains


class BackendUtilsTest(unittest.TestCase):
    def test_dedupe_domains_normalizes_and_preserves_order(self):
        self.assertEqual(
            dedupe_domains(
                ["  api.example.com/ ", "", "api.example.com", "img.example.com//"]
            ),
            ["api.example.com", "img.example.com"],
        )


if __name__ == "__main__":
    unittest.main()
