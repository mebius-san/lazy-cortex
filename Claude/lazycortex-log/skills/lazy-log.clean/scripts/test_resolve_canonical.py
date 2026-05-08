import json
import subprocess
from pathlib import Path
from textwrap import dedent

SCRIPT = Path(__file__).parent / "resolve-canonical.py"

def _make_skill(tmp_path, name, frontmatter):
    skill_dir = tmp_path / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(dedent(f"""\
        ---
        name: {name}
        description: stub
        {frontmatter}
        ---
        # {name}
        """))
    return skill_dir

def test_waivered_skill_appears_in_waivered_map(tmp_path, monkeypatch):
    _make_skill(tmp_path, "test.waived", 'logging-waiver: "mechanical worker"')
    _make_skill(tmp_path, "test.normal",  "")
    monkeypatch.chdir(tmp_path)
    out = subprocess.check_output(["python3", str(SCRIPT)], text=True)
    data = json.loads(out)
    assert "test.waived" in data["canonical"]
    assert "test.normal" in data["canonical"]
    assert data["waivered"] == {"test.waived": "mechanical worker"}

def test_no_waivers_yields_empty_waivered_map(tmp_path, monkeypatch):
    _make_skill(tmp_path, "test.normal", "")
    monkeypatch.chdir(tmp_path)
    out = subprocess.check_output(["python3", str(SCRIPT)], text=True)
    data = json.loads(out)
    assert data["waivered"] == {}
