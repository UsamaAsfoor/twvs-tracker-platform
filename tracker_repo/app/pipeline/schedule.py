"""Scheduled scrape configuration and APScheduler integration."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import ADMIN_STATE_DIR, DEFAULT_SCHEDULE_HOURS, ensure_dirs
from app.pipeline.jobs import job_store
from app.pipeline.runner import PIPELINE_STEPS, start_job_async


class ScheduleManager:
    def __init__(self) -> None:
        ensure_dirs()
        self._path = ADMIN_STATE_DIR / "schedule.json"
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler(daemon=True)
        self._config = self._default_config()
        self._load()

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "enabled": False,
            "interval_hours": DEFAULT_SCHEDULE_HOURS,
            "steps": PIPELINE_STEPS,
            "last_run_at": None,
            "last_job_id": None,
            "next_run_at": None,
        }

    def _load(self) -> None:
        if self._path.is_file():
            try:
                self._config = {**self._default_config(), **json.loads(self._path.read_text())}
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._config, indent=2), encoding="utf-8")

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._config)

    def update(self, *, enabled: Optional[bool] = None, interval_hours: Optional[int] = None) -> dict[str, Any]:
        with self._lock:
            if enabled is not None:
                self._config["enabled"] = enabled
            if interval_hours is not None:
                self._config["interval_hours"] = max(1, min(interval_hours, 168))
            self._save()
            self._apply_scheduler()
            return dict(self._config)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
        self._apply_scheduler()

    def _apply_scheduler(self) -> None:
        self._scheduler.remove_all_jobs()
        if not self._config.get("enabled"):
            self._config["next_run_at"] = None
            self._save()
            return

        hours = int(self._config.get("interval_hours", DEFAULT_SCHEDULE_HOURS))
        self._scheduler.add_job(
            self._run_scheduled,
            trigger=IntervalTrigger(hours=hours),
            id="scrape_pipeline",
            replace_existing=True,
        )
        job = self._scheduler.get_job("scrape_pipeline")
        if job and job.next_run_time:
            self._config["next_run_at"] = job.next_run_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        self._save()

    def _run_scheduled(self) -> None:
        steps = self._config.get("steps", PIPELINE_STEPS)
        job_id = start_job_async("scheduled_pipeline", steps, meta={"trigger": "schedule"})
        with self._lock:
            self._config["last_run_at"] = _now()
            self._config["last_job_id"] = job_id
            self._save()
        job_store.append_log(job_id, "Started by scheduler.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


schedule_manager = ScheduleManager()
