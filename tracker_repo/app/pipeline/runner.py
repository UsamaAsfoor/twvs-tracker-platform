"""Run the full data pipeline: scrape → LLM → engine → publish."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from app.config import REPO_ROOT, anthropic_key, ensure_dirs
from app.pipeline.jobs import JobStatus, job_store
from app.pipeline.paths import env_for_subprocess, repo_data, scripts_on_path
from app.scraper.patreon import run_scrape


PIPELINE_STEPS = ["scrape", "llm_requests", "llm_library", "llm_done", "engine", "publish"]


def _run_script(name: str, script: str, job_id: str) -> None:
    job_store.append_log(job_id, f"Running {name}…")
    env = env_for_subprocess()
    if anthropic_key():
        env["ANTHROPIC_API_KEY"] = anthropic_key()

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines()[-20:]:
            job_store.append_log(job_id, line)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()[-500:]
        raise RuntimeError(f"{name} failed: {err}")
    job_store.append_log(job_id, f"{name} finished OK.")


def _run_engine(job_id: str) -> None:
    job_store.append_log(job_id, "Running rebuild engine…")
    scripts_on_path()
    env = env_for_subprocess()
    # Execute engine in-process so path patching applies cleanly.
    import rebuild_tracker_allmonths as engine

    engine.DATA = repo_data()
    engine.main()
    job_store.append_log(job_id, "Engine finished OK.")


def _run_publish(job_id: str) -> None:
    job_store.append_log(job_id, "Publishing tracker HTML…")
    env = env_for_subprocess()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "render_tracker_modern.py")],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            job_store.append_log(job_id, line)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "publish failed")[-500:])
    job_store.append_log(job_id, "Frontend data published.")


def execute_job(job_id: str, steps: list[str]) -> None:
    job_store.update(job_id, status=JobStatus.RUNNING, started_at=_now())
    job = job_store.get(job_id)
    if not job:
        return

    try:
        for step in steps:
            job_store.update(job_id, current_step=step)
            job_store.append_log(job_id, f"── Step: {step} ──")

            if step == "scrape":
                ok, msg = run_scrape(log=lambda m: job_store.append_log(job_id, m))
                if not ok:
                    raise RuntimeError(msg)

            elif step == "llm_requests":
                if not anthropic_key():
                    job_store.append_log(job_id, "Skipping LLM requests — no API key configured.")
                else:
                    _run_script("LLM extract requests", "llm_extract_requests.py", job_id)

            elif step == "llm_library":
                if not anthropic_key():
                    job_store.append_log(job_id, "Skipping LLM library — no API key configured.")
                else:
                    _run_script("LLM extract library", "llm_extract_library.py", job_id)

            elif step == "llm_done":
                if not anthropic_key():
                    job_store.append_log(job_id, "Skipping LLM done matching — no API key configured.")
                else:
                    _run_script("LLM match done", "llm_match_done.py", job_id)

            elif step == "engine":
                _run_engine(job_id)

            elif step == "publish":
                _run_publish(job_id)

            else:
                job_store.append_log(job_id, f"Unknown step skipped: {step}")

        job_store.update(
            job_id,
            status=JobStatus.SUCCESS,
            finished_at=_now(),
            current_step=None,
        )
        job_store.append_log(job_id, "✅ Pipeline complete.")
    except Exception as exc:
        job_store.update(
            job_id,
            status=JobStatus.FAILED,
            finished_at=_now(),
            error=str(exc),
            current_step=None,
        )
        job_store.append_log(job_id, f"❌ {exc}")


def start_job_async(kind: str, steps: list, meta=None) -> str:
    job = job_store.create(kind=kind, steps=steps, meta=meta or {})
    thread = threading.Thread(target=execute_job, args=(job.id, steps), daemon=True)
    thread.start()
    return job.id


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
