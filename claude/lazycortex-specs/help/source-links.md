---
chapter_type: block
summary: Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
last_regen: 2026-06-23
diagram_spec:
  anchor: "How the three skills compose"
  request: "Show how spec.resolve-repo, spec.resolve-dependency, and spec.source-url call each other: spec.source-url calls spec.resolve-repo to get RepoInfo; spec.resolve-dependency calls spec.resolve-repo internally for internal-product and internal-repo entries; spec.resolve-repo reads lazy.settings.json[repos] and inspects the git remote. Output is a URL or a dep record."
source_skills:
  - spec.resolve-repo
  - spec.resolve-dependency
  - spec.source-url
---
# Source links — repos, dependencies, and forge-correct URLs

When a spec document links to source code or records a dependency on another product, it needs to know which git forge hosts the code and what path scheme that forge uses. GitHub uses `/blob/<branch>/<path>`, GitLab uses `/-/blob/<branch>/<path>`, Bitbucket uses `/src/<branch>/<path>`, and the list goes on. Baking that knowledge into every skill that emits a link is fragile; the source-links block centralises it in three focused primitives so the rest of the spec system never has to think about forge differences.

`/spec.resolve-repo` is the foundation: given a repo key from your settings, it reads the git remote, normalises the URL, and identifies the forge. `/spec.source-url` sits above it and builds one correct URL for any file or directory in that repo, handling branch pinning transparently. `/spec.resolve-dependency` sits beside them and turns the three flavours of dependency entry — internal product, internal repo, external — into a ready-to-use record containing both a spec wikilink and a dev URL.

## When you'd use this

- A skill such as `/spec.create-from-code` or `/spec.sync-with-code` aborts with a forge or repo error, and you need to diagnose or fix the registration.
- You're looking at a spec document with a broken or stale source link and want to understand where the configuration gap is.
- You've registered a product hosted on a self-hosted GitLab or Gitea instance and want to confirm the forge override is resolving correctly.
- You're running `/spec.product-config` and it asks about dependencies — the wizard calls `/spec.resolve-dependency` to classify each entry, so understanding the three entry shapes (`product:`, `repo:`, `external:`) helps you answer the wizard accurately.
- A spec doc's `## Sources` section has incorrect or missing links after a branch merge and you need to trace which part of the resolution chain produced the wrong URL.

## How it fits together

Everything flows through `/spec.resolve-repo`. You give it a repo key — a string you chose when you ran `/spec.product-config` to register the repo, such as `backend` or `shared`. The skill reads that record from `lazy.settings.json[repos]`, runs `git remote get-url origin` on the local checkout, normalises the URL from SSH to HTTPS if needed, and identifies the forge by matching the hostname against the known-forges table. What comes back is a `RepoInfo` record: `local_path`, `branch`, `remote_url`, `host`, `owner`, `repo`, `forge`, and `base_url`. Each skill run caches the record for its duration, so building hundreds of source URLs for a large codebase doesn't shell out on every call.

`/spec.source-url` calls `/spec.resolve-repo` first, then picks up the forge key and looks up the URL template for the requested kind — `blob` for a file link, `tree` for a directory link. It substitutes `base_url`, branch, and path into the template and returns the complete URL. When the calling doc pins a branch via `spec_source_branches`, you pass it as the optional `branch` argument and the URL points at the feature branch instead of the default. The skill is stateless and idempotent: same inputs, same URL, every time.

`/spec.resolve-dependency` handles the dependency side. A product's `dependencies` array in `lazy.settings.json` accepts three entry shapes. A `product:` entry names another product by compound key; the skill looks that product up, calls `/spec.resolve-repo` on its source repo, and returns a wikilink to its design doc plus a `dev_link` pointing at the repo root. A `repo:` entry names a repo key directly; the skill resolves it the same way and finds whichever product declares that repo as its source. An `external:` entry already has `spec_url` and `dev_url` spelled out — the skill validates the fields are present and returns them as-is. The output is always `{kind, spec_link, dev_link, local_spec_path?}` — one consistent shape regardless of entry flavour, which is what callers like `/spec.product-config` import classification expect.

## Common adjustments

**Registering a repo** — if `/spec.resolve-repo` aborts because a key is not registered, run `/spec.product-config` to add or edit the product that owns that repo. The wizard writes `lazy.settings.json[repos][<key>]` with `local_path` and `branch`. Do not edit the settings file by hand.

**Adding a forge override for a self-hosted instance** — if the hostname is not in the known-forges table (for example, `gitlab.internal.company.example`), `/spec.resolve-repo` aborts with a message naming the missing key. Run `/spec.product-config`, find the repo record, and set `forge` to one of the supported keys (`github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`) — whichever matches the instance's URL scheme. The skill writes the override.

**Changing the default branch** — the `branch` field in the repo record controls which branch source URLs default to. If your project has moved its default branch, run `/spec.product-config` to update the record. Existing spec docs that had the old branch pinned via `spec_source_branches` are reconciled by `/spec.finalize-branch` once the old branch merges or is deleted.

**Adding or editing a product dependency** — run `/spec.product-config` in edit mode to extend the `dependencies` array. The wizard accepts all three entry shapes (`product:`, `repo:`, `external:`) interactively and calls `/spec.resolve-dependency` to validate each entry before writing. You do not edit the `products` section by hand.

## How the three skills compose

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  callerSourceUrl[spec.source-url]
  callerResolveDep[spec.resolve-dependency]
  resolveRepo[spec.resolve-repo]
  readSettings[Read lazy.settings.json repos]
  inspectRemote[Inspect git remote]
  entryType{Entry type?}
  buildRepoInfo[Build RepoInfo]
  returnUrl[Return URL]
  returnDepRecord[Return dep record]

  callerSourceUrl -->|calls| resolveRepo
  callerResolveDep -->|calls internally| entryType
  entryType -->|internal-product or internal-repo| resolveRepo
  entryType -->|external| returnDepRecord
  resolveRepo -->|reads| readSettings
  resolveRepo -->|inspects| inspectRemote
  readSettings -->|provides repos map| buildRepoInfo
  inspectRemote -->|provides remote URL| buildRepoInfo
  buildRepoInfo -->|returns RepoInfo| callerSourceUrl
  callerSourceUrl -->|produces| returnUrl
  buildRepoInfo -->|returns RepoInfo| callerResolveDep
  callerResolveDep -->|produces| returnDepRecord

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef store fill:#5f3a1e,stroke:#e2904a,color:#fff

  class callerSourceUrl entry
  class callerResolveDep entry
  class entryType guard
  class resolveRepo action
  class readSettings store
  class inspectRemote action
  class buildRepoInfo action
  class returnUrl success
  class returnDepRecord success
```

## See also

- [install-and-audit](install-and-audit.md) — register products and repos via `/spec.product-config`, which is the only writer for the settings this block reads.
- [code-sync](code-sync.md) — `/spec.sync-with-code` and `/spec.finalize-branch` are the primary callers of `/spec.source-url` in normal operation.
- [asset-to-release](walkthroughs/asset-to-release.md) — walkthrough that exercises source-link generation as part of the full gate journey.
