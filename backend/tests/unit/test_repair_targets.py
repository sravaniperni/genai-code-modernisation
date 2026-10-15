"""Which files a repair prompt shows when the editable-content budget cannot hold every candidate."""

from __future__ import annotations

from modernisation.agents.workflow import WorkflowEngine

REPORT = """Problems: 2 new test failure(s)

FAILED tests.test_resample::test_mean: AttributeError: module 'numpy' has no attribute 'float_'
tests/test_resample.py:9: in test_mean
    assert resample(xs) == 2.0
src/pkg/resample.py:42: in resample
    return np.float_(x)
/env/lib/python3.12/site-packages/numpy/__init__.py:400: in __getattr__
  File "/work/src/pkg/anomaly.py", line 3
../outside/x.py:1: in f

FAILED tests.test_cal.TestCal::test_fit: assert 1 == 2
"""
EXISTING = {
    "src/pkg/resample.py",
    "src/pkg/anomaly.py",
    "src/pkg/calibration.py",
    "pyproject.toml",
    "tests/test_resample.py",
    "tests/test_cal.py",
}


def test_report_paths_are_repository_relative_and_never_escape():
    paths = WorkflowEngine._report_paths(REPORT)
    assert paths[:3] == ["tests/test_resample.py", "src/pkg/resample.py", "src/pkg/anomaly.py"]
    assert not any(p.startswith(("env/", "/")) or ".." in p for p in paths)


def test_failing_test_paths_use_the_longest_existing_module_path():
    assert WorkflowEngine._failing_test_paths(REPORT, EXISTING.__contains__) == [
        "tests/test_resample.py",
        "tests/test_cal.py",
    ]


def test_repair_targets_put_implicated_and_untouched_files_before_already_changed_ones():
    targets = WorkflowEngine._repair_targets(
        plan_targets=["pyproject.toml", "src/pkg/calibration.py", "src/pkg/resample.py"],
        changed=["pyproject.toml", "src/pkg/calibration.py"],
        check_report=REPORT,
        exists=EXISTING.__contains__,
    )
    assert targets == [
        "src/pkg/resample.py",  # named by the traceback
        "src/pkg/anomaly.py",  # named by the traceback, not in the plan
        "pyproject.toml",  # already changed
        "src/pkg/calibration.py",
        "tests/test_resample.py",  # failing tests last
        "tests/test_cal.py",
    ]
