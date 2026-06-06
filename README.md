# twvs-tracker

Hosted song-request tracker for **Tim Welch Vocal Studio** — scrapes Patreon comments, processes them with LLM, and serves a public tracker UI with an admin dashboard for scraping.

## Architecture

- **API** (FastAPI): public tracker JSON, admin auth, scrape jobs, scheduler
- **Scraper** (Playwright): Patreon login session + headless comment scrape
- **Pipeline**: LLM extract → rebuild engine → publish tracker
- **Frontend** (`tracker/`): modern public tracker page

## Quick start

```bash
cd tracker_repo
cp .env.example .env          # set ADMIN_PASSWORD and JWT_SECRET
pip3 install -r requirements.txt
playwright install chromium

python3 -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

- **Public tracker:** http://localhost:8000/tracker/
- **Admin dashboard:** http://localhost:8000/admin/
- **API health:** http://localhost:8000/api/health

Or use the helper script:

```bash
./scripts/run_api.sh
```

## Project layout

```
tracker_repo/
  app/           # FastAPI API, admin UI, scraper, pipeline
  tracker/       # Public tracker frontend (HTML/CSS/JS)
  scripts/       # Scrape + LLM + engine CLI scripts
  data/          # JSON data files (scrape output + engine)
  frontend/      # Next.js shell (optional future UI)
```
