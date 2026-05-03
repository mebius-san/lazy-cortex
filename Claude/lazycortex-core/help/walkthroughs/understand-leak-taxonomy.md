---
chapter_type: walkthrough
summary: Learn the FAIL-vs-WARN leak taxonomy, how waivers work, and what the public-repo flow checks before publishing.
last_regen: 2026-05-03
diagram_spec:
  anchor: "Taxonomy at a glance"
  request: "Decision tree: is a finding a FAIL (secrets — never waivable) or a WARN (PII / infrastructure / local paths / author metadata — waivable with reason), plus the credential-isolation rule as a separate branch."
  kind_hint: decision-tree
source_skills:
  - lazy-guard.security
---
# How does the public-repo flow know what counts as a leak?

When you run `/lazy-repo.mark-public` or `/lazy-guard.check-public`, every tracked file is inspected against a fixed taxonomy defined in the `lazy-guard.security` rule. That rule divides findings into two severity tiers — FAIL and WARN — and specifies exactly which patterns belong to each tier. This walkthrough explains what each tier contains, how the scanner detects each category, how waivers silence accepted exceptions, and why credentials are handled separately from everything else.

## What you need

- The `lazycortex-core` plugin installed in your repo.
- A git-tracked repository (the scanner operates on `git ls-files` output).
- No prerequisites for reading this chapter — you do not need to run a scan first.

## The flow

### Step 1 — Understand the two-tier severity model

Every finding that `/lazy-guard.check-public` produces is one of two severities:

**FAIL** means the finding must be resolved before the repo (or subtree) can go public. FAIL findings can never be waived — they must be encrypted, template-ized, or redacted. FAIL findings live in category A (Secrets):

- Private key markers (`BEGIN RSA PRIVATE KEY`, `BEGIN OPENSSH PRIVATE KEY`, and similar PEM headers).
- AWS access key IDs (the 20-character `AKIA…` pattern).
- API key, token, or password literals — any assignment where the right-hand side is a real credential string rather than a variable reference or placeholder.
- High-entropy base64 strings on lines that contain words like `key`, `token`, `secret`, or `password`.
- Connection strings that embed credentials in the URL (e.g. `postgres://user:pass@host`).
- Literal bearer tokens.

Template expressions (`{{ ... }}`), environment-variable references (`$VAR`, `${VAR}`), and placeholder values (`YOUR_KEY_HERE`, `changeme`, `xxx`) are excluded from all category A checks.

**WARN** means the finding is a candidate for leakage but may be intentional or safe in context. WARN findings can be accepted with a documented reason; they block publishing only if left unacknowledged. WARN findings live in categories B, C, and D:

- **B — PII**: real email addresses (excluding `@example.com`, `noreply@`, and `Co-Authored-By` git trailers), numeric service or chat IDs in config context, and author identity in tracked package manifests.
- **C — Infrastructure**: Tailscale/CGNAT IPs (the `100.64.0.0/10` range), publicly routable IPs outside well-known DNS addresses, and internal hostnames found in SSH configs or deploy scripts.
- **D — Local repo refs**: absolute `/Users/<name>/` or `/home/<name>/` paths, and home-subdirectory refs that would not exist on another machine (e.g. `~/Dropbox/`, `~/Docker/`).

There is also severity **INFO** (e.g. a personal name in a `.gitconfig` file tracked in a dotfiles repo). INFO findings are shown for awareness and can be auto-waived.

### Step 2 — Understand author metadata as a special WARN

Author identity in manifests (`plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, `README`, `CITATION.cff`) is check B4 and deserves extra attention. The scanner never infers who the intended public author is from `git config` or past commits — your local git identity may be your real name, not the handle you want published.

When you run `/lazy-repo.mark-public` or `/lazy-guard.check-public`, every B4 hit stays WARN until you tell the skill your intended public identity. Once you confirm it, the skill records it as `public_author` in `.guard-waivers.json`. From that point on, any B4 match equal to your declared public name or email automatically flips to WAIVED — no per-file waiver entry is needed. If `public_author` is absent from the file, every B4 match stays WARN on every subsequent scan until you set it.

### Step 3 — Understand how waivers work

Accepted exceptions live in `.guard-waivers.json` at the repo root. Run `/lazy-repo.mark-public` or `/lazy-guard.check-public` and select the waiver option for each WARN finding — the skill creates and manages this file. Each waiver entry records:

- `check` — the specific check ID (e.g. `B1`, `D2`) or `*` for all checks.
- `scope` — a file-path glob restricting which files the waiver covers.
- `pattern` — a regex that must match the finding text.
- `reason` — a human-readable justification you provide.
- `added` — the date the waiver was accepted.
- `expires` — optional; the waiver is ignored after this date.

The file also supports a `global_skip_paths` array for vendored or third-party directories you want excluded from every scan entirely.

A waiver matches a finding only when all four conditions hold (check, scope, pattern, and expiry). The scanner never silently applies a waiver that misses any condition.

`.guard-waivers.json` also acts as the opt-in switch for the pre-commit hook. The hook only runs in repos that have this file. Creating the file — even with an empty `waivers` array — enables pre-commit scanning on every future commit. Deleting it disables the hook.

### Step 4 — Understand public scopes (subtree-public mode)

If only part of your repo should be treated as a public surface (for example, a `claude/**` subtree that gets published while the rest of the vault stays private), `.guard-waivers.json` supports a top-level `public_scopes` array of repo-relative globs. When `public_scopes` is set, the scanner and the pre-commit hook consider only files matching at least one glob; everything else is implicitly private and ignored.

In subtree-public mode, `/lazy-repo.mark-public` skips the GitHub-visibility flip entirely. The repo stays private; the guard just protects the declared paths on every commit.

### Step 5 — Understand credential isolation (the separate safety rule)

Separate from the FAIL/WARN taxonomy is a hard constraint that applies to every action the AI takes, not just scans: authentication credentials, OAuth tokens, API keys in auth stores, and session files (under `~/.claude/`, `~/.config/`, and similar) must never be read, listed, copied, or transferred between machines. Auth is per-machine and the user handles it interactively. This rule is always-loaded — it applies before any scan runs and cannot be waived.

## After you're done

With the taxonomy in hand, you can interpret any `/lazy-guard.check-public` report without guessing why a finding is FAIL versus WARN. When you are ready to publish, run `/lazy-repo.mark-public` — it walks through the full audit, resolves findings with you, writes `.guard-waivers.json`, and optionally flips GitHub visibility. After publishing, the pre-commit hook re-runs the scan on every commit automatically, covering only the files in `public_scopes` if you set that field.

## Taxonomy at a glance

```mermaid
%%{init: {'themeVariables':{'lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
%% intent: decision tree for lazycortex-core public-repo leak taxonomy — finding category drives FAIL vs WARN severity and waiver eligibility
flowchart TD
  findingCategory{Finding category?}
  credIsolation{Credential isolation issue?}

  secretsType{Secret type?}
  piiType{PII type?}
  infraType{Infrastructure ref?}
  localPathType{Local path ref?}

  secretsFail[FAIL — secrets: must encrypt, template, or redact — never waivable]
  piiAuthorMatch{Matches public_author?}
  piiAutoWaive[WARN B4 — author metadata auto-waived via public_author]
  piiWaivable[WARN — PII: waivable with documented reason]
  infraWaivable[WARN — infrastructure ref: waivable with documented reason]
  localPathWaivable[WARN — local path ref: waivable with documented reason]
  credNeverTransfer[BLOCKED — auth tokens and session files under ~/.claude/ or ~/.config/ must never be read, copied, or transferred between machines — applies to all AI actions — cannot be waived]

  findingCategory -->|A - secrets| secretsType
  findingCategory -->|B - PII| piiType
  findingCategory -->|C - infrastructure| infraType
  findingCategory -->|D - local paths| localPathType
  credIsolation -->|credential isolation triggered| credNeverTransfer

  secretsType -->|private keys, AWS keys, API tokens, connection strings, bearer tokens| secretsFail

  piiType -->|B4 - author metadata in manifests| piiAuthorMatch
  piiType -->|real emails, service IDs| piiWaivable
  piiAuthorMatch -->|yes| piiAutoWaive
  piiAuthorMatch -->|no| piiWaivable

  infraType -->|Tailscale IPs, public IPs, internal hostnames| infraWaivable

  localPathType -->|/Users/, /home/, ~/Dropbox/ refs| localPathWaivable

  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef error fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px

  class findingCategory guard
  class credIsolation guard
  class secretsType guard
  class piiType guard
  class infraType guard
  class localPathType guard
  class piiAuthorMatch guard
  class secretsFail error
  class credNeverTransfer error
  class piiAutoWaive success
  class piiWaivable success
  class infraWaivable success
  class localPathWaivable success
```
