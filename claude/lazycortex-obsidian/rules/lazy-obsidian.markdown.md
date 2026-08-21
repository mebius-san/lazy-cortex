---
description: Markdown constructs Obsidian interprets as structure — what to escape when writing into a vault so notes do not gain phantom tags, lose their frontmatter, or grow unintended dataview fields.
always_loaded: "every markdown write into a vault can silently break its indexing, and writes happen on any turn"
---
# Vault-safe markdown

The repo is an Obsidian vault. Obsidian indexes and renders note bodies, so text an author meant literally can become structure. The constructs below are the ones that actually bite; each has a cheap escape.

## 1. Bare `#` tokens become tags

Any `#` followed by letters, digits, `_`, `-`, or `/` is indexed as a tag and shows up in the tag pane — hex colours (`` `#93c5fd` ``), issue and PR numbers (`` `#5` ``), booking codes, tag literals quoted inside prose.

- Write such a token in backticks. Obsidian does not parse tags inside inline code or fenced blocks.
- A run of consecutive numbers is wrapped whole (`` `#10/#11/#12` ``), not one by one — per-token backticks shred the line.
- Markdown headings (`# `, `## `) and `#` inside fences are unaffected — no tag is created there.

**An intentional tag is written bare.** This rule is about accidental tokens — a `#` that reached the text as part of a number, a colour, a code, a quotation. When the author does mean a tag in that spot, they write it as is and it indexes. Backticks say "this is not a tag"; their absence says "this is one".

## 2. Unquoted frontmatter values destroy the whole block

A value containing `:` or starting with `#`, `@`, `{`, or `[` makes the YAML unparseable. Obsidian drops the entire frontmatter silently — the note loses `tags`, `spec_role`, `review_active`, and vanishes from dataview queries, gate scans, and the review loop.

Quote any value that is not a plain word or number. When in doubt, quote.

## 3. `key:: value` in prose creates a dataview field

Double colon is dataview's inline-field syntax anywhere in a note body, not only in a dedicated section. Use it only where the field is intended; never as ordinary punctuation.

## 4. Angle-bracket placeholders are parsed as HTML

Markdown passes raw HTML through, so `<slug>`, `<test name>`, `<plugin>` are read as opening tags: the text vanishes in reading view and is coloured as markup in the editor. Any placeholder, generic parameter, or literal tag written in prose goes in backticks — `` `<slug>` ``. Inside fenced blocks it is already inert.
