'use strict';

const RELOADER_VERSION = '2.4.0';

const { Plugin, PluginSettingTab, Setting, Platform } = require('obsidian');

// Node `fs` / `path` are desktop-only. On iOS/Android `require('fs')` is
// either absent or a stub. Guard the import so the file loads cleanly on
// mobile and we run in metadataCache-only mode there.
let fs = null;
let path = null;
try {
  fs = require('fs');
  path = require('path');
} catch (e) {
  // mobile — handled via Platform.isMobile branches below.
}

const TARGET_PLUGIN_ID = 'obsidian-icon-folder';
const FILE_EXPLORER_ID = 'file-explorer';
const DEBOUNCE_MS = 250;

// Vault-wide fs.watch for folder-notes (desktop only) — fires on disk write,
// bypassing Obsidian's metadataCache polling cadence. On Dropbox-synced vaults
// the cache can lag many seconds (sometimes until restart) before re-parsing
// externally modified .md files; events that depend on it (folder-icon repaint
// after an agent stage flip) feel broken. fs.watch on macOS uses FSEvents so
// it picks up writes within ~100ms regardless of who wrote them.
const MD_WATCH_DEBOUNCE_MS = 80;
const MD_WATCH_EXCLUDED = new Set(['.obsidian', '.git', '.claude', '.githooks', 'node_modules']);

const FOLDER_NOTES_PLUGIN_ID = 'folder-notes';
const FOLDER_NOTE_TEMPLATE_DEFAULT = '{{folder_name}}';

// Notebook Navigator owns its own folder-note frontmatter pipeline (its
// `folderNoteMetadataAdapter` reads `frontmatterIconField` / `frontmatterColorField`
// per file and paints folder icons natively). The reloader only needs to push the
// three settings keys that align NB's reader with Iconize's namespace —
// `useFrontmatterMetadata`, `frontmatterIconField`, `frontmatterColorField` —
// nothing folder-side, no data-mirroring.
const NB_PLUGIN_ID = 'notebook-navigator';

// Vault-relative paths — accepted by Obsidian's adapter on every platform.
const DATA_VAULT_PATH = `.obsidian/plugins/${TARGET_PLUGIN_ID}/data.json`;
const FN_DATA_VAULT_PATH = `.obsidian/plugins/${FOLDER_NOTES_PLUGIN_ID}/data.json`;
const NB_DATA_VAULT_PATH = `.obsidian/plugins/${NB_PLUGIN_ID}/data.json`;

const RESERVED_KEYS = new Set(['settings', 'rules', 'recentlyUsedIcons']);

// Reloader's own settings — persisted to .obsidian/plugins/iconize-reloader/data.json
// via Obsidian's Plugin.loadData / saveData. Field names default to the LazyCortex
// `iconize_*` namespace; consumers who want to align with Iconize's stock `icon` /
// `iconColor` keys can change them here, and `enforceIconizeSettings` will push the
// chosen names into Iconize's own settings on load.
const DEFAULT_SETTINGS = Object.freeze({
  iconFieldName: 'iconize_icon',
  colorFieldName: 'iconize_color',
  folderNotePropagation: true,
  enforceIconizeSettings: true,
});

// ---------------------------------------------------------------------------
// data.json + Folder Notes plugin data — adapter-based, single platform-agnostic
// I/O surface. Returns null on read failure (file absent, malformed JSON, etc.).
// ---------------------------------------------------------------------------

async function readIconizeData(adapter) {
  try {
    const raw = await adapter.read(DATA_VAULT_PATH);
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

async function writeIconizeData(adapter, obj) {
  await adapter.write(DATA_VAULT_PATH, JSON.stringify(obj, null, 2) + '\n');
}

// Notebook Navigator data.json — surgical settings-only access. Returns null when
// NB is not installed or its data.json is unreadable.
async function readNbData(adapter) {
  try {
    const raw = await adapter.read(NB_DATA_VAULT_PATH);
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

async function writeNbData(adapter, obj) {
  await adapter.write(NB_DATA_VAULT_PATH, JSON.stringify(obj, null, 2) + '\n');
}

// Upsert `{folderPath: {iconName, iconColor?}}`. Returns true when a write
// happened, false on no-op or guarded write. Async because the adapter is.
async function upsertFolderEntry(adapter, folderPath, iconName, iconColor) {
  const data = await readIconizeData(adapter);
  if (data === null) return false;
  if (RESERVED_KEYS.has(folderPath)) return false;
  const existing = data[folderPath];
  const entry = { iconName };
  if (iconColor) entry.iconColor = iconColor;
  if (existing && existing.iconName === entry.iconName && existing.iconColor === entry.iconColor) {
    return false;
  }
  data[folderPath] = entry;
  await writeIconizeData(adapter, data);
  return true;
}

// Remove `folderPath`. Returns true when a write happened.
async function removeFolderEntry(adapter, folderPath) {
  const data = await readIconizeData(adapter);
  if (data === null) return false;
  if (RESERVED_KEYS.has(folderPath)) return false;
  if (!(folderPath in data)) return false;
  delete data[folderPath];
  await writeIconizeData(adapter, data);
  return true;
}

// Read the Folder Notes community plugin's configured folder-note name template.
// Returns the template string (e.g. '{{folder_name}}' or 'index') or null if
// the plugin is missing, disabled, or its data.json is unreadable.
async function readFolderNoteTemplate(adapter) {
  try {
    const raw = await adapter.read(FN_DATA_VAULT_PATH);
    const data = JSON.parse(raw);
    return (typeof data.folderNoteName === 'string' && data.folderNoteName)
      ? data.folderNoteName
      : FOLDER_NOTE_TEMPLATE_DEFAULT;
  } catch (e) {
    return null;
  }
}

// Given a folder-note template and a vault-relative file path, decide whether
// the file is the folder-note for its parent folder. Supports the
// `{{folder_name}}` token plus literal filenames. Returns the folder's
// vault-relative path when the file IS a folder-note, or null otherwise.
function folderNoteTarget(template, vaultRelPath) {
  if (!template) return null;
  // vault root files cannot be folder-notes (no parent folder).
  const lastSlash = vaultRelPath.lastIndexOf('/');
  if (lastSlash < 0) return null;
  const parent = vaultRelPath.slice(0, lastSlash);      // 'Projects/Foo'
  const file = vaultRelPath.slice(lastSlash + 1);       // 'Foo.md'
  if (!file.endsWith('.md')) return null;
  const stem = file.slice(0, -3);                       // 'Foo'

  const parentBasename = parent.split('/').pop();       // 'Foo'
  const expected = template.replace(/\{\{\s*folder_name\s*\}\}/g, parentBasename);
  return stem === expected ? parent : null;
}

// Minimal disk-side frontmatter parser — extracts the configured icon / color
// fields from the leading `---`-fenced block. Used by the desktop fs.watch path
// so we don't have to wait for Obsidian's metadataCache to re-parse the file.
// Field names are passed in (configurable via the reloader's settings tab) so
// consumers can align with Iconize's own `icon` / `iconColor` namespace if they
// prefer. Desktop only; never invoked on mobile (no `fs`).
function readIconFieldsFromDisk(absPath, iconFieldName, colorFieldName) {
  let raw;
  try {
    raw = fs.readFileSync(absPath, 'utf8');
  } catch (e) {
    return { icon: null, color: null };
  }
  if (!raw.startsWith('---\n')) return { icon: null, color: null };
  const end = raw.indexOf('\n---', 4);
  if (end < 0) return { icon: null, color: null };
  const block = raw.slice(4, end);
  let icon = null, color = null;
  for (const line of block.split('\n')) {
    const m = /^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$/.exec(line);
    if (!m) continue;
    const k = m[1];
    let v = m[2].trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (k === iconFieldName) icon = v || null;
    else if (k === colorFieldName) color = v || null;
  }
  return { icon, color };
}

class IconizeReloaderPlugin extends Plugin {
  async onload() {
    await this.loadSettings();
    const adapter = this.app.vault.adapter;
    const isDesktop = !Platform.isMobile;
    const basePath = isDesktop && adapter && adapter.basePath ? adapter.basePath : null;
    if (isDesktop && !basePath) {
      console.warn('[iconize-reloader] desktop without basePath; fs.watch path inert');
    }

    // Absolute paths are needed only by Node fs/fs.watch on desktop.
    const absDataFile = isDesktop && basePath && path
      ? path.join(basePath, '.obsidian', 'plugins', TARGET_PLUGIN_ID, 'data.json')
      : null;
    const absPluginDir = isDesktop && basePath && path
      ? path.join(basePath, '.obsidian', 'plugins', TARGET_PLUGIN_ID)
      : null;
    const absFolderNotesDir = isDesktop && basePath && path
      ? path.join(basePath, '.obsidian', 'plugins', FOLDER_NOTES_PLUGIN_ID)
      : null;

    let lastMtime = 0;
    if (absDataFile) {
      try { lastMtime = fs.statSync(absDataFile).mtimeMs; } catch (e) { /* not present yet */ }
    }

    // Re-entrancy: when we write data.json for folder entries, we record the
    // mtime here so the desktop external-change watcher can distinguish
    // self-writes from Iconize-writes / user-click writes. On mobile this
    // value stays 0 forever — there's no fs.watch to suppress.
    let lastSelfWriteMtime = 0;

    // Bump after every successful write. Desktop-only; on mobile we have
    // nothing to suppress.
    const bumpSelfWriteMtime = () => {
      if (!absDataFile || !fs) return;
      try { lastSelfWriteMtime = fs.statSync(absDataFile).mtimeMs; } catch (e) { /* file vanished */ }
    };
    // Expose for `_enforceIconizeSettings`, which writes Iconize's `data.json`
    // outside the onload closure (e.g. from the settings tab).
    this._bumpSelfWriteMtime = bumpSelfWriteMtime;

    // Re-assert Iconize's frontmatter settings now that we can suppress the
    // self-write echo. Aligns Iconize's own file-side frontmatter feature with
    // the same field names this plugin scans for folder-side propagation, so a
    // single `iconize_*` namespace in note frontmatter drives both layers.
    // Notebook Navigator (when present) gets the same field names pushed into
    // its own settings — it owns its folder-note frontmatter pipeline natively,
    // so this is settings-only, no data mirroring.
    if (this.settings.enforceIconizeSettings) {
      try {
        await this._enforceIconizeSettings();
      } catch (e) {
        console.error('[iconize-reloader] enforceIconizeSettings failed', e);
      }
      try {
        await this._enforceNotebookNavigatorSettings();
      } catch (e) {
        console.error('[iconize-reloader] enforceNotebookNavigatorSettings failed', e);
      }
    }

    // Folder-note template (read once, refreshed on Folder Notes settings change).
    let folderNoteTemplate = await readFolderNoteTemplate(adapter);
    if (folderNoteTemplate === null) {
      console.warn('[iconize-reloader] folder-notes plugin not installed/disabled — folder-icon propagation inert');
    }

    // Extract the configured icon / color fields from a file's cached frontmatter.
    // Field names come from `this.settings`; defaults are `iconize_icon` /
    // `iconize_color`. Returns { icon, color } with nullable fields, or both null
    // when the file has no frontmatter at all.
    const extractIconFields = (file) => {
      const cache = this.app.metadataCache.getFileCache(file);
      const fm = cache && cache.frontmatter;
      if (!fm) return { icon: null, color: null };
      const iconKey = this.settings.iconFieldName;
      const colorKey = this.settings.colorFieldName;
      return {
        icon: typeof fm[iconKey] === 'string' ? fm[iconKey] : null,
        color: typeof fm[colorKey] === 'string' ? fm[colorKey] : null,
      };
    };

    // Mirror our folder-entry write into Iconize's in-memory `data` object.
    // Necessary because Iconize's own frontmatter-feature handler calls its
    // saveData() after each .md save — which stomps our on-disk write by
    // serializing its stale in-memory state back to data.json. Keeping both
    // representations in sync means whichever writer runs second still ends
    // up with the correct folder entry.
    const mirrorFolderEntryToMemory = (folderPath, iconName, iconColor) => {
      const iconize = this.app.plugins.plugins[TARGET_PLUGIN_ID];
      if (!iconize || typeof iconize.data !== 'object' || iconize.data === null) return;
      if (RESERVED_KEYS.has(folderPath)) return;
      if (iconName) {
        const entry = { iconName };
        if (iconColor) entry.iconColor = iconColor;
        iconize.data[folderPath] = entry;
      } else {
        delete iconize.data[folderPath];
      }
    };

    // Watchdog pass: re-assert our desired folder-entry state after any
    // concurrent write has settled. Iconize's `removeFolderIcon` (fires on
    // vault.delete for every deleted .md) calls `saveIconFolderData()` async
    // with its own `this.data` that still contains the folder entry we just
    // cleared. Adapter writes are FIFO, so Iconize's stomp lands after our
    // sync write — and our `refreshTree`'s `loadData` re-absorbs the stale
    // state into `iconize.data`. This watchdog re-writes disk + memory once
    // more after ~500ms to guarantee our state is final. Same pattern covers
    // applyFolderNote writes (color edits) which hit a similar race.
    //
    // `desired` is either { iconName, iconColor? } for an upsert target or
    // null to assert the entry must be absent.
    const WATCHDOG_DELAY_MS = 500;
    const scheduleWatchdog = (target, desired) => {
      setTimeout(async () => {
        const data = await readIconizeData(adapter);
        if (data === null) return;
        const existing = data[target];
        const matches =
          (desired === null && !(target in data)) ||
          (desired !== null && existing &&
            existing.iconName === desired.iconName &&
            existing.iconColor === desired.iconColor);
        if (matches) return;
        console.log('[iconize-reloader] watchdog re-asserting', target, '→', desired);
        let wrote;
        if (desired === null) {
          wrote = await removeFolderEntry(adapter, target);
        } else {
          wrote = await upsertFolderEntry(adapter, target, desired.iconName, desired.iconColor);
        }
        if (wrote) {
          bumpSelfWriteMtime();
          mirrorFolderEntryToMemory(target, desired ? desired.iconName : null, desired ? desired.iconColor : null);
          scheduleSelfRefresh();
        }
      }, WATCHDOG_DELAY_MS);
    };

    // Apply a folder-note's current frontmatter to data.json. No-op when the
    // file isn't a folder-note or when Folder Notes plugin is missing.
    // Returns true when a write happened (caller may want to trigger refresh).
    const applyFolderNote = async (file) => {
      if (!this.settings.folderNotePropagation) return false;
      if (!folderNoteTemplate) return false;
      const target = folderNoteTarget(folderNoteTemplate, file.path);
      if (!target) return false;
      const { icon, color } = extractIconFields(file);
      let wrote = false;
      if (icon) {
        wrote = await upsertFolderEntry(adapter, target, icon, color);
      } else {
        wrote = await removeFolderEntry(adapter, target);
      }
      if (wrote) {
        bumpSelfWriteMtime();
        mirrorFolderEntryToMemory(target, icon, color);
        const desired = icon ? (color ? { iconName: icon, iconColor: color } : { iconName: icon }) : null;
        scheduleWatchdog(target, desired);
        return true;
      }
      return false;
    };

    // On folder-note deletion or rename-away, drop the folder key.
    // Returns true when a write happened.
    const dropFolderNote = async (oldPath) => {
      if (!this.settings.folderNotePropagation) return false;
      if (!folderNoteTemplate) return false;
      const target = folderNoteTarget(folderNoteTemplate, oldPath);
      if (!target) return false;
      const wrote = await removeFolderEntry(adapter, target);
      if (wrote) {
        bumpSelfWriteMtime();
        mirrorFolderEntryToMemory(target, null, null);
        scheduleWatchdog(target, null);
        return true;
      }
      return false;
    };

    // Expose for testing (set before any async gap).
    this.applyFolderNote = applyFolderNote;
    this.dropFolderNote = dropFolderNote;

    let debounceTimer = null;
    let running = false;

    // Schedule a refreshTree after one of our own writes. Needed because the
    // fs.watch-based onChange suppresses self-writes (to avoid loops), but
    // Iconize's in-memory `data` is now stale relative to the file we just
    // wrote. Without a direct call, the file-explorer shows no new icon until
    // something else (user click, external edit, app reload) triggers a
    // refresh.
    const scheduleSelfRefresh = () => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => { debounceTimer = null; refreshTree(); }, DEBOUNCE_MS);
    };

    // Refresh iconize WITHOUT disabling it. Sequence:
    //   1. Pull fresh data.json into iconize's in-memory `data` via its own
    //      Plugin.loadData() — same shape iconize itself uses.
    //   2. Strip existing `.iconize-icon` DOM nodes from every file-explorer
    //      tree-item. Required because addAll's `children.length === 2 || === 1`
    //      check fails for folders that already have an icon (folder baseline
    //      = 2 children: collapse-indicator + inner-title; with icon = 3, check
    //      fails, painting skipped). Stripping returns baseline to 2 (folder)
    //      / 1 (file) so the check passes.
    //   3. Clear iconize.registeredFileExplorers — otherwise addAll's outer
    //      loop skips already-registered explorers (it's designed for
    //      first-mount, not re-paint).
    //   4. Trigger workspace `layout-change` — re-paints file-explorer, tabs,
    //      and title icons from the now-fresh `data`. No window reload, no
    //      plugin toggle, no race with iconize's onunload writeback.
    const refreshTree = async () => {
      if (running) return;
      running = true;
      try {
        const iconize = this.app.plugins.plugins[TARGET_PLUGIN_ID];
        if (iconize && typeof iconize.loadData === 'function') {
          const fresh = await iconize.loadData();
          if (fresh && typeof iconize.data === 'object' && iconize.data !== null) {
            for (const k of Object.keys(iconize.data)) delete iconize.data[k];
            Object.assign(iconize.data, fresh);
          } else {
            iconize.data = fresh;
          }
        }

        if (iconize) {
          let stripped = 0;
          const leaves = this.app.workspace.getLeavesOfType(FILE_EXPLORER_ID);
          for (const leaf of leaves) {
            const fileItems = leaf.view && leaf.view.fileItems;
            if (!fileItems) continue;
            for (const p of Object.keys(fileItems)) {
              const item = fileItems[p];
              const titleEl = item && (item.selfEl || item.titleEl || item.el);
              if (!titleEl) continue;
              const existing = titleEl.querySelector(':scope > .iconize-icon');
              if (existing) { existing.remove(); stripped++; }
            }
          }

          if (iconize.registeredFileExplorers && typeof iconize.registeredFileExplorers.clear === 'function') {
            iconize.registeredFileExplorers.clear();
          }

          // Emit layout-change rather than calling iconize.handleChangeLayout
          // directly: Folder Notes also listens to layout-change and uses it
          // to re-apply `has-folder-note` / `is-folder-note` CSS classes to
          // newly-created folder-notes. Calling iconize's method in isolation
          // skipped Folder Notes' re-eval pass, leaving externally-created
          // folder-notes visible as siblings until the next app reload.
          this.app.workspace.trigger('layout-change');
          console.log('[iconize-reloader] refresh done; stripped', stripped, 'existing icon nodes');
        }
      } catch (e) {
        console.error('[iconize-reloader] refresh failed', e);
      } finally {
        running = false;
      }
    };

    // Folder-note frontmatter events — metadataCache.changed fires on every
    // .md save, including the first parse after vault open. We filter inside
    // applyFolderNote via folderNoteTarget. This is the cross-platform path —
    // works identically on desktop and mobile.
    const onChangedFile = (file) => {
      if (!(file && file.path && file.path.endsWith('.md'))) return;
      applyFolderNote(file)
        .then((wrote) => { if (wrote) scheduleSelfRefresh(); })
        .catch((e) => console.error('[iconize-reloader] applyFolderNote failed', e));
    };
    this.registerEvent(this.app.metadataCache.on('changed', onChangedFile));

    // Nudge Folder Notes' CSS classes onto the folder + folder-note elements,
    // and KEEP them on. Two failure modes are covered:
    //   (1) File-explorer hasn't rendered the new folder/file yet — poll for
    //       both elements up to 6s in 200ms ticks. (Heavy vaults — many
    //       plugins, large file counts — can lag well past the previous 1.5s
    //       budget, which left the classes never applied at all.)
    //   (2) Folder Notes' `updateCSSClassesForFolder` runs while its own
    //       `getFolderNote(folder)` still returns null (folder not yet a
    //       TFolder in the vault index, or children not linked). In that
    //       path Folder Notes calls `removeCSSClassFromFileExplorerEL` and
    //       STRIPS the classes we just applied (folder-notes 1.8.x:
    //       main.js ~L2099). A short-lived class-attribute MutationObserver
    //       on each element reverts any strip immediately. Observers
    //       disconnect once Folder Notes' state catches up — signalled by
    //       `metadataCache.changed` for the new file — or after a hard cap.
    //       This avoids re-emitting `layout-change` in a loop, which would
    //       re-iterate every folder dozens of times in a heavy vault.
    const FN_FIND_MAX = 30;
    const FN_FIND_DELAY = 200;
    const FN_OBSERVE_HARD_CAP_MS = 6000;
    const FN_OBSERVE_STABLE_MS = 1500;
    const nudgeFolderNoteCSS = (folderPath, filePath) => {
      const startedAt = Date.now();
      let folderEl = null;
      let fileEl = null;
      let folderObs = null;
      let fileObs = null;
      let stableTimer = null;
      let hardCapTimer = null;
      let metaRef = null;
      let done = false;

      const cleanup = () => {
        if (done) return;
        done = true;
        if (folderObs) folderObs.disconnect();
        if (fileObs) fileObs.disconnect();
        if (stableTimer) clearTimeout(stableTimer);
        if (hardCapTimer) clearTimeout(hardCapTimer);
        if (metaRef) this.app.metadataCache.offref(metaRef);
      };

      const armStable = () => {
        if (stableTimer) clearTimeout(stableTimer);
        stableTimer = setTimeout(cleanup, FN_OBSERVE_STABLE_MS);
      };

      const ensureFolder = () => {
        if (folderEl && !folderEl.classList.contains('has-folder-note')) {
          folderEl.classList.add('has-folder-note');
          armStable();
        }
      };
      const ensureFile = () => {
        if (fileEl && !fileEl.classList.contains('is-folder-note')) {
          fileEl.classList.add('is-folder-note');
          armStable();
        }
      };

      const onFound = () => {
        ensureFolder();
        ensureFile();

        folderObs = new MutationObserver(ensureFolder);
        folderObs.observe(folderEl, { attributes: true, attributeFilter: ['class'] });
        fileObs = new MutationObserver(ensureFile);
        fileObs.observe(fileEl, { attributes: true, attributeFilter: ['class'] });

        armStable();
        const remaining = Math.max(0, FN_OBSERVE_HARD_CAP_MS - (Date.now() - startedAt));
        hardCapTimer = setTimeout(cleanup, remaining);

        metaRef = this.app.metadataCache.on('changed', (file) => {
          if (file && file.path === filePath) cleanup();
        });
      };

      let attempts = 0;
      const find = () => {
        if (done) return;
        folderEl = document.querySelector(`.nav-folder-title[data-path="${CSS.escape(folderPath)}"]`);
        fileEl = document.querySelector(`.nav-file-title[data-path="${CSS.escape(filePath)}"]`);
        if (folderEl && fileEl) {
          onFound();
        } else if (++attempts < FN_FIND_MAX) {
          setTimeout(find, FN_FIND_DELAY);
        }
      };
      find();
    };

    // Create / Rename / Delete — vault events are platform-agnostic.
    this.registerEvent(this.app.vault.on('create', (file) => {
      if (!file || !file.path || !file.path.endsWith('.md')) return;
      if (!folderNoteTemplate) return;
      const target = folderNoteTarget(folderNoteTemplate, file.path);
      if (target) {
        scheduleSelfRefresh();
        nudgeFolderNoteCSS(target, file.path);
      }
    }));

    this.registerEvent(this.app.vault.on('rename', (file, oldPath) => {
      (async () => {
        let wrote = false;
        if (oldPath && oldPath.endsWith('.md')) wrote = (await dropFolderNote(oldPath)) || wrote;
        if (file && file.path && file.path.endsWith('.md')) wrote = (await applyFolderNote(file)) || wrote;
        if (wrote) scheduleSelfRefresh();
      })().catch((e) => console.error('[iconize-reloader] rename handler failed', e));
    }));

    this.registerEvent(this.app.vault.on('delete', (file) => {
      if (!(file && file.path && file.path.endsWith('.md'))) return;
      dropFolderNote(file.path)
        .then((wrote) => { if (wrote) scheduleSelfRefresh(); })
        .catch((e) => console.error('[iconize-reloader] delete handler failed', e));
    }));

    // Initial scan: iterate every markdown file once so pre-existing folder-note
    // frontmatter is reflected in data.json. Defer one tick so metadataCache is
    // populated. Trigger a single refreshTree after the sweep when any write
    // happened — otherwise Iconize's in-memory `data` stays stale.
    const initialScan = async () => {
      if (!folderNoteTemplate) return;
      const mdFiles = this.app.vault.getMarkdownFiles();
      let wrote = false;
      for (const file of mdFiles) {
        wrote = (await applyFolderNote(file)) || wrote;
      }
      if (wrote) scheduleSelfRefresh();
    };
    // Expose for the settings tab — invoked after a field-name change so the
    // worker re-walks every md file under the new namespace, replacing any
    // entries written under the previous names.
    this._initialScan = initialScan;
    this._scheduleSelfRefresh = scheduleSelfRefresh;

    this.app.workspace.onLayoutReady(() => {
      setTimeout(() => {
        initialScan().catch((e) => console.error('[iconize-reloader] initialScan failed', e));
      }, 100);
    });

    // -------------------------------------------------------------------
    // Desktop-only fs.watch surface — three watchers + the disk-driven
    // folder-note apply path. On mobile (`Platform.isMobile === true`) all
    // of this is gated off; the metadataCache + vault.create/rename/delete
    // listeners above keep the folder-icon bridge alive without polling.
    // -------------------------------------------------------------------
    let watcher = null;
    let fnWatcher = null;
    let mdWatcher = null;
    const mdDebounceTimers = new Map();

    if (isDesktop && fs && path && absDataFile && absPluginDir) {
      const onChange = () => {
        let m = 0;
        try { m = fs.statSync(absDataFile).mtimeMs; } catch (e) { return; }
        if (m === lastMtime) return;
        lastMtime = m;
        // Self-write suppression: our own folder-entry writes just bumped
        // mtime. Allow one "slack" so we only suppress the write we made
        // and still repaint when the same mtime value is produced by an
        // unrelated edit later.
        if (m === lastSelfWriteMtime) {
          lastSelfWriteMtime = 0; // single-shot
          return;
        }
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => { debounceTimer = null; refreshTree(); }, DEBOUNCE_MS);
      };

      // Watch the parent dir and filter — survives atomic rename
      // (Dropbox/iCloud).
      watcher = fs.watch(absPluginDir, { persistent: false }, (_event, filename) => {
        if (filename === 'data.json') onChange();
      });

      // Watch Folder Notes plugin's data.json for template changes.
      if (absFolderNotesDir) {
        try {
          fnWatcher = fs.watch(absFolderNotesDir, { persistent: false }, (_event, filename) => {
            if (filename !== 'data.json') return;
            (async () => {
              const next = await readFolderNoteTemplate(adapter);
              if (next === folderNoteTemplate) return;
              folderNoteTemplate = next;
              console.log('[iconize-reloader] folder-notes template changed →', next);
              await initialScan();
            })().catch((e) => console.error('[iconize-reloader] fnWatcher handler failed', e));
          });
        } catch (e) {
          // Folder Notes plugin dir absent — leave fnWatcher null; reloader
          // stays inert on folder side but file-side painting via Iconize
          // still works.
        }
      }

      // Disk-driven folder-note apply: parse frontmatter from disk and upsert
      // data.json without waiting for Obsidian's metadataCache to catch up.
      // Coalesces rapid writes (atomic-replace fires multiple events) via
      // per-path debounce. Returns true on no-op so caller can decide to
      // refresh.
      const applyFolderNoteFromDisk = async (vaultRel) => {
        if (!this.settings.folderNotePropagation) return;
        if (!folderNoteTemplate) return;
        const target = folderNoteTarget(folderNoteTemplate, vaultRel);
        if (!target) return;
        const absPath = path.join(basePath, vaultRel);
        let exists = false;
        try { exists = fs.statSync(absPath).isFile(); } catch (e) { /* deleted */ }
        if (exists) {
          const { icon, color } = readIconFieldsFromDisk(
            absPath,
            this.settings.iconFieldName,
            this.settings.colorFieldName,
          );
          if (icon) {
            const wrote = await upsertFolderEntry(adapter, target, icon, color);
            if (wrote) {
              bumpSelfWriteMtime();
              mirrorFolderEntryToMemory(target, icon, color);
              const desired = color ? { iconName: icon, iconColor: color } : { iconName: icon };
              scheduleWatchdog(target, desired);
              scheduleSelfRefresh();
              console.log('[iconize-reloader] fs.watch upsert', target, '→', desired);
            }
          } else {
            const wrote = await removeFolderEntry(adapter, target);
            if (wrote) {
              bumpSelfWriteMtime();
              mirrorFolderEntryToMemory(target, null, null);
              scheduleWatchdog(target, null);
              scheduleSelfRefresh();
              console.log('[iconize-reloader] fs.watch remove', target, '(no icon in fm)');
            }
          }
        } else {
          const wrote = await removeFolderEntry(adapter, target);
          if (wrote) {
            bumpSelfWriteMtime();
            mirrorFolderEntryToMemory(target, null, null);
            scheduleWatchdog(target, null);
            scheduleSelfRefresh();
            console.log('[iconize-reloader] fs.watch remove', target, '(file deleted)');
          }
        }
      };

      // Vault-wide recursive fs.watch. macOS uses FSEvents under the hood,
      // which suppresses some atomic-replace intermediates and aggregates
      // rapid bursts. We filter on .md suffix and excluded top-level dirs at
      // event time.
      try {
        mdWatcher = fs.watch(basePath, { persistent: false, recursive: true },
          (_event, filename) => {
            if (!filename) return;
            // POSIX-ize for downstream string ops.
            const vaultRel = filename.split(path.sep).join('/');
            if (!vaultRel.endsWith('.md')) return;
            // Skip atomic-replace intermediates from frontmatter_rewriter.
            if (vaultRel.endsWith('.md.tmp')) return;
            const top = vaultRel.split('/', 1)[0];
            if (MD_WATCH_EXCLUDED.has(top)) return;
            // Cheap pre-filter: only proceed for paths that look like
            // folder-notes (filename stem matches parent basename, by template).
            if (!folderNoteTemplate) return;
            if (!folderNoteTarget(folderNoteTemplate, vaultRel)) return;

            const prev = mdDebounceTimers.get(vaultRel);
            if (prev) clearTimeout(prev);
            mdDebounceTimers.set(vaultRel, setTimeout(() => {
              mdDebounceTimers.delete(vaultRel);
              applyFolderNoteFromDisk(vaultRel)
                .catch((e) => console.error('[iconize-reloader] applyFolderNoteFromDisk failed', e));
            }, MD_WATCH_DEBOUNCE_MS));
          });
        console.log('[iconize-reloader] watching vault for folder-notes →', basePath);
      } catch (e) {
        console.warn('[iconize-reloader] vault fs.watch failed; folder-note disk events inert', e);
      }

      console.log('[iconize-reloader] watching', absDataFile);
    } else if (Platform.isMobile) {
      console.log('[iconize-reloader] mobile mode — metadataCache-only (fs.watch surface inert)');
    }

    this.register(() => {
      if (watcher) watcher.close();
      if (fnWatcher) fnWatcher.close();
      if (mdWatcher) mdWatcher.close();
      if (debounceTimer) clearTimeout(debounceTimer);
      for (const t of mdDebounceTimers.values()) clearTimeout(t);
      mdDebounceTimers.clear();
    });

    this.addCommand({
      id: 'reload-iconize',
      name: 'Reload Iconize now',
      callback: refreshTree,
    });

    this.addSettingTab(new IconizeReloaderSettingTab(this.app, this));
  }

  async loadSettings() {
    const stored = (await this.loadData()) || {};
    this.settings = Object.assign({}, DEFAULT_SETTINGS, stored);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  // Push our preferred frontmatter field names into Iconize's own settings
  // block, plus enable Iconize's frontmatter-driven file-side painting. Returns
  // true when a write happened. Callable from onload (early, after the
  // self-write-mtime closure is wired) and from the settings tab's onChange
  // handlers. No-op on mobile when Iconize's data.json is missing.
  async _enforceIconizeSettings() {
    const adapter = this.app.vault.adapter;
    const data = await readIconizeData(adapter);
    if (data === null) return false;
    const settings = data.settings || (data.settings = {});
    let changed = false;
    if (settings.iconInFrontmatterEnabled !== true) {
      settings.iconInFrontmatterEnabled = true;
      changed = true;
    }
    if (settings.iconInFrontmatterFieldName !== this.settings.iconFieldName) {
      settings.iconInFrontmatterFieldName = this.settings.iconFieldName;
      changed = true;
    }
    if (settings.iconColorInFrontmatterFieldName !== this.settings.colorFieldName) {
      settings.iconColorInFrontmatterFieldName = this.settings.colorFieldName;
      changed = true;
    }
    if (changed) {
      await writeIconizeData(adapter, data);
      if (this._bumpSelfWriteMtime) this._bumpSelfWriteMtime();
      console.log('[iconize-reloader] re-asserted Iconize frontmatter settings →',
        this.settings.iconFieldName, '/', this.settings.colorFieldName);
    }
    return changed;
  }

  // Push our preferred frontmatter field names into Notebook Navigator's settings
  // and flip its master `useFrontmatterMetadata` toggle on. NB owns the folder-note
  // frontmatter read pipeline itself — this method is settings-only; no data
  // mirroring, no folder-icon dictionary writes. No-op when NB is not installed
  // (data.json absent → readNbData returns null).
  async _enforceNotebookNavigatorSettings() {
    const adapter = this.app.vault.adapter;
    const data = await readNbData(adapter);
    if (data === null) return false;
    let changed = false;
    if (data.useFrontmatterMetadata !== true) {
      data.useFrontmatterMetadata = true;
      changed = true;
    }
    if (data.frontmatterIconField !== this.settings.iconFieldName) {
      data.frontmatterIconField = this.settings.iconFieldName;
      changed = true;
    }
    if (data.frontmatterColorField !== this.settings.colorFieldName) {
      data.frontmatterColorField = this.settings.colorFieldName;
      changed = true;
    }
    if (changed) {
      await writeNbData(adapter, data);
      console.log('[iconize-reloader] re-asserted Notebook Navigator frontmatter settings →',
        this.settings.iconFieldName, '/', this.settings.colorFieldName);
    }
    return changed;
  }
}

class IconizeReloaderSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl('h2', { text: 'Iconize Reloader' });

    new Setting(containerEl)
      .setName('Folder-note → folder icon propagation')
      .setDesc('Watch every folder-note\'s frontmatter and write the matching icon entry into Iconize\'s data.json so the parent folder paints with the configured icon. Turn off to leave folders alone (file-side painting via Iconize\'s built-in frontmatter feature still works).')
      .addToggle((t) => t
        .setValue(this.plugin.settings.folderNotePropagation)
        .onChange(async (v) => {
          this.plugin.settings.folderNotePropagation = v;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('Icon field name')
      .setDesc(`Frontmatter key the reloader reads — and Iconize is configured to read — for the icon name. Default: ${DEFAULT_SETTINGS.iconFieldName}`)
      .addText((t) => t
        .setPlaceholder(DEFAULT_SETTINGS.iconFieldName)
        .setValue(this.plugin.settings.iconFieldName)
        .onChange(async (v) => {
          const next = (v || '').trim() || DEFAULT_SETTINGS.iconFieldName;
          if (next === this.plugin.settings.iconFieldName) return;
          this.plugin.settings.iconFieldName = next;
          await this.plugin.saveSettings();
          await this._reapplyAfterFieldChange();
        }));

    new Setting(containerEl)
      .setName('Color field name')
      .setDesc(`Frontmatter key the reloader reads — and Iconize is configured to read — for the icon color. Default: ${DEFAULT_SETTINGS.colorFieldName}`)
      .addText((t) => t
        .setPlaceholder(DEFAULT_SETTINGS.colorFieldName)
        .setValue(this.plugin.settings.colorFieldName)
        .onChange(async (v) => {
          const next = (v || '').trim() || DEFAULT_SETTINGS.colorFieldName;
          if (next === this.plugin.settings.colorFieldName) return;
          this.plugin.settings.colorFieldName = next;
          await this.plugin.saveSettings();
          await this._reapplyAfterFieldChange();
        }));

    new Setting(containerEl)
      .setName('Re-assert plugin settings on load')
      .setDesc('On every reloader load, push iconInFrontmatterEnabled=true plus the field names above into Iconize\'s settings, and useFrontmatterMetadata=true with the same field names into Notebook Navigator\'s settings (when present). Survives manual toggling-off in either plugin\'s own settings UI.')
      .addToggle((t) => t
        .setValue(this.plugin.settings.enforceIconizeSettings)
        .onChange(async (v) => {
          this.plugin.settings.enforceIconizeSettings = v;
          await this.plugin.saveSettings();
          if (v) {
            try { await this.plugin._enforceIconizeSettings(); }
            catch (e) { console.error('[iconize-reloader] enforce iconize on toggle failed', e); }
            try { await this.plugin._enforceNotebookNavigatorSettings(); }
            catch (e) { console.error('[iconize-reloader] enforce notebook-navigator on toggle failed', e); }
          }
        }));
  }

  // Settings-tab helper: after a field-name edit, push the new names into
  // Iconize and Notebook Navigator, then re-walk every md file so existing
  // folder-icon entries (Iconize-side) land under the new namespace. Wrapped in
  // try/catch so a malformed plugin data.json doesn't throw out of the onChange
  // handler.
  async _reapplyAfterFieldChange() {
    try {
      if (this.plugin.settings.enforceIconizeSettings) {
        await this.plugin._enforceIconizeSettings();
        await this.plugin._enforceNotebookNavigatorSettings();
      }
      if (this.plugin._initialScan) await this.plugin._initialScan();
      if (this.plugin._scheduleSelfRefresh) this.plugin._scheduleSelfRefresh();
    } catch (e) {
      console.error('[iconize-reloader] re-apply after field change failed', e);
    }
  }
}

module.exports = IconizeReloaderPlugin;
module.exports.RELOADER_VERSION = RELOADER_VERSION;
module.exports.__testables__ = {
  readFolderNoteTemplate, folderNoteTarget,
  upsertFolderEntry, removeFolderEntry, readIconizeData, writeIconizeData,
};
