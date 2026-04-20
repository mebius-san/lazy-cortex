"""Minimal test harness — run all test_*.py in the same directory.

Supports a single fixture: tmp_path (injected as a temporary directory).
"""
import importlib.util, inspect, pathlib, sys, tempfile, traceback

test_dir = pathlib.Path(__file__).parent
passed = 0; failed = 0

for tf in sorted(test_dir.glob("test_*.py")):
    spec = importlib.util.spec_from_file_location(tf.stem, tf)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"IMPORT ERROR {tf.name}: {e}")
        traceback.print_exc()
        failed += 1
        continue
    for name in sorted(dir(mod)):
        if not name.startswith("test_"):
            continue
        fn = getattr(mod, name)
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(tmp_path=pathlib.Path(td))
            else:
                fn()
            passed += 1
            print(f"  PASS {tf.name}::{name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {tf.name}::{name}: {e}")
            traceback.print_exc()

print(f"\nTotal: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
