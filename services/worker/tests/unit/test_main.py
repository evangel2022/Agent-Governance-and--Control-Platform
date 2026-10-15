"""Tests for the worker entry point and job loop (T123)."""

from __future__ import annotations

import pytest

from gov.worker.main import Worker, build_jobs


def test_no_jobs_are_registered_yet_and_that_is_deliberate() -> None:
    """The job implementations arrive with T033, T066, T090 and T108."""
    assert build_jobs() == ()


def test_a_worker_reports_how_many_jobs_it_has() -> None:
    assert Worker(jobs=[lambda: None, lambda: None]).job_count == 2
    assert Worker().job_count == 0


def test_run_once_runs_every_job_and_counts_the_successes() -> None:
    calls: list[str] = []
    worker = Worker(
        jobs=[
            lambda: calls.append("a"),
            lambda: calls.append("b"),
        ]
    )
    assert worker.run_once() == 2
    assert calls == ["a", "b"]


def test_a_failing_job_does_not_stop_the_others() -> None:
    completed: list[str] = []

    def broken() -> None:
        raise RuntimeError("job blew up")

    worker = Worker(jobs=[broken, lambda: completed.append("after")])
    assert worker.run_once() == 1
    assert completed == ["after"]


def test_the_loop_runs_a_bounded_number_of_passes() -> None:
    passes_seen = 0

    def job() -> None:
        nonlocal passes_seen
        passes_seen += 1

    worker = Worker(jobs=[job], poll_seconds=0.001)
    assert worker.run(max_passes=3) == 3
    assert passes_seen == 3


def test_requesting_stop_ends_the_loop() -> None:
    worker = Worker(jobs=[lambda: worker.request_stop()], poll_seconds=0.001)
    assert worker.run() == 1
    assert worker.stopping is True


def test_poll_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="poll_seconds"):
        Worker(poll_seconds=0)
