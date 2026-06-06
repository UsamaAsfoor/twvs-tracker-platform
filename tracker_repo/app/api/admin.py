"""Admin endpoints: Patreon session, scrape jobs, schedule."""
from __future__ import annotations

import threading
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_admin
from app.config import DATA_DIR, TRACKER_DIR, anthropic_key
from app.pipeline.jobs import job_store
from app.pipeline.runner import PIPELINE_STEPS, start_job_async
from app.pipeline.schedule import schedule_manager
from app.scraper.patreon import (
    check_session_valid,
    credentials_configured,
    login_headless,
    open_login_browser,
    session_exists,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginStartResponse(BaseModel):
    job_id: str
    message: str


class RunPipelineRequest(BaseModel):
    steps: list[str] = Field(default_factory=lambda: list(PIPELINE_STEPS))


class ScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_hours: Optional[int] = Field(default=None, ge=1, le=168)


@router.get("/status")
def admin_status(_: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    valid, session_msg = check_session_valid()
    schedule = schedule_manager.get()
    engine_path = DATA_DIR / "tracker_allmonths_engine.json"
    standalone = TRACKER_DIR / "tracker_standalone.html"
    return {
        "patreon_session_exists": session_exists(),
        "patreon_session_valid": valid,
        "patreon_message": session_msg,
        "patreon_credentials_configured": credentials_configured(),
        "anthropic_key_configured": bool(anthropic_key()),
        "engine_data_updated": engine_path.stat().st_mtime if engine_path.is_file() else None,
        "standalone_updated": standalone.stat().st_mtime if standalone.is_file() else None,
        "schedule": schedule,
        "available_steps": PIPELINE_STEPS,
    }


@router.post("/patreon/login")
def start_patreon_login(_: Annotated[str, Depends(require_admin)]) -> LoginStartResponse:
    job = job_store.create(kind="patreon_login", steps=["login"])

    def _run() -> None:
        from app.pipeline.jobs import JobStatus

        job_store.update(job.id, status=JobStatus.RUNNING)
        ok, msg = open_login_browser(log=lambda m: job_store.append_log(job.id, m))
        from datetime import datetime, timezone

        job_store.update(
            job.id,
            status=JobStatus.SUCCESS if ok else JobStatus.FAILED,
            error=None if ok else msg,
            finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        job_store.append_log(job.id, msg)

    threading.Thread(target=_run, daemon=True).start()
    return LoginStartResponse(
        job_id=job.id,
        message="Browser opened. Log into Patreon with email + password, then wait for confirmation.",
    )


@router.post("/patreon/login-headless")
def start_patreon_login_headless(_: Annotated[str, Depends(require_admin)]) -> LoginStartResponse:
    if not credentials_configured():
        raise HTTPException(
            400,
            "Set PATREON_EMAIL and PATREON_PASSWORD as Fly secrets before using headless login.",
        )

    job = job_store.create(kind="patreon_login_headless", steps=["login"])

    def _run() -> None:
        from app.pipeline.jobs import JobStatus
        from datetime import datetime, timezone

        job_store.update(job.id, status=JobStatus.RUNNING)
        ok, msg = login_headless(log=lambda m: job_store.append_log(job.id, m))
        job_store.update(
            job.id,
            status=JobStatus.SUCCESS if ok else JobStatus.FAILED,
            error=None if ok else msg,
            finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        job_store.append_log(job.id, msg)

    threading.Thread(target=_run, daemon=True).start()
    return LoginStartResponse(
        job_id=job.id,
        message="Headless Patreon login started. Watch the job log for progress.",
    )


@router.get("/patreon/session")
def patreon_session(_: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    valid, msg = check_session_valid()
    return {"exists": session_exists(), "valid": valid, "message": msg}


@router.post("/pipeline/run")
def run_pipeline(
    body: RunPipelineRequest,
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, str]:
    steps = [s for s in body.steps if s in PIPELINE_STEPS]
    if not steps:
        raise HTTPException(400, f"No valid steps. Choose from: {PIPELINE_STEPS}")
    job_id = start_job_async("manual_pipeline", steps, meta={"trigger": "manual"})
    return {"job_id": job_id, "message": "Pipeline started.", "steps": steps}


@router.get("/jobs")
def list_jobs(_: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    return {"jobs": [j.to_dict() for j in job_store.list_jobs(30)]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, _: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@router.get("/schedule")
def get_schedule(_: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    return schedule_manager.get()


@router.put("/schedule")
def update_schedule(
    body: ScheduleUpdateRequest,
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, Any]:
    return schedule_manager.update(enabled=body.enabled, interval_hours=body.interval_hours)
