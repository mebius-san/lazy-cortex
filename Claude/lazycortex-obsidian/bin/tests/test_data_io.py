import json, pathlib, sys, shutil
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import iconize_sync as isync

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "vault"

def _copy_vault(tmp):
    dst = pathlib.Path(tmp) / "vault"
    shutil.copytree(FIXTURE, dst)
    return dst

def test_find_vault_from_subdir(tmp_path):
    v = _copy_vault(tmp_path)
    sub = v / "some" / "sub"
    sub.mkdir(parents=True)
    assert isync.find_vault_walk_up(sub) == v

def test_find_vault_override_requires_obsidian_dir(tmp_path):
    empty = tmp_path / "notavault"
    empty.mkdir()
    try:
        isync.find_vault(str(empty))
    except isync.IconizeError as e:
        assert e.code == isync.EXIT_DATAFILE_MISSING
    else:
        raise AssertionError("expected IconizeError")

def test_load_and_dump_round_trip(tmp_path):
    v = _copy_vault(tmp_path)
    dp = isync.find_data_path(v)
    obj, mtime = isync.load_data(dp)
    obj["New/Path"] = {"iconName": "LiStar"}
    isync.dump_data(dp, obj, mtime)
    reread = json.loads(dp.read_text())
    assert reread["New/Path"] == {"iconName": "LiStar"}
    assert reread["settings"]["iconInFrontmatterEnabled"] is False

def test_dump_detects_concurrent_mutation(tmp_path):
    v = _copy_vault(tmp_path)
    dp = isync.find_data_path(v)
    _, mtime = isync.load_data(dp)
    dp.write_text(dp.read_text() + "\n")
    try:
        isync.dump_data(dp, {}, mtime)
    except isync.IconizeError as e:
        assert e.code == isync.EXIT_CONCURRENT
    else:
        raise AssertionError("expected EXIT_CONCURRENT")
