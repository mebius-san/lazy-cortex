import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

def test_basename_predicate():
    assert isync.eval_when({"basename": "design.md"}, "dir/design.md", {}) is True
    assert isync.eval_when({"basename": "design.md"}, "dir/plan.md", {}) is False

def test_basename_in_predicate():
    w = {"basename_in": ["design.md", "plan.md"]}
    assert isync.eval_when(w, "dir/plan.md", {}) is True
    assert isync.eval_when(w, "dir/tech.md", {}) is False

def test_path_glob_predicate():
    assert isync.eval_when({"path_glob": "**/requests/*.md"}, "product/requests/foo.md", {}) is True
    assert isync.eval_when({"path_glob": "**/requests/*.md"}, "product/design.md", {}) is False

def test_frontmatter_equality():
    assert isync.eval_when({"frontmatter.role": "design"}, "x.md", {"role": "design"}) is True
    assert isync.eval_when({"frontmatter.blocked": True}, "x.md", {"blocked": True}) is True
    assert isync.eval_when({"frontmatter.blocked": True}, "x.md", {"blocked": False}) is False

def test_role_matches_basename_shorthand():
    w = {"role_matches_basename": True}
    assert isync.eval_when(w, "x/design.md", {"role": "design"}) is True
    assert isync.eval_when(w, "x/design.md", {"role": "plan"}) is False

def test_and_semantics_across_keys():
    w = {"basename_in": ["design.md"], "role_matches_basename": True}
    assert isync.eval_when(w, "x/design.md", {"role": "design"}) is True
    assert isync.eval_when(w, "x/design.md", {"role": "plan"}) is False

def test_path_glob_respects_segment_boundaries():
    # `**` crosses segments, `*` does not.
    w = {"path_glob": "**/requests/*.md"}
    assert isync.eval_when(w, "requests/foo.md", {}) is True           # root-level match
    assert isync.eval_when(w, "a/b/requests/foo.md", {}) is True       # deep prefix
    assert isync.eval_when(w, "x/requests/sub/deep/foo.md", {}) is False  # over-deep
    # `*.md` must NOT match across path separators.
    assert isync.eval_when({"path_glob": "*.md"}, "a/b/c.md", {}) is False
    assert isync.eval_when({"path_glob": "*.md"}, "c.md", {}) is True

def test_basename_in_rejects_non_list():
    try: isync.eval_when({"basename_in": "design.md"}, "x/design.md", {})
    except isync.IconizeError: pass
    else: raise AssertionError("expected IconizeError on string for basename_in")

def test_unknown_predicate_raises():
    try: isync.eval_when({"frobnicate": "x"}, "x/y.md", {})
    except isync.IconizeError: pass
    else: raise AssertionError("expected IconizeError on unknown predicate")
