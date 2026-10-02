"""Register quality tests without tying them to either generator API."""

from __future__ import annotations

from collections.abc import Callable

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import TestResult


TestFunction = Callable[[MotionSequence, dict], TestResult]


class TestRegistry:
    def __init__(self) -> None:
        self._tests: dict[str, TestFunction] = {}

    def register(self, name: str, function: TestFunction) -> None:
        if not name or name in self._tests:
            raise ValueError(f"Duplicate or empty test name: {name!r}")
        self._tests[name] = function

    def run(self, name: str, motion: MotionSequence, settings: dict) -> TestResult:
        try:
            function = self._tests[name]
        except KeyError as exc:
            raise KeyError(f"Unknown MotionLint test: {name}") from exc
        result = function(motion, settings)
        if result.test_name != name:
            raise ValueError(f"Test {name} returned result for {result.test_name}")
        return result

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tests)
