"""Job Search on a phone: launchd starts the page when it is asked for, and
Tailscale carries the phone to it (ui/phone.py); the page answers a forwarded
request only for the account set up here (core.refusal); and the icon is drawn
in code (ui/icon.py). Nothing here touches launchd, Tailscale, or the network:
each is a stand-in."""

from __future__ import annotations

import os
import plistlib
import struct
import sys
import zlib

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402
import icon  # noqa: E402
import phone  # noqa: E402

HOST, LOGIN = "averys-mac.tail1234.ts.net", "avery@example.com"


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """Phone access, recorded in a file of the test's own."""
    monkeypatch.setattr(core, "REMOTE", str(tmp_path / "ui-remote.json"))
    core._remote.update(mtime=None, value=None)
    yield
    core._remote.update(mtime=None, value=None)


# ------------------------------------------------------------- who is asked

def test_a_forwarded_request_is_refused_until_phone_access_is_set_up(remote):
    assert "not set up" in core.refusal(HOST, None, LOGIN, True)
    assert core.refusal("127.0.0.1:8765", None) is None          # this Mac, as always
    assert core.refusal(HOST, None) is not None                  # a tailnet name, not forwarded


def test_only_the_account_set_up_reaches_the_page(remote):
    core.save_remote_access(HOST, LOGIN, 8765)
    assert core.remote_access() == {"host": HOST, "login": LOGIN, "port": 8765, "https_port": 8443}
    assert core.refusal(HOST, None, LOGIN, True) is None
    assert core.refusal(HOST, None, "AVERY@example.com", True) is None   # logins ignore case
    assert "signed in as avery@example.com" in core.refusal(HOST, None, "someone@example.org", True)
    assert "signed in as" in core.refusal(HOST, None, None, True)      # forwarded, no account
    assert "answers only at" in core.refusal("evil.example", None, LOGIN, True)
    # Serve may hand the request on addressed to this Mac: the account still decides.
    assert core.refusal("127.0.0.1:8765", None, LOGIN, True) is None
    assert core.refusal("127.0.0.1:8765", None, "someone@example.org", True) is not None


def test_the_phones_page_may_post_and_no_other_site_may(remote):
    core.save_remote_access(HOST, LOGIN)
    assert core.remote_url(core.remote_access()) == f"https://{HOST}:8443/"
    assert core.refusal(f"{HOST}:8443", f"https://{HOST}:8443", LOGIN, True) is None
    assert core.refusal(f"{HOST}:8443", "https://evil.example", LOGIN, True) == (
        "A page on another site cannot use this one.")
    # The root of the same name is another app's, which may not post here.
    assert core.refusal(f"{HOST}:8443", f"https://{HOST}", LOGIN, True) is not None
    # A site open on this Mac cannot borrow the tailnet origin without serve.
    assert core.refusal("127.0.0.1:8765", f"https://{HOST}:8443") is not None


def test_a_setup_from_before_the_port_of_its_own_keeps_its_address(remote):
    """data/ui-remote.json written before phone access had a port of its own
    has none: its address is the root, until it is set up again."""
    import json
    with open(core.REMOTE, "w", encoding="utf-8") as fh:
        json.dump({"host": HOST, "login": LOGIN, "port": 8765}, fh)
    old = core.remote_access()
    assert old["https_port"] == 443 and core.remote_url(old) == f"https://{HOST}/"
    assert core.refusal(HOST, f"https://{HOST}", LOGIN, True) is None
    assert core.refusal(HOST, f"https://{HOST}:8443", LOGIN, True) is not None


def test_turning_phone_access_off_takes_effect_at_once(remote):
    core.save_remote_access(HOST, LOGIN)
    assert core.refusal(HOST, None, LOGIN, True) is None
    core.save_remote_access(None)
    assert core.remote_access() is None
    assert core.refusal(HOST, None, LOGIN, True) is not None


# ------------------------------------------------------------------ launchd

def test_the_agent_lets_launchd_start_the_page_at_a_connection():
    p = plistlib.loads(phone.agent_plist("/Users/a/job search", port=8765))
    assert p["Label"] == phone.LABEL
    assert p["ProgramArguments"] == ["/bin/sh", "/Users/a/job search/ui/launch.sh", "--launchd"]
    sock = p["Sockets"]["Listeners"]
    assert (sock["SockNodeName"], sock["SockServiceName"]) == ("127.0.0.1", "8765")  # this Mac alone
    assert p["ThrottleInterval"] == 1 and p["AssociatedBundleIdentifiers"] == [phone.APP_ID]
    assert p["StandardOutPath"] == p["StandardErrorPath"] == phone.LOG
    assert "KeepAlive" not in p and "RunAtLoad" not in p          # nothing runs between uses


def test_launchd_hands_its_socket_only_to_what_it_started():
    if sys.platform == "darwin":
        with pytest.raises(OSError):        # this test is no launchd job
            core.launchd_sockets()
    else:
        with pytest.raises(RuntimeError):
            core.launchd_sockets()


def test_under_launchd_a_restart_is_only_stopping(monkeypatch):
    started = []
    monkeypatch.delenv("BS_LAUNCHER", raising=False)
    monkeypatch.setenv("BS_LAUNCHD", "1")
    core.restart(8765, core.Runs(), popen=lambda *a, **k: started.append(a))
    assert started == []                    # the next request starts it, through launch.sh


@pytest.mark.parametrize("held, says", [("other", "another program"),
                                        ("another", "another folder")])
def test_the_agent_never_takes_a_port_from_something_else(monkeypatch, held, says):
    monkeypatch.setattr(core, "probe_port", lambda port: (held, "/elsewhere"))
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "_health", lambda port, timeout: {"working": False})
    monkeypatch.setattr(phone, "_launchctl", lambda *a: pytest.fail("launchctl was run"))
    with pytest.raises(core.Stop, match=says):
        phone.install_agent("/copy")


def test_setting_up_again_takes_the_old_agent_out_before_looking_at_the_port(tmp_path, monkeypatch):
    """With the agent loaded and its page idle, a question to the port starts the
    page, and a cold start outlasts probe_port's two seconds, which reads as
    another program: what `sh install.sh --phone` hit when run to repair it."""
    loaded = {"now": True}
    calls = []

    def launchctl(*args):
        calls.append(args[0])
        if args[0] == "bootout":
            loaded["now"] = False
        if args[0] == "bootstrap":
            loaded["now"] = True
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: loaded["now"])
    monkeypatch.setattr(phone, "_launchctl", launchctl)
    monkeypatch.setattr(core, "probe_port",
                        lambda port: ("other", "") if loaded["now"] else ("free", ""))
    monkeypatch.setattr(phone, "_health", lambda port, timeout: {"working": False, "root": "/copy"})
    monkeypatch.setattr(phone, "plist_path", lambda label=phone.LABEL: str(tmp_path / "agent.plist"))
    monkeypatch.setattr(phone, "LOG", str(tmp_path / "page.log"))
    phone.install_agent("/copy", label="test")
    assert calls == ["bootout", "bootstrap"]

    # A run working in the agent's page is never cut off.
    calls.clear()
    monkeypatch.setattr(phone, "_health", lambda port, timeout: {"working": True})
    with pytest.raises(core.Stop, match="working"):
        phone.install_agent("/copy", label="test")
    assert calls == []


def test_a_working_run_is_never_cut_off_to_set_it_up(monkeypatch):
    monkeypatch.setattr(core, "probe_port", lambda port: ("this", "/copy"))
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "_health", lambda port, timeout: {"working": True})
    monkeypatch.setattr(phone, "_post", lambda *a: pytest.fail("the page was asked to quit"))
    with pytest.raises(core.Stop, match="working"):
        phone.install_agent("/copy")


def test_a_copy_macos_keeps_from_background_starts_is_refused_untouched(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    for inside, where in (("Documents/job search", "Documents"), ("Desktop/js", "Desktop"),
                          ("Library/Mobile Documents/com~apple~CloudDocs/js", "iCloud Drive")):
        assert phone.protected_folder(str(tmp_path / inside)) == where
    assert phone.protected_folder(str(tmp_path / "job-search")) is None
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(core, "ROOT", str(tmp_path / "Documents" / "job search"))
    monkeypatch.setattr(phone, "install_agent", lambda *a, **k: pytest.fail("launchd was touched"))
    assert phone.enable() == 1
    out = capsys.readouterr().out
    assert "mv '" in out and "~/job-search" in out and "sh install.sh --phone" in out


def test_an_agent_that_cannot_start_the_page_is_taken_out_again(tmp_path, monkeypatch):
    """Left loaded, it would hold the port and fail every request, Job Search
    on the Desktop's included."""
    log = tmp_path / "page.log"
    log.write_text("earlier lines\n")
    plist = tmp_path / "agent.plist"
    calls = []

    def launchctl(*args):
        calls.append(args[0])
        if args[0] == "bootstrap":   # launchd tries the page, and macOS refuses it
            with open(log, "a") as fh:
                fh.write("/bin/sh: /Users/x/Documents/js/ui/launch.sh: Operation not permitted\n")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(phone, "LOG", str(log))
    monkeypatch.setattr(phone, "plist_path", lambda label=phone.LABEL: str(plist))
    monkeypatch.setattr(core, "probe_port", lambda port: ("free", ""))
    loaded = {"now": False}
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: loaded["now"])
    monkeypatch.setattr(phone, "_launchctl", launchctl)
    monkeypatch.setattr(phone, "_health", lambda port, timeout: None)
    with pytest.raises(core.Stop, match="Move the copy"):
        phone.install_agent(str(tmp_path / "Documents" / "js"), port=8799, label="test")
    assert not plist.exists()                       # nothing left for launchd


# ---------------------------------------------------------------- Tailscale

def test_tailscale_status_names_this_mac_and_its_account():
    got = phone.parse_status({
        "BackendState": "Running",
        "Self": {"DNSName": "Averys-Mac.tail1234.ts.net.", "UserID": 42},
        "User": {"42": {"LoginName": LOGIN}}})
    assert got == {"running": True, "host": HOST, "login": LOGIN}
    assert phone.parse_status({"BackendState": "NeedsLogin"})["running"] is False


def test_enable_records_the_address_and_account_the_page_answers(monkeypatch, remote, capsys):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/fake/tailscale")
    monkeypatch.setattr(phone, "tailscale_status", lambda cli=None: {
        "found": True, "running": True, "host": HOST, "login": LOGIN})
    monkeypatch.setattr(phone, "serving", lambda cli: {443: "http://127.0.0.1:5103"})
    served = []
    monkeypatch.setattr(phone, "serve", lambda cli, port=phone.PORT, https_port=phone.HTTPS_PORT:
                        served.append((port, https_port)) or True)
    assert phone.enable() == 0
    assert served == [(8765, 8443)]
    assert core.remote_access()["host"] == HOST and core.remote_access()["https_port"] == 8443
    out = capsys.readouterr().out
    assert f"https://{HOST}:8443/" in out and "Add to Home Screen" in out
    assert "Website Data" not in out and "still forwards" not in out   # nothing to move from

    monkeypatch.setattr(phone, "remove_agent", lambda: None)
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "serving", lambda cli: {443: "http://127.0.0.1:5103",
                                                       8443: "http://127.0.0.1:8765"})
    monkeypatch.setattr(phone, "unserve", lambda cli: True)
    assert phone.disable() == 0
    assert core.remote_access() is None


SERVING = {   # `tailscale serve status --json`, with another app at the root
    "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
    "Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5103"}}},
            f"{HOST}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}}}


def test_tailscale_serve_status_says_what_each_port_forwards_to():
    assert phone.parse_serve(SERVING) == {443: "http://127.0.0.1:5103", 8443: "http://127.0.0.1:8765"}
    assert phone.parse_serve({}) == {}
    # A port that serves files, or forwards raw TCP, is taken all the same.
    assert phone.parse_serve({"TCP": {"8443": {"TCPForward": "127.0.0.1:22"}}}) == {8443: "tcp 127.0.0.1:22"}
    assert phone.parse_serve({"Web": {f"{HOST}:8443": {"Handlers": {"/": {"Path": "/srv"}}}}}) == {8443: "/srv"}
    assert phone.ours("http://127.0.0.1:8765") and phone.ours("http://127.0.0.1:8765/")
    assert not phone.ours("http://127.0.0.1:5103") and not phone.ours(None)


def test_the_page_has_a_port_of_its_own_on_the_tailnet_alone():
    """The root of this Mac's address is the one every app set up this way
    takes, and a phone keeps icons and storage by address."""
    argv = phone.serve_argv()
    assert argv == ["serve", "--bg", "--https=8443", "http://127.0.0.1:8765"]
    assert phone.HTTPS_PORT == core.PHONE_HTTPS_PORT == 8443
    with open(phone.__file__, encoding="utf-8") as fh:
        code = fh.read()
    assert '"funnel"' not in code and "--https=443\"" not in code     # never Funnel, never the root


def _enable_ready(monkeypatch):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/fake/tailscale")
    monkeypatch.setattr(phone, "tailscale_status", lambda cli=None: {
        "found": True, "running": True, "host": HOST, "login": LOGIN})


def test_enable_never_takes_over_a_port_another_app_serves(monkeypatch, remote, capsys):
    _enable_ready(monkeypatch)
    monkeypatch.setattr(phone, "serving", lambda cli: {8443: "http://127.0.0.1:5103"})
    monkeypatch.setattr(phone, "serve", lambda *a, **k: pytest.fail("serve ran"))
    assert phone.enable() == 2
    out = capsys.readouterr().out
    assert f"https://{HOST}:8443/" in out and "http://127.0.0.1:5103" in out
    assert core.remote_access() is None


def test_moving_from_the_root_says_what_to_do_on_the_phone_and_leaves_the_root(monkeypatch, remote, capsys):
    """Set up before at the root: the record moves to the port, the phone is
    told to drop what it saved at the old address, and the root is only
    named, never turned off, since another app may have it by now."""
    import json
    with open(core.REMOTE, "w", encoding="utf-8") as fh:
        json.dump({"host": HOST, "login": LOGIN, "port": 8765}, fh)
    core._remote.update(mtime=None, value=None)
    _enable_ready(monkeypatch)
    monkeypatch.setattr(phone, "serving", lambda cli: {443: "http://127.0.0.1:8765"})
    monkeypatch.setattr(phone, "serve", lambda *a, **k: True)
    assert phone.enable() == 0
    assert core.remote_access()["https_port"] == 8443
    out = capsys.readouterr().out
    assert f"the old icon opened https://{HOST}/" in out and "Website Data" in out
    assert out.index("Website Data") < out.index(f"Open https://{HOST}:8443/")
    assert f"still forwards https://{HOST}/" in out and "'/fake/tailscale' serve --https=443 off" in out


def test_turning_phone_access_off_turns_off_its_own_port_and_never_the_root(monkeypatch, remote, capsys):
    import json
    import subprocess
    core.save_remote_access(HOST, LOGIN)
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "remove_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/fake/tailscale")
    ran = []

    def run(argv, **kw):
        ran.append(argv[1:])
        out = json.dumps(SERVING) if argv[1:3] == ["serve", "status"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out)
    monkeypatch.setattr(phone.subprocess, "run", run)
    assert phone.disable() == 0
    assert ran == [["serve", "status", "--json"], ["serve", "--https=8443", "off"]]
    assert "still forwards" not in capsys.readouterr().out      # the root is another app's


def test_without_tailscale_the_mac_still_starts_the_page_on_demand(monkeypatch, remote, capsys):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: None)
    assert phone.enable() == 2
    assert "tailscale.com/download" in capsys.readouterr().out
    assert core.remote_access() is None


def test_why_names_the_first_thing_that_stops_phone_access(remote):
    ok = {"running": True, "host": HOST, "login": LOGIN}
    on = {"installed": True, "loaded": True}
    rec = {"host": HOST, "login": LOGIN, "port": 8765, "https_port": 8443}
    assert phone.diagnose(ok, rec, on) is None
    assert phone.diagnose(ok, None, on) is None                      # never set up
    assert phone.diagnose({**ok, "host": "new-name.tail1234.ts.net"}, rec, on)["code"] == "address"
    off = phone.diagnose({**ok, "running": False}, rec, on)
    assert off["code"] == "tailscale" and LOGIN in off["text"] and "Applications" in off["text"]
    assert phone.diagnose({"running": False, "host": None}, rec, on)["code"] == "tailscale"
    assert phone.diagnose(ok, rec, {"installed": False, "loaded": False})["code"] == "unfinished"
    switched = phone.diagnose(ok, rec, {"installed": True, "loaded": False})
    assert switched["code"] == "switched-off" and "Login Items" in switched["text"]


def test_a_setup_at_the_root_is_asked_to_move_to_its_own_port(remote):
    ok = {"running": True, "host": HOST, "login": LOGIN}
    on = {"installed": True, "loaded": True}
    rec = {"host": HOST, "login": LOGIN, "port": 8765, "https_port": 8443}
    assert phone.diagnose(ok, rec, on) is None
    moved = phone.diagnose(ok, {**rec, "https_port": 443}, on)
    assert moved["code"] == "moved" and f"https://{HOST}:8443/" in moved["text"]
    assert f"https://{HOST}/," in moved["text"] and "Website Data" in moved["text"]


def test_status_gives_each_command_with_its_cd(remote, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert phone.cd(str(tmp_path / "job-search")) == "cd ~/job-search"
    assert phone.cd(str(tmp_path / "my search")) == f"cd '{tmp_path}/my search'"
    assert phone.cd("/opt/js") == "cd '/opt/js'"

    monkeypatch.setattr(core, "ROOT", str(tmp_path / "job-search"))
    monkeypatch.setattr(phone, "tailscale_status", lambda cli=None: {
        "found": True, "running": True, "host": HOST, "login": LOGIN})
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "plist_path", lambda label=phone.LABEL: str(tmp_path / "agent.plist"))
    core.save_remote_access(HOST, LOGIN)
    (tmp_path / "agent.plist").write_bytes(b"")
    s = phone.status()
    assert s["setup"] == "cd ~/job-search && sh install.sh --phone"
    assert s["disable"] == "cd ~/job-search && uv run python ui/phone.py disable"
    assert not s["ready"] and s["why"]["code"] == "switched-off"
    assert "Prevent automatic sleeping" in s["awake"] and "app switcher" in s["recover"]


def test_check_says_why_and_what_to_do(remote, monkeypatch, capsys):
    monkeypatch.setattr(phone, "status", lambda: {
        "ready": False, "protected": None, "url": f"https://{HOST}:8443/",
        "why": {"code": "switched-off", "label": "switched off", "text": "Turn it on."},
        "setup": "cd ~/job-search && sh install.sh --phone"})
    assert phone.check() == 1
    out = capsys.readouterr().out
    assert "switched off. Turn it on." in out and "cd ~/job-search && sh install.sh --phone" in out
    monkeypatch.setattr(phone, "status", lambda: {"ready": True, "url": f"https://{HOST}:8443/"})
    assert phone.check() == 0
    assert f"set up: https://{HOST}:8443/" in capsys.readouterr().out


def test_disable_never_cuts_off_a_working_run(remote, monkeypatch, capsys):
    core.save_remote_access(HOST, LOGIN)
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: True)
    monkeypatch.setattr(phone, "_health", lambda port, timeout: {"working": True})
    monkeypatch.setattr(phone, "remove_agent", lambda: pytest.fail("the agent was taken out"))
    monkeypatch.setattr(phone, "unserve", lambda cli: pytest.fail("Tailscale was changed"))
    assert phone.disable() == 1
    assert "working" in capsys.readouterr().out
    assert core.remote_access() is not None                       # nothing changed


def test_disable_says_when_tailscale_may_still_forward(remote, monkeypatch, capsys):
    core.save_remote_access(HOST, LOGIN)
    removed = []
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "remove_agent", lambda: removed.append(True))
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    monkeypatch.setattr(phone, "serving", lambda cli: None)      # not running: cannot say
    monkeypatch.setattr(phone, "unserve", lambda cli: False)
    assert phone.disable() == 1
    out = capsys.readouterr().out
    assert "serve --https=8443 off" in out and "'/Applications/Tailscale.app/Contents/MacOS/Tailscale'" in out
    assert "--https=443" not in out
    assert removed and core.remote_access() is None               # the rest is still undone

    # Nothing served on its port: nothing to turn off, which Tailscale would
    # call an error, and another app's root is left as it is.
    core.save_remote_access(HOST, LOGIN)
    monkeypatch.setattr(phone, "serving", lambda cli: {443: "http://127.0.0.1:5103"})
    monkeypatch.setattr(phone, "unserve", lambda cli: pytest.fail("unserve ran"))
    assert phone.disable() == 0
    assert "--https=443" not in capsys.readouterr().out


def test_enable_says_how_to_keep_the_mac_reachable(monkeypatch, remote, capsys):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/fake/tailscale")
    monkeypatch.setattr(phone, "tailscale_status", lambda cli=None: {
        "found": True, "running": True, "host": HOST, "login": LOGIN})
    import subprocess
    ran = []
    monkeypatch.setattr(phone.subprocess, "run",
                        lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0))
    assert phone.enable() == 0
    assert ["/fake/tailscale", "serve", "--bg", "--https=8443", "http://127.0.0.1:8765"] in ran
    out = capsys.readouterr().out
    assert "$ tailscale serve --bg --https=8443 http://127.0.0.1:8765" in out
    assert "login.tailscale.com" in out and "Enable" in out           # before serve waits on it
    assert "Prevent automatic sleeping on power adapter" in out
    assert "app switcher" in out and "127.0.0.1:8765" in out and "phone.py disable" in out


def test_without_tailscale_the_app_store_comes_first(monkeypatch, remote, capsys):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: None)
    assert phone.enable() == 2
    out = capsys.readouterr().out
    assert out.index("Mac App Store") < out.index("tailscale.com/download") and "administrator" in out


# --------------------------------------------------------------------- icon

def _pixels(data: bytes) -> tuple[int, int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
    return width, height, zlib.decompress(idat)


@pytest.mark.parametrize("size", [16, 180, 192])
def test_the_icon_is_a_square_png_of_the_size_asked(size):
    width, height, raw = _pixels(icon.png(size))
    assert (width, height) == (size, size)
    assert len(raw) == size * (1 + 3 * size)        # a filter byte, then RGB, per row


def test_the_icon_is_a_gold_briefcase_on_espresso_filled_to_the_edge():
    size = 192
    _, _, raw = _pixels(icon.png(size))

    def px(x, y):
        i = y * (1 + 3 * size) + 1 + 3 * x
        return tuple(raw[i:i + 3])
    corner = px(0, 0)
    assert max(corner) < 0x30                      # dark, to the corner: iOS rounds it
    assert px(size // 2, int(size * 0.66)) == icon.GOLD           # the case
    assert icon.png(size) == icon.png(size)         # drawn the same every time


def test_the_mac_icon_is_a_rounded_tile_on_a_clear_canvas():
    data = icon.png(64, tile=True)
    assert data[25] == 6                            # RGBA
    width, _, raw = _pixels(data)
    row = 1 + 4 * width

    def alpha(x, y):
        return raw[y * row + 1 + 4 * x + 3]
    assert alpha(0, 0) == 0 and alpha(2, 32) == 0  # the margin is clear
    assert alpha(32, 32) == 255                     # the tile is solid
    assert alpha(9, 9) < 255                        # its corner is rounded


def test_the_manifest_makes_the_page_an_app():
    m = core.manifest()
    assert m["display"] == "standalone" and m["start_url"] == "./"
    v = icon.fingerprint()
    assert {i["src"] for i in m["icons"]} == {f"icon-192.png?v={v}", f"icon-512.png?v={v}"}
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_on_a_phone_the_mark_tells_the_sites_launch_button_where_this_page_is():
    """seanbattey.com's Launch opens an app's phone address once the phone has it, and the
    site never names anyone's address. So the SB mark, on a page reached over Tailscale,
    carries this page's address after "#phone=job-search@", which a browser never sends to a
    server, and the link has no referrer, so the site's server never learns it either."""
    with open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert ('<a class="brand-mark-link" href="https://seanbattey.com" rel="noreferrer" '
            'aria-label="seanbattey.com">') in page
    with open(os.path.join(ROOT, "ui", "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    block = app[app.index('if (location.protocol === "https:" && location.hostname.endsWith(".ts.net")) {'):]
    block = block[:block.index("\n}\n")]
    assert ('mark.href = "https://seanbattey.com/#phone=job-search@" + '
            'encodeURIComponent(location.origin + "/");') in block
