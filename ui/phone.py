"""Job Search on your phone: an icon on its home screen that opens the page,
from anywhere, while the page itself stays on this Mac.

    uv run python ui/phone.py status    # what is set up, as JSON
    uv run python ui/phone.py check     # whether it works now; if not, why and what to do
    uv run python ui/phone.py enable    # set it up: cd ~/job-search && sh install.sh --phone
    uv run python ui/phone.py disable   # take it all down again

Two pieces, both on this Mac, and the Tailscale app on the phone:

  * launchd starts the page when something asks for it. A LaunchAgent holds
    127.0.0.1:8765 and runs `ui/launch.sh --launchd` at the first connection,
    so nothing runs between uses: the page still stops itself ten minutes after
    its last tab closes, and the next tap, on the phone or on Job Search on the
    Desktop, starts it again.
  * Tailscale carries the phone to it. `tailscale serve` gives this Mac an
    HTTPS address that only devices signed in to the same Tailscale account can
    reach, https://<mac>.<tailnet>.ts.net, and forwards it to the page, which
    goes on listening on this Mac alone. Serve says who is asking, and the page
    answers only the account recorded here, in data/ui-remote.json, which never
    leaves this machine (core.refusal).

On the phone: install Tailscale and sign in to the same account, open that
address in Safari (or Chrome on Android), and Add to Home Screen. The Mac has
to be awake for the phone to reach it, and a Mac sleeps on its own once its
display turns off, even plugged in: SLEEP says how to keep it awake. Nothing
here changes that setting, which is the user's.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

LABEL = "io.github.batteys.bs-job-search"
# Job Search on the Desktop (install.sh). macOS names the agent after it under
# Login Items, rather than after /bin/sh.
APP_ID = "io.github.batteys.bs-job-search"
PORT = 8765
LOG = os.path.expanduser("~/Library/Logs/BS Job Search.log")
TAILSCALE_APP = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
# The App Store first: a standard (non-admin) account can install from it, and
# the download from tailscale.com is an installer that asks for an administrator.
GET_TAILSCALE = ("Install the Tailscale app from the Mac App Store (search for Tailscale), or from "
                 "tailscale.com/download if you are an administrator of this Mac, since that "
                 "installer asks for one. Open it, sign in, and allow what it asks for; then run "
                 "this again. It is free for personal use, and its command-line tool is not needed.")
# What keeps the Mac reachable. Said, never done: the setting is the user's.
SLEEP = ("This Mac has to be awake for your phone to reach it, and a Mac sleeps on its own once its "
         "display turns off, even plugged in; a laptop also sleeps with its lid closed. To keep it "
         "reachable, keep it plugged in and turn on \"Prevent automatic sleeping on power adapter "
         "when the display is off\", in System Settings > Battery > Options (on a desktop Mac, "
         "\"Prevent automatic sleeping when the display is off\": search System Settings for it). "
         "After a restart, someone has to log in on the Mac before your phone can reach it.")
# What to do when the icon opens to an error page of the phone's own.
RECOVER = ("If the icon opens to an error, wake the Mac and check that Tailscale is on, on the "
           "phone, then swipe Job Search away in the app switcher and open it again.")
# The one thing phone access changes for other people with accounts on this Mac.
SHARED = ("If other people have accounts on this Mac: with phone access on, they can open your "
          f"page too, at 127.0.0.1:{PORT}, whenever they like, since it starts when asked for.")

# Folders macOS keeps from anything it starts in the background (Files and
# Folders privacy): launchd cannot run the page from a copy inside one, and it
# fails with "Operation not permitted" rather than asking. Job Search on the
# Desktop can, because you opened it and macOS asked you.
PROTECTED = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents", "Library/CloudStorage")
BLOCKED = "Operation not permitted"


def protected_folder(root: str, home: str | None = None) -> str | None:
    """The protected folder the copy is in, as macOS names it, or None."""
    home = os.path.realpath(home or os.path.expanduser("~"))
    real = os.path.realpath(root)
    if real.startswith("/Volumes/"):
        return "another disk"
    for name in PROTECTED:
        top = os.path.join(home, name)
        if real == top or real.startswith(top + os.sep):
            return {"Library/Mobile Documents": "iCloud Drive",
                    "Library/CloudStorage": "a cloud drive's folder"}.get(name, name)
    return None


def move_advice(root: str, where: str) -> str:
    return (f"This copy is in {where} ({root}), which macOS does not let anything started in the "
            "background open, so the page could not start for your phone. Move the copy to a "
            "folder of its own in your home folder, then run the installer there:\n\n"
            f"    mv {_sh(root)} ~/job-search && cd ~/job-search && sh install.sh --phone\n\n"
            "Job Search on the Desktop is remade to point at the new place. Close the page first.")


def _sh(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def cd(root: str, home: str | None = None) -> str:
    """`cd` to the copy, as a person would type it, so a command works from a
    new Terminal window: ~/job-search rather than the whole path, when the copy
    is in the home folder under a plain name."""
    home = home or os.path.expanduser("~")
    if root.startswith(home.rstrip(os.sep) + os.sep):
        rest = root[len(home.rstrip(os.sep)) + 1:]
        if rest and all(c.isalnum() or c in "-_./" for c in rest):
            return f"cd ~/{rest}"
    return f"cd {_sh(root)}"


def say(text: str = "") -> None:
    print(text, flush=True)


# ------------------------------------------------------------------ launchd

def plist_path(label: str = LABEL) -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")


def agent_plist(root: str, port: int = PORT, label: str = LABEL) -> bytes:
    """The LaunchAgent: launchd listens on the page's port and, at a connection,
    runs the launcher in --launchd mode, which becomes the page and takes the
    socket (core.launchd_sockets)."""
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/sh", os.path.join(root, "ui", "launch.sh"), "--launchd"],
        "Sockets": {"Listeners": {"SockNodeName": "127.0.0.1", "SockServiceName": str(port),
                                  "SockType": "stream", "SockFamily": "IPv4"}},
        "WorkingDirectory": root,
        "StandardOutPath": LOG,
        "StandardErrorPath": LOG,
        # A restart is the page stopping, then the next request starting it:
        # launchd's 10-second default would hold that request up.
        "ThrottleInterval": 1,
        "AssociatedBundleIdentifiers": [APP_ID],
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)


def agent_loaded(label: str = LABEL) -> bool:
    try:
        return _launchctl("print", f"gui/{os.getuid()}/{label}").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _unload(label: str) -> None:
    """Take the agent out of launchd, and wait until it is out: bootout returns
    first, and loading it again before then fails."""
    _launchctl("bootout", f"gui/{os.getuid()}/{label}")
    end = time.time() + 10
    while agent_loaded(label) and time.time() < end:
        time.sleep(0.2)


def _health(port: int, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _post(port: int, path: str) -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        return 0, str(exc)


def _wait_free(port: int, seconds: float = 20) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if core.probe_port(port)[0] == "free":
            return True
        time.sleep(0.5)
    return False


WORKING = "A run is working in the page. Let it finish, then run this again."


def install_agent(root: str = core.ROOT, port: int = PORT, label: str = LABEL) -> None:
    """Hand the page's port to launchd. An agent set up before is taken out
    first, and a page of this copy that is running now is asked to stop, unless
    a run is working in either; anything else on the port stops here, changed
    nothing."""
    if agent_loaded(label):
        # Setting up again, as when it broke. The agent holds the port, so any
        # question starts its page, and a cold start outlasts probe_port's two
        # seconds, which would read as another program. So ask with time to
        # spare, and only whether a run is working (no answer: none can be),
        # then take the agent out and see what is left on the port. Out with
        # its plist: if this stops below, the Setup tab says setup did not
        # finish, rather than that the agent was switched off.
        if (_health(port, 30) or {}).get("working"):
            raise core.Stop(WORKING)
        remove_agent(label)
        _wait_free(port, 10)
    held, where = core.probe_port(port)
    if held == "another":
        raise core.Stop(f"Port {port} is taken by Job Search for another folder, {where}. "
                        "Stop that one first.")
    if held == "other":
        raise core.Stop(f"Port {port} is taken by another program, which launchd would need.")
    if held == "this":
        if (_health(port, 5) or {}).get("working"):
            raise core.Stop(WORKING)
        code, text = _post(port, "/api/quit")
        if code != 200 or not _wait_free(port):
            raise core.Stop(f"The page running now would not stop ({code}: {text[:200]}). Close its "
                            "tabs, wait ten minutes for it to stop by itself, then run this again.")
    path = plist_path(label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    size = os.path.getsize(LOG) if os.path.isfile(LOG) else 0
    with open(path, "wb") as fh:
        fh.write(agent_plist(root, port, label))
    r = _launchctl("bootstrap", f"gui/{os.getuid()}", path)
    if r.returncode != 0:
        remove_agent(label)
        raise core.Stop(f"launchd did not take the agent: {(r.stderr or r.stdout).strip()}")
    h = _health(port, 120)   # this request is what starts the page
    if not h or not h.get("root") or os.path.realpath(h["root"]) != os.path.realpath(root):
        # Leave the Mac as it was: an agent that cannot start the page would hold
        # its port and fail every request, Job Search on the Desktop's too.
        remove_agent(label)
        printed = _since(LOG, size)
        if BLOCKED in printed:
            raise core.Stop(move_advice(root, protected_folder(root) or "a folder macOS protects"))
        raise core.Stop("launchd could not start the page, so phone access is not set up and "
                        "nothing has changed. The last of what it printed:\n\n"
                        + "\n".join(printed.strip().splitlines()[-8:]) + f"\n\nAll of it is in {LOG}")


def _since(path: str, size: int) -> str:
    """What was written to a file after it had `size` bytes."""
    try:
        with open(path, "rb") as fh:
            fh.seek(size)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def remove_agent(label: str = LABEL) -> None:
    if agent_loaded(label):
        _unload(label)
    try:
        os.remove(plist_path(label))
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- Tailscale

def find_tailscale() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    return TAILSCALE_APP if os.path.isfile(TAILSCALE_APP) else None


def tailscale_status(cli: str | None = None) -> dict:
    """{found, running, host, login}: whether Tailscale is here and signed in,
    this Mac's tailnet name, and the account it is signed in as."""
    cli = cli or find_tailscale()
    out = {"found": bool(cli), "running": False, "host": None, "login": None}
    if not cli:
        return out
    try:
        r = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    return {**out, **parse_status(data)}


def parse_status(data: dict) -> dict:
    """What tailscale_status needs from `tailscale status --json`."""
    me = data.get("Self") or {}
    user = (data.get("User") or {}).get(str(me.get("UserID")), {})
    host = (me.get("DNSName") or "").rstrip(".").lower() or None
    return {"running": data.get("BackendState") == "Running", "host": host,
            "login": user.get("LoginName")}


def serve(cli: str, port: int = PORT) -> bool:
    """Point this Mac's tailnet address at the page. The first time, Tailscale
    may print a link to turn HTTPS on for the tailnet, and waits until it is."""
    say("The first time, Tailscale may print a login.tailscale.com link to turn on HTTPS for your "
        "tailnet: open it (hold Command and double-click it) and click Enable. This step waits up "
        "to 10 minutes for that.")
    say(f"$ tailscale serve --bg http://127.0.0.1:{port}")
    try:
        return subprocess.run([cli, "serve", "--bg", f"http://127.0.0.1:{port}"],
                              timeout=600).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"tailscale serve did not run: {exc}")
        return False


def served(cli: str, port: int = PORT) -> bool | None:
    """Whether Tailscale forwards this Mac's address to the page, or None when
    it cannot say, as when it is not running."""
    try:
        r = subprocess.run([cli, "serve", "status", "--json"], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return f"127.0.0.1:{port}" in (r.stdout or "")


def unserve(cli: str) -> bool:
    """Stop forwarding this Mac's address: whether Tailscale says it has."""
    try:
        return subprocess.run([cli, "serve", "--https=443", "off"], capture_output=True,
                              timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------- what

def diagnose(ts: dict, remote: dict | None, agent: dict) -> dict | None:
    """Why phone access, set up here, does not work now, and what to do: the
    first of these that holds. None when it works, or was never set up. The
    Setup tab and the installer both say this, so they cannot disagree."""
    if not remote:
        return None
    if ts.get("host") and ts["host"] != remote["host"]:
        return {"code": "address", "label": "address changed",
                "text": f"This Mac's Tailscale address is now {ts['host']}, not {remote['host']}, "
                        "which phone access was set up for: the Mac was renamed, or Tailscale is "
                        "signed in to another account. Set phone access up again, then open the "
                        "new address on your phone and add it to the Home Screen in place of the "
                        "old icon."}
    if not ts.get("running") or not ts.get("host"):
        return {"code": "tailscale", "label": "Tailscale is off",
                "text": f"Open Tailscale (in Applications) on this Mac and sign in as "
                        f"{remote['login']}: your phone reaches the page through it."}
    if not agent.get("installed"):
        return {"code": "unfinished", "label": "not finished",
                "text": "launchd no longer starts the page for your phone: the last setup did not "
                        "finish. Set phone access up again."}
    if not agent.get("loaded"):
        return {"code": "switched-off", "label": "switched off",
                "text": "Job Search is switched off in System Settings > General > Login Items & "
                        "Extensions, under Allow in the Background, so launchd no longer starts "
                        "the page. Turn it on there, then set phone access up again."}
    return None


def status() -> dict:
    """What the Setup tab shows: the agent, Tailscale, the phone's address,
    why it does not work when it is set up but does not (`why`), and the
    commands that set it up again and take it down, each with its `cd`."""
    ts = tailscale_status()
    remote = core.remote_access()
    where = protected_folder(core.ROOT)
    agent = {"installed": os.path.isfile(plist_path()), "loaded": agent_loaded()}
    here = cd(core.ROOT)
    return {"mac": sys.platform == "darwin", "protected": where,
            "move": f"mv {_sh(core.ROOT)} ~/job-search && cd ~/job-search && sh install.sh --phone"
                    if where else None,
            "agent": agent, "tailscale": ts, "remote": remote,
            "url": f"https://{remote['host']}/" if remote else None,
            "ready": bool(remote and ts["running"] and ts["host"] == remote["host"]
                          and agent["loaded"]),
            "why": None if where else diagnose(ts, remote, agent),
            "setup": f"{here} && sh install.sh --phone",
            "disable": f"{here} && uv run python ui/phone.py disable",
            "awake": SLEEP, "recover": RECOVER}


def check() -> int:
    """Whether phone access works now, for the installer: 0 when it does, else
    1, with why and what to do, from the same diagnosis as the Setup tab."""
    s = status()
    if s["ready"]:
        say(f"set up: {s['url']} opens the page on your phone")
        return 0
    if s["protected"]:
        say(move_advice(core.ROOT, s["protected"]))
        return 1
    why = s["why"]
    if not why:
        say(f"Not set up. To set it up: {s['setup']}")
        return 1
    say(f"Phone access: {why['label']}. {why['text']}")
    if why["code"] != "tailscale":
        say(f"    {s['setup']}")
    return 1


def enable() -> int:
    if sys.platform != "darwin":
        say("Phone access is set up on a Mac for now.")
        return 1
    where = protected_folder(core.ROOT)
    if where:
        say(move_advice(core.ROOT, where))
        return 1
    say("Handing the page's port to launchd, which starts the page when something asks...")
    try:
        install_agent()
    except core.Stop as exc:
        say(str(exc))
        return 1
    say(f"  ok  launchd starts the page on 127.0.0.1:{PORT} when it is asked for")
    cli = find_tailscale()
    if not cli:
        say("\nTailscale is not on this Mac, so only this Mac can open the page so far. " + GET_TAILSCALE)
        return 2
    ts = tailscale_status(cli)
    if not ts["running"] or not ts["host"] or not ts["login"]:
        say("\nTailscale is installed but not running, or not signed in. Open Tailscale (in "
            "Applications), sign in, then run this again.")
        return 2
    if not serve(cli):
        say("\ntailscale serve did not finish. If it printed a link to turn on HTTPS for your "
            "tailnet, open it, turn HTTPS on, then run this again. Only the tailnet's owner or an "
            "admin of it can: on a tailnet someone else runs, such as an employer's, ask them.")
        return 2
    core.save_remote_access(ts["host"], ts["login"], PORT)
    url = f"https://{ts['host']}/"
    say(f"  ok  {url} reaches the page from your devices, signed in as {ts['login']}")
    say("\nOn your phone:")
    say("  1. Install the Tailscale app and sign in as " + ts["login"] + ".")
    say(f"  2. Open {url} in Safari (Chrome on Android).")
    say("  3. Share, then Add to Home Screen. The icon opens Job Search like an app.")
    say("\n" + SLEEP)
    say("\n" + RECOVER)
    say("\n" + SHARED + f" To turn phone access off: {cd(core.ROOT)} && uv run python ui/phone.py "
        "disable")
    return 0


def disable() -> int:
    # Taking the agent out stops its page, and a run working in it with it.
    if agent_loaded() and (_health(PORT, 5) or {}).get("working"):
        say(WORKING + " Turning phone access off stops the page.")
        return 1
    cli = find_tailscale()
    # Only what is on: turning off what is not makes Tailscale fail.
    left = bool(cli) and served(cli) is not False and not unserve(cli)
    core.save_remote_access(None)
    remove_agent()
    if left:
        say("Phone access is off on this Mac: the page answers it alone again, and refuses "
            "anything Tailscale still forwards. But Tailscale did not say it stopped forwarding "
            "this Mac's address to it. Once Tailscale is running, stop that with:\n\n"
            f"    {_sh(cli)} serve --https=443 off")
        return 1
    say("Phone access is off: the page answers this Mac alone again, and Job Search on the "
        "Desktop starts it as before.")
    return 0


def main(argv: list[str]) -> int:
    what = argv[0] if argv else "status"
    if what == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if what == "check":
        return check()
    if what == "enable":
        return enable()
    if what == "disable":
        return disable()
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
