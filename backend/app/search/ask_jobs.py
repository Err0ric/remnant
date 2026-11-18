"""Ask as a background job (D269): a submit returns at once with a job id, the work runs
on, and the asker polls for what is done so far. Jobs live in memory only, like the
answers in `ask_runs` (none survives a restart), bounded in count and age, and each is
readable only by the person who submitted it."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from app.core.errors import NotFoundError, RateLimitedError

KEEP_FOR = timedelta(minutes=30)  # after the job finishes (ask_runs.KEEP_FOR)
KEEP_AT_MOST = 200  # finished jobs kept; the oldest go first
RUNNING_AT_MOST = 16  # jobs running at once in this process (one per person besides)

StepName = Literal["sql", "run", "summary"]
StepState = Literal["running", "done", "failed", "timed_out"]


@dataclass(slots=True)
class JobStep:
    name: StepName
    state: StepState = "running"
    ms: int | None = None
    error: tuple[str, str] | None = None  # (code, message), as the HTTP error would say
    started: float = field(default_factory=time.monotonic, repr=False)


@dataclass(slots=True)
class AskJob:
    job_id: str
    user_id: str
    at: datetime
    state: Literal["running", "done", "failed"] = "running"
    finished_at: datetime | None = None
    steps: list[JobStep] = field(default_factory=list)
    # The API's own response models, set as each step finishes.
    ask: BaseModel | None = None
    result: BaseModel | None = None
    summary: BaseModel | None = None
    error: tuple[str, str] | None = None


class AskJobs:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._jobs: OrderedDict[str, AskJob] = OrderedDict()

    def start(self, user_id: str, now: datetime) -> AskJob:
        job = AskJob(str(uuid.uuid4()), user_id, now)
        with self.lock:
            self._prune(now)
            if sum(1 for j in self._jobs.values() if j.state == "running") >= RUNNING_AT_MOST:
                raise RateLimitedError("Too many questions are running. Try again in a moment.", 5)
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str, user_id: str, now: datetime) -> AskJob:
        """The job, only for the person who submitted it and only while it is kept."""
        with self.lock:
            job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id or _expired(job, now):
            raise NotFoundError("That question has expired. Ask again.")
        return job

    def begin(self, job: AskJob, name: StepName) -> JobStep:
        step = JobStep(name)
        with self.lock:
            job.steps.append(step)
        return step

    def end(
        self, job: AskJob, step: JobStep, state: StepState, error: tuple[str, str] | None = None
    ) -> None:
        with self.lock:
            step.state, step.error = state, error
            step.ms = round((time.monotonic() - step.started) * 1000)

    def finish(self, job: AskJob, now: datetime, error: tuple[str, str] | None = None) -> None:
        with self.lock:
            job.state, job.error = ("failed", error) if error else ("done", None)
            job.finished_at = now

    def __len__(self) -> int:
        with self.lock:
            return len(self._jobs)

    def _prune(self, now: datetime) -> None:
        for job_id in [k for k, j in self._jobs.items() if _expired(j, now)]:
            del self._jobs[job_id]
        done = [k for k, j in self._jobs.items() if j.state != "running"]
        for job_id in done[: max(0, len(self._jobs) - KEEP_AT_MOST)]:
            del self._jobs[job_id]


def _expired(job: AskJob, now: datetime) -> bool:
    """A finished job is kept KEEP_FOR from when it finished; a running one is bounded by
    RUNNING_AT_MOST and the model time limits."""
    return job.finished_at is not None and now - job.finished_at > KEEP_FOR
