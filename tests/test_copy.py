"""Keeping a copy current and backed up, through ui/core.py: telling the copy's
layout, how far behind the template it is, the update for each layout, and Back
up. Every repository is a temporary one: the template and each backup are bare
repositories on disk, so nothing touches the network, and git reads a config of
the test's own, with no one's name, signing, or credential helpers in it."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import types

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402

THE_TEMPLATE = "https://github.com/BatteyS/BS-Job-Search.git"
# Addresses with a user in them are assembled, so the export's personal-data
# check does not read them as email addresses.
AT = "@"

# The template at v1.0: a few files of each kind the page treats differently.
TEMPLATE_FILES = {
    "README.md": "# BS Job Search\n",
    ".gitignore": "content/contact.local.md\n/Applications/\n",
    "pyproject.toml": "[project]\nname = 'bs-job-search'\n",
    "ui/core.py": "# the page\n",
    "ui/app.js": "// the page\n",
    "scripts/fetch_jobs.py": "# a script\n",
    "scan.ps1": "# a launcher from before the page\n",
    "content/story.example.md": "# Your story\n",
    "examples/nurse/master.md": "# An example\n",
}


@pytest.fixture(autouse=True)
def own_git(tmp_path, monkeypatch):
    """git with a config of the test's own: main as the first branch, and no
    name to commit under unless a test gives one. The page's memory of checks
    and starts is cleared too."""
    config = tmp_path / "gitconfig"
    config.write_text("[init]\n\tdefaultBranch = main\n[user]\n\tuseConfigOnly = true\n"
                      "[commit]\n\tgpgSign = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(core, "_checked", {"at": None, "error": None})
    monkeypatch.setattr(core, "_started", {"head": None})
    monkeypatch.setattr(core, "_private", set())


def git(cwd, *args: str, check: bool = True) -> str:
    """git as the tests run it, with a name of their own for the commits they
    make. The page's own commits get none from here."""
    r = subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stdout}{r.stderr}")
    return r.stdout.strip()


def write(folder, files: dict) -> None:
    for rel, text in files.items():
        path = folder / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def commit(folder, message: str, files: dict | None = None) -> str:
    write(folder, files or {})
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", message)
    return git(folder, "rev-parse", "HEAD")


def head(folder) -> str:
    return git(folder, "rev-parse", "HEAD")


def give_a_name(folder) -> None:
    git(folder, "config", "user.name", "Pat Lee")
    git(folder, "config", "user.email", "pat@example.com")


class Template:
    """The template: a folder where each release is made, and the bare
    repository the copies clone and fetch from, as they would from GitHub."""

    def __init__(self, tmp):
        self.work, self.bare = tmp / "template-work", tmp / "template.git"
        self.work.mkdir()
        git(self.work, "init", "-q")
        self.release("v1.0", TEMPLATE_FILES)
        git(tmp, "clone", "-q", "--bare", str(self.work), str(self.bare))

    def release(self, version: str, files: dict, notes: str = "") -> str:
        sha = commit(self.work, f"BS-Job-Search-{version}" + (f"\n\n{notes}" if notes else ""),
                     files)
        if self.bare.exists():
            git(self.work, "push", "-q", str(self.bare), "main")
        return sha


@pytest.fixture
def template(tmp_path, monkeypatch):
    t = Template(tmp_path)
    monkeypatch.setattr(core, "TEMPLATE_URL", str(t.bare))
    return t


def point_at(monkeypatch, folder):
    monkeypatch.setattr(core, "ROOT", str(folder))
    return folder


@pytest.fixture
def clone(template, tmp_path, monkeypatch):
    """A copy as Get started makes one: a clone of the template."""
    git(tmp_path, "clone", "-q", str(template.bare), str(tmp_path / "copy"))
    return point_at(monkeypatch, tmp_path / "copy")


@pytest.fixture
def backed_up(clone, tmp_path):
    """The clone, pushed to a private repository of its own as the README says:
    the template renamed to `template`, the backup added as `origin`."""
    git(tmp_path, "init", "-q", "--bare", str(tmp_path / "backup.git"))
    git(clone, "remote", "rename", "origin", "template")
    git(clone, "remote", "add", "origin", str(tmp_path / "backup.git"))
    git(clone, "push", "-q", "-u", "origin", "main")
    give_a_name(clone)
    return clone


def another_machine(tmp_path, name: str = "laptop"):
    """A second clone of the backup, where the user also works."""
    git(tmp_path, "clone", "-q", str(tmp_path / "backup.git"), str(tmp_path / name))
    return tmp_path / name


@pytest.fixture
def from_the_button(template, tmp_path, monkeypatch):
    """A copy made with GitHub's Use this template: the template's v1.0 files in
    a first commit of its own, the user's profile on top, and no remote for the
    template yet."""
    copy = tmp_path / "made"
    copy.mkdir()
    git(copy, "init", "-q")
    commit(copy, "Initial commit", TEMPLATE_FILES)
    commit(copy, "My profile", {"profile/profile.md": "mine\n"})
    give_a_name(copy)
    return point_at(monkeypatch, copy)


# ----------------------------------------------------------------- layouts

def test_a_folder_that_is_not_a_repository_is_told_so(tmp_path, monkeypatch):
    point_at(monkeypatch, tmp_path)
    s = core.copy_status()
    assert s["layout"] == "none" and "not a git repository" in s["about"]
    with pytest.raises(core.Stop):
        core.update_copy()
    assert core.check_copy()["layout"] == "none"


def test_a_clone_of_the_template(clone):
    s = core.copy_status()
    assert s["layout"] == "clone" and s["branch"] == "main"
    assert s["template"]["remote"] == "origin" and s["template"]["behind"] == 0
    assert s["template"]["version"] == "v1.0"
    assert s["backup"]["remote"] is None          # nowhere of its own to back up to


def test_a_copy_backed_up_to_a_repository_of_its_own(backed_up):
    s = core.copy_status()
    assert s["layout"] == "backup"
    assert s["template"]["remote"] == "template" and s["backup"]["remote"] == "origin"
    assert s["backup"]["unpushed"] == 0 and s["identity"]


def test_a_copy_made_with_use_this_template_shares_no_history(from_the_button, template):
    assert core.copy_status()["layout"] == "unlinked"
    s = core.link_template()
    assert s["layout"] == "unrelated"
    assert git(from_the_button, "remote", "get-url", "template") == str(template.bare)
    assert s["template"]["behind"] == 0 and s["template"]["unit"] == "files"


def test_linking_never_replaces_a_remote_of_the_same_name(from_the_button, tmp_path):
    git(from_the_button, "remote", "add", "template", str(tmp_path / "something-else.git"))
    with pytest.raises(core.Stop, match="already has a remote named template"):
        core.link_template()
    assert git(from_the_button, "remote", "get-url", "template").endswith("something-else.git")


@pytest.mark.parametrize("url", [
    "https://github.com/BatteyS/BS-Job-Search.git",
    "https://github.com/BatteyS/BS-Job-Search",
    "https://github.com/batteys/bs-job-search/",
    "git@github.com:BatteyS/BS-Job-Search.git",
    "ssh://git@github.com/BatteyS/BS-Job-Search.git",
    "ssh://git@github.com:22/BatteyS/BS-Job-Search",
    f"https://someone:ghp_s3cr3t{AT}github.com/BatteyS/BS-Job-Search.git",
])
def test_the_template_is_known_however_its_address_is_written(url):
    assert core._repo_key(url) == core._repo_key(THE_TEMPLATE)
    assert "s3cr3t" not in core._shown(url) and "someone" not in core._shown(url)


@pytest.mark.parametrize("url", [
    "https://github.com/BatteyS/BS-Job-Search-fork.git",
    "https://github.com/someone/BS-Job-Search.git",
    f"git{AT}gitlab.com:BatteyS/BS-Job-Search.git",
    "/Users/pat/BS-Job-Search",
])
def test_another_repository_is_not_the_template(url):
    assert core._repo_key(url) != core._repo_key(THE_TEMPLATE)


# ----------------------------------------------------------------- a check

def test_a_check_counts_the_updates_and_reads_their_notes(clone, template):
    before = head(clone)
    template.release("v1.1", {"README.md": "# BS Job Search\nNew.\n"},
                     notes="What changed, and why.")
    assert core.copy_status()["template"]["behind"] == 0     # nothing fetched yet
    s = core.check_copy()
    assert s["checked"] and s["error"] is None
    t = s["template"]
    assert t["behind"] == 1 and t["version"] == "v1.1"
    assert t["notes"] == [{"subject": "BS-Job-Search-v1.1", "body": "What changed, and why."}]
    assert head(clone) == before and git(clone, "status", "--porcelain") == ""


def test_a_check_that_cannot_reach_the_template_is_noted_not_raised(clone, tmp_path,
                                                                    monkeypatch):
    git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    monkeypatch.setattr(core, "TEMPLATE_URL", str(tmp_path / "gone.git"))
    s = core.check_copy()
    assert s["layout"] == "clone" and "could not reach the template" in s["error"]


# ------------------------------------------------------------ updating a clone

def test_an_update_brings_the_template_in_and_leaves_the_users_files(clone, template):
    write(clone, {"profile/profile.md": "mine\n"})
    template.release("v1.1", {"README.md": "new\n", "scan.ps1": None})
    r = core.update_copy()
    assert r["ok"] and r["message"] == "Brought in 1 update from the template."
    assert head(clone) == head(template.work)                # a fast-forward
    assert r["changed"] == ["README.md", "scan.ps1"]
    assert not (clone / "scan.ps1").exists()
    assert (clone / "profile/profile.md").read_text(encoding="utf-8") == "mine\n"
    assert r["status"]["template"]["behind"] == 0
    assert core.update_copy()["message"] == "Already up to date."


def test_an_update_stops_before_writing_over_uncommitted_changes(clone, template):
    write(clone, {"README.md": "my edit\n"})
    template.release("v1.1", {"README.md": "new\n"})
    assert core.check_copy()["template"]["blocked"] == ["README.md"]
    before = head(clone)
    with pytest.raises(core.Stop, match="write over README.md"):
        core.update_copy()
    assert head(clone) == before
    assert (clone / "README.md").read_text(encoding="utf-8") == "my edit\n"


def test_an_update_keeps_uncommitted_changes_it_does_not_touch(clone, template):
    write(clone, {"ui/app.js": "// mine\n"})
    template.release("v1.1", {"README.md": "new\n"})
    assert core.update_copy()["ok"]
    assert (clone / "ui/app.js").read_text(encoding="utf-8") == "// mine\n"


def test_an_update_stops_before_replacing_a_file_git_does_not_track(clone, template):
    write(clone, {"ui/router.py": "# mine, not committed\n"})
    template.release("v1.1", {"ui/router.py": "# the template's\n"})
    with pytest.raises(core.Stop, match="ui/router.py"):
        core.update_copy()
    assert (clone / "ui/router.py").read_text(encoding="utf-8") == "# mine, not committed\n"


def test_a_clone_with_commits_of_its_own_is_merged_never_rebased(clone, template):
    give_a_name(clone)
    mine = commit(clone, "My profile", {"profile/profile.md": "mine\n"})   # /setup offers this
    theirs = template.release("v1.1", {"README.md": "new\n"})
    r = core.update_copy()
    assert r["ok"]
    assert git(clone, "log", "-1", "--format=%P").split() == [mine, theirs]
    assert git(clone, "log", "-1", "--format=%s") == "Update from the template to v1.1"


def test_a_conflict_is_undone_and_named(clone, template):
    give_a_name(clone)
    mine = commit(clone, "My README", {"README.md": "mine\n"})
    template.release("v1.1", {"README.md": "theirs\n"})
    with pytest.raises(core.Stop, match="README.md changed both here and in the template"):
        core.update_copy()
    assert head(clone) == mine
    assert git(clone, "status", "--porcelain") == ""
    assert git(clone, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False) == ""


def test_a_merge_needs_a_name_to_label_it(clone, template):
    commit(clone, "My profile", {"profile/profile.md": "mine\n"})
    template.release("v1.1", {"README.md": "new\n"})
    assert not core.copy_status()["identity"]
    with pytest.raises(core.Stop, match="name and an email"):
        core.update_copy()
    core.save_identity("Pat Lee", "pat@example.com")
    assert git(clone, "config", "--local", "user.email") == "pat@example.com"
    assert core.update_copy()["ok"]
    assert git(clone, "log", "-1", "--format=%an <%ae>") == "Pat Lee <pat@example.com>"


@pytest.mark.parametrize("name,email", [
    ("", "pat@example.com"), ("Pat\nLee", "pat@example.com"), ("Pat <x>", "pat@example.com"),
    ("Pat", "not-an-email"), ("Pat", "pat lee@example.com"), ("Pat", ""),
])
def test_a_name_and_an_email_are_one_line_each(clone, name, email):
    with pytest.raises(ValueError):
        core.save_identity(name, email)
    assert git(clone, "config", "--local", "--get", "user.name", check=False) == ""


def test_the_page_says_when_an_update_needs_it_reloaded_or_restarted(clone, template,
                                                                     monkeypatch):
    core.remember_start()
    template.release("v1.1", {"ui/app.js": "// new\n", "scripts/fetch_jobs.py": "# new\n"})
    r = core.update_copy()
    assert r["reload"] and not r["status"]["restart"]       # the page's files, and a script it runs
    template.release("v1.2", {"pyproject.toml": "[project]\nname = 'new'\n"})
    assert core.update_copy()["status"]["restart"]           # a package the page needs

    core.remember_start()
    template.release("v1.3", {"scripts/fetch_jobs.py": "# newer\n"})
    assert not core.update_copy()["status"]["restart"]
    loaded = types.ModuleType("fetch_jobs")
    loaded.__file__ = str(clone / "scripts" / "fetch_jobs.py")
    monkeypatch.setitem(sys.modules, "copy_test_fetch_jobs", loaded)
    assert core.copy_status()["restart"]                     # once the page has imported it


def test_a_merge_left_partway_outside_the_page_is_not_touched(clone, template):
    give_a_name(clone)
    commit(clone, "My README", {"README.md": "mine\n"})
    template.release("v1.1", {"README.md": "theirs\n"})
    git(clone, "fetch", "-q")
    git(clone, "merge", "origin/main", check=False)          # a person's merge, conflicted
    with pytest.raises(core.Stop, match="partway through a merge"):
        core.update_copy()
    assert git(clone, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)


def test_a_copy_not_on_a_branch_is_left_alone(clone, template):
    git(clone, "checkout", "-q", "--detach")
    template.release("v1.1", {"README.md": "new\n"})
    assert "not on a branch" in core.copy_status()["about"]
    with pytest.raises(core.Stop, match="not on a branch"):
        core.update_copy()


def test_one_change_at_a_time_and_none_under_a_working_skill(clone, template):
    template.release("v1.1", {"README.md": "new\n"})
    run = types.SimpleNamespace(name="job-scan", status="running")
    runs = types.SimpleNamespace(active_claude=lambda: run)
    with pytest.raises(core.Stop, match="job-scan is running"):
        core.update_copy(runs)
    with core._git_lock:
        with pytest.raises(core.Stop, match="already running"):
            core.update_copy()
        assert core.check_copy()["busy"]                     # a check while busy just says so
    run.status = "idle"                                      # waiting for a reply, not working
    assert core.update_copy(runs)["ok"]


# ----------------------------------------------------- a copy with a backup

def test_back_up_commits_only_the_users_own_files_and_pushes_them(backed_up, tmp_path):
    write(backed_up, {
        "profile/profile.md": "how a role is judged\n",
        "digests/2026-11-02.md": "# Digest\n",
        "content/master.md": "every fact\n",
        "sources/companies.yaml": "acme: {}\n",
        "content/contact.local.md": "pat@example.com\n",       # gitignored
        "sources/adzuna.local.yaml": "app_key: x\n",           # a key, gitignored or not
        "content/story.example.md": "# Your story, edited\n",  # the template's
        "ui/app.js": "// a tweak\n",                            # the template's
        "notes.txt": "a stray file\n",
    })
    b = core.copy_status()["backup"]
    mine = ["content/master.md", "digests/2026-11-02.md", "profile/profile.md",
            "sources/companies.yaml"]
    assert b["changes"] == mine
    assert b["other"] == ["content/story.example.md", "ui/app.js"]

    r = core.back_up("Set up my profile")
    assert r["ok"] and r["message"] == f"Backed up 4 files to {tmp_path / 'backup.git'}."
    assert git(backed_up, "log", "-1", "--format=%B") == "Set up my profile"
    assert sorted(git(backed_up, "show", "--name-only", "--format=", "HEAD").split()) == mine
    assert git(tmp_path / "backup.git", "rev-parse", "main") == head(backed_up)
    assert "contact.local.md" not in git(backed_up, "log", "--all", "--name-only", "--format=")
    assert "adzuna.local.yaml" not in git(backed_up, "log", "--all", "--name-only", "--format=")
    left = git(backed_up, "status", "--porcelain", "--untracked-files=all")
    assert " M ui/app.js" in left and "?? notes.txt" in left
    after = r["status"]["backup"]
    assert after["changes"] == [] and after["unpushed"] == 0
    assert core.back_up("Again")["message"] == "Nothing new to back up."


def test_back_up_brings_in_another_machines_backup_first(backed_up, tmp_path):
    laptop = another_machine(tmp_path)
    commit(laptop, "Marked the digest on the laptop", {"digests/2026-11-02.md": "laptop\n"})
    git(laptop, "push", "-q")
    write(backed_up, {"profile/profile.md": "desktop\n"})
    assert core.check_copy()["backup"]["behind"] == 1

    r = core.back_up("Edited the profile on the desktop")
    assert r["ok"] and r["message"].startswith("Brought in 1 change from your backup.")
    mine = git(backed_up, "log", "-1", "--format=%H", "--", "profile/profile.md")
    assert git(backed_up, "log", "-1", "--format=%s", mine) == "Edited the profile on the desktop"
    assert git(backed_up, "log", "-1", "--format=%P").split()[0] == mine    # merged, not rebased
    assert (backed_up / "digests/2026-11-02.md").read_text(encoding="utf-8") == "laptop\n"
    assert git(tmp_path / "backup.git", "rev-parse", "main") == head(backed_up)


def test_two_machines_changing_the_same_lines_stops_with_both_kept(backed_up, tmp_path):
    commit(backed_up, "Profile", {"profile/profile.md": "one\n"})
    git(backed_up, "push", "-q")
    laptop = another_machine(tmp_path)
    commit(laptop, "Laptop", {"profile/profile.md": "laptop\n"})
    git(laptop, "push", "-q")
    write(backed_up, {"profile/profile.md": "desktop\n"})

    r = core.back_up("Desktop")
    assert not r["ok"]
    assert "Saved 1 file on this machine, but could not back them up" in r["message"]
    assert "profile/profile.md changed both on this machine and on another one" in r["message"]
    assert git(backed_up, "log", "-1", "--format=%s") == "Desktop"     # kept here
    assert git(backed_up, "status", "--porcelain") == ""
    assert git(tmp_path / "backup.git", "log", "-1", "--format=%s", "main") == "Laptop"


def test_an_update_brings_in_the_backup_then_the_template_then_pushes(backed_up, template,
                                                                      tmp_path):
    laptop = another_machine(tmp_path)
    commit(laptop, "Laptop digest", {"digests/2026-11-02.md": "laptop\n"})
    git(laptop, "push", "-q")
    theirs = template.release("v1.1", {"README.md": "new\n"})
    s = core.check_copy()
    assert s["backup"]["behind"] == 1 and s["template"]["behind"] == 1

    r = core.update_copy()
    assert r["ok"] and r["message"] == ("Brought in 1 change from your backup and 1 update "
                                        "from the template. Backed up.")
    assert theirs in git(backed_up, "log", "-1", "--format=%P").split()
    assert git(tmp_path / "backup.git", "rev-parse", "main") == head(backed_up)
    assert (laptop / "README.md").read_text(encoding="utf-8") == "# BS Job Search\n"
    git(laptop, "pull", "-q", "--no-rebase")
    assert (laptop / "README.md").read_text(encoding="utf-8") == "new\n"


def test_nothing_is_pushed_to_a_repository_anyone_can_read(backed_up, monkeypatch):
    monkeypatch.setattr(core, "_readable_by_anyone", lambda url: True)
    write(backed_up, {"profile/profile.md": "candid\n"})
    before = head(backed_up)
    with pytest.raises(core.Stop, match="Anyone can read"):
        core.back_up("My profile")
    assert head(backed_up) == before
    assert "profile/profile.md" in git(backed_up, "status", "--porcelain", "--untracked-files=all")


def test_a_clone_has_nowhere_to_back_up_to(clone):
    write(clone, {"profile/profile.md": "mine\n"})
    with pytest.raises(core.Stop, match="only on this machine"):
        core.back_up("My profile")
    b = core.copy_status()["backup"]
    assert b["remote"] is None and b["changes"] == ["profile/profile.md"]


@pytest.mark.parametrize("message", ["", "   ", None, "\x00\x01"])
def test_a_backup_of_changed_files_needs_a_message(backed_up, message):
    write(backed_up, {"profile/profile.md": "mine\n"})
    before = head(backed_up)
    with pytest.raises(ValueError):
        core.back_up(message)
    assert head(backed_up) == before


def test_pushing_what_is_already_committed_needs_no_message(backed_up, tmp_path):
    commit(backed_up, "Committed, but the push failed", {"profile/profile.md": "mine\n"})
    assert core.copy_status()["backup"]["unpushed"] == 1
    r = core.back_up(None)
    assert r["ok"] and git(tmp_path / "backup.git", "rev-parse", "main") == head(backed_up)


def test_only_an_address_on_a_network_is_asked_whether_it_is_public(monkeypatch, tmp_path):
    asked = []

    def fake(*args, **kw):
        asked.append(args)
        return subprocess.CompletedProcess(args, 128 if "private" in " ".join(args) else 0, "", "")

    monkeypatch.setattr(core, "_git", fake)
    assert not core._readable_by_anyone(str(tmp_path))                   # a folder on disk
    assert not core._readable_by_anyone(f"git{AT}git.example.org:pat/jobs.git")   # its own ssh host
    assert asked == []

    assert not core._readable_by_anyone("git@github.com:pat/private-jobs.git")
    assert "https://github.com/pat/private-jobs.git" in asked[-1]
    assert "credential.helper=" in asked[-1]                            # asked as a stranger
    assert not core._readable_by_anyone(f"https://pat:tok3n{AT}github.com/pat/private-jobs.git")
    assert len(asked) == 1                                               # private: not asked again

    assert core._readable_by_anyone(f"https://pat:tok3n{AT}github.com/pat/jobs.git")
    assert "tok3n" not in " ".join(asked[-1])


# ------------------------------------------- a copy with no shared history

def test_the_first_update_takes_the_templates_files_and_joins_its_history(from_the_button,
                                                                         template):
    commit(from_the_button, "My own script and app tweak", {
        "scripts/mine.py": "# mine\n", "ui/app.js": "// my tweak\n"})
    core.link_template()
    theirs = template.release("v1.1", {"README.md": "new\n", "scan.ps1": None,
                                        "ui/new.py": "# new\n"})
    s = core.check_copy()
    assert s["layout"] == "unrelated"
    assert s["template"]["behind"] == 3 and s["template"]["unit"] == "files"
    assert s["template"]["notes"][0]["subject"] == "BS-Job-Search-v1.1"

    r = core.update_copy()
    assert r["ok"] and r["message"] == "Brought in 3 files from the template."
    read = lambda rel: (from_the_button / rel).read_text(encoding="utf-8")  # noqa: E731
    assert read("README.md") == "new\n" and read("ui/new.py") == "# new\n"
    assert not (from_the_button / "scan.ps1").exists()                     # the template dropped it
    assert read("ui/app.js") == "// my tweak\n"                            # only changed here: kept
    assert read("scripts/mine.py") == "# mine\n" and read("profile/profile.md") == "mine\n"
    assert theirs in git(from_the_button, "log", "-1", "--format=%P").split()

    s = r["status"]
    assert s["layout"] == "clone" and s["template"]["behind"] == 0        # joined: no backup
    newer = template.release("v1.2", {"README.md": "newer\n"})
    r = core.update_copy()
    assert r["ok"] and git(from_the_button, "log", "-1", "--format=%P").split()[1] == newer


def test_a_file_both_changed_stops_the_first_update(from_the_button, template):
    commit(from_the_button, "My README", {"README.md": "mine\n"})
    core.link_template()
    template.release("v1.1", {"README.md": "theirs\n", "ui/app.js": "// new\n"})
    assert core.check_copy()["template"]["conflicts"] == ["README.md"]
    before = head(from_the_button)
    with pytest.raises(core.Stop, match="README.md was changed in this copy"):
        core.update_copy()
    assert head(from_the_button) == before
    assert (from_the_button / "ui/app.js").read_text(encoding="utf-8") == "// the page\n"


def test_the_first_update_stops_before_writing_over_uncommitted_changes(from_the_button,
                                                                       template):
    core.link_template()
    template.release("v1.1", {"README.md": "new\n"})
    write(from_the_button, {"README.md": "edited, not committed\n"})
    with pytest.raises(core.Stop, match="write over README.md"):
        core.update_copy()
    assert (from_the_button / "README.md").read_text(encoding="utf-8") == "edited, not committed\n"


# ---------------------------------------------------------------- version
# Which version the page shows in its header (core.version).

def test_a_clone_shows_the_export_it_is_at_and_commits_since(clone, monkeypatch):
    monkeypatch.setattr(core, "_version", {"head": "", "value": None})
    v = core.version()
    assert v["label"] == "v1.0" and v["commit"] == head(clone)[:7] and not v["changed"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["date"])
    assert core.version_text(v) == "v1.0"          # the export alone: no commit
    commit(clone, "My own change", {"profile/profile.md": "# mine\n"})
    commit(clone, "Another", {"profile/profile.md": "# mine, again\n"})
    assert core.version()["label"] == "v1.0+2" and core.version_text() == "v1.0+2"
    # Code edited and not committed says so; a profile file does not count.
    write(clone, {"profile/profile.md": "# edited\n"})
    assert not core.version()["changed"]
    write(clone, {"ui/app.js": "// edited here\n"})
    assert core.version()["changed"] and core.version_text() == "v1.0+2 · edited"


def test_a_copy_with_no_export_is_labeled_by_its_latest_merged_pr(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_version", {"head": "", "value": None})
    repo = tmp_path / "private"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, "Start", {"ui/app.js": "// a\n"})
    point_at(monkeypatch, repo)
    assert core.version()["label"] == "" and core.version_text() == head(repo)[:7]
    commit(repo, "Merge pull request #12 from someone/branch", {"ui/app.js": "// b\n"})
    commit(repo, "Merge pull request #59 from someone/later", {"ui/app.js": "// c\n"})
    commit(repo, "Fix a typo", {"README.md": "x\n"})
    assert core.version()["label"] == "#59"
    assert core.version_text() == f"#59 · {head(repo)[:7]}"   # the private repo keeps its commit


def test_outside_git_there_is_no_version(tmp_path, monkeypatch):
    point_at(monkeypatch, tmp_path)
    assert core.version() == {"label": "", "commit": "", "date": "", "changed": False}
    assert core.version_text() == ""


def test_the_page_carries_its_version_and_a_tag_for_the_phones_copy(clone, monkeypatch):
    pytest.importorskip("fastapi")
    import asyncio
    import server
    monkeypatch.setattr(core, "_version", {"head": "", "value": None})
    page = server.page_html()
    sha = head(clone)[:7]
    assert "<title>BS Job Search</title>" in page        # no version in the tab
    assert f'class="version" title="Commit {sha} of ' in page and ">v1.0</span>" in page

    def get(headers):
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": "/", "raw_path": b"/", "query_string": b"", "root_path": "",
                 "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
                 "headers": [(b"host", b"127.0.0.1:8765")] + [(k.encode(), v.encode()) for k, v in headers.items()]}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            sent.append(m)

        asyncio.run(server.app(scope, receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        return start["status"], {k.decode().lower(): v.decode() for k, v in start["headers"]}

    status, h = get({})
    assert status == 200 and h["etag"].startswith('"') and "default-src 'self'" in h["content-security-policy"]
    assert get({"if-none-match": h["etag"]})[0] == 304
    assert get({})[1]["etag"] == h["etag"]                 # the same page, the same tag: no reload on a phone
    commit(clone, "Mine", {"profile/profile.md": "# mine\n"})
    assert get({})[1]["etag"] != h["etag"]                 # a new version: the phone's copy reloads once
