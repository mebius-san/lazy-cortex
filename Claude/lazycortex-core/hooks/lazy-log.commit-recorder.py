#!/usr/bin/env python3
"""PostToolUse hook: record every successful git commit to .logs/commits.jsonl.

Fires after Bash(git commit*) or mcp__git__git_commit. Writes one JSON line per
commit with: sha, date, author, branch, message, files_changed, insertions,
deletions.

This is the raw commit feed that `lazy-log.distill` later converts into
functional prose in .logs/changelog.md, and that `lazy-log.recall` searches.

Design:
- No LLM call, no network, fast (~50ms)
- Silent on failure (never blocks the commit outcome)
- Creates .logs/ directory if missing
- Works whether invoked via Bash git commit or via MCP git_commit
"""

import json
import os
import re
import subprocess
import sys


def get_commit_info():
    """Return a dict describing HEAD, or None if not in a git repo / no HEAD."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    try:
        # sha, iso-date, author, subject
        raw = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:%H%x00%cI%x00%an <%ae>%x00%s"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        sha, date, author, subject = raw.split("\x00", 3)
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None

    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        branch = ""

    try:
        body = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:%b"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        body = ""

    # File stats from numstat (insertions, deletions, filename)
    try:
        numstat = subprocess.check_output(
            ["git", "show", "--numstat", "--format=", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        numstat = ""

    files = []
    total_ins = 0
    total_del = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            ins_raw, del_raw, path = parts
            # Binary files show "-" instead of numbers
            ins = int(ins_raw) if ins_raw.isdigit() else 0
            dl = int(del_raw) if del_raw.isdigit() else 0
            files.append(path)
            total_ins += ins
            total_del += dl

    return {
        "root": root,
        "sha": sha,
        "date": date,
        "author": author,
        "branch": branch,
        "subject": subject,
        "body": body.strip(),
        "files": files,
        "insertions": total_ins,
        "deletions": total_del,
    }


def should_run(payload):
    """Gate: only handle successful git commits."""
    tool_name = payload.get("tool_name", "")
    if tool_name == "mcp__git__git_commit":
        return True
    if tool_name == "Bash":
        command = payload.get("tool_input", {}).get("command", "")
        if re.match(r"git\s+commit\b", command):
            # In PostToolUse we also want to skip failures. Check tool_response if present.
            response = payload.get("tool_response", {})
            # response may contain "exit_code" or similar; be permissive
            exit_code = response.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return False
            return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    if not should_run(payload):
        return

    info = get_commit_info()
    if info is None:
        return

    root = info.pop("root")
    logs_dir = os.path.join(root, ".logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        return

    path = os.path.join(logs_dir, "commits.jsonl")

    # Idempotency: don't append the same SHA twice (useful if the hook fires
    # multiple times somehow — e.g., for both Bash and MCP on the same commit).
    try:
        with open(path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("sha") == info["sha"]:
                    return
    except FileNotFoundError:
        pass

    try:
        with open(path, "a") as f:
            f.write(json.dumps(info) + "\n")
    except OSError:
        return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
