import subprocess, sys, pathlib
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"

def _run(*args):
    return subprocess.run([sys.executable, str(WORKER), *args], capture_output=True, text=True)

def test_version_flag_prints_protocol_and_hook_versions():
    r = _run("--version")
    assert r.returncode == 0
    # Expect both versions on stdout, whitespace-separated
    assert "protocol_version=" in r.stdout
    assert "hook_version=" in r.stdout

def test_missing_subcommand_exits_validation():
    r = _run()
    assert r.returncode == 1
    assert "usage" in (r.stderr + r.stdout).lower()

def test_unknown_subcommand_exits_validation():
    r = _run("nope")
    assert r.returncode == 1
