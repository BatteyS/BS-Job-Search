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
    assert core.remote_access() == {"host": HOST, "login": LOGIN, "port": 8765}
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
    assert core.refusal(HOST, f"https://{HOST}", LOGIN, True) is None
    assert core.refusal(HOST, "https://evil.example", LOGIN, True) == (
        "A page on another site cannot use this one.")
    # A site open on this Mac cannot borrow the tailnet origin without serve.
    assert core.refusal("127.0.0.1:8765", f"https://{HOST}") is not None


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
    served = []
    monkeypatch.setattr(phone, "serve", lambda cli, port=phone.PORT: served.append(port) or True)
    assert phone.enable() == 0
    assert served == [8765]
    assert core.remote_access()["host"] == HOST
    out = capsys.readouterr().out
    assert f"https://{HOST}/" in out and "Add to Home Screen" in out

    monkeypatch.setattr(phone, "remove_agent", lambda: None)
    monkeypatch.setattr(phone, "agent_loaded", lambda label=phone.LABEL: False)
    monkeypatch.setattr(phone, "served", lambda cli, port=phone.PORT: True)
    monkeypatch.setattr(phone, "unserve", lambda cli: True)
    assert phone.disable() == 0
    assert core.remote_access() is None


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
    rec = {"host": HOST, "login": LOGIN, "port": 8765}
    assert phone.diagnose(ok, rec, on) is None
    assert phone.diagnose(ok, None, on) is None                      # never set up
    assert phone.diagnose({**ok, "host": "new-name.tail1234.ts.net"}, rec, on)["code"] == "address"
    off = phone.diagnose({**ok, "running": False}, rec, on)
    assert off["code"] == "tailscale" and LOGIN in off["text"] and "Applications" in off["text"]
    assert phone.diagnose({"running": False, "host": None}, rec, on)["code"] == "tailscale"
    assert phone.diagnose(ok, rec, {"installed": False, "loaded": False})["code"] == "unfinished"
    switched = phone.diagnose(ok, rec, {"installed": True, "loaded": False})
    assert switched["code"] == "switched-off" and "Login Items" in switched["text"]


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
        "ready": False, "protected": None, "url": f"https://{HOST}/",
        "why": {"code": "switched-off", "label": "switched off", "text": "Turn it on."},
        "setup": "cd ~/job-search && sh install.sh --phone"})
    assert phone.check() == 1
    out = capsys.readouterr().out
    assert "switched off. Turn it on." in out and "cd ~/job-search && sh install.sh --phone" in out
    monkeypatch.setattr(phone, "status", lambda: {"ready": True, "url": f"https://{HOST}/"})
    assert phone.check() == 0
    assert f"set up: https://{HOST}/" in capsys.readouterr().out


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
    monkeypatch.setattr(phone, "served", lambda cli, port=phone.PORT: None)     # not running: cannot say
    monkeypatch.setattr(phone, "unserve", lambda cli: False)
    assert phone.disable() == 1
    out = capsys.readouterr().out
    assert "serve --https=443 off" in out and "'/Applications/Tailscale.app/Contents/MacOS/Tailscale'" in out
    assert removed and core.remote_access() is None               # the rest is still undone

    # Nothing served: nothing to turn off, which Tailscale would call an error.
    core.save_remote_access(HOST, LOGIN)
    monkeypatch.setattr(phone, "served", lambda cli, port=phone.PORT: False)
    monkeypatch.setattr(phone, "unserve", lambda cli: pytest.fail("unserve ran"))
    assert phone.disable() == 0


def test_enable_says_how_to_keep_the_mac_reachable(monkeypatch, remote, capsys):
    monkeypatch.setattr(phone.sys, "platform", "darwin")
    monkeypatch.setattr(phone, "protected_folder", lambda root, home=None: None)
    monkeypatch.setattr(phone, "install_agent", lambda: None)
    monkeypatch.setattr(phone, "find_tailscale", lambda: "/fake/tailscale")
    monkeypatch.setattr(phone, "tailscale_status", lambda cli=None: {
        "found": True, "running": True, "host": HOST, "login": LOGIN})
    import subprocess
    monkeypatch.setattr(phone.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0))
    assert phone.enable() == 0
    out = capsys.readouterr().out
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
    assert {i["src"] for i in m["icons"]} == {"icon-192.png", "icon-512.png"}
    assert any(i.get("purpose") == "maskable" for i in m["icons"])
