---
since: 5.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-wiki, terms-recase, --check]}
writes:
  - "{terms}"
---
## Why

A term's file name and its title line now follow the letter case of the term's language: an English term starts every word with a capital, a Russian term only its first word, and a proper name inside a term keeps its own capital. An earlier release kept whatever case a document used, so one dictionary mixed `Quest Board.md` with `автор раздела.md`, and the title inside each file repeated that case. The curator now writes every new title in the canon, so a dictionary left in the old state keeps both kinds side by side with no rule to tell them apart.

The `terms-recase` verb brings every terms scope whose dictionary is already a directory of term files to the canon. It raises the first letters of each term file's title line as the canon asks and changes nothing else in the file. A file whose name is its title's file name, letter case aside, is renamed to the cased title's file name, through a temporary name so that the file system records a change of path. The verb then asks git, without staging anything, whether it sees the old path deleted and the new one untracked. On a case-insensitive checkout git may not notice a case-only rename of a tracked file; the verb then moves the file back, so its name stays, its title is still cased, and the links to it keep pointing at the name it has. The outcome line names each file under `renamed` or `kept`, and the check below never waits for a name git cannot take. A file named otherwise keeps its name, and a file with no title line is left alone. Then every document of the scope, documents under review included, has each link to a renamed file moved onto the new name, and a link without display text keeps showing the words it showed, so no sentence a reader sees changes. A document the scope excludes from link editing is left as it is. A scope that still names its old single dictionary file waits for step 001.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<wiki-cli>` is `bin/lazycortex-wiki` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-wiki --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-recase --repo "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <wiki-cli> terms-recase --check --repo "<repo-root>"` exits 1: no term file of a migrated scope still has a title the canon changes, or a file name it changes that git on this checkout can take.
