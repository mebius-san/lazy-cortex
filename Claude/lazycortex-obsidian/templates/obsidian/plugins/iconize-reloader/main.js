'use strict';

const RELOADER_VERSION = '2.0.8';

const { Plugin } = require('obsidian');
const fs = require('fs');
const path = require('path');

const TARGET_PLUGIN_ID = 'obsidian-icon-folder';
const FILE_EXPLORER_ID = 'file-explorer';
const DEBOUNCE_MS = 250;

const FOLDER_NOTES_PLUGIN_ID = 'folder-notes';
const FOLDER_NOTE_TEMPLATE_DEFAULT = '{{folder_name}}';

// Read the Folder Notes community plugin's configured folder-note name template.
// Returns the template string (e.g. '{{folder_name}}' or 'index') or null if the
// plugin is missing, disabled, or its data.json is unreadable.
function readFolderNoteTemplate(basePath) {
  const p = path.join(basePath, '.obsidian', 'plugins', FOLDER_NOTES_PLUGIN_ID, 'data.json');
  try {
    const raw = fs.readFileSync(p, 'utf8');
    const data = JSON.parse(raw);
    // Folder Notes stores it under `folderNoteName`. Fall back to default if absent.
    return (typeof data.folderNoteName === 'string' && data.folderNoteName)
      ? data.folderNoteName
      : FOLDER_NOTE_TEMPLATE_DEFAULT;
  } catch (e) {
    return null;
  }
}

// Given a folder-note template and a vault-relative file path, decide whether the
// file is the folder-note for its parent folder. Supports the `{{folder_name}}`
// token plus literal filenames. Returns the folder's vault-relative path when the
// file IS a folder-note, or null otherwise.
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

// Read, mutate, write iconize data.json. Never touches reserved keys.
const RESERVED_KEYS = new Set(['settings', 'rules', 'recentlyUsedIcons']);

function readIconizeData(dataFile) {
  try {
    return JSON.parse(fs.readFileSync(dataFile, 'utf8'));
  } catch (e) {
    return null;
  }
}

function writeIconizeData(dataFile, obj) {
  const tmp = dataFile + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', 'utf8');
  fs.renameSync(tmp, dataFile);
  return fs.statSync(dataFile).mtimeMs;
}

// Upsert `{folderPath: {iconName, iconColor?}}`. Returns updated mtime or null on no-op.
function upsertFolderEntry(dataFile, folderPath, iconName, iconColor) {
  const data = readIconizeData(dataFile);
  if (data === null) return null;
  if (RESERVED_KEYS.has(folderPath)) return null;
  const existing = data[folderPath];
  const entry = { iconName };
  if (iconColor) entry.iconColor = iconColor;
  if (existing && existing.iconName === entry.iconName && existing.iconColor === entry.iconColor) {
    return null; // no-op
  }
  data[folderPath] = entry;
  return writeIconizeData(dataFile, data);
}

// Remove `folderPath`. Returns updated mtime or null when key absent.
function removeFolderEntry(dataFile, folderPath) {
  const data = readIconizeData(dataFile);
  if (data === null) return null;
  if (RESERVED_KEYS.has(folderPath)) return null;
  if (!(folderPath in data)) return null;
  delete data[folderPath];
  return writeIconizeData(dataFile, data);
}

class IconizeReloaderPlugin extends Plugin {
  async onload() {
    const basePath = this.app.vault.adapter.basePath;
    if (!basePath) {
      console.warn('[iconize-reloader] no vault basePath; desktop-only');
      return;
    }
    const pluginDir = path.join(basePath, '.obsidian', 'plugins', TARGET_PLUGIN_ID);
    const dataFile = path.join(pluginDir, 'data.json');

    let lastMtime = 0;
    try { lastMtime = fs.statSync(dataFile).mtimeMs; } catch (e) { /* not present yet */ }

    // Re-entrancy: when we (the reloader) write data.json for folder entries,
    // we record the mtime here so the external-change watcher can distinguish
    // self-writes from Iconize-writes / user-click writes.
    let lastSelfWriteMtime = 0;

    // Folder-note template (read once, refreshed on Folder Notes settings change).
    let folderNoteTemplate = readFolderNoteTemplate(basePath);
    if (folderNoteTemplate === null) {
      console.warn('[iconize-reloader] folder-notes plugin not installed/disabled — folder-icon propagation inert');
    }

    // Extract iconize_* from a file's cached frontmatter. Returns { icon, color }
    // with nullable fields, or null when the file has no frontmatter at all.
    const extractIconFields = (file) => {
      const cache = this.app.metadataCache.getFileCache(file);
      const fm = cache && cache.frontmatter;
      if (!fm) return { icon: null, color: null };
      return {
        icon: typeof fm.iconize_icon === 'string' ? fm.iconize_icon : null,
        color: typeof fm.iconize_color === 'string' ? fm.iconize_color : null,
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
      setTimeout(() => {
        const data = readIconizeData(dataFile);
        if (data === null) return;
        const existing = data[target];
        const matches =
          (desired === null && !(target in data)) ||
          (desired !== null && existing &&
            existing.iconName === desired.iconName &&
            existing.iconColor === desired.iconColor);
        if (matches) return;
        console.log('[iconize-reloader] watchdog re-asserting', target, '→', desired);
        let mt;
        if (desired === null) {
          mt = removeFolderEntry(dataFile, target);
        } else {
          mt = upsertFolderEntry(dataFile, target, desired.iconName, desired.iconColor);
        }
        if (mt) {
          lastSelfWriteMtime = mt;
          mirrorFolderEntryToMemory(target, desired ? desired.iconName : null, desired ? desired.iconColor : null);
          scheduleSelfRefresh();
        }
      }, WATCHDOG_DELAY_MS);
    };

    // Apply a folder-note's current frontmatter to data.json. No-op when the
    // file isn't a folder-note or when Folder Notes plugin is missing.
    // Returns true when a write happened (caller may want to trigger refresh).
    const applyFolderNote = (file) => {
      if (!folderNoteTemplate) return false;
      const target = folderNoteTarget(folderNoteTemplate, file.path);
      if (!target) return false;
      const { icon, color } = extractIconFields(file);
      let mt;
      if (icon) {
        mt = upsertFolderEntry(dataFile, target, icon, color);
      } else {
        mt = removeFolderEntry(dataFile, target);
      }
      if (mt) {
        lastSelfWriteMtime = mt;
        mirrorFolderEntryToMemory(target, icon, color);
        const desired = icon ? (color ? { iconName: icon, iconColor: color } : { iconName: icon }) : null;
        scheduleWatchdog(target, desired);
        return true;
      }
      return false;
    };

    // On folder-note deletion or rename-away, drop the folder key.
    // Returns true when a write happened.
    const dropFolderNote = (oldPath) => {
      if (!folderNoteTemplate) return false;
      const target = folderNoteTarget(folderNoteTemplate, oldPath);
      if (!target) return false;
      const mt = removeFolderEntry(dataFile, target);
      if (mt) {
        lastSelfWriteMtime = mt;
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
    //   4. Call iconize.handleChangeLayout() — re-paints file-explorer, tabs
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

    const onChange = () => {
      let m = 0;
      try { m = fs.statSync(dataFile).mtimeMs; } catch (e) { return; }
      if (m === lastMtime) return;
      lastMtime = m;
      // Self-write suppression: our own folder-entry writes just bumped mtime.
      // Allow one "slack" so we only suppress the write we made and still repaint
      // when the same mtime value is produced by an unrelated edit later.
      if (m === lastSelfWriteMtime) {
        lastSelfWriteMtime = 0; // single-shot
        return;
      }
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => { debounceTimer = null; refreshTree(); }, DEBOUNCE_MS);
    };

    // Watch the parent dir and filter — survives atomic rename (Dropbox/iCloud).
    const watcher = fs.watch(pluginDir, { persistent: false }, (_event, filename) => {
      if (filename === 'data.json') onChange();
    });

    // Folder-note frontmatter events — metadataCache.changed fires on every
    // .md save, including the first parse after vault open. We filter inside
    // applyFolderNote via folderNoteTarget.
    const onChangedFile = (file) => {
      if (file && file.path && file.path.endsWith('.md')) {
        if (applyFolderNote(file)) scheduleSelfRefresh();
      }
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

    // Create: when a new folder-note appears (externally or from the worker's
    // PostToolUse hook), Folder Notes' own vault.create listener applies CSS
    // classes but often before the file-explorer has rendered the new file —
    // leaving the note visible as a sibling until app reload. Schedule a
    // refresh (which emits layout-change) and also directly nudge the CSS
    // classes with retries so the merge lands even if Folder Notes' handler
    // missed the DOM.
    this.registerEvent(this.app.vault.on('create', (file) => {
      if (!file || !file.path || !file.path.endsWith('.md')) return;
      if (!folderNoteTemplate) return;
      const target = folderNoteTarget(folderNoteTemplate, file.path);
      if (target) {
        scheduleSelfRefresh();
        nudgeFolderNoteCSS(target, file.path);
      }
    }));

    // Rename: decide based on old + new paths.
    this.registerEvent(this.app.vault.on('rename', (file, oldPath) => {
      let wrote = false;
      if (oldPath && oldPath.endsWith('.md')) wrote = dropFolderNote(oldPath) || wrote;
      if (file && file.path && file.path.endsWith('.md')) wrote = applyFolderNote(file) || wrote;
      if (wrote) scheduleSelfRefresh();
    }));

    // Delete: drop the folder-keyed entry if the deleted path was a folder-note.
    this.registerEvent(this.app.vault.on('delete', (file) => {
      if (file && file.path && file.path.endsWith('.md')) {
        if (dropFolderNote(file.path)) scheduleSelfRefresh();
      }
    }));

    // Initial scan: iterate every markdown file once so pre-existing folder-note
    // frontmatter is reflected in data.json. Defer one tick so metadataCache is
    // populated. Trigger a single refreshTree after the sweep when any write
    // happened — otherwise Iconize's in-memory `data` stays stale (our own
    // writes are suppressed by fs.watch's self-write filter).
    const initialScan = () => {
      if (!folderNoteTemplate) return;
      const mdFiles = this.app.vault.getMarkdownFiles();
      let wrote = false;
      for (const file of mdFiles) wrote = applyFolderNote(file) || wrote;
      if (wrote) scheduleSelfRefresh();
    };
    this.app.workspace.onLayoutReady(() => setTimeout(initialScan, 100));

    // Watch Folder Notes plugin's data.json for template changes.
    const fnDir = path.join(basePath, '.obsidian', 'plugins', FOLDER_NOTES_PLUGIN_ID);
    let fnWatcher = null;
    try {
      fnWatcher = fs.watch(fnDir, { persistent: false }, (_event, filename) => {
        if (filename !== 'data.json') return;
        const next = readFolderNoteTemplate(basePath);
        if (next === folderNoteTemplate) return;
        folderNoteTemplate = next;
        console.log('[iconize-reloader] folder-notes template changed →', next);
        // Re-scan so folder-note matches shift.
        initialScan();
      });
    } catch (e) {
      // Folder Notes plugin dir absent — leave fnWatcher null; reloader stays inert
      // on folder side but file-side painting via Iconize still works.
    }

    this.register(() => {
      watcher.close();
      if (fnWatcher) fnWatcher.close();
      if (debounceTimer) clearTimeout(debounceTimer);
    });

    this.addCommand({
      id: 'reload-iconize',
      name: 'Reload Iconize now',
      callback: refreshTree,
    });

    console.log('[iconize-reloader] watching', dataFile);
  }
}

module.exports = IconizeReloaderPlugin;
module.exports.RELOADER_VERSION = RELOADER_VERSION;
module.exports.__testables__ = {
  readFolderNoteTemplate, folderNoteTarget,
  upsertFolderEntry, removeFolderEntry, readIconizeData, writeIconizeData,
};
