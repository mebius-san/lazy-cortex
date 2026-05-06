import json, pathlib, shutil, subprocess, sys
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"
PLUGIN_ROOT = WORKER.parents[1]
FIX = pathlib.Path(__file__).parent / "fixtures"


def _prep(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(FIX / "vault", vault)
    return vault


def _run(vault, *args):
    env = {**__import__("os").environ, "LAZY_OBSIDIAN_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    return subprocess.run([sys.executable, str(WORKER), "--vault", str(vault), *args],
                          capture_output=True, text=True, cwd=str(vault), env=env)


def _install_icon_map(vault, overrides=None):
    mapdir = vault / ".claude" / "iconize"; mapdir.mkdir(parents=True, exist_ok=True)
    src = json.loads((FIX / "obsidian-icon-map.json").read_text())
    if overrides:
        src.update(overrides)
    (mapdir / "obsidian-icon-map.json").write_text(json.dumps(src, indent=2) + "\n")


# ---------------------------------------------------------------------------
# install-hooks + check-versions
# ---------------------------------------------------------------------------

def test_check_versions_returns_drift_when_no_hooks_installed(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "check-versions")
    assert r.returncode == 5  # EXIT_VERSION_DRIFT
    assert "HOOK_VERSION" in (r.stdout + r.stderr)


def test_install_hooks_writes_shim_only(tmp_path):
    """Worker now only installs the pre-commit shim. The PostToolUse hook is
    plugin-shipped (hooks/hooks.json); no consumer settings.json mutation."""
    vault = _prep(tmp_path)
    r = _run(vault, "install-hooks")
    assert r.returncode == 0, r.stderr
    shim = vault / ".githooks" / "pre-commit"
    assert shim.exists()
    assert "HOOK_VERSION: 2.0.0" in shim.read_text()
    # Worker must not touch consumer settings.json anymore.
    assert not (vault / ".claude" / "settings.json").exists()


def test_shim_is_path_agnostic(tmp_path):
    """Installed shim must not leak /Users/... or any absolute plugin path into
    executable code. Documentation comments describing what we avoid are fine."""
    vault = _prep(tmp_path)
    _run(vault, "install-hooks")
    body = (vault / ".githooks" / "pre-commit").read_text()
    # Strip comment lines so we only audit the executable portion.
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "/Users/" not in code
    assert str(PLUGIN_ROOT) not in code
    assert "{{PLUGIN_BIN_PATH}}" not in body  # no un-substituted token anywhere


def test_check_versions_passes_after_install(tmp_path):
    vault = _prep(tmp_path)
    _run(vault, "install-hooks")
    r = _run(vault, "check-versions")
    assert r.returncode == 0, r.stderr


def test_check_versions_reports_schema_block(tmp_path):
    """check-versions includes icon_map_schema.declared when the vault has one."""
    vault = _prep(tmp_path)
    _install_icon_map(vault, overrides={"schema_version": 2})
    _run(vault, "install-hooks")
    r = _run(vault, "check-versions")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["icon_map_schema"]["declared"] == 2
    assert report["icon_map_schema"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Preflight (bilateral version handshake)
# ---------------------------------------------------------------------------

def _prep_sync_target(vault):
    (vault / "app").mkdir(exist_ok=True)
    (vault / "app" / "design.md").write_text("---\nrole: design\nstage: draft\n---\nbody\n")


def test_preflight_incompatible_schema_exits_ok_silently(tmp_path):
    """Hook must never block: incompatible schema → exit 0 + stderr diagnostic."""
    vault = _prep(tmp_path)
    _install_icon_map(vault, overrides={"schema_version": 99})
    _prep_sync_target(vault)
    data_before = (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text()
    r = _run(vault, "sync", "app/design.md")
    assert r.returncode == 0, r.stderr
    assert "schema_version" in r.stderr
    assert "inert" in r.stderr
    # No mutation.
    assert (vault / ".obsidian/plugins/obsidian-icon-folder/data.json").read_text() == data_before


def test_preflight_min_hook_version_too_new_exits_ok_silently(tmp_path):
    vault = _prep(tmp_path)
    _install_icon_map(vault, overrides={"min_hook_version": "99.0.0"})
    _prep_sync_target(vault)
    r = _run(vault, "sync", "app/design.md")
    assert r.returncode == 0, r.stderr
    assert "min_hook_version" in r.stderr
    assert "99.0.0" in r.stderr


