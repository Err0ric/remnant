"""The Ask job store (D269): in memory, bounded in count and age, one person's own."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import NotFoundError, RateLimitedError
from app.search import ask_jobs
from app.search.ask_jobs import KEEP_FOR, AskJobs

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_a_job_is_only_for_the_person_who_submitted_it() -> None:
    jobs = AskJobs()
    job = jobs.start("u-ana", NOW)
    assert jobs.get(job.job_id, "u-ana", NOW) is job
    for other in ("u-bob", "u-admin"):
        with pytest.raises(NotFoundError):
            jobs.get(job.job_id, other, NOW)


def test_finished_jobs_expire_and_running_ones_do_not() -> None:
    jobs = AskJobs()
    done, running = jobs.start("u-ana", NOW), jobs.start("u-bob", NOW)
    jobs.finish(done, NOW)
    later = NOW + KEEP_FOR + timedelta(seconds=1)
    with pytest.raises(NotFoundError):
        jobs.get(done.job_id, "u-ana", later)
    assert jobs.get(running.job_id, "u-bob", later) is running
    jobs.start("u-carol", later)  # each start prunes what expired
    assert len(jobs) == 2


def test_the_store_never_grows_past_its_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask_jobs, "KEEP_AT_MOST", 5)
    jobs = AskJobs()
    for i in range(50):
        jobs.finish(jobs.start(f"u{i}", NOW), NOW)
    assert len(jobs) <= 6  # the bound, plus the one just started


def test_too_many_running_jobs_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask_jobs, "RUNNING_AT_MOST", 2)
    jobs = AskJobs()
    jobs.start("u1", NOW)
    jobs.start("u2", NOW)
    with pytest.raises(RateLimitedError):
        jobs.start("u3", NOW)


def test_steps_record_their_state_time_and_error() -> None:
    jobs = AskJobs()
    job = jobs.start("u-ana", NOW)
    step = jobs.begin(job, "sql")
    assert step.state == "running" and step.ms is None
    jobs.end(job, step, "timed_out", ("model_timeout", "The model took too long."))
    jobs.finish(job, NOW, step.error)
    assert step.ms is not None and job.state == "failed" and job.error == step.error


def test_a_finished_job_is_kept_from_when_it_finished_not_from_submit() -> None:
    jobs = AskJobs()
    job = jobs.start("u-ana", NOW)
    jobs.finish(job, NOW + timedelta(minutes=40))  # a long job
    assert jobs.get(job.job_id, "u-ana", NOW + timedelta(minutes=45)) is job
    assert jobs.get(job.job_id, "u-ana", NOW + timedelta(minutes=40) + KEEP_FOR) is job
    with pytest.raises(NotFoundError):
        jobs.get(job.job_id, "u-ana", NOW + timedelta(minutes=41) + KEEP_FOR)
