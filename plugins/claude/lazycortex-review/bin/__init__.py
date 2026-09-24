"""lazycortex-review — pure-Python doc-review state machine.

Layered (bottom → top):

  Primitives:        errors, frontmatter, parser, git_ops, job_ids
  Document parts:    body, banner, history, edit_markup
  Assembly:          payload, reapply
  Orchestration:     state_machine, dispatcher
  CLI entry:         lazy_review
  Slash commands:    start, finalize, stop, status
"""
