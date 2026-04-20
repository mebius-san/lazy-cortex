import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

def test_parse_frontmatter_returns_dict():
    text = "---\nrole: design\nstage: draft\n---\n\nbody\n"
    fm = isync.parse_frontmatter(text)
    assert fm == {"role": "design", "stage": "draft"}

def test_parse_frontmatter_missing_returns_empty_dict():
    assert isync.parse_frontmatter("no frontmatter here") == {}

def test_parse_frontmatter_parses_booleans():
    fm = isync.parse_frontmatter("---\nblocked: true\ncancelled: false\n---\n")
    assert fm == {"blocked": True, "cancelled": False}

def test_normalize_path_strips_leading_dot_slash_and_trailing_slash():
    assert isync.normalize_path("./a/b/") == "a/b"

def test_normalize_path_rejects_leading_slash():
    try: isync.normalize_path("/abs")
    except isync.IconizeError as e: assert e.code == isync.EXIT_VALIDATION
    else: raise AssertionError()

def test_validate_color_accepts_short_and_long():
    isync.validate_color("#fab"); isync.validate_color("#fed7aa")

def test_validate_color_rejects_uppercase_or_bad():
    for bad in ("#FFF", "fed7aa", "#zzz"):
        try: isync.validate_color(bad)
        except isync.IconizeError: pass
        else: raise AssertionError(f"should have rejected {bad}")

def test_normalize_path_rejects_home_and_backslash():
    for bad in ("~/a", "~user/a", r"a\b"):
        try: isync.normalize_path(bad)
        except isync.IconizeError as e: assert e.code == isync.EXIT_VALIDATION
        else: raise AssertionError(f"should have rejected {bad!r}")

def test_normalize_path_rejects_dotslash_only():
    try: isync.normalize_path("./")
    except isync.IconizeError as e: assert e.code == isync.EXIT_VALIDATION
    else: raise AssertionError("should have rejected './'")

def test_parse_frontmatter_skips_empty_keys():
    fm = isync.parse_frontmatter("---\n: orphan\nreal: ok\n---\n")
    assert fm == {"real": "ok"}

def test_validate_icon_name_accepts_regex_match_and_short_emoji():
    isync.validate_icon_name("LiFolder")
    isync.validate_icon_name("Li-Folder_2")
    isync.validate_icon_name("\U0001F600")  # single emoji grapheme (≤8 chars)

def test_validate_icon_name_rejects_empty_whitespace_and_long_unrecognized():
    # Non-regex-matching AND >8 chars → reject. Long bareword is fine (matches regex).
    for bad in ("", " LiFolder", "LiFolder ", "name with space", "\U0001F600\U0001F600\U0001F600\U0001F600\U0001F600\U0001F600\U0001F600\U0001F600\U0001F600"):
        try: isync.validate_icon_name(bad)
        except isync.IconizeError: pass
        else: raise AssertionError(f"should have rejected {bad!r}")
