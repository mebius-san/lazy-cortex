# Domain groups

The dictionary of groups legal in `# Domain(group):` blocks across this
project. The `lazy-python.domain-writer` agent validates every block against this file and
never invents a group of its own: when nothing here fits, it files the block under the
reserved group `unfiled` and reports a candidate — add the real group below and rename the
block to resolve the checker finding. The reserved `unfiled` group is never listed here.

Format: one `##` heading per group (lowercase, dot-separated hierarchy) and a one-line
gloss under it.

<!-- Replace the sample group below with your project's groups. -->

## simulation

Rules of the simulated world's mechanics: what happens, in what order, under which chances.
