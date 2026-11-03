"""A local page over this workflow: read and mark digests, find what was filed
under Applications/, run the checks, and read your profile.

    uv run python ui/server.py            # opens http://127.0.0.1:8765
    uv run python ui/server.py --port 8800 --no-open

Run it again while the page is up and it opens the running page instead.

It listens on 127.0.0.1 only and has no login, because it reads your resume
facts and your keys' presence: anyone who can reach it can read them. Leave it
that way. Needs the `ui` extra: `uv sync --extra ui` (name every extra you use).

The routes are thin. What they do is in core.py, which the tests cover.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
except ImportError:
    raise SystemExit("The page needs the `ui` extra: uv sync --extra ui "
                     "(add --extra pdf and --extra scraped if you use them)")

import core  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="BS Job Search", docs_url=None, redoc_url=None)
runs = core.Runs()


def _or_404(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------- page

# Served with no caching, so an edit shows on the next reload.
FRESH = {"Cache-Control": "no-cache"}


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "index.html"), headers=FRESH)


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(HERE, "app.js"), media_type="text/javascript", headers=FRESH)


@app.get("/style.css")
def style_css():
    return FileResponse(os.path.join(HERE, "style.css"), media_type="text/css", headers=FRESH)


# ---------------------------------------------------------------- digests

@app.get("/api/health")
def health():
    """Which page this is, and for which folder: a second start reads it."""
    return {"app": core.APP_NAME, "root": core.ROOT}


@app.get("/api/digests")
def digests():
    return core.list_digests()


@app.get("/api/digests/{date}")
def digest(date: str):
    return _or_404(core.read_digest, date)


@app.put("/api/digests/{date}/entries/{n}")
def mark(date: str, n: int, marks: dict):
    allowed = {"apply", "skip", "letter", "skip_reason"}
    bad = set(marks) - allowed
    if bad:
        raise HTTPException(400, f"unknown marks: {sorted(bad)}")
    for key in ("apply", "skip", "letter"):
        if key in marks and not isinstance(marks[key], bool):
            raise HTTPException(400, f"{key} must be true or false")
    if "skip_reason" in marks and not isinstance(marks["skip_reason"], str):
        raise HTTPException(400, "skip_reason must be text")
    return _or_404(core.mark_entry, date, n, **marks)


@app.get("/api/digests/{date}/verdicts")
def verdicts(date: str):
    return _or_404(core.verdicts_section, date)


@app.post("/api/digests/{date}/verdicts/append")
def append_verdicts(date: str):
    return {"appended_to": _or_404(core.append_feedback, date)}


# ----------------------------------------------------------- applications

@app.get("/api/applications")
def applications():
    return core.list_applications()


@app.get("/api/applications/{company:path}/{name}")
def application_file(company: str, name: str):
    path = _or_404(core.application_file, company, name)
    if path.lower().endswith(".pdf"):
        return FileResponse(path, media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})
    return PlainTextResponse(open(path, encoding="utf-8", errors="replace").read())


# ---------------------------------------------------------------- profile

@app.get("/api/profile")
def profile_files():
    return core.list_profile_files()


@app.get("/api/profile/{rel:path}")
def profile_file(rel: str):
    return PlainTextResponse(_or_404(core.read_profile_file, rel))


# ------------------------------------------------------------------- runs

@app.get("/api/commands")
def commands():
    return runs.commands()


@app.get("/api/runs")
def list_runs():
    return runs.list()


@app.post("/api/runs/{name}")
def start_run(name: str, params: dict | None = None):
    return _or_404(runs.start, name, params or {}).summary()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = _or_404(runs.get, run_id)
    items = run.events if hasattr(run, "events") else run.lines
    return {**run.summary(), "output": items}


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str, start: int = 0):
    """The run's lines (a script) or events (a skill) as server-sent events,
    then one `done` event."""
    run = _or_404(runs.get, run_id)

    def events():
        for item in run.follow(start):
            if item is None:
                yield f"event: done\ndata: {run.status}\n\n"
                return
            i, payload = item
            data = json.dumps(payload) if isinstance(payload, dict) else payload
            yield f"id: {i}\ndata: {data}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ----------------------------------------------------------------- skills
# The page runs a skill through the user's own Claude Code. Everything Claude
# Code would ask a person comes back as a card on the run; see ui/claude_run.py.

def _claude():
    try:
        import claude_run
    except ImportError as exc:   # the ui extra without the SDK
        raise HTTPException(503, f"the Agent SDK is not installed: {exc}")
    return claude_run


@app.get("/api/claude/status")
def claude_status():
    try:
        return _claude().claude_status()
    except HTTPException as exc:
        return {"available": False, "cli": None, "version": None, "reason": exc.detail}


@app.get("/api/skills")
def skills():
    return _claude().skills()


def _start(name: str, params: dict, resume: str | None = None, prompt: str | None = None):
    try:
        return runs.start_skill(name, params, resume=resume, prompt=prompt).summary()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/skills/{name}")
def start_skill(name: str, params: dict | None = None):
    _claude()
    return _start(name, params or {})


@app.get("/api/claude/runs")
def past_runs():
    return list(reversed(_claude().load_index()))


@app.post("/api/claude/resume")
def resume_run(body: dict):
    cr = _claude()
    session_id = str(body.get("session_id") or "")
    text = str(body.get("text") or "").strip()
    entry = next((e for e in cr.load_index() if e.get("session_id") == session_id), None)
    if entry is None:
        raise HTTPException(404, "no past run with that session")
    if not text:
        raise HTTPException(400, "say what to do next")
    return _start(entry["skill"], {}, resume=session_id, prompt=text)


def _claude_run(run_id: str):
    run = _or_404(runs.get, run_id)
    if run.summary().get("kind") != "claude":
        raise HTTPException(400, "not a skill run")
    return run


@app.post("/api/claude/{run_id}/answer")
def answer_card(run_id: str, body: dict):
    run = _claude_run(run_id)
    answers = body.get("answers")
    if answers is not None and not isinstance(answers, dict):
        raise HTTPException(400, "answers must be an object")
    _or_404(run.answer, str(body.get("card_id") or ""), str(body.get("decision") or ""),
            str(body.get("message") or ""), answers)
    return run.summary()


@app.post("/api/claude/{run_id}/say")
def say(run_id: str, body: dict):
    run = _claude_run(run_id)
    _or_404(run.say, str(body.get("text") or ""))
    return run.summary()


@app.post("/api/claude/{run_id}/stop")
def stop_run(run_id: str):
    run = _claude_run(run_id)
    run.stop()
    return run.summary()


# ------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    held, root = core.probe_port(args.port)
    if held == "this":
        print(f"BS Job Search is already running at {url}"
              + ("" if args.no_open else "; opening it."))
        if not args.no_open:
            webbrowser.open(url)
        return
    if held == "another":
        raise SystemExit(f"Port {args.port} is taken by BS Job Search for another folder, {root}. "
                         f"Stop that one, or start this one with --port {args.port + 1}.")
    if held == "other":
        raise SystemExit(f"Port {args.port} is taken by another program. Start the page "
                         f"with --port {args.port + 1}, or another free port.")
    if not args.no_open:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    print(f"BS Job Search at {url}  (this machine only; Ctrl-C stops it)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
