from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from jm_app.tasks import library_tool_tasks
from jm_app.tasks.library_tool_tasks import LibraryToolWorker


class LibraryToolTasksTest(unittest.TestCase):
    def test_external_super_resolution_normalizes_paths_and_scale(self):
        worker = LibraryToolWorker(
            "external_sr",
            {
                "paths": ["input one.png", "input&two.png"],
                "output_dir": "output dir",
                "command": "tool.exe {input} {output}",
            },
        )
        with patch.object(
            library_tool_tasks,
            "run_external_super_resolution",
            return_value=[Path("output dir/result.png")],
        ) as run_external:
            result = worker._execute_action()

        self.assertEqual(result, [Path("output dir/result.png")])
        run_external.assert_called_once_with(
            [Path("input one.png"), Path("input&two.png")],
            Path("output dir"),
            "tool.exe {input} {output}",
        )

    def test_webdav_action_maps_credentials_without_transforming_them(self):
        worker = LibraryToolWorker(
            "webdav",
            {
                "source": "archive.cbz",
                "base_url": "https://dav.example.test",
                "remote_path": "漫画/archive.cbz",
                "username": "reader",
                "password": "secret&value",
            },
        )
        with patch.object(
            library_tool_tasks, "upload_webdav", return_value="uploaded"
        ) as upload:
            result = worker._execute_action()

        self.assertEqual(result, "uploaded")
        upload.assert_called_once_with(
            Path("archive.cbz"),
            "https://dav.example.test",
            "漫画/archive.cbz",
            "reader",
            "secret&value",
        )

    def test_unknown_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知工具操作"):
            LibraryToolWorker("unknown", {})._execute_action()


if __name__ == "__main__":
    unittest.main()
