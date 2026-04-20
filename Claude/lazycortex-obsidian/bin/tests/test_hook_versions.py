import pathlib, sys, subprocess, json, shutil
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

def test_check_versions_returns_drift_when_no_hooks_installed(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "check-versions")
    assert r.returncode == 5  # EXIT_VERSION_DRIFT
    assert "HOOK_VERSION" in (r.stdout + r.stderr)

def test_install_hooks_writes_shim_and_settings_entry(tmp_path):
    vault = _prep(tmp_path)
    r = _run(vault, "install-hooks")
    assert r.returncode == 0, r.stderr
    shim = vault / ".githooks" / "pre-commit"
    assert shim.exists()
    assert "HOOK_VERSION: 1.0.0" in shim.read_text()
    settings = json.loads((vault / ".claude" / "settings.json").read_text())
    postuse = settings["hooks"]["PostToolUse"]
    cmd = postuse[0]["hooks"][0]["command"]
    assert "HOOK_VERSION: 1.0.0" in cmd

def test_check_versions_passes_after_install(tmp_path):
    vault = _prep(tmp_path)
    _run(vault, "install-hooks")
    r = _run(vault, "check-versions")
    assert r.returncode == 0, r.stderr

def test_render_snippet_escapes_json_unsafe_chars(monkeypatch=None):
    sys.path.insert(0, str(WORKER.parent))
    import iconize_sync as isync
    orig = isync._plugin_bin_path
    try:
        isync._plugin_bin_path = lambda: pathlib.Path('/tmp/w"eird\\path')
        result = isync._render_post_tool_use_snippet()
    finally:
        isync._plugin_bin_path = orig
    cmd = result["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "iconize_sync.py" in cmd
    assert 'w\\"eird' in cmd or 'w"eird' in cmd
