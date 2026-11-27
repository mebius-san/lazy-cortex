---
description: "Shape every Bash command so it runs under an allow-list permission mode — no redundant cd, one plain command per call, the pathspec commit form, one plain retry after a denial, no change to the given environment."
always_loaded: "Every session and every daemon expert job issues Bash commands, and a job runs in a non-interactive permission mode where a denied command ends the job."
---

# `lazy-core.shell` — command shape

A daemon expert job runs with an allow-list and no operator to answer a prompt. A command that matches no allowed pattern is denied, and a job that cannot rephrase it fails and leaves the tree dirty. Allow-list patterns match one plain command, so the shape of the command decides whether it runs.

## 1. `cd` only to reach another directory

The working directory is already the repository root. A command about this repository runs without `cd` and names its files by repo-relative or absolute paths. When a command genuinely has to run in another directory, `cd` into that directory is allowed.

## 2. One plain command per Bash call

Issue one command per call. No `;` or `&&` chains, no `for` / `while` loops, no `xargs`, and no `$(…)` substitution wrapped around `git`. Several steps are several calls; a list of files is read first and then passed as explicit arguments.

## 3. Commit with an explicit pathspec

Commit as `git commit -m "<message>" -- <path> <path>`, naming every path, per `lazy-core.git`.

## 4. One plain retry after a denial

When a command is denied, rewrite it once in the plain form sections 1–3 describe and issue it again. Only a denial of that plain form ends the job as failed.

## 5. Work in the environment you are given

A command runs in the environment the session or job was given. Never set an environment variable for it — `VIRTUAL_ENV`, `LAZYCORTEX_PLUGIN_DIRS` or any other —, never point it at another virtual environment or another plugin version, and never edit a checker's configuration. A plugin, a path or a virtual environment that cannot be found stops the work, and its error is reported verbatim. A check of the work that fails or cannot run fails that work — a job ends with `outcome: error` and the exact error text — and never ends in success. A settings problem is fixed by the operator or by the plugin, never by the session or job that met it.
