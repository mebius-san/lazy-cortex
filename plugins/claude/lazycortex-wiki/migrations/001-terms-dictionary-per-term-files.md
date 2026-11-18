---
since: 4.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-wiki, terms-migrate, --check]}
writes:
  - "{terms}"
  - ".claude/lazy.settings.json"
---
## Why

An earlier release kept the terms dictionary of a scope in one file (`terms.file`) and let every document carry its own `## Terms` section that repeated definitions. The dictionary is now a directory with one file per term (`terms.scopes.<id>.dir`), and a document no longer copies a definition: it links the term file at each use of the term. A repository left in the old shape keeps the one-file dictionary, which the plugin no longer reads, and documents whose `## Terms` sections the plugin no longer maintains.

The `terms-migrate` verb cuts the legacy dictionary file into term files under the scope's `dir` (the path of the legacy file without its extension), drops the `legacy_file` key from the scope's settings once the cut is done, and passes over the documents of the scope, including documents under review: it removes the lines of their old `## Terms` sections whose terms the dictionary now holds, together with a section left empty, and moves links to headings of the legacy file onto the term files. A link to such a heading that stands where a link edit never reaches — a heading line, a checkbox line, a comment, code — stays as written; the verb names each one, in its report and on stderr, so the operator can move it by hand, and the check below never waits for it. A document that changes on disk while the verb runs is left as it stands and named the same way. The lines the dictionary does not settle stay; the curator settles them in the pass step 002 queues. A document the scope excludes as a term source, which no curator pass reads, loses its `## Terms` section whole. Only documents tracked by git are migrated. Two terms whose names normalise to one file name are joined into one term file with both definitions.

This step does not run when the repository grants it no paths to write in the terms scopes: when it has no `terms` section, when its scopes name no dictionary, or when any one scope names its dictionary or legacy file with a wildcard, whitespace, an absolute path, a `..` or a `.git` segment, or has a document glob that is absolute, climbs out with `..`, passes through a `.git` segment or starts with a wildcard — one such scope withholds every scope, so the step never writes outside the repository's own documents. The operator then runs two commands by hand, using the CLI path that step 1 prints (`bin/lazycortex-wiki` under the plugin root it prints), in this order: `terms-migrate --repo "<repo-root>"` and a commit of what it changed, then `terms-sweep --dispatch --include-review --repo "<repo-root>"` in the checkout where the daemon works.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<wiki-cli>` is `bin/lazycortex-wiki` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-wiki --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-migrate --repo "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-migrate --check --repo "<repo-root>"` exits 1: no scope still holds a legacy dictionary file to cut, and no document of a scope still carries a `## Terms` section the verb removes.
