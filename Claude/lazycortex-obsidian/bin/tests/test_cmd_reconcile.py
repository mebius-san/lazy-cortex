import pathlib, sys, json, shutil, subprocess
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _prep(tmp_path, with_stale=True):
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "obsidian-iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "icon-map.json", mapdir / "icon-map.json")
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    if with_stale:
        dp = vault / ".obsidian/plugins/obsidian-icon-folder/data.json"
        d = json.loads(dp.read_text())
        d["app/OBSOLETE.md"] = {"iconName": "LiGhost"}
        dp.write_text(json.dumps(d, indent=2) + "\n")
    return vault

def _run(vault, *args):
    return subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), *args],
                          capture_output=True, text=True, cwd=str(vault))

def test_reconcile_adds_derived_entries(tmp_path):
    vault = _prep(tmp_path, with_stale=False)
    r = _run(vault, "reconcile")
    assert r.returncode == 0, r.stderr
    data = json.loads((vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text())
    assert "app/design.md" in data

def test_reconcile_drops_stale_entries_in_prefix(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "reconcile", "--prefix", "app")
    assert r.returncode == 0
    data = json.loads((vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text())
    assert "app/OBSOLETE.md" not in data
    assert "app/design.md" in data

def test_reconcile_preserves_reserved_keys(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "reconcile")
    assert r.returncode == 0
    data = json.loads((vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text())
    assert "settings" in data and "rules" in data

def test_reconcile_dry_run_writes_nothing_and_emits_plan(tmp_path):
    vault = _prep(tmp_path)
    dp = vault / ".obsidian/plugins/obsidian-icon-folder/data.json"
    before = dp.read_text()
    r = _run(vault, "--dry-run", "reconcile", "--prefix", "app")
    assert r.returncode == 0, r.stderr
    assert dp.read_text() == before  # untouched
    plan = json.loads(r.stdout)
    assert plan["op"] == "reconcile"
    assert plan["dry_run"] is True
    assert plan["prefix"] == "app"
    assert "app/design.md" in plan["add_or_update"]
    assert "app/OBSOLETE.md" in plan["drop"]

def test_reconcile_preserves_stale_outside_prefix(tmp_path):
    vault = _prep(tmp_path)
    dp = vault / ".obsidian/plugins/obsidian-icon-folder/data.json"
    d = json.loads(dp.read_text())
    d["other/X.md"] = {"iconName": "LiBox"}
    dp.write_text(json.dumps(d, indent=2) + "\n")
    r = _run(vault, "reconcile", "--prefix", "app")
    assert r.returncode == 0, r.stderr
    data = json.loads(dp.read_text())
    assert "other/X.md" in data  # outside prefix → untouched
    assert "app/OBSOLETE.md" not in data  # inside prefix → dropped

def test_reconcile_skips_hidden_dirs(tmp_path):
    vault = _prep(tmp_path, with_stale=False)
    # Put a .md file inside each skip-dir. Reconcile shouldn't emit paths for them.
    for hidden in (".obsidian", ".git", ".claude", ".githooks"):
        d = vault / hidden / "sub"
        d.mkdir(parents=True, exist_ok=True)
        (d / "note.md").write_text("---\nrole: design\nstage: draft\n---\n")
    r = _run(vault, "--dry-run", "reconcile")
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    for hidden in (".obsidian", ".git", ".claude", ".githooks"):
        assert not any(p.startswith(f"{hidden}/") for p in plan["add_or_update"])
