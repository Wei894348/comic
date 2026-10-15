from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jm_app.backend.library_tools import run_external_super_resolution


class ExternalSuperResolutionTest(unittest.TestCase):
    def test_paths_with_windows_shell_metacharacters_stay_single_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input & (special)"
            root.mkdir(parents=True)
            source = root / "panel & (1).png"
            source.write_bytes(b"image")
            output_dir = Path(directory) / "output & (special)"
            output_dir.mkdir()
            target = output_dir / "panel & (1)_sr.png"
            target.write_bytes(b"result")
            template = f'"{sys.executable}" --input "{{input}}" --output "{{output}}"'

            with patch(
                "jm_app.backend.library_tools.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                outputs = run_external_super_resolution([source], output_dir, template)

            self.assertEqual(outputs, [target])
            command = run.call_args.args[0]
            self.assertEqual(command, [sys.executable, "--input", str(source), "--output", str(target)])
            self.assertIs(run.call_args.kwargs["shell"], False)

    def test_command_interpreter_templates_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "panel.png"
            source.write_bytes(b"image")
            with self.assertRaisesRegex(ValueError, "命令解释器"):
                run_external_super_resolution(
                    [source],
                    Path(directory) / "output",
                    "cmd.exe /c tool --input {input} --output {output}",
                )


if __name__ == "__main__":
    unittest.main()
