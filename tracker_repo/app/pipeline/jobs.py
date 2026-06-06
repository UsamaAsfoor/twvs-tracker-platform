"""Persistent job state for admin scrape/pipeline runs."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.config import ADMIN_STATE_DIR, ensure_dirs


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class JobStore:
    def __init__(self) -> None:
        ensure_dirs()
        self._path = ADMIN_STATE_DIR / "jobs.json"
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw.get("jobs", []):
                item["status"] = JobStatus(item["status"])
                self._jobs[item["id"]] = Job(**item)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._jobs = {}

    def _save(self) -> None:
        payload = {"jobs": [j.to_dict() for j in self._jobs.values()]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def create(self, kind: str, steps: list[str] | None = None, meta: dict | None = None) -> Job:
        with self._lock:
            job = Job(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                status=JobStatus.PENDING,
                created_at=_now(),
                steps=steps or [],
                meta=meta or {},
            )
            self._jobs[job.id] = job
            self._save()
            return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[Job]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.logs.append(f"[{_now()}] {line}")
            if len(job.logs) > 500:
                job.logs = job.logs[-500:]
            self._save()

    def update(self, job_id: str, **kwargs) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in kwargs.items():
                if key == "status" and isinstance(value, str):
                    value = JobStatus(value)
                setattr(job, key, value)
            self._save()
            return job


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


job_store = JobStore()
