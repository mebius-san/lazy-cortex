'use strict';

const { Plugin } = require('obsidian');
const fs = require('fs');
const path = require('path');

const TARGET_PLUGIN_ID = 'obsidian-icon-folder';
const DEBOUNCE_MS = 250;
const SELF_WRITE_MUTE_MS = 2000;

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
    let mutedUntil = 0;

    const softReload = async () => {
      try {
        mutedUntil = Date.now() + SELF_WRITE_MUTE_MS;
        await this.app.plugins.disablePlugin(TARGET_PLUGIN_ID);
        await this.app.plugins.enablePlugin(TARGET_PLUGIN_ID);
        console.log('[iconize-reloader] soft-reloaded', TARGET_PLUGIN_ID);
      } catch (e) {
        console.error('[iconize-reloader] reload failed', e);
      }
    };

    const onChange = () => {
      if (Date.now() < mutedUntil) return;
      let m = 0;
      try { m = fs.statSync(dataFile).mtimeMs; } catch (e) { return; }
      if (m === lastMtime) return;
      lastMtime = m;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => { debounceTimer = null; softReload(); }, DEBOUNCE_MS);
    };

    // Watch the parent dir and filter — survives atomic rename (Dropbox/iCloud).
    const watcher = fs.watch(pluginDir, { persistent: false }, (_event, filename) => {
      if (filename === 'data.json') onChange();
    });

    this.register(() => { watcher.close(); if (debounceTimer) clearTimeout(debounceTimer); });

    this.addCommand({
      id: 'reload-iconize',
      name: 'Reload Iconize now',
      callback: softReload,
    });

    console.log('[iconize-reloader] watching', dataFile);
  }
}

module.exports = IconizeReloaderPlugin;
