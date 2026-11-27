---
description: Code examples for `lazy-core.hook-writing` § 5.1 and § 5.2 — the defer-on-foreign-staged-content pattern and the refuse-on-pathspec check — and the § 5 audit severities. Read on demand when writing a hook that stages or commits, or when auditing one.
---
# Hook-writing examples

The code examples and audit severities of `lazy-core.hook-writing` § 5, extracted and read on demand: open this file when writing a hook that stages or auto-commits its own writes.

## § 5.1 No `git commit -- <pathspec>` to filter the index

```python
# Acceptable: detect foreign, defer
foreign = [p for p in pre_staged if p not in our_paths]
if foreign:
    sys.stderr.write(f"<hook>: foreign staged content; deferring\n")
    return                                      # writes stay in working tree
git_add(our_paths); git_commit(message)         # NO pathspec — index is clean
```

## § 5.2 No staging-without-committing handoff

```python
# Bash branch: refuse if pathspec
if re.search(r"\bgit\s+commit\b.*\s--\s+\S", command):
    _context("<hook-name>: pathspec on commit; modification declined")
    return
```

## § 5 Severity

`lazy-core.audit` Agent B:

- **FAIL** — hook calls `git commit ... -- <pathspec>` (literal pattern: `commit"` followed by `"--"` plus path arguments in the same arg list).
- **FAIL** — hook calls `git add` with no matching `git commit` in the same execution branch (heuristic, same shape as § 4 enforcement).
- **WARN** — hook detects pre-existing staged content (`git diff --cached --name-only`) but doesn't act on the detection (no defer / no refuse / no warning emitted).
