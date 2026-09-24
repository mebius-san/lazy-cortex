"""
Per-section migration ladders for `lazy.settings.json`.

Each sibling module in this package owns one top-level settings section and
exposes a `MIGRATIONS` dict mapping `from_version` to a callable that returns
the section content at `from_version + 1`. The `lazy_settings` helper walks
the ladder up to `CURRENT_VERSIONS[<section>]` on every load.
"""
