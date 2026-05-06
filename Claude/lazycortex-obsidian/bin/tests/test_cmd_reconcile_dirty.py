import pathlib, sys, json, shutil, subprocess
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _prep(tmp_path, init_git=True):
    """Copy the fixture vault, install the icon-map, and (optionally) initialise a
    clean git repo so `git status` reports a clean tree until tests dirty it."""
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "obsidian-icon-map.json", mapdir / "obsidian-icon-map.json")
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


def test_reconcile_dirty_modified_file_rewrites_frontmatter(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    body = (vault / "app" / "design.md").read_text()
    assert "iconize_icon: LiDraftingCompass" in body
    assert 'iconize_color: "#fde68a"' in body


def test_reconcile_dirty_untracked_file_walks_prefix(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app" / "new.md").write_text("---\nrole: design\nstage: draft\n---\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    # The prefix re-walk picks up the matching design.md sibling.
    body = (vault / "app" / "design.md").read_text()
    assert "iconize_icon: LiDraftingCompass" in body


def test_reconcile_dirty_clears_stale_frontmatter_in_dirty_prefix(tmp_path):
    vault = _prep(tmp_path)
    # A non-matching file with stale icon keys; sits in same prefix as a dirty .md.
    stale = vault / "app" / "stale.md"
    stale.write_text("---\niconize_icon: LiGhost\n---\nbody\n")
    # Dirty the prefix so reconcile-dirty walks it.
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert "iconize_icon" not in stale.read_text()


def test_reconcile_dirty_clean_tree_is_noop(tmp_path):
    vault = _prep(tmp_path)
    before = (vault / "app" / "design.md").read_text()
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # no output on the early-return path
    assert (vault / "app" / "design.md").read_text() == before


def test_reconcile_dirty_non_git_vault_is_noop(tmp_path):
    vault = _prep(tmp_path, init_git=False)
    before = (vault / "app" / "design.md").read_text()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nedited\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_reconcile_dirty_ignores_non_markdown_changes(tmp_path):
    vault = _prep(tmp_path)
    (vault / "script.py").write_text("print('hello')\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # no .md dirty → early return


def test_reconcile_dirty_ignores_changes_under_obsidian(tmp_path):
    vault = _prep(tmp_path)
    (vault / ".obsidian" / "rogue.md").write_text("---\nrole: design\n---\n")
    r = _run(vault, "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_reconcile_dirty_dry_run_emits_plan(tmp_path):
    vault = _prep(tmp_path)
    src = "---\nrole: design\nstage: draft\n---\nedited\n"
    (vault / "app" / "design.md").write_text(src)
    r = _run(vault, "--dry-run", "reconcile-dirty")
    assert r.returncode == 0, r.stderr
    assert (vault / "app" / "design.md").read_text() == src
    plan = json.loads(r.stdout)
    assert plan["op"] == "reconcile-dirty"
    assert plan["dry_run"] is True
    assert plan["prefixes"] == ["app"]
    assert {"path": "app/design.md", "icon": "LiDraftingCompass", "color": "#fde68a"} in plan["planned"]
