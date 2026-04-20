import pathlib, sys, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

ICON_MAP = json.loads((pathlib.Path(__file__).parent / "fixtures" / "icon-map.json").read_text())

def test_resolve_authored_doc_emits_self_entry():
    entries = isync.resolve_matchers(ICON_MAP, "app/design.md", {"role": "design", "stage": "draft"})
    assert entries == [("app/design.md", {"iconName": "LiDraftingCompass", "iconColor": "#fde68a"})]

def test_resolve_authored_doc_unmatched_role_returns_empty():
    entries = isync.resolve_matchers(ICON_MAP, "app/design.md", {"role": "xenon", "stage": "draft"})
    assert entries == []

def test_resolve_status_file_emits_self_and_parent_dir():
    entries = isync.resolve_matchers(ICON_MAP, "app/feature/_folder.md",
                                     {"stage": "draft-design"})
    paths = [p for p, _ in entries]
    assert "app/feature/_folder.md" in paths
    assert "app/feature" in paths
    assert entries[0][1] == entries[1][1]
    assert entries[0][1]["iconName"] == "LiPencil"

def test_resolve_status_file_cancelled_overlay_wins_over_blocked():
    fm = {"stage": "draft-design", "blocked": True, "cancelled": True}
    entries = isync.resolve_matchers(ICON_MAP, "app/x/_folder.md", fm)
    _, entry = entries[0]
    assert entry["iconName"] == "LiXCircle"
    assert entry["iconColor"] == "#e2e8f0"

def test_resolve_unmatched_file_returns_empty():
    entries = isync.resolve_matchers(ICON_MAP, "README.md", {})
    assert entries == []

def test_resolve_status_file_with_missing_stage_and_no_overlay_returns_empty():
    entries = isync.resolve_matchers(ICON_MAP, "app/x/_folder.md", {})
    assert entries == []

def test_resolve_overlay_when_sees_full_path():
    """Overlay `when` uses `path_glob` — verifies full path is threaded through."""
    icon_map = {
        "version": "1.0.0",
        "matchers": [{
            "id": "path-overlay",
            "when": {"basename": "_folder.md"},
            "resolve": {
                "base": {"iconName": "LiBase"},
                "overlays": [
                    {"when": {"path_glob": "archive/**"}, "iconName": "LiArchive", "priority": 1},
                ],
            },
            "emit": ["self"],
        }],
    }
    # Under archive/ → overlay wins
    entries = isync.resolve_matchers(icon_map, "archive/old/_folder.md", {})
    assert entries[0][1]["iconName"] == "LiArchive"
    # Not under archive/ → base wins
    entries = isync.resolve_matchers(icon_map, "live/x/_folder.md", {})
    assert entries[0][1]["iconName"] == "LiBase"

def test_resolve_parent_dir_skipped_for_top_level_file():
    """parent_dir emit on a file with no directory component → no extra entry."""
    icon_map = {
        "version": "1.0.0",
        "matchers": [{
            "id": "top",
            "when": {"basename": "_folder.md"},
            "resolve": {"iconName": "LiRoot"},
            "emit": ["self", "parent_dir"],
        }],
    }
    entries = isync.resolve_matchers(icon_map, "_folder.md", {})
    assert len(entries) == 1
    assert entries[0][0] == "_folder.md"
