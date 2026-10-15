"""Worker entry point: runs the background job loop.

The loop, the job registry and graceful shutdown are implemented here. The jobs
themselves arrive with their own tasks - the outbox relay (T033), approval expiry
(T066), evaluation (T090) and retention (T108) - so until those land the registry
is empty and the worker says so explicitly rather than appearing productive.

Standard library only on purpose: the entry point must be importable and
testable before the persistence libraries it will eventually drive are wired in.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable, Sequence

logger = logging.getLogger("gov.worker")

#: A job is a callable that performs one pass over its work. Jobs must be
#: idempotent, because a worker can be interrupted between passes.
Job = Callable[[], None]

DEFAULT_POLL_SECONDS = 5.0


def build_jobs() -> tuple[Job, ...]:
    """Return the jobs this worker should run.

    Empty until the job implementations land (T033, T066, T090, T108). The
    function exists now so that registering a job is a one-line change in a
    known place rather than a rewrite of the loop.
    """
    return ()


class Worker:
    """Runs registered jobs in a loop until asked to stop."""

    def __init__(
        self,
        *,
        jobs: Sequence[Job] = (),
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._jobs = tuple(jobs)
        self._poll_seconds = poll_seconds
        self._stopping = False

    @property
    def job_count(self) -> int:
        return len(self._jobs)

    def request_stop(self) -> None:
        """Ask the loop to finish the current pass and exit."""
        self._stopping = True

    @property
    def stopping(self) -> bool:
        return self._stopping

    def run_once(self) -> int:
        """Run every job once, returning how many completed successfully.

        A failing job is logged and skipped: one broken job must not stop the
        others, and the failure stays visible rather than being swallowed.
        """
        completed = 0
        for job in self._jobs:
            try:
                job()
            except Exception:
                logger.exception("job %r failed", getattr(job, "__name__", job))
                continue
            completed += 1
        return completed

    def run(self, *, max_passes: int | None = None) -> int:
        """Run the loop until stopped, or for a bounded number of passes."""
        if not self._jobs:
            logger.warning(
                "no jobs registered; job implementations arrive with T033, T066, "
                "T090 and T108"
            )
        passes = 0
        while not self._stopping:
            self.run_once()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                break
            if self._stopping:
                break
            time.sleep(self._poll_seconds)
        logger.info("worker stopped after %d passes", passes)
        return passes


def _install_signal_handlers(worker: Worker) -> None:
    def _handle(signum: int, _frame: object) -> None:
        logger.info("received signal %s; finishing the current pass", signum)
        worker.request_stop()

    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                signal.signal(number, _handle)
            except (ValueError, OSError):
                # Not the main thread, or the platform does not support it.
                continue


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = Worker(jobs=build_jobs())
    _install_signal_handlers(worker)
    worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
