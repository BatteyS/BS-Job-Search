"""A local page over this workflow: read and mark digests, find what was filed
under Applications/ and track where each application stands, run the checks,
read your profile, and keep this copy updated from the template and backed up.

    uv run ui/server.py                   # opens http://127.0.0.1:8765
    uv run ui/server.py --port 8800 --no-open

Run it again while the page is up and it opens the running page instead.

It listens on 127.0.0.1 only and has no login, because it reads your resume
facts and your keys' presence: anyone who can reach it can read them. Leave it
that way. uv installs its packages with the rest; without uv,
`pip install fastapi uvicorn claude-agent-sdk`.

The routes are thin. What they do is in core.py, which the tests cover.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse, Response,
                                   StreamingResponse)
except ImportError:
    raise SystemExit("The page's packages are not installed. Start it with uv run ui/server.py, "
                     "which installs them, or: pip install fastapi uvicorn claude-agent-sdk")

import core  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# How the page stops, whether idle, asked to (Restart, ui/phone.py's quit) or
# signalled: uvicorn closes its port, waits up to SHUTDOWN_GRACE seconds for
# the requests it has, then cancels them. A run's stream ends at its next beat,
# as only then does the thread reading it come back to be cancelled. Anything
# else that would keep the process alive is cut off EXIT_DEADLINE seconds after
# that, which must stay many beats long: a stream cancelled just after a beat
# takes a whole beat more to end, and is not stuck. It matters most under
# launchd (ui/phone.py): a page that has closed its port but lives on holds it,
# as launchd starts no other while it lives and queues every request for it,
# the Desktop's and the phone's alike.
STREAM_BEAT = 2          # seconds
SHUTDOWN_GRACE = 3
EXIT_DEADLINE = 30


@contextlib.asynccontextmanager
async def _lifespan(_app):
    yield
    # Past the grace: the port is closed, and every request ended or cancelled.
    # Only for a server that main() runs, never a test's app.
    if SERVER is not None:
        _exit_by_deadline(EXIT_DEADLINE)


def _exit_by_deadline(seconds: float) -> None:
    def cut_off():
        print(f"The page had not stopped {seconds:g} seconds after closing its port; "
              "ending it.", flush=True)
        os._exit(1)
    timer = threading.Timer(seconds, cut_off)
    timer.daemon = True
    timer.start()


app = FastAPI(title="BS Job Search", docs_url=None, redoc_url=None, lifespan=_lifespan)
runs = core.Runs()
idle = core.Idle()
# Set by main(): the restart route needs the port to start again on, and the
# server to stop.
PORT = 8765
SERVER = None


class OnlyThisPage:
    """Refuses what core.refusal() refuses, before any route sees it. Plain
    ASGI rather than a FastAPI middleware, so the runs' streams pass through
    untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            idle.touch()
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
            why = core.refusal(headers.get("host"), headers.get("origin"),
                               headers.get("tailscale-user-login"),
                               "x-forwarded-for" in headers)
            if why:
                await PlainTextResponse(why, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(OnlyThisPage)


def _or_404(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except core.tracker.Conflict as exc:
        # A change made against an out-of-date view: what is there now, to show.
        raise HTTPException(409, {"message": str(exc), "current": exc.current})
    except core.Stop as exc:
        raise HTTPException(409, str(exc))
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------- page

# Served with no caching, so an edit shows on the next reload.
FRESH = {"Cache-Control": "no-cache"}


# What the page may load: its own files and routes alone. Nothing in it is
# inline, so a script or a style that reached a digest or a profile file would
# not run, on the Mac or from a phone's copy of the page.
CSP = ("default-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


def page_html() -> str:
    """index.html with this copy's version in its title and header
    (core.version), so a tab, a phone's copy, or a screenshot says which
    version it shows."""
    import html
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    v = core.version()
    text = core.version_text(v)
    if not text:
        return page
    title = f"BS Job Search {v['label'] or v['commit']}"
    shown = html.escape(text)
    about = html.escape(f"Commit {v['commit']} of {v['date']}"
                        + (", with code edited since" if v["changed"] else ""), quote=True)
    page = page.replace("<title>BS Job Search</title>", f"<title>{html.escape(title)}</title>", 1)
    return page.replace('<span id="version" class="version"></span>',
                        f'<span id="version" class="version" title="{about}">{shown}</span>', 1)


@app.get("/")
def index(request: Request):
    """The page, tagged by what it holds: the phone's copy (ui/sw.js) asks
    again each open and reloads only when the tag changes."""
    import hashlib
    body = page_html().encode("utf-8")
    tag = f'"{hashlib.sha256(body).hexdigest()[:24]}"'
    headers = {**FRESH, "Content-Security-Policy": CSP, "ETag": tag}
    held = [t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")]
    if tag in held:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(HERE, "app.js"), media_type="text/javascript", headers=FRESH)


@app.get("/style.css")
def style_css():
    return FileResponse(os.path.join(HERE, "style.css"), media_type="text/css", headers=FRESH)


@app.get("/sw.js")
def sw_js():
    """The phone's copy of the page (ui/sw.js): app.js registers it only off
    the Mac, and it keeps what /api/snapshot sends."""
    return FileResponse(os.path.join(HERE, "sw.js"), media_type="text/javascript", headers=FRESH)


# The page as an app on a phone's home screen: its manifest, and the icon
# (ui/icon.py) at the sizes iOS and Android ask for.
ICONS = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(core.manifest(), media_type="application/manifest+json")


@app.get("/{name}.png")
def icon(name: str):
    import icon as drawn
    if f"{name}.png" not in ICONS:
        raise HTTPException(404, "no such icon")
    return Response(drawn.png(ICONS[f"{name}.png"]), media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- digests

@app.get("/api/health")
def health():
    """Which page this is, and for which folder: a second start reads it, and
    so does ui/launch.sh. `started` tells the page a restarted server from the
    one it loaded from, and `restart` says whether it can restart itself."""
    return {"app": core.APP_NAME, "root": core.ROOT, "started": core.STARTED,
            "restart": core.launcher() is not None or core.by_launchd(),
            "launchd": core.by_launchd(), "working": runs.working(), "git": core.git_busy(),
            "version": core.version_text()}


@app.get("/api/snapshot")
def snapshot(request: Request):
    """Everything a phone keeps for reading while the Mac is away (ui/sw.js):
    core.snapshot(). Its tag is the ETag, so a copy that is current costs a 304."""
    snap = core.snapshot()
    tag = f'"{snap["etag"]}"'
    held = [t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")]
    if tag in held:
        return Response(status_code=304, headers={"ETag": tag})
    return JSONResponse(snap, headers={"ETag": tag, **FRESH})


@app.post("/api/restart")
def restart():
    """Start the page again, for code an update changed. Only a page that
    ui/launch.sh started can: it has no window to do it in by hand."""
    try:
        core.restart(PORT, runs)
    except core.Stop as exc:
        raise HTTPException(409, str(exc))
    if SERVER is not None:   # after this answer has gone out
        threading.Timer(0.5, lambda: setattr(SERVER, "should_exit", True)).start()
    return {"restarting": True}


@app.post("/api/quit")
def quit_page():
    """Stop the page, when no run is working: ui/phone.py asks, to hand the
    page's port to launchd."""
    if runs.working():
        raise HTTPException(409, "A run is still working. Let it finish, then try again.")
    if SERVER is not None:
        threading.Timer(0.3, lambda: setattr(SERVER, "should_exit", True)).start()
    return {"quitting": True}


@app.get("/api/phone")
def phone_status():
    """Whether the page can be opened from a phone, and at what address."""
    import phone
    return phone.status()


@app.get("/api/digests")
def digests():
    return core.list_digests()


@app.get("/api/digests/{date}")
def digest(date: str):
    return _or_404(core.read_digest, date)


@app.put("/api/digests/{date}/entries/{n}")
def mark(date: str, n: int, marks: dict):
    """Tick or untick one entry's boxes. `expect` (what the page saw in the boxes
    it changes) and `entry` ({company, title}, the role it means) make a change
    made against an out-of-date view answer 409 with what is there now."""
    bad = set(marks) - {*_MARK_TYPES, "expect", "entry"}
    if bad:
        raise HTTPException(400, f"unknown marks: {sorted(bad)}")
    _check_marks(marks)
    if "expect" in marks:
        if not isinstance(marks["expect"], dict) or set(marks["expect"]) - set(_MARK_TYPES):
            raise HTTPException(400, f"expect holds only {', '.join(_MARK_TYPES)}")
        _check_marks(marks["expect"], "expected ")
    if "entry" in marks and not (isinstance(marks["entry"], dict)
                                 and set(marks["entry"]) == {"company", "title"}
                                 and all(isinstance(v, str) for v in marks["entry"].values())):
        raise HTTPException(400, "entry is {company, title}, as text")
    return _or_404(core.mark_entry, date, n, **marks)


_MARK_TYPES = {"apply": bool, "skip": bool, "letter": bool, "skip_reason": str}


def _check_marks(marks: dict, said: str = "") -> None:
    for key, kind in _MARK_TYPES.items():
        if key in marks and not isinstance(marks[key], kind):
            raise HTTPException(400, f"{said}{key} must be {'true or false' if kind is bool else 'text'}")


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


@app.put("/api/applications/status")
def application_status(change: dict):
    """Change where one application stands, in profile/applications.yaml: a new
    status, the date of the last one, the note, or undo the last change.
    `expect_last` (the last history line the page saw) and `expect_note` make a
    change made against an out-of-date view answer 409 with what is there now."""
    bad = set(change) - {"company", "role", "status", "date", "note", "undo",
                         "expect_last", "expect_note"}
    if bad:
        raise HTTPException(400, f"unknown fields: {sorted(bad)}")
    for key in ("company", "role", "status", "date", "note", "expect_last", "expect_note"):
        if key in change and not isinstance(change[key], str):
            raise HTTPException(400, f"{key} must be text")
    if "undo" in change and not isinstance(change["undo"], bool):
        raise HTTPException(400, "undo must be true or false")
    if not change.get("company"):
        raise HTTPException(400, "say which employer")
    company, role = change.pop("company"), change.pop("role", "")
    if change.get("undo") is False:
        del change["undo"]   # asks for nothing, the same as leaving it out
    return _or_404(core.set_application_status, company, role, **change)


@app.get("/api/filed")
def filed(since: float, until: float | None = None):
    """What was filed under Applications/ in a span of time: a run's."""
    return core.filed(since, until)


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


# ------------------------------------------------------------------ setup

@app.get("/api/setup")
def setup():
    """How far setup has got. Fast: the page asks on every load, to pick its
    first tab."""
    return core.setup_state()


@app.get("/api/setup/checks")
def setup_checks():
    return core.setup_checks()


@app.get("/api/setup/test-resume")
def setup_test_resume():
    """The resume setup builds from every bullet, to open beside the interview.
    Not cached: setup builds it again after each correction."""
    return FileResponse(_or_404(core.test_resume), media_type="application/pdf",
                        headers={"Content-Disposition": "inline", **FRESH})


@app.put("/api/keys/{name}")
def save_keys(name: str, values: dict):
    """Saves one source's key file. The answer names the file, never the values."""
    return {"saved": _or_404(core.save_keys, name, values)}


# --------------------------------------------------------------- the copy
# Updates from the template, and backups to the user's own repository. What
# each does, and when it stops, is in core.py. A stop changed nothing: 409.

def _copy(fn, *args):
    try:
        return fn(*args)
    except core.Stop as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/copy")
def copy_status():
    """Where the copy stands as of the last check. Reads only."""
    return core.copy_status()


@app.post("/api/copy/check")
def copy_check():
    """Fetches the template, and the user's own repository, quietly."""
    return core.check_copy()


@app.post("/api/copy/update")
def copy_update():
    return _copy(core.update_copy, runs)


@app.post("/api/copy/backup")
def copy_backup(body: dict):
    return _copy(core.back_up, body.get("message"), runs)


@app.put("/api/copy/identity")
def copy_identity(body: dict):
    return _copy(core.save_identity, body.get("name"), body.get("email"))


@app.post("/api/copy/link")
def copy_link():
    return _copy(core.link_template)


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
    then one `done` event. A comment every STREAM_BEAT seconds with nothing
    new, which EventSource ignores, ends the stream soon after its page has
    gone, or the server stops."""
    run = _or_404(runs.get, run_id)

    def events():
        for item in run.follow(start, beat=STREAM_BEAT):
            if item is core.BEAT:
                yield ": beat\n\n"
                continue
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


@app.get("/api/usage")
def usage_now():
    """The plan's usage windows as last reported, and the page's runs' totals."""
    cr = _claude()
    return cr.usage.summary(cr.load_index())


@app.post("/api/usage/check")
def usage_check():
    """Ask Claude Code's /usage now. It calls no model, so it uses none of the plan."""
    cr = _claude()
    try:
        cr.check_usage()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(503, str(exc))
    return cr.usage.summary(cr.load_index())


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
    pick = {k: body[k] for k in ("model", "effort") if body.get(k)}
    return _start(entry["skill"], pick, resume=session_id, prompt=text)


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
    global PORT, SERVER
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    ap.add_argument("--idle-exit", type=float, default=0, metavar="MINUTES",
                    help="stop once no page has asked for anything this long and no run "
                         "is going; an open page asks every minute (default: never)")
    ap.add_argument("--launchd", action="store_true",
                    help="serve on the socket launchd holds for the page (ui/phone.py sets that "
                         "up; ui/launch.sh --launchd passes this)")
    args = ap.parse_args()
    if args.launchd:
        serve_for_launchd(args.idle_exit)
        return
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
    core.remember_start()   # so the page can say when an update needs it restarted
    if not args.no_open:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    print(f"BS Job Search at {url}  (this machine only; Ctrl-C stops it)", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                           log_level="warning",
                                           timeout_graceful_shutdown=SHUTDOWN_GRACE))
    PORT, SERVER = args.port, server
    watch_idle(server, args.idle_exit)
    server.run()


def watch_idle(server, minutes: float) -> None:
    if minutes <= 0:
        return

    def watch():
        while not server.should_exit:
            time.sleep(15)
            if idle.should_exit(minutes, runs):
                print(f"No page open for {minutes:g} minutes; stopping.", flush=True)
                server.should_exit = True
    threading.Thread(target=watch, name="idle-exit", daemon=True).start()


def serve_for_launchd(idle_minutes: float) -> None:
    """Serve on the socket launchd listens on for the page: it started this
    process at a request, and starts another at the next request after this one
    stops."""
    global PORT, SERVER
    socks = core.launchd_sockets()
    PORT = socks[0].getsockname()[1]
    core.remember_start()
    print(f"BS Job Search at http://127.0.0.1:{PORT}  (started by launchd)", flush=True)
    SERVER = uvicorn.Server(uvicorn.Config(app, log_level="warning",
                                           timeout_graceful_shutdown=SHUTDOWN_GRACE))
    watch_idle(SERVER, idle_minutes)
    SERVER.run(sockets=socks)


if __name__ == "__main__":
    main()
