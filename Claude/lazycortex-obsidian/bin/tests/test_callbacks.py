import os, pathlib, stat, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

CB_DIR = pathlib.Path(__file__).parent / "fixtures" / "callbacks"


def setup_module(module=None):
    """Ensure fixture callbacks are executable (git may not preserve +x).

    `not-exec` is intentionally left without the exec bit so the
    non-executable error path can be tested."""
    if not CB_DIR.is_dir():
        return
    for p in CB_DIR.iterdir():
        if not p.is_file() or p.name == "not-exec":
            continue
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# Run at import time for the harness (harness doesn't call setup_module).
setup_module()


def test_callback_when_returns_true():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_when("always-match", "x.md", {}) is True
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev


def test_callback_when_missing_returns_false():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_when("nonexistent", "x.md", {}) is False
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev


def test_callback_resolve_returns_entry():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_resolve("custom-resolver", {}, {}) == {
            "iconName": "LiZap",
            "iconColor": "#abcdef",
        }
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev


def test_callback_when_nonzero_exit_returns_false():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_when("exits-nonzero", "x.md", {}) is False
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev


def test_callback_when_non_json_returns_false():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_when("non-json", "x.md", {}) is False
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev


def test_callback_when_non_executable_returns_false():
    prev = isync.CALLBACK_DIR_OVERRIDE
    isync.CALLBACK_DIR_OVERRIDE = CB_DIR
    try:
        assert isync._callback_when("not-exec", "x.md", {}) is False
    finally:
        isync.CALLBACK_DIR_OVERRIDE = prev
