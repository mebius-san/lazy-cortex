import pathlib, sys, json, shutil, subprocess, os
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _git(cwd, *args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(cwd))

def _prep(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "obsidian-iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "icon-map.json", mapdir / "icon-map.json")
    _git(vault, "init", "-q")
    _git(vault, "config", "user.email", "t@t"); _git(vault, "config", "user.name", "t")
    _git(vault, "add", "."); _git(vault, "commit", "-q", "-m", "init")
    return vault

def test_sync_staged_processes_staged_md_files(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    _git(vault, "add", "app/design.md")
    r = subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), "sync-staged"],
                       capture_output=True, text=True, cwd=str(vault))
    assert r.returncode == 0, r.stderr
    data = json.loads((vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text())
    assert "app/design.md" in data

def test_sync_staged_noop_when_nothing_staged(tmp_path):
    vault = _prep(tmp_path)
    before = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    r = subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), "sync-staged"],
                       capture_output=True, text=True, cwd=str(vault))
    assert r.returncode == 0, r.stderr
    after = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    assert before == after

def test_sync_staged_dry_run_writes_nothing(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    _git(vault, "add", "app/design.md")
    before = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    r = subprocess.run([sys.executable, str(WORKER), "--vault", str(vault),
                        "--dry-run", "sync-staged"],
                       capture_output=True, text=True, cwd=str(vault))
    assert r.returncode == 0, r.stderr
    after = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    assert before == after
    payload = json.loads(r.stdout)
    assert payload["op"] == "sync-staged"
    assert payload["dry_run"] is True

def test_sync_staged_ignores_deleted_files(tmp_path):
    vault = _prep(tmp_path)
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\n")
    _git(vault, "add", "app/design.md")
    _git(vault, "commit", "-q", "-m", "add design")
    # Now delete and stage the deletion
    (vault / "app" / "design.md").unlink()
    _git(vault, "add", "-A", "app/design.md")
    r = subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), "sync-staged"],
                       capture_output=True, text=True, cwd=str(vault))
    assert r.returncode == 0, r.stderr
    # Deletion is not synced; reconcile handles purging.
