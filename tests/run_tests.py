"""Run the mandatory MADO LOOP P0-P5 integration contract."""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TextIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


MANDATORY_MODULES = (
    "tests.integration.test_p0_p1",
    "tests.integration.test_p2_p3",
    "tests.integration.test_p4",
    "tests.integration.test_p5",
)


@dataclass(frozen=True)
class ModuleResult:
    module: str
    tests_run: int
    failures: int
    errors: int
    skipped: int
    expected_failures: int
    unexpected_successes: int
    load_errors: int

    @property
    def passed(self) -> bool:
        return (
            self.tests_run > 0
            and self.failures == 0
            and self.errors == 0
            and self.skipped == 0
            and self.expected_failures == 0
            and self.unexpected_successes == 0
            and self.load_errors == 0
        )


@dataclass(frozen=True)
class RunSummary:
    modules: List[ModuleResult]

    @property
    def passed(self) -> bool:
        return len(self.modules) == len(MANDATORY_MODULES) and all(
            result.passed for result in self.modules
        )

    @property
    def tests_run(self) -> int:
        return sum(result.tests_run for result in self.modules)

    def to_dict(self) -> dict:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "tests_run": self.tests_run,
            "modules": [
                {**asdict(result), "status": "PASS" if result.passed else "FAIL"}
                for result in self.modules
            ],
        }


def run_mandatory_tests(
    module_names: Sequence[str] = MANDATORY_MODULES,
    *,
    stream: Optional[TextIO] = None,
    importer: Callable[[str], object] = importlib.import_module,
    loader: Optional[unittest.TestLoader] = None,
) -> RunSummary:
    """Run every named module in order and return a testable aggregate."""
    output = stream if stream is not None else sys.stderr
    test_loader = loader if loader is not None else unittest.defaultTestLoader
    collected: List[ModuleResult] = []

    for module_name in module_names:
        output.write(f"\n=== {module_name} ===\n")
        try:
            module = importer(module_name)
            suite = test_loader.loadTestsFromModule(module)
        except Exception as exc:  # keep later mandatory levels runnable
            output.write(f"LOAD ERROR: {type(exc).__name__}: {exc}\n")
            collected.append(ModuleResult(module_name, 0, 0, 0, 0, 0, 0, 1))
            continue

        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
        collected.append(
            ModuleResult(
                module=module_name,
                tests_run=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                skipped=len(result.skipped),
                expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses),
                load_errors=0,
            )
        )

    return RunSummary(collected)


def main() -> int:
    summary = run_mandatory_tests()
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
