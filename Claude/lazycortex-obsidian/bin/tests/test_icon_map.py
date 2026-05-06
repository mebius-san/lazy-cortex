import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "obsidian-icon-map.json"

def test_load_icon_map_returns_dict_with_expected_keys():
    m = isync.load_icon_map(FIXTURE)
    assert m["schema_version"] == 2
    assert "roles" in m["registries"]
    assert "steps" in m["registries"]
    assert len(m["matchers"]) >= 2

def test_lookup_dotted_path_returns_registry_dict():
    m = isync.load_icon_map(FIXTURE)
    roles = isync.lookup_dotted(m, "registries.roles")
    assert "design" in roles

def test_lookup_dotted_missing_key_returns_none():
    m = isync.load_icon_map(FIXTURE)
    assert isync.lookup_dotted(m, "registries.nonexistent") is None

def test_interpolate_substitutes_frontmatter_and_basename():
    fm = {"role": "design", "stage": "draft"}
    assert isync.interpolate("{{frontmatter.role}}", fm, "design.md") == "design"
    assert isync.interpolate("{{basename}}", fm, "design.md") == "design.md"
    assert isync.interpolate("static", fm, "x.md") == "static"

def test_interpolate_handles_basename_stem_and_missing_key():
    assert isync.interpolate("{{basename.stem}}", {}, "design.md") == "design"
    assert isync.interpolate("{{frontmatter.absent}}", {}, "x.md") == ""
    # Unrecognized token left literal per spec (silent-miss downstream).
    assert isync.interpolate("{{unknown}}", {}, "x.md") == "{{unknown}}"

def test_load_icon_map_rejects_non_list_matchers(tmp_path):
    import json
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"matchers": "oops"}))
    try: isync.load_icon_map(bad)
    except isync.IconizeError as e: assert e.code == isync.EXIT_VALIDATION
    else: raise AssertionError("expected IconizeError on non-list matchers")

def test_load_icon_map_rejects_missing_matchers(tmp_path):
    import json
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"registries": {}}))
    try: isync.load_icon_map(bad)
    except isync.IconizeError as e: assert e.code == isync.EXIT_VALIDATION
    else: raise AssertionError("expected IconizeError on missing matchers")
