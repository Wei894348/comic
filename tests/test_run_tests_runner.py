from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from script import run_tests


class RunTestsRunnerTest(unittest.TestCase):
    test_file = run_tests.ROOT / "tests" / "test_example.py"

    @staticmethod
    def _result(returncode: int) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], returncode)

    def test_assertion_failure_is_not_retried(self):
        with (
            patch.object(run_tests, "_child", return_value=self._result(1)) as child,
            patch.object(run_tests, "_collect_nodeids") as collect_nodeids,
        ):
            result = run_tests._run_isolated_file(self.test_file, ["-x"])

        self.assertEqual(result, 1)
        child.assert_called_once_with([str(self.test_file), "-x"])
        collect_nodeids.assert_not_called()

    def test_native_crash_can_recover_through_isolated_nodeids(self):
        nodeids = [
            "tests/test_example.py::ExampleTest::test_one",
            "tests/test_example.py::ExampleTest::test_two",
        ]
        with (
            patch.object(
                run_tests,
                "_child",
                side_effect=[self._result(0xC0000005), self._result(0), self._result(0)],
            ) as child,
            patch.object(run_tests, "_collect_nodeids", return_value=nodeids) as collect_nodeids,
        ):
            result = run_tests._run_isolated_file(self.test_file, ["-x", "-q"])

        self.assertEqual(result, 0)
        collect_nodeids.assert_called_once_with(self.test_file)
        self.assertEqual(
            child.call_args_list,
            [
                call([str(self.test_file), "-x", "-q"]),
                call([nodeids[0], "-q"]),
                call([nodeids[1], "-q"]),
            ],
        )

    def test_native_crash_remains_failed_when_an_isolated_test_fails(self):
        nodeid = "tests/test_example.py::ExampleTest::test_one"
        with (
            patch.object(
                run_tests,
                "_child",
                side_effect=[self._result(-1073741819), self._result(1)],
            ),
            patch.object(run_tests, "_collect_nodeids", return_value=[nodeid]),
        ):
            result = run_tests._run_isolated_file(self.test_file, [])

        self.assertEqual(result, 1)

    def test_strict_file_process_does_not_retry_a_native_crash(self):
        crash_code = -1073741819
        with (
            patch.object(
                run_tests,
                "_child",
                return_value=self._result(crash_code),
            ) as child,
            patch.object(run_tests, "_collect_nodeids") as collect_nodeids,
        ):
            result = run_tests._run_isolated_file(
                self.test_file,
                ["-q"],
                recover_native_crash=False,
            )

        self.assertEqual(result, crash_code)
        child.assert_called_once_with([str(self.test_file), "-q"])
        collect_nodeids.assert_not_called()

    def test_recursive_directory_target_matches_pytest_collection_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested" / "test_nested.py"
            nested.parent.mkdir()
            nested.write_text("def test_example(): pass\n", encoding="utf-8")

            self.assertEqual(run_tests._test_files([str(root)]), [nested.resolve()])

    def test_selection_option_and_its_value_are_forwarded_unchanged(self):
        arguments = ["--ignore", "tests/test_example.py", "tests"]
        with (
            patch.object(sys, "argv", ["run_tests.py", *arguments]),
            patch.object(run_tests, "_direct_pytest", return_value=0) as direct,
            patch.object(run_tests, "_run_isolated_file") as isolated,
        ):
            result = run_tests.main()

        self.assertEqual(result, 0)
        direct.assert_called_once_with(arguments)
        isolated.assert_not_called()

    def test_nodeid_is_forwarded_directly(self):
        nodeid = "tests/test_example.py::ExampleTest::test_one"
        with (
            patch.object(sys, "argv", ["run_tests.py", nodeid, "-q"]),
            patch.object(run_tests, "_direct_pytest", return_value=0) as direct,
        ):
            result = run_tests.main()

        self.assertEqual(result, 0)
        direct.assert_called_once_with([nodeid, "-q"])

    def test_exitfirst_stops_after_first_failed_file(self):
        files = [
            run_tests.ROOT / "tests" / "test_first.py",
            run_tests.ROOT / "tests" / "test_second.py",
        ]
        with (
            patch.object(sys, "argv", ["run_tests.py", "tests", "-x"]),
            patch.object(run_tests, "_test_files", return_value=files),
            patch.object(run_tests, "_run_isolated_file", side_effect=[1, 0]) as isolated,
        ):
            result = run_tests.main()

        self.assertEqual(result, 1)
        isolated.assert_called_once_with(
            files[0],
            ["-x"],
            recover_native_crash=True,
        )

    def test_strict_runner_option_is_consumed_before_pytest_execution(self):
        files = [run_tests.ROOT / "tests" / "test_first.py"]
        with (
            patch.object(
                sys,
                "argv",
                ["run_tests.py", "tests", run_tests.STRICT_FILE_PROCESS_OPTION, "-q"],
            ),
            patch.object(run_tests, "_test_files", return_value=files),
            patch.object(run_tests, "_run_isolated_file", return_value=0) as isolated,
        ):
            result = run_tests.main()

        self.assertEqual(result, 0)
        isolated.assert_called_once_with(
            files[0],
            ["-q"],
            recover_native_crash=False,
        )


if __name__ == "__main__":
    unittest.main()
