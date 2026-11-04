"""Running a skill through the user's own Claude Code, for the page.

The page starts `/job-scan`, `/tailor-digest` and the rest the way a person would
type them, through the Agent SDK driving a Claude Code binary in this folder. The
skills, CLAUDE.md and .claude/settings.json load as they do in a terminal, so what
runs is the real skill, and its rules hold.

Everything Claude Code would stop and ask a person -- a tool call no rule allows,
a write to one of the ground-truth files (an `ask` rule in settings.json), and
every AskUserQuestion -- arrives at one callback here, becomes a card in the page,
and waits for the answer. A write to master.md, story.md or profile.md therefore
always shows its exact text first, whatever the prompt said. A turn that ends
with a question in plain text leaves the run idle, and the page's reply box sends
the answer into the same session.

Each run gets the model and effort router.py picks for it, and passes the plan
usage every request reports on to usage.py, with the run's own tokens and cost.

Only find_claude() and the pure helpers run without the SDK installed; ClaudeRun
imports it when a run starts, so the page and the tests work without it.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import router  # noqa: E402
import usage  # noqa: E402

ROOT = core.ROOT
INDEX = os.path.join(ROOT, "data", "ui-runs.json")

# The files CLAUDE.md calls ground truth. settings.json has an `ask` rule for
# each, which is what routes their edits to the card; this list only decides how
# the card looks (the exact text, and no "always allow").
GROUND_TRUTH = ("profile/profile.md", "content/master.md", "content/story.md")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# What to do when the SDK is missing. Only a Python without uv can lack it.
SDK_MISSING = ("the Agent SDK is not installed: start the page with uv run ui/server.py, "
               "or pip install claude-agent-sdk")

# Where a Claude Code binary may be, after BS_CLAUDE_BIN and PATH.
USUAL_PATHS = ("~/.claude/local/claude", "~/.local/bin/claude", "~/.local/bin/claude.exe",
               "~/.npm-global/bin/claude",
               "/usr/local/bin/claude", "/opt/homebrew/bin/claude",
               "~/node_modules/.bin/claude", "~/.yarn/bin/claude")
# The Claude desktop app keeps its own copy, one folder per version.
DESKTOP_GLOB = "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude"
# How find_claude() names the copy inside the Agent SDK, the last resort.
BUNDLED = "the Agent SDK's own copy"

# Claude Code's own installer, by system (code.claude.com/docs/en/setup), for
# the page to show when it finds no Claude Code of the user's own.
INSTALL = {"Windows": "irm https://claude.ai/install.ps1 | iex"}
INSTALL_UNIX = "curl -fsSL https://claude.ai/install.sh | bash"

# name -> label, what it does, the slash command, what it needs from the page:
# None, "date" (the open digest, optional), "text" (a URL or pasted posting), or
# "application" (a company and job title with a posting filed under Applications/).
SKILLS: dict[str, tuple[str, str, str, str | None]] = {
    "job-scan": ("Job scan", "Fetch, filter, score against your profile, and write a digest",
                 "/job-scan", None),
    "tailor-digest": ("Tailor the digest",
                      "A resume for every apply on a digest, and a letter for every cover letter",
                      "/tailor-digest", "date"),
    "tailor-resume": ("Tailor a resume", "One resume for one posting", "/tailor-resume", "text"),
    "cover-letter": ("Cover letter",
                     "A letter for one posting; asks you for what your files lack",
                     "/cover-letter", "text"),
    "interview-prep": ("Interview prep",
                       "Likely questions with sourced answers, gaps, and questions to ask, "
                       "for one application",
                       "/interview-prep", "application"),
    "setup": ("Set up", "The first-time interview, or one left unfinished", "/setup", None),
}


# ---------------------------------------------------------------- the binary

def _version_key(path: str) -> tuple:
    m = re.search(r"/claude-code/(\d+)\.(\d+)\.(\d+)/", path)
    return tuple(int(x) for x in m.groups()) if m else (0,)


def find_claude(env: dict | None = None, which=shutil.which,
                exists=os.path.isfile) -> tuple[str | None, str]:
    """(path, where it came from). The user's own install first, the SDK's
    bundled copy last: the page is a front end to the Claude Code they already
    use, with their own login."""
    env = os.environ if env is None else env
    chosen = env.get("BS_CLAUDE_BIN")
    if chosen:
        if exists(chosen):
            return chosen, "BS_CLAUDE_BIN"
        return None, f"BS_CLAUDE_BIN is set to {chosen}, which is not a file"
    found = which("claude")
    if found:
        return found, "on PATH"
    for p in USUAL_PATHS:
        p = os.path.expanduser(p)
        if exists(p):
            return p, "a usual install location"
    hits = sorted(glob.glob(os.path.expanduser(DESKTOP_GLOB)), key=_version_key)
    if hits:
        return hits[-1], "the Claude desktop app"
    try:
        import claude_agent_sdk
        bundled = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
        if exists(bundled):
            return bundled, BUNDLED
    except ImportError:
        pass
    return None, ("no Claude Code binary found: install Claude Code, or set BS_CLAUDE_BIN "
                  "to the binary")


def install_command(system: str | None = None) -> str:
    return INSTALL.get(system or platform.system(), INSTALL_UNIX)


def claude_status() -> dict:
    """What the page shows beside the skill buttons and on its Setup tab. When
    Claude Code is not ready, `install` or `login` holds the one command to run.
    Only the SDK's own copy, not logged in, asks for an install rather than a
    login: the page is a front end to the user's own Claude Code."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return {"available": False, "cli": None, "version": None,
                "reason": SDK_MISSING}
    cli, how = find_claude()
    if not cli:
        return {"available": False, "cli": None, "version": None, "reason": how,
                "install": install_command()}
    import subprocess
    version, logged_in = "", None
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=5)
        version = (out.stdout or out.stderr).strip().split("\n")[0]
        out = subprocess.run([cli, "auth", "status", "--json"], capture_output=True,
                             text=True, timeout=5)
        logged_in = bool(json.loads(out.stdout).get("loggedIn"))
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        pass
    out = {"available": logged_in is not False, "cli": cli, "how": how,
           "version": version, "logged_in": logged_in, "reason": ""}
    if logged_in is False and how == BUNDLED:
        out["install"] = install_command()
        out["reason"] = (f"Claude Code is not installed. Install it in a terminal with "
                         f"{out['install']}  then log in with: claude auth login")
    elif logged_in is False:
        out["login"] = login_command(cli)
        out["reason"] = _explain("Not logged in", cli)
    return out


def child_env(env: dict | None = None) -> dict:
    """The environment a run gets. A server started from the Claude desktop app
    inherits that session's CLAUDE_CODE_* (its messaging socket, its session id);
    none of it belongs to the child, so all of it goes."""
    env = os.environ if env is None else env
    out = {k: v for k, v in env.items()
           if not k.startswith("CLAUDE_CODE") and k != "CLAUDECODE"}
    out["CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL"] = "true"
    return out


# ------------------------------------------------------------------ prompts

def skills(limits: dict | None = None) -> list[dict]:
    """The skill buttons, each with the route a run started now would get, at
    `limits` (the latest plan usage when not given)."""
    limits = usage.windows() if limits is None else limits
    return [{"name": k, "label": v[0], "about": v[1], "needs": v[3],
             "route": router.route(k, {}, limits)} for k, v in SKILLS.items()]


def build_prompt(name: str, params: dict | None = None) -> str:
    """The prompt a person would type for this skill, from the page's parameters."""
    if name not in SKILLS:
        raise ValueError(f"no skill named {name!r}")
    params = params or {}
    _, _, command, needs = SKILLS[name]
    text = str(params.get("text") or "").strip()
    if needs == "text":
        if not text:
            raise ValueError("this skill needs a posting: a URL, or the posting's text")
        return f"{command} {text}"
    if needs == "date" and params.get("date"):
        core.digest_path(str(params["date"]))   # raises on a bad date
        return f"{command} for digests/{params['date']}.md"
    if needs == "application":
        company = str(params.get("company") or "").strip()
        title = str(params.get("title") or "").strip()
        core.posting_path(company, title)   # raises unless that posting is filed
        return f"{command} for Applications/{company}/{title} - posting.txt"
    return command


# ------------------------------------------------------------------- events

def _excerpt(content, limit: int = 600) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    parts.append(str(c.get("text", "")))
                elif c.get("type") == "image":
                    parts.append("[image]")
            else:
                parts.append(str(c))
        content = "\n".join(parts)
    content = str(content)
    return content if len(content) <= limit else content[:limit] + " …"


def tool_summary(name: str, input_data: dict) -> str:
    """One line that says what a tool call is, for the collapsed row."""
    if name == "Bash":
        return str(input_data.get("command", ""))[:200]
    if name in EDIT_TOOLS + ("Read",):
        return os.path.relpath(str(input_data.get("file_path", "")), ROOT)
    if name == "Skill":
        return str(input_data.get("skill", ""))
    if name in ("Glob", "Grep"):
        return str(input_data.get("pattern", ""))
    if name == "AskUserQuestion":
        return "a question for you"
    return json.dumps(input_data)[:200]


def events_from(msg) -> list[dict]:
    """The page's events for one SDK message. Matches on the type's name and
    attributes, so the tests feed plain stand-ins."""
    kind = type(msg).__name__
    out: list[dict] = []
    if kind == "SystemMessage":
        if getattr(msg, "subtype", "") == "init":
            data = getattr(msg, "data", {}) or {}
            out.append({"kind": "init", "session_id": data.get("session_id"),
                        "model": data.get("model")})
    elif kind == "AssistantMessage":
        for block in getattr(msg, "content", []) or []:
            b = type(block).__name__
            if b == "TextBlock" and block.text.strip():
                out.append({"kind": "text", "text": block.text})
            elif b == "ToolUseBlock":
                out.append({"kind": "tool_use", "id": block.id, "name": block.name,
                            "summary": tool_summary(block.name, block.input or {})})
    elif kind == "UserMessage":
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if type(block).__name__ == "ToolResultBlock":
                    out.append({"kind": "tool_result", "id": block.tool_use_id,
                                "ok": not bool(block.is_error),
                                "excerpt": _excerpt(block.content)})
    elif kind == "ResultMessage":
        # usage is this turn's; total_cost_usd is the session's so far.
        u = getattr(msg, "usage", None) or {}
        out.append({"kind": "turn_end", "subtype": getattr(msg, "subtype", ""),
                    "is_error": bool(getattr(msg, "is_error", False)),
                    "num_turns": getattr(msg, "num_turns", None),
                    "cost": getattr(msg, "total_cost_usd", None),
                    "tokens": sum(int(u.get(k) or 0) for k in (
                        "input_tokens", "output_tokens", "cache_read_input_tokens",
                        "cache_creation_input_tokens")),
                    "result": (getattr(msg, "result", "") or "")
                    if getattr(msg, "is_error", False) else ""})
    elif kind == "RateLimitEvent":
        info = getattr(msg, "rate_limit_info", None)
        if info is not None:
            out.append({"kind": "limits", "windows": usage.from_event(info)})
    return out


# -------------------------------------------------------------------- cards

def is_ground_truth(tool_name: str, input_data: dict) -> bool:
    if tool_name not in EDIT_TOOLS:
        return False
    path = str(input_data.get("file_path") or "")
    if not path:
        return False
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(ROOT)).replace(os.sep, "/")
    return rel in GROUND_TRUTH


def make_card(tool_name: str, input_data: dict, suggestions: list | None = None) -> dict:
    """What the page needs to draw one prompt and answer it."""
    card = {"card_id": uuid.uuid4().hex[:10], "tool": tool_name}
    if tool_name == "AskUserQuestion":
        card["card_kind"] = "question"
        card["questions"] = input_data.get("questions") or []
        return card
    card["card_kind"] = "permission"
    card["input"] = input_data
    card["summary"] = tool_summary(tool_name, input_data)
    card["guard"] = is_ground_truth(tool_name, input_data)
    if tool_name in EDIT_TOOLS:
        card["file"] = os.path.relpath(str(input_data.get("file_path", "")), ROOT)
    # Only a rule the page may write back (to .claude/settings.local.json)
    # is offered as "always"; a guarded file never is.
    card["can_always"] = (not card["guard"]) and any(
        getattr(s, "destination", None) == "localSettings" for s in (suggestions or []))
    return card


def permission_result(card: dict, decision: str, message: str = "",
                      answers: dict | None = None, suggestions: list | None = None) -> dict:
    """The answer to hand the SDK, as a plain dict: {"behavior": "allow",
    "updated_input": ..., "updated_permissions": [...]} or {"behavior": "deny",
    "message": ...}. _can_use_tool wraps it in the SDK's types."""
    if card["card_kind"] == "question":
        if decision == "deny":
            return {"behavior": "deny", "message": message or "The user dismissed the question."}
        return {"behavior": "allow",
                "updated_input": {"questions": card["questions"], "answers": answers or {}}}
    if decision == "deny":
        return {"behavior": "deny",
                "message": message or "The user declined this. Do not retry it the same way."}
    if decision not in ("allow", "always"):
        raise ValueError(f"decision must be allow, always or deny, not {decision!r}")
    result = {"behavior": "allow", "updated_input": card["input"]}
    if decision == "always" and card.get("can_always"):
        result["updated_permissions"] = [s for s in (suggestions or [])
                                         if getattr(s, "destination", None) == "localSettings"]
    return result


# -------------------------------------------------------------- the index

def load_index() -> list[dict]:
    try:
        with open(INDEX, encoding="utf-8") as fh:
            return list(json.load(fh))
    except (OSError, ValueError):
        return []


def save_index(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(entries[-50:], fh, indent=1)


def index_upsert(entry: dict) -> None:
    entries = [e for e in load_index() if e.get("id") != entry["id"]]
    entries.append(entry)
    save_index(entries)


# ---------------------------------------------------------------- the run

ACTIVE = ("starting", "running", "waiting", "idle")

# How long a stopped turn gets to end on its own before the session is closed
# under it. The first live stop, on 2026-11-03, interrupted a turn that never
# ended, and its Claude Code process outlived the run.
STOP_GRACE = 5.0


class ClaudeRun:
    """One conversation with Claude Code: a skill from its first prompt to the
    end. Shaped like core.Run (id, name, status, follow, summary) so the registry
    and the stream route treat both alike, but it keeps events, not lines.

    Runs on a daemon thread with its own asyncio loop. The server thread talks to
    it through answer(), say() and stop(), each of which hands work to that loop.
    """

    def __init__(self, skill: str, prompt: str, cli_path: str, resume: str | None = None,
                 route: dict | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.name = skill
        self.prompt = prompt
        self.cli_path = cli_path
        self.resume = resume
        self.route = route or {}
        self.tokens = 0          # this run's, summed over its turns
        self.cost = 0.0          # at API prices: the session's figure, as of its last turn
        self.events: list[dict] = []
        self.status = "starting"
        self.pending: dict | None = None
        self.session_id: str | None = resume
        self.started = time.time()
        self.updated = self.started   # its last change of status
        self.changed = threading.Condition()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbox: asyncio.Queue | None = None
        self._client = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._answers: dict[str, list] = {}

    # -- what the server thread sees

    def start(self) -> "ClaudeRun":
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()),
                                        name=f"claude-{self.id}", daemon=True)
        self._thread.start()
        return self

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": "claude", "status": self.status,
                "started": self.started, "updated": self.updated, "session_id": self.session_id,
                "pending": self.pending, "lines": len(self.events), "route": self.route,
                "tokens": self.tokens, "cost": self.cost}

    def follow(self, start: int = 0):
        """Yield (index, event) from `start`, then None once the run has ended."""
        i = start
        while True:
            with self.changed:
                while i >= len(self.events) and self.status in ACTIVE:
                    self.changed.wait(timeout=0.5)
                if i < len(self.events):
                    item = self.events[i]
                elif self.status not in ACTIVE:
                    yield None
                    return
                else:
                    continue
            yield i, item
            i += 1

    def answer(self, card_id: str, decision: str, message: str = "",
               answers: dict | None = None) -> None:
        if not self.pending or self.pending["card_id"] != card_id:
            raise ValueError("that card is not waiting for an answer")
        if decision not in ("allow", "always", "deny"):
            raise ValueError(f"decision must be allow, always or deny, not {decision!r}")
        slot = self._answers[card_id]
        slot[1] = (decision, message, answers)
        self._call_soon(slot[0].set)

    def say(self, text: str) -> None:
        if self.status != "idle":
            raise ValueError("the run is not waiting for a reply")
        if not text.strip():
            raise ValueError("nothing to say")
        self._set_status("running")
        self._call_soon(self._inbox.put_nowait, text.strip())

    def stop(self) -> None:
        """End the run: deny an open card, interrupt a turn, and close the
        session. A turn still going STOP_GRACE seconds later is cut off, so a
        stopped run never leaves its Claude Code process behind."""
        if self.status not in ACTIVE:
            return
        was_idle = self.status == "idle"
        if self.pending:
            try:
                self.answer(self.pending["card_id"], "deny", "The user stopped the run.")
            except ValueError:
                pass
        self._stopping = True
        self._set_status("done" if was_idle else "stopped")
        if self._loop is None or self._inbox is None:
            return   # not started yet: _main sees _stopping and never opens a session
        try:
            self._call_soon(self._inbox.put_nowait, None)
            if not was_idle and self._client is not None:
                asyncio.run_coroutine_threadsafe(self._interrupt(), self._loop)
            self._call_soon(self._loop.call_later, STOP_GRACE, self._cut_off)
        except (ValueError, RuntimeError):
            pass     # the loop has closed: the run already ended

    # -- internals

    _stopping = False

    def _call_soon(self, fn, *args) -> None:
        if self._loop is None:
            raise ValueError("the run has not started")
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:   # the loop has closed
            raise ValueError("the run has ended")

    def _cut_off(self) -> None:
        """Close the session under a turn that did not end when interrupted.
        Through the SDK's disconnect(), on a task of its own, rather than by
        cancelling the run's task: the SDK's close() escalates to terminating
        and killing its process only when it is not itself being cancelled."""
        if self._task is not None and not self._task.done() and self._client is not None:
            asyncio.ensure_future(self._close_session(self._client))

    async def _close_session(self, client) -> None:
        try:
            await client.disconnect()   # ends the process and the stream the run waits on
        except Exception:
            pass
        await asyncio.sleep(1)
        if self._task is not None and not self._task.done():
            self._task.cancel()         # last resort; the process is already gone

    def _emit(self, kind: str, **data) -> None:
        with self.changed:
            self.events.append({"i": len(self.events), "kind": kind, "t": time.time(), **data})
            self.changed.notify_all()

    def _set_status(self, status: str) -> None:
        with self.changed:
            self.status = status
            self.updated = time.time()
        self._emit("status", status=status)
        index_upsert({"id": self.id, "skill": self.name, "session_id": self.session_id,
                      "started": self.started, "status": status, "prompt": self.prompt[:200],
                      "route": self.route.get("label", ""), "tokens": self.tokens,
                      "cost": self.cost})

    async def _interrupt(self) -> None:
        try:
            await self._client.interrupt()
        except Exception:   # the turn may already be over
            pass

    async def _main(self) -> None:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        except ImportError:
            self._emit("error", message=SDK_MISSING)
            self._set_status("failed")
            return
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._inbox = asyncio.Queue()
        if self._stopping:   # stopped before it started
            return
        model = self.route.get("model")
        options = ClaudeAgentOptions(cwd=ROOT, cli_path=self.cli_path, permission_mode="default",
                                     can_use_tool=self._can_use_tool, env=child_env(),
                                     resume=self.resume, model=model,
                                     effort=self.route.get("effort"),
                                     # Overload only: rate limits never switch models.
                                     fallback_model="sonnet" if model == "opus" else None)
        try:
            async with ClaudeSDKClient(options=options) as client:
                self._client = client
                if self._stopping:
                    return
                self._set_status("running")
                if self.route:
                    self._emit("route", **self.route)
                self._emit("user", text=self.prompt)
                await client.query(self.prompt)
                if not await self._drain(client):
                    return
                while not self._stopping:
                    text = await self._inbox.get()
                    if text is None:
                        break
                    self._emit("user", text=text)
                    await client.query(text)
                    if not await self._drain(client):
                        return
        except asyncio.CancelledError:   # _close_session's last resort
            pass
        except Exception as exc:   # the CLI died, or the SDK refused something
            if not self._stopping:   # closing a stopped session under a turn may raise
                self._emit("error", message=f"{type(exc).__name__}: {exc}")
                self._set_status("failed")
        finally:
            self._client = None
            if self.status in ACTIVE:
                self._set_status("done")

    async def _drain(self, client) -> bool:
        """Read one turn. Returns False when the run is over."""
        async for msg in client.receive_response():
            for ev in events_from(msg):
                if ev["kind"] == "init" and ev.get("session_id"):
                    self.session_id = ev["session_id"]
                if ev["kind"] == "limits":
                    usage.record(ev["windows"], "run")
                if ev["kind"] == "turn_end":
                    self.tokens += ev.get("tokens") or 0
                    if isinstance(ev.get("cost"), (int, float)):
                        self.cost = float(ev["cost"])
                    if ev["is_error"]:
                        # A stopped turn ends in an error result: that is the
                        # stop working, not the run failing.
                        if not self._stopping:
                            self._emit("error", message=_explain(ev["result"], self.cli_path))
                        self._emit(**ev)
                        if not self._stopping:
                            self._set_status("failed")
                        return False
                    self._emit(**ev)
                    if not self._stopping:
                        self._set_status("idle")
                    continue
                self._emit(**ev)
        return not self._stopping

    async def _can_use_tool(self, tool_name: str, input_data: dict, context):
        suggestions = list(getattr(context, "suggestions", None) or [])
        card = make_card(tool_name, input_data, suggestions)
        event = asyncio.Event()
        self._answers[card["card_id"]] = [event, None]
        with self.changed:
            self.pending = card
        self._emit("card", **card)
        self._set_status("waiting")
        await event.wait()
        decision, message, answers = self._answers.pop(card["card_id"])[1]
        with self.changed:
            self.pending = None
        self._emit("card_answered", card_id=card["card_id"], decision=decision)
        if self.status == "waiting":
            self._set_status("running")
        return self._to_sdk(permission_result(card, decision, message, answers, suggestions))

    @staticmethod
    def _to_sdk(spec: dict):
        from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
        if spec["behavior"] == "deny":
            return PermissionResultDeny(message=spec["message"])
        return PermissionResultAllow(updated_input=spec["updated_input"],
                                     updated_permissions=spec.get("updated_permissions"))


def login_command(cli: str | None) -> str:
    """The command that logs this binary in, as the user would type it. A copy
    inside the Claude desktop app is not on PATH, so `claude` alone would fail."""
    on_path = shutil.which("claude")
    if not cli or (on_path and os.path.realpath(on_path) == os.path.realpath(cli)):
        return "claude auth login"
    return f'"{cli}" auth login'


# The plan's usage windows, as a failed turn names the one that is used up.
LIMIT_NAMES = {"five_hour": "5-hour session", "seven_day": "weekly",
               "seven_day_opus": "weekly Opus", "seven_day_sonnet": "weekly Sonnet"}


def _when(ts: float, now: float | None = None) -> str:
    """A reset time as a person reads it: at 3:40 PM, or on Nov 7 at 10:59 PM."""
    at = time.localtime(ts)
    clock = time.strftime("%I:%M %p", at).lstrip("0")
    if time.strftime("%Y-%m-%d", at) == time.strftime("%Y-%m-%d", time.localtime(now)):
        return f"at {clock}"
    return f"on {time.strftime('%b', at)} {at.tm_mday} at {clock}"


def limit_reached(windows: dict | None = None, now: float | None = None) -> str:
    """Which of the plan's windows is used up and when it resets, from the
    rate-limit events Claude Code reports, or "" when none is."""
    windows = usage.windows(now) if windows is None else windows
    for name, w in windows.items():
        if not isinstance(w, dict) or w.get("reset"):
            continue
        if w.get("status") == "rejected" or (w.get("used") or 0) >= 1:
            what = LIMIT_NAMES.get(name, name.replace("_", " "))
            resets = w.get("resets_at")
            return (f"Your Claude plan's {what} limit is used up"
                    + (f"; it resets {_when(resets, now)}." if isinstance(resets, (int, float))
                       else "."))
    return ""


def _explain(result_text: str, cli: str | None = None) -> str:
    text = result_text or ""
    low = text.lower()
    said = f" (Claude Code said: {text.strip()})" if text.strip() else ""
    if "not logged in" in low:
        return ("Claude Code is not logged in. Run this once in a terminal; it opens your "
                f"browser to sign in: {login_command(cli)}  The Claude desktop app's own "
                "login does not carry over to it.")
    limit = limit_reached()
    if limit or ("limit" in low and any(w in low for w in ("usage", "reached", "rate"))):
        return ((limit or "Your Claude plan's usage limit is reached.")
                + " Once it resets, pick this run up again from Past runs in the Runs tab; "
                "the header shows how much of the plan is used." + said)
    if "credit balance" in low:
        return ("This Anthropic Console account has run out of credit. Add some at "
                "console.anthropic.com, then pick this run up again from Past runs." + said)
    return text or "the turn ended with an error"


def start_skill(name: str, params: dict | None = None, resume: str | None = None,
                prompt: str | None = None) -> ClaudeRun:
    """A run for one skill, or a resumed session with the user's next message,
    on the model and effort the router picks: params may carry the Runs tab's
    pick as `model` and `effort`."""
    cli, how = find_claude()
    if not cli:
        raise FileNotFoundError(how)
    params = params or {}
    chosen = router.route(name, params, usage.windows(),
                          {"model": params.get("model"), "effort": params.get("effort")})
    if prompt is None:
        prompt = build_prompt(name, params)
    return ClaudeRun(name, prompt, cli, resume=resume, route=chosen).start()


def check_usage() -> dict:
    """Ask Claude Code's /usage for the plan's windows, and keep them. It
    answers without calling a model, so this uses none of the plan, and it runs
    with no settings, hooks or saved session."""
    cli, how = find_claude()
    if not cli:
        raise FileNotFoundError(how)
    from claude_agent_sdk import ClaudeAgentOptions, query
    options = ClaudeAgentOptions(cwd=ROOT, cli_path=cli, env=child_env(), setting_sources=[],
                                 allowed_tools=[], max_turns=1,
                                 extra_args={"no-session-persistence": None})

    async def ask() -> str:
        text = ""
        async for msg in query(prompt="/usage", options=options):
            if type(msg).__name__ == "ResultMessage":
                text = getattr(msg, "result", "") or ""
        return text

    text = asyncio.run(ask())
    found = usage.from_usage_text(text)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if not found:
        raise ValueError(_explain(text, cli) if "Not logged in" in text else
                         f"/usage gave no usage windows: {first or 'no answer'}")
    return usage.record(found, "check", note=first)
