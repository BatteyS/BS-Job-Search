"""Running a skill from the page, through ui/claude_run.py, without the Agent
SDK: finding the binary, building the prompt, turning SDK messages into the
page's events, and the card round trip that every approval and question goes
through."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import types
from dataclasses import dataclass, field

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import claude_run  # noqa: E402
import core  # noqa: E402
import router  # noqa: E402
import usage  # noqa: E402


# --------------------------------------------------------------- the binary

def test_find_claude_prefers_the_users_own_install(monkeypatch):
    monkeypatch.setattr(claude_run.glob, "glob", lambda p: [])
    exists = lambda p: p in {"/x/claude", os.path.expanduser("~/.local/bin/claude")}  # noqa: E731

    assert claude_run.find_claude({"BS_CLAUDE_BIN": "/x/claude"}, which=lambda n: None,
                                  exists=exists) == ("/x/claude", "BS_CLAUDE_BIN")
    path, why = claude_run.find_claude({"BS_CLAUDE_BIN": "/nope"}, which=lambda n: None,
                                       exists=exists)
    assert path is None and "BS_CLAUDE_BIN" in why
    assert claude_run.find_claude({}, which=lambda n: "/opt/bin/claude", exists=exists)[1] == "on PATH"
    assert claude_run.find_claude({}, which=lambda n: None, exists=exists) == (
        os.path.expanduser("~/.local/bin/claude"), "a usual install location")


def test_find_claude_takes_the_newest_desktop_copy_then_gives_up(monkeypatch):
    hits = ["/A/claude-code/2.1.9/a/claude.app/Contents/MacOS/claude",
            "/A/claude-code/2.1.300/b/claude.app/Contents/MacOS/claude"]
    monkeypatch.setattr(claude_run.glob, "glob", lambda p: list(reversed(hits)))
    path, how = claude_run.find_claude({}, which=lambda n: None, exists=lambda p: False)
    assert path == hits[1] and how == "the Claude desktop app"

    monkeypatch.setattr(claude_run.glob, "glob", lambda p: [])
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)   # import fails
    path, how = claude_run.find_claude({}, which=lambda n: None, exists=lambda p: False)
    assert path is None and "install Claude Code" in how


def test_child_env_drops_the_desktop_sessions_variables():
    env = claude_run.child_env({"PATH": "/bin", "CLAUDECODE": "1",
                                "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/x", "HOME": "/h"})
    assert env == {"PATH": "/bin", "HOME": "/h",
                   "CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL": "true"}


# ------------------------------------------------------------------ prompts

def test_prompts_are_what_a_person_would_type(monkeypatch):
    assert claude_run.build_prompt("job-scan") == "/job-scan"
    assert claude_run.build_prompt("setup", {"text": "ignored"}) == "/setup"
    assert claude_run.build_prompt("tailor-resume", {"text": " https://x/y "}) == \
        "/tailor-resume https://x/y"
    with pytest.raises(ValueError, match="needs a posting"):
        claude_run.build_prompt("cover-letter", {})
    with pytest.raises(ValueError, match="no skill"):
        claude_run.build_prompt("rm")

    monkeypatch.setattr(core, "digest_path", lambda d: d)
    assert claude_run.build_prompt("tailor-digest", {"date": "2026-11-02"}) == \
        "/tailor-digest for digests/2026-11-02.md"
    assert claude_run.build_prompt("tailor-digest") == "/tailor-digest"
    assert [s["name"] for s in claude_run.skills()] == [
        "job-scan", "tailor-digest", "tailor-resume", "cover-letter", "setup"]


# ------------------------------------------------------------------- events
# Stand-ins named like the SDK's types: events_from() matches on the name.

@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: object = None
    is_error: bool | None = None


@dataclass
class SystemMessage:
    subtype: str
    data: dict = field(default_factory=dict)


@dataclass
class AssistantMessage:
    content: list


@dataclass
class UserMessage:
    content: object


@dataclass
class ResultMessage:
    subtype: str = "success"
    is_error: bool = False
    result: str = ""
    num_turns: int = 1
    total_cost_usd: float | None = None
    usage: dict | None = None


@dataclass
class RateLimitEvent:
    rate_limit_info: object


def test_sdk_messages_become_page_events():
    init = claude_run.events_from(SystemMessage("init", {"session_id": "s1", "model": "m"}))
    assert init == [{"kind": "init", "session_id": "s1", "model": "m"}]
    assert claude_run.events_from(SystemMessage("status", {})) == []

    assistant = AssistantMessage([
        TextBlock("Reading the posting."), TextBlock("  "),
        ToolUseBlock("t1", "Bash", {"command": "python scripts/doctor.py"}),
        ToolUseBlock("t2", "Edit", {"file_path": os.path.join(ROOT, "content/master.md")}),
    ])
    assert claude_run.events_from(assistant) == [
        {"kind": "text", "text": "Reading the posting."},
        {"kind": "tool_use", "id": "t1", "name": "Bash", "summary": "python scripts/doctor.py"},
        {"kind": "tool_use", "id": "t2", "name": "Edit", "summary": "content/master.md"},
    ]
    result = claude_run.events_from(UserMessage([ToolResultBlock(
        "t1", [{"type": "text", "text": "ok " * 400}, {"type": "image"}], False)]))
    assert result[0]["id"] == "t1" and result[0]["ok"] and result[0]["excerpt"].endswith(" …")
    assert claude_run.events_from(UserMessage("plain text")) == []

    done = claude_run.events_from(ResultMessage(num_turns=3, total_cost_usd=0.5))[0]
    assert done == {"kind": "turn_end", "subtype": "success", "is_error": False,
                    "num_turns": 3, "cost": 0.5, "tokens": 0, "result": ""}
    err = claude_run.events_from(ResultMessage(is_error=True, result="Not logged in"))[0]
    assert err["is_error"] and err["result"] == "Not logged in"
    assert "auth login" in claude_run._explain(err["result"], "/x/claude")


def test_plan_usage_and_tokens_become_events():
    info = types.SimpleNamespace(status="allowed", rate_limit_type="five_hour", utilization=None,
                                 resets_at=100, raw={"unifiedWindows": {
                                     "five_hour": {"utilization": 0.4, "resetsAt": 100},
                                     "seven_day": {"utilization": 0.1, "resetsAt": 900}}})
    [ev] = claude_run.events_from(RateLimitEvent(info))
    assert ev["kind"] == "limits"
    assert ev["windows"]["five_hour"]["used"] == 0.4 and ev["windows"]["seven_day"]["used"] == 0.1

    turn = ResultMessage(total_cost_usd=0.2, usage={
        "input_tokens": 2, "output_tokens": 30, "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 100, "output_tokens_details": {"thinking_tokens": 5}})
    assert claude_run.events_from(turn)[0]["tokens"] == 1032


def test_the_login_hint_names_the_binary_the_page_found(monkeypatch):
    monkeypatch.setattr(claude_run.shutil, "which", lambda n: None)
    assert claude_run.login_command("/A B/claude") == '"/A B/claude" auth login'
    assert '"/A B/claude" auth login' in claude_run._explain("Not logged in", "/A B/claude")
    monkeypatch.setattr(claude_run.shutil, "which", lambda n: "/A B/claude")
    assert claude_run.login_command("/A B/claude") == "claude auth login"
    assert claude_run._explain("boom", "/A B/claude") == "boom"


def test_the_setup_tab_gets_the_one_command_to_run(monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    import subprocess

    def fake_run(argv, **kw):
        out = '{"loggedIn": %s}' % ("true" if logged_in else "false")
        return subprocess.CompletedProcess(argv, 0, out if "auth" in argv else "2.1.317", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(claude_run.shutil, "which", lambda n: "/u/bin/claude")

    monkeypatch.setattr(claude_run, "find_claude", lambda: (None, "no Claude Code binary found"))
    s = claude_run.claude_status()
    assert not s["available"] and s["install"] == claude_run.install_command() and "login" not in s

    logged_in = False
    monkeypatch.setattr(claude_run, "find_claude", lambda: ("/u/bin/claude", "on PATH"))
    s = claude_run.claude_status()
    assert not s["available"] and s["login"] == "claude auth login" and "install" not in s

    # Only the SDK's own copy: the page asks for Claude Code itself, not a login to that copy.
    monkeypatch.setattr(claude_run, "find_claude", lambda: ("/sdk/_bundled/claude", claude_run.BUNDLED))
    s = claude_run.claude_status()
    assert not s["available"] and "install" in s and "login" not in s

    logged_in = True
    s = claude_run.claude_status()
    assert s["available"] and s["logged_in"] and "install" not in s and "login" not in s


def test_the_install_command_fits_the_system():
    assert claude_run.install_command("Windows").startswith("irm https://claude.ai/install.ps1")
    assert claude_run.install_command("Darwin") == claude_run.install_command("Linux")
    assert "https://claude.ai/install.sh" in claude_run.install_command("Darwin")


# -------------------------------------------------------------------- cards

@dataclass
class Suggestion:
    destination: str


def test_a_ground_truth_edit_is_a_guarded_card_with_no_always():
    master = os.path.join(ROOT, "content", "master.md")
    card = claude_run.make_card("Edit", {"file_path": master, "old_string": "a", "new_string": "b"},
                                [Suggestion("localSettings")])
    assert card["card_kind"] == "permission" and card["guard"] is True
    assert card["file"] == "content/master.md" and card["can_always"] is False

    digest = os.path.join(ROOT, "digests", "2026-11-02.md")
    card = claude_run.make_card("Write", {"file_path": digest, "content": "x"},
                                [Suggestion("session"), Suggestion("localSettings")])
    assert card["guard"] is False and card["can_always"] is True
    assert claude_run.make_card("Bash", {"command": "ls"}, [])["can_always"] is False


def test_permission_results():
    card = claude_run.make_card("Bash", {"command": "mkdir x"},
                                [Suggestion("session"), Suggestion("localSettings")])
    assert claude_run.permission_result(card, "allow") == {
        "behavior": "allow", "updated_input": {"command": "mkdir x"}}
    always = claude_run.permission_result(card, "always", suggestions=[
        Suggestion("session"), Suggestion("localSettings")])
    assert [s.destination for s in always["updated_permissions"]] == ["localSettings"]
    deny = claude_run.permission_result(card, "deny", "use a different folder")
    assert deny == {"behavior": "deny", "message": "use a different folder"}
    with pytest.raises(ValueError):
        claude_run.permission_result(card, "maybe")

    guarded = claude_run.make_card("Edit", {"file_path": os.path.join(ROOT, "content/story.md")},
                                   [Suggestion("localSettings")])
    assert "updated_permissions" not in claude_run.permission_result(
        guarded, "always", suggestions=[Suggestion("localSettings")])

    questions = [{"question": "Which clusters?", "header": "Clusters",
                  "options": [{"label": "a", "description": ""}], "multiSelect": True}]
    q = claude_run.make_card("AskUserQuestion", {"questions": questions})
    assert q["card_kind"] == "question" and q["questions"] == questions
    assert claude_run.permission_result(q, "allow", answers={"Which clusters?": ["a"]}) == {
        "behavior": "allow",
        "updated_input": {"questions": questions, "answers": {"Which clusters?": ["a"]}}}
    assert claude_run.permission_result(q, "deny")["behavior"] == "deny"


def test_a_card_blocks_the_run_until_the_page_answers(monkeypatch, tmp_path):
    """The callback runs on the run's own loop and waits; answer() from another
    thread releases it with the page's decision."""
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    run = claude_run.ClaudeRun("job-scan", "/job-scan", "/bin/true")
    monkeypatch.setattr(run, "_to_sdk", lambda spec: spec)
    got = {}

    async def drive():
        run._loop = asyncio.get_running_loop()
        run._set_status("running")
        got["spec"] = await run._can_use_tool(
            "AskUserQuestion", {"questions": [{"question": "Colour?", "options": []}]}, None)

    t = threading.Thread(target=lambda: asyncio.run(drive()))
    t.start()
    for _ in range(200):
        if run.pending:
            break
        threading.Event().wait(0.01)
    assert run.status == "waiting" and run.pending["card_kind"] == "question"
    with pytest.raises(ValueError):
        run.answer("wrong-id", "allow")
    run.answer(run.pending["card_id"], "allow", answers={"Colour?": "red"})
    t.join(timeout=5)
    assert got["spec"]["updated_input"]["answers"] == {"Colour?": "red"}
    assert run.pending is None and run.status == "running"
    assert [e["kind"] for e in run.events if e["kind"] != "status"] == ["card", "card_answered"]
    assert [e["status"] for e in run.events if e["kind"] == "status"] == ["running", "waiting", "running"]

    entries = claude_run.load_index()
    assert entries[-1]["id"] == run.id and entries[-1]["status"] == "running"


def test_say_and_stop_follow_the_status(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    run = claude_run.ClaudeRun("setup", "/setup", "/bin/true")
    with pytest.raises(ValueError, match="not waiting"):
        run.say("hello")
    run.stop()                      # never started: nothing to interrupt
    assert run.status == "stopped"

    loop = asyncio.new_event_loop()
    run._loop, run._inbox = loop, asyncio.Queue()
    run._set_status("idle")
    run.say("my answer")
    loop.run_until_complete(asyncio.sleep(0))
    assert run.status == "running" and run._inbox.get_nowait() == "my answer"
    run._set_status("idle")
    run.stop()
    loop.run_until_complete(asyncio.sleep(0))
    assert run.status == "done" and run._inbox.get_nowait() is None
    assert list(run.follow(0))[-1] is None


def test_a_skill_starts_on_its_route_and_the_pick_is_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_run, "find_claude", lambda: ("/bin/true", "test"))
    monkeypatch.setattr(claude_run.ClaudeRun, "start", lambda self: self)
    monkeypatch.setattr(usage, "USAGE", str(tmp_path / "ui-usage.json"))
    run = claude_run.start_skill("cover-letter", {"text": "https://example.com/job"})
    assert run.prompt == "/cover-letter https://example.com/job"
    assert (run.route["model"], run.route["effort"], run.route["auto"]) == ("opus", "high", True)

    run = claude_run.start_skill("cover-letter", {"text": "x", "model": "sonnet"})
    assert (run.route["model"], run.route["effort"]) == ("sonnet", "high")
    with pytest.raises(ValueError):
        claude_run.start_skill("setup", {"effort": "ultra"})

    usage.record({"five_hour": {"used": 0.9, "resets_at": 4_000_000_000}}, "run")
    assert claude_run.start_skill("tailor-resume", {"text": "x"}).route["model"] == "sonnet"
    assert [s["route"]["model"] for s in claude_run.skills(limits={})] == [
        router.ROUTES[name][0] for name in claude_run.SKILLS]


def test_one_skill_at_a_time(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    runs = core.Runs()
    started = []
    monkeypatch.setattr(claude_run, "start_skill",
                        lambda name, params=None, resume=None, prompt=None: started.append(
                            claude_run.ClaudeRun(name, prompt or "/" + name, "/bin/true")) or started[-1])
    first = runs.start_skill("job-scan")
    assert runs.active_claude() is first
    with pytest.raises(RuntimeError, match="still starting"):
        runs.start_skill("setup")
    first._set_status("done")
    assert runs.active_claude() is None
    runs.start_skill("setup")
    assert [r.summary()["kind"] for r in started] == ["claude", "claude"]


# ------------------------------------------------------------- stopping
# A stand-in for the SDK's client, so a whole run goes through _main().

def fake_sdk(opened: threading.Event, disconnected: threading.Event):
    class Client:
        def __init__(self, options):
            opened.set()
            self.closed = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            await self.disconnect()
            return False

        async def query(self, prompt):
            pass

        async def interrupt(self):
            pass                              # ends nothing, as on 2026-11-03

        async def disconnect(self):           # the real one ends the CLI process
            disconnected.set()
            self.closed.set()

        async def receive_response(self):
            await self.closed.wait()          # a turn that never ends on its own,
            raise RuntimeError("stream closed")   # and a stream that breaks when closed
            yield

    return types.SimpleNamespace(ClaudeAgentOptions=lambda **kw: kw, ClaudeSDKClient=Client)


def test_stop_closes_a_session_whose_turn_will_not_end(monkeypatch, tmp_path):
    """The first live stop interrupted a turn that never ended, and the run's
    Claude Code process outlived it. stop() now disconnects the session, which
    ends the process, and the run reads as stopped rather than failed."""
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    monkeypatch.setattr(claude_run, "STOP_GRACE", 0.1)
    opened, disconnected = threading.Event(), threading.Event()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk(opened, disconnected))

    run = claude_run.ClaudeRun("job-scan", "/job-scan", "/bin/true").start()
    for _ in range(300):
        if run.status == "running":
            break
        threading.Event().wait(0.01)
    assert run.status == "running"
    run.stop()
    run._thread.join(timeout=3)
    assert disconnected.is_set() and not run._thread.is_alive()
    assert run.status == "stopped"
    assert not [e for e in run.events if e["kind"] == "error"]


def test_a_stopped_turn_that_ends_in_an_error_reads_as_stopped(monkeypatch, tmp_path):
    """Interrupted, Claude Code ends the turn with an error result. That is the
    stop working: the run reads as stopped, with no error shown."""
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))

    class Client:
        def __init__(self, options):
            self.halt = asyncio.Event()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def query(self, prompt):
            pass

        async def interrupt(self):
            self.halt.set()

        async def disconnect(self):
            self.halt.set()

        async def receive_response(self):
            await self.halt.wait()
            yield ResultMessage(subtype="error_during_execution", is_error=True)

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(
        ClaudeAgentOptions=lambda **kw: kw, ClaudeSDKClient=Client))
    run = claude_run.ClaudeRun("job-scan", "/job-scan", "/bin/true").start()
    for _ in range(300):
        if run.status == "running":
            break
        threading.Event().wait(0.01)
    run.stop()
    run._thread.join(timeout=3)
    assert run.status == "stopped" and not run._thread.is_alive()
    assert not [e for e in run.events if e["kind"] == "error"]


def test_a_run_goes_out_on_its_route_and_keeps_its_usage(monkeypatch, tmp_path):
    """The route reaches Claude Code as --model and --effort, Opus gets Sonnet
    as its overload fallback, the route is the run's first note, and each turn's
    tokens and the plan's windows are kept."""
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    monkeypatch.setattr(usage, "USAGE", str(tmp_path / "ui-usage.json"))
    seen = {}
    info = types.SimpleNamespace(status="allowed", rate_limit_type="five_hour", utilization=None,
                                 resets_at=None, raw={"unifiedWindows": {
                                     "five_hour": {"utilization": 0.33, "resetsAt": 4_000_000_000}}})

    class Client:
        def __init__(self, options):
            seen["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def query(self, prompt):
            seen["prompt"] = prompt

        async def interrupt(self):
            pass

        async def disconnect(self):
            pass

        async def receive_response(self):
            yield RateLimitEvent(info)
            yield ResultMessage(total_cost_usd=0.12, usage={"input_tokens": 10, "output_tokens": 90})

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", types.SimpleNamespace(
        ClaudeAgentOptions=lambda **kw: kw, ClaudeSDKClient=Client))
    run = claude_run.ClaudeRun("cover-letter", "/cover-letter x", "/bin/true",
                               route=router.route("cover-letter")).start()
    for _ in range(300):
        if run.status == "idle":
            break
        threading.Event().wait(0.01)
    assert run.status == "idle"
    opts = seen["options"]
    assert (opts["model"], opts["effort"], opts["fallback_model"]) == ("opus", "high", "sonnet")
    kinds = [e["kind"] for e in run.events if e["kind"] != "status"]
    assert kinds[:2] == ["route", "user"] and "limits" in kinds
    assert (run.tokens, run.cost) == (100, 0.12)
    assert usage.windows()["five_hour"]["used"] == 0.33
    assert claude_run.load_index()[-1]["route"] == "Opus · high"
    run.stop()
    run._thread.join(timeout=3)
    assert run.status == "done"


def test_a_run_stopped_before_it_starts_never_opens_a_session(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_run, "INDEX", str(tmp_path / "ui-runs.json"))
    opened, disconnected = threading.Event(), threading.Event()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk(opened, disconnected))

    run = claude_run.ClaudeRun("job-scan", "/job-scan", "/bin/true")
    run.stop()
    run.start()
    run._thread.join(timeout=3)
    assert not opened.is_set() and run.status == "stopped"
