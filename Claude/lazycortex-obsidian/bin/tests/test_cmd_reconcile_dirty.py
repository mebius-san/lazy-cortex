import pathlib, sys, json, shutil, subprocess
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _prep(tmp_path, init_git=True):
    """Copy the fixture vault, install the icon-map, and (optionally) initialise a
    clean git repo so `git status` reports a clean tree until tests dirty it."""
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "obsidian-iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "icon-map.json", mapdir / "icon-map.json")
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    if init_git:
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
        for cmd in (["git", "init", "-q"],
                    ["git", "add", "-A"],
                    ["git", "commit", "-q", "-m", "init"]):
            r = subprocess.run(cmd, cwd=str(vault), env=env, capture_output=True, text=True)
            assert r.returncode == 0, f"{cmd}: {r.stderr}"
    return vault

def _run(vault, *args):
    return subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), *args],
                          capture_output=True, text=True, cwd=str(vault))

def _data(vault):
    return json.loads((vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text())


def test_reconcile_dirty_modified_file_emits_entry(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert _data(vault).get("app/design.md") == {"iconName": "LiDraftingCompass", "iconColor": "#fde68a"}

def test_reconcile_dirty_untracked_file_emits_entry(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app" / "new.md").write_text("---\nrole: design\nstage: draft\n---\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    d = _data(vault)
    # "new.md" doesn't match 'role == design' + 'basename == design' rule; but the file's
    # prefix "app" triggers a rewalk, which will pick up the pre-existing design.md.
    assert d.get("app/design.md") == {"iconName": "LiDraftingCompass", "iconColor": "#fde68a"}

def test_reconcile_dirty_deletion_cleans_stale_key(tmp_path):
    vault = _prep(tmp_path)
    dp = vault / ".obsidian/plugins/obsidian-icon-folder/data.json"
    d = json.loads(dp.read_text())
    d["app/design.md"] = {"iconName": "LiDraftingCompass", "iconColor": "#fde68a"}
    d["app/OBSOLETE.md"] = {"iconName": "LiGhost"}
    dp.write_text(json.dumps(d, indent=2) + "\n")
    # Delete design.md — git status now reports a deletion under app/.
    (vault / "app" / "design.md").unlink()
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    data = _data(vault)
    # design.md is gone; OBSOLETE.md sat in the same prefix and isn't regenerated, so
    # the reconcile prunes it too.
    assert "app/design.md" not in data
    assert "app/OBSOLETE.md" not in data

def test_reconcile_dirty_clean_tree_is_noop(tmp_path):
    vault = _prep(tmp_path)
    before = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # no output on the early-return path
    assert (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text() == before

def test_reconcile_dirty_non_git_vault_is_noop(tmp_path):
    vault = _prep(tmp_path, init_git=False)
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    # No write, nothing to verify in data.json; just confirm exit 0 + no crash.

def test_reconcile_dirty_ignores_non_markdown_changes(tmp_path):
    vault = _prep(tmp_path)
    (vault / "script.py").write_text("print('hello')\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # no .md dirty → early return

def test_reconcile_dirty_ignores_changes_under_obsidian(tmp_path):
    vault = _prep(tmp_path)
    # Commit the .md first so only the .obsidian change is dirty.
    (vault / ".obsidian" / "rogue.md").write_text("---\nrole: design\n---\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""

def test_reconcile_dirty_dry_run_emits_plan(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    dp = vault / ".obsidian/plugins/obsidian-icon-folder/data.json"
    before = dp.read_text()
    r = _run(vault, "--dry-run", "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert dp.read_text() == before  # untouched
    plan = json.loads(r.stdout)
    assert plan["op"] == "reconcile-dirty"
    assert plan["dry_run"] is True
    assert plan["prefixes"] == ["app"]
    assert "app/design.md" in plan["add_or_update"]
