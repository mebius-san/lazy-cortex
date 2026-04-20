import subprocess, sys, json, pathlib
WORKER = pathlib.Path(__file__).resolve().parents[1] / "iconize_sync.py"

def _run(payload):
    return subprocess.run([sys.executable, str(WORKER), "--validate-entry"],
                          input=json.dumps(payload), capture_output=True, text=True)

def test_valid_entry_exits_zero():
    r = _run({"iconName": "LiBook", "iconColor": "#bfdbfe"})
    assert r.returncode == 0

def test_monochrome_valid():
    r = _run({"iconName": "LiBook"})
    assert r.returncode == 0

def test_bad_color_exits_one():
    r = _run({"iconName": "LiBook", "iconColor": "#FFF"})
    assert r.returncode == 1

def test_bad_iconname_exits_one():
    r = _run({"iconName": "has space"})
    assert r.returncode == 1
