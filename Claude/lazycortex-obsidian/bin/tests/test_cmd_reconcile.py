import pathlib, sys, json, shutil, subprocess
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _prep(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "obsidian-icon-map.json", mapdir / "obsidian-icon-map.json")
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    return vault

def _run(vault, *args):
    return subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), *args],
                          capture_output=True, text=True, cwd=str(vault))


def test_reconcile_writes_frontmatter_for_matched_files(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "reconcile")
    assert r.returncode == 0, r.stderr
    body = (vault / "app" / "design.md").read_text()
    assert "iconize_icon: LiDraftingCompass" in body
    assert 'iconize_color: "#fde68a"' in body


def test_reconcile_clears_stale_frontmatter_keys_in_prefix(tmp_path):
    """A note that previously matched and now doesn't (e.g. role removed) should
    have its `iconize_*` keys cleared by a fresh reconcile."""
    vault = _prep(tmp_path)
    # Plant a stale icon line on a file that won't match the icon-map (no role).
    stale = vault / "app" / "stale.md"
    stale.write_text("---\niconize_icon: LiGhost\niconize_color: \"#ff00ff\"\n---\nbody\n")
    r = _run(vault, "reconcile", "--prefix", "app")
    assert r.returncode == 0, r.stderr
    txt = stale.read_text()
    assert "iconize_icon" not in txt
    assert "iconize_color" not in txt


def test_reconcile_dry_run_writes_nothing_and_emits_plan(tmp_path):
    vault = _prep(tmp_path)
    before = (vault / "app" / "design.md").read_text()
    r = _run(vault, "--dry-run", "reconcile", "--prefix", "app")
    assert r.returncode == 0, r.stderr
    assert (vault / "app" / "design.md").read_text() == before
    plan = json.loads(r.stdout)
    assert plan["op"] == "reconcile"
    assert plan["dry_run"] is True
    assert plan["prefix"] == "app"
    assert {"path": "app/design.md", "icon": "LiDraftingCompass", "color": "#fde68a"} in plan["planned"]


def test_reconcile_leaves_files_outside_prefix_untouched(tmp_path):
    vault = _prep(tmp_path)
    (vault / "other").mkdir()
    other = vault / "other" / "design.md"
    src = "---\nrole: design\nstage: draft\n---\n"  # would match if it were in scope
    other.write_text(src)
    r = _run(vault, "reconcile", "--prefix", "app")
    assert r.returncode == 0, r.stderr
    assert other.read_text() == src  # outside prefix → not walked, no rewrite


def test_reconcile_skips_hidden_dirs(tmp_path):
    vault = _prep(tmp_path)
    # Put a .md file inside each skip-dir. Reconcile shouldn't emit paths for them.
    for hidden in (".obsidian", ".git", ".claude", ".githooks"):
        d = vault / hidden / "sub"
        d.mkdir(parents=True, exist_ok=True)
        (d / "note.md").write_text("---\nrole: design\nstage: draft\n---\n")
    r = _run(vault, "--dry-run", "reconcile")
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    for hidden in (".obsidian", ".git", ".claude", ".githooks"):
        assert not any(p["path"].startswith(f"{hidden}/") for p in plan["planned"])
