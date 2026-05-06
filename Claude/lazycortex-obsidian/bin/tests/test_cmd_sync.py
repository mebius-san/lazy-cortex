import pathlib, sys, json, shutil, subprocess
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
FIX = pathlib.Path(__file__).parent / "fixtures"

def _prep(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    mapdir = vault / ".claude" / "iconize"; mapdir.mkdir(parents=True)
    shutil.copy(FIX / "obsidian-icon-map.json", mapdir / "obsidian-icon-map.json")
    (vault / "app").mkdir()
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nbody\n")
    return vault

def _run(vault, *args):
    return subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), *args],
                          capture_output=True, text=True, cwd=str(vault))

def _read(vault, rel):
    return (vault / rel).read_text()


def test_sync_writes_frontmatter_for_authored_doc(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "sync", "app/design.md")
    assert r.returncode == 0, r.stderr
    body = _read(vault, "app/design.md")
    assert "iconize_icon: LiDraftingCompass" in body
    assert 'iconize_color: "#fde68a"' in body


def test_sync_noop_for_unmatched_file(tmp_path):
    vault = _prep(tmp_path)
    (vault / "README.md").write_text("no frontmatter")
    r = _run(vault, "sync", "README.md")
    assert r.returncode == 0
    assert _read(vault, "README.md") == "no frontmatter"


def test_sync_unmatched_emits_changed_false_payload(tmp_path):
    vault = _prep(tmp_path)
    (vault / "README.md").write_text("no frontmatter")
    r = _run(vault, "sync", "README.md")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload == {"op": "sync", "path": "README.md", "changed": False,
                       "icon": None, "color": None}


def test_sync_dry_run_writes_nothing(tmp_path):
    vault = _prep(tmp_path)
    before = _read(vault, "app/design.md")
    r = _run(vault, "--dry-run", "sync", "app/design.md")
    assert r.returncode == 0
    assert _read(vault, "app/design.md") == before


def test_sync_accepts_absolute_path_inside_vault(tmp_path):
    """PostToolUse hooks always pass absolute paths (Claude Code's tool_input.file_path
    is always absolute). The worker must relativize against the vault, not reject."""
    vault = _prep(tmp_path)
    abs_path = str(vault / "app" / "design.md")
    r = _run(vault, "sync", abs_path)
    assert r.returncode == 0, r.stderr
    body = _read(vault, "app/design.md")
    assert "iconize_icon: LiDraftingCompass" in body


def test_sync_noop_for_absolute_path_outside_vault(tmp_path):
    """Paths outside the vault are common when the hook fires on an unrelated edit —
    silently no-op, don't fail."""
    vault = _prep(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("---\nrole: design\n---\n")
    r = _run(vault, "sync", str(outside))
    assert r.returncode == 0, r.stderr
    assert outside.read_text() == "---\nrole: design\n---\n"
