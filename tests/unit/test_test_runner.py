import io
import sys
import types
import unittest
from pathlib import Path
from typing import Dict, List


TESTS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS_ROOT))

import run_tests  # noqa: E402


def _case(kind: str) -> unittest.TestCase:
    def run_test(self: unittest.TestCase) -> None:
        if kind == "failure":
            self.fail("measured failure")
        if kind == "error":
            raise RuntimeError("measured error")

    if kind == "skip":
        run_test = unittest.skip("mandatory tool unavailable")(run_test)
    if kind == "expected_failure":
        run_test = unittest.expectedFailure(lambda self: self.fail("known defect"))
    if kind == "unexpected_success":
        run_test = unittest.expectedFailure(lambda self: None)
    case_type = type("SyntheticTest", (unittest.TestCase,), {"runTest": run_test})
    return case_type()


def _module(name: str, case: unittest.TestCase) -> types.ModuleType:
    module = types.ModuleType(name)
    module.Case = type("Case", (case.__class__,), {"__module__": name})
    return module


class TestUnifiedRunner(unittest.TestCase):
    def _run(self, cases: Dict[str, unittest.TestCase]) -> run_tests.RunSummary:
        invoked: List[str] = []

        def importer(name: str) -> object:
            invoked.append(name)
            return _module(name, cases[name])

        summary = run_tests.run_mandatory_tests(
            stream=io.StringIO(), importer=importer
        )
        self.assertEqual(invoked, list(run_tests.MANDATORY_MODULES))
        return summary

    def test_all_mandatory_modules_run_in_fixed_order_and_clean_is_green(self) -> None:
        summary = self._run(
            {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        )
        self.assertTrue(summary.passed)
        self.assertEqual(summary.tests_run, 4)
        self.assertEqual(summary.to_dict()["status"], "PASS")

    def test_failure_is_non_green_without_stopping_later_modules(self) -> None:
        cases = {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        cases[run_tests.MANDATORY_MODULES[1]] = _case("failure")
        summary = self._run(cases)
        self.assertFalse(summary.passed)
        self.assertEqual(summary.tests_run, 4)
        self.assertEqual(summary.modules[1].failures, 1)

    def test_error_is_non_green(self) -> None:
        cases = {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        cases[run_tests.MANDATORY_MODULES[2]] = _case("error")
        summary = self._run(cases)
        self.assertFalse(summary.passed)
        self.assertEqual(summary.modules[2].errors, 1)

    def test_skip_is_non_green(self) -> None:
        cases = {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        cases[run_tests.MANDATORY_MODULES[3]] = _case("skip")
        summary = self._run(cases)
        self.assertFalse(summary.passed)
        self.assertEqual(summary.modules[3].skipped, 1)

    def test_expected_failure_is_non_green(self) -> None:
        cases = {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        cases[run_tests.MANDATORY_MODULES[0]] = _case("expected_failure")
        summary = self._run(cases)
        self.assertFalse(summary.passed)
        self.assertEqual(summary.modules[0].expected_failures, 1)

    def test_unexpected_success_is_non_green(self) -> None:
        cases = {name: _case("pass") for name in run_tests.MANDATORY_MODULES}
        cases[run_tests.MANDATORY_MODULES[0]] = _case("unexpected_success")
        summary = self._run(cases)
        self.assertFalse(summary.passed)
        self.assertEqual(summary.modules[0].unexpected_successes, 1)

    def test_load_error_and_empty_module_are_non_green_and_do_not_short_circuit(self) -> None:
        invoked: List[str] = []

        def importer(name: str) -> object:
            invoked.append(name)
            if name == run_tests.MANDATORY_MODULES[0]:
                raise ImportError("fixture unavailable")
            if name == run_tests.MANDATORY_MODULES[1]:
                return types.ModuleType(name)
            return _module(name, _case("pass"))

        summary = run_tests.run_mandatory_tests(
            stream=io.StringIO(), importer=importer
        )
        self.assertEqual(invoked, list(run_tests.MANDATORY_MODULES))
        self.assertFalse(summary.passed)
        self.assertEqual(summary.modules[0].load_errors, 1)
        self.assertEqual(summary.modules[1].tests_run, 0)


if __name__ == "__main__":
    unittest.main()
