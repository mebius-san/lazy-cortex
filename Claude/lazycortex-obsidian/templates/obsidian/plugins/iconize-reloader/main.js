'use strict';

const { Plugin } = require('obsidian');
const fs = require('fs');
const path = require('path');

const TARGET_PLUGIN_ID = 'obsidian-icon-folder';
const FILE_EXPLORER_ID = 'file-explorer';
const DEBOUNCE_MS = 250;

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

    let debounceTimer = null;
    let running = false;

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

          if (typeof iconize.handleChangeLayout === 'function') {
            iconize.handleChangeLayout();
          } else {
            this.app.workspace.trigger('layout-change');
          }
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
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => { debounceTimer = null; refreshTree(); }, DEBOUNCE_MS);
    };

    // Watch the parent dir and filter — survives atomic rename (Dropbox/iCloud).
    const watcher = fs.watch(pluginDir, { persistent: false }, (_event, filename) => {
      if (filename === 'data.json') onChange();
    });

    this.register(() => { watcher.close(); if (debounceTimer) clearTimeout(debounceTimer); });

    this.addCommand({
      id: 'reload-iconize',
      name: 'Reload Iconize now',
      callback: refreshTree,
    });

    console.log('[iconize-reloader] watching', dataFile);
  }
}

module.exports = IconizeReloaderPlugin;
