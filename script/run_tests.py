"""Stable local/CI test entry point for the Qt application.

QtWebEngine, application-wide styles and QUiLoader widgets can leave native
process state behind even after Python objects are closed. Test files run in
separate processes; a file that crashes is retried per nodeid so real assertion
failures remain visible while native cross-test contamination is isolated.
"""

from __future__ import annotations

import os
import logging
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("COMIC18_TESTING", "1")

from script.downloader import ensure_qt_plugin_path


PYTEST_EXIT_CODES = frozenset(range(6))
STRICT_FILE_PROCESS_OPTION = "--strict-file-process"
STRICT_FILE_PROCESS_ENV = "COMIC18_STRICT_FILE_PROCESS"
ISOLATION_SAFE_OPTIONS = frozenset(
    {
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "-s",
        "-x",
        "--exitfirst",
        "--disable-warnings",
        "--no-header",
        "--no-summary",
    }
)


def _direct_pytest(arguments: List[str]) -> int:
    ensure_qt_plugin_path()
    import pytest

    try:
        return int(pytest.main(arguments))
    finally:
        logging.shutdown()


def _test_files(targets: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for target in targets:
        path = Path(target)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_dir():
            files.extend(sorted(path.rglob("test_*.py")))
        elif path.is_file() and path.name.startswith("test_") and path.suffix == ".py":
            files.append(path)
    unique = {path.resolve(): path.resolve() for path in files}
    return sorted(unique.values(), key=lambda path: str(path).lower())


def _supports_file_isolation(arguments: Iterable[str]) -> bool:
    """Keep selection-changing or value-taking pytest options fully native."""
    for argument in arguments:
        if not argument.startswith("-"):
            continue
        if argument in ISOLATION_SAFE_OPTIONS:
            continue
        if argument.startswith("-r") and len(argument) > 2:
            continue
        if argument.startswith(("--tb=", "--color=", "--capture=")):
            continue
        if len(argument) > 1 and argument[0] == "-" and set(argument[1:]) <= {"q", "v"}:
            continue
        return False
    return True


def _child(arguments: List[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    command = [sys.executable, str(Path(__file__).resolve()), "--direct", *arguments]
    return subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=capture,
        env=os.environ.copy(),
        check=False,
    )


def _collect_nodeids(test_file: Path) -> List[str]:
    result = _child([str(test_file), "--collect-only", "-q"], capture=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return []
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("=", "<"))
    ]


def _run_isolated_file(
    test_file: Path,
    options: List[str],
    *,
    recover_native_crash: bool = True,
) -> int:
    try:
        relative = test_file.relative_to(ROOT)
    except ValueError:
        relative = test_file
    print(f"\n=== {relative} ===", flush=True)
    result = _child([str(test_file), *options])
    if result.returncode == 0:
        return 0
    if result.returncode in PYTEST_EXIT_CODES:
        return result.returncode
    if not recover_native_crash:
        print(
            f"{relative} crashed in its shared file process "
            f"(exit code {result.returncode}); strict mode disables isolated retries.",
            file=sys.stderr,
            flush=True,
        )
        return result.returncode or 1

    nodeids = _collect_nodeids(test_file)
    if not nodeids:
        return result.returncode or 1
    print(
        f"{relative} failed in a shared process; retrying {len(nodeids)} isolated tests.",
        flush=True,
    )
    failures = 0
    retry_options = [option for option in options if option not in {"-x", "--exitfirst"}]
    for nodeid in nodeids:
        print(f"--- isolated: {nodeid}", flush=True)
        returncode = _child([nodeid, *retry_options]).returncode
        if returncode != 0:
            print(f"FAILED ({returncode}): {nodeid}", file=sys.stderr, flush=True)
            failures += 1
    return 1 if failures else 0


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "--direct":
        return _direct_pytest(arguments[1:])
    strict_file_process = STRICT_FILE_PROCESS_OPTION in arguments or os.environ.get(
        STRICT_FILE_PROCESS_ENV, ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    arguments = [
        argument for argument in arguments if argument != STRICT_FILE_PROCESS_OPTION
    ]
    if not _supports_file_isolation(arguments):
        return _direct_pytest(arguments or ["tests"])
    # A nodeid is already the narrowest possible pytest target.  It cannot be
    # resolved as a filesystem path, so preserve it instead of treating the
    # entire test suite as the implicit target set.
    if any("::" in argument for argument in arguments):
        return _direct_pytest(arguments)

    explicit_targets = [argument for argument in arguments if (ROOT / argument).exists()]
    options = [argument for argument in arguments if argument not in explicit_targets]
    files = _test_files(explicit_targets or ["tests"])
    if not files:
        return _direct_pytest(arguments or ["tests"])

    failed_files = []
    for test_file in files:
        if _run_isolated_file(
            test_file,
            options,
            recover_native_crash=not strict_file_process,
        ) != 0:
            try:
                failed_files.append(test_file.relative_to(ROOT))
            except ValueError:
                failed_files.append(test_file)
            if "-x" in options or "--exitfirst" in options:
                break
    if failed_files:
        print("\nFailed test files:", ", ".join(map(str, failed_files)), file=sys.stderr)
        return 1
    print(f"\nAll {len(files)} test files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
