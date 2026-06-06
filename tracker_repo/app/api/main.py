"""FastAPI application entrypoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.admin import router as admin_router
from app.api.auth import create_token, verify_password
from app.api.health import router as health_router
from app.config import DATA_DIR, TRACKER_DIR, ensure_dirs
from app.pipeline.schedule import schedule_manager

ADMIN_DIR = Path(__file__).resolve().parents[1] / "admin"

app = FastAPI(title="TWVS Tracker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(admin_router)


class LoginRequest(BaseModel):
    password: str


@app.post("/api/admin/login")
def admin_login(body: LoginRequest) -> dict:
    if not verify_password(body.password):
        return JSONResponse({"detail": "Invalid password"}, status_code=401)
    return create_token()


@app.get("/api/tracker")
def public_tracker_data() -> FileResponse:
    """Public tracker JSON consumed by the frontend."""
    path = DATA_DIR / "tracker_allmonths_engine.json"
    if not path.is_file():
        return JSONResponse({"detail": "Tracker data not published yet"}, status_code=404)
    return FileResponse(path, media_type="application/json")


@app.on_event("startup")
def on_startup() -> None:
    ensure_dirs()
    schedule_manager.start()


# Static tracker + admin UI
if TRACKER_DIR.is_dir():
    app.mount("/tracker", StaticFiles(directory=str(TRACKER_DIR), html=True), name="tracker")

if ADMIN_DIR.is_dir():
    app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True), name="admin")
