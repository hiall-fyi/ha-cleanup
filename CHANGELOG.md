# Changelog

All notable changes to this project will be documented in this file.

---

## [1.5.0] — 2026-04-03

**Reliability & code quality release**

### Bug Fixes

- **Fixed orphan detection overriding device/config checks for automations, scripts, and scenes** — Previously, if an automation entity had a broken device reference but a valid unique_id, it wouldn't be flagged as orphaned. Now device and config entry checks are always respected alongside definition checks.
- **Fixed database purge hanging on large databases** — Previously, a single massive DELETE on a 4GB+ database could hang for a very long time with no feedback. Rows are now deleted in batches of 100k with progress logged after each batch. VACUUM also runs on a dedicated connection outside any transaction, which is what SQLite requires.
- **Fixed file permissions not preserved after saving registry files** — When the tool wrote a registry file, the new file could end up with different permissions than the original. Now the original file's permissions are restored after the atomic rename.

### Improvements

- **Record counts use comma formatting** — `7,056,691 states` instead of `7056691 states`.
- **WAL journal mode enabled during purge** — Improves write performance on large deletes.
- **Orphan attribute cleanup uses a more efficient query** — Switched from `NOT EXISTS` subquery to `NOT IN` with `DISTINCT`, which performs better on large tables.
- **VACUUM now warns you it may take a while** — On multi-gigabyte databases, VACUUM can take minutes. The tool now logs a heads-up before starting.
- **Version number now shows in the menu header** — You can see which version you're running at a glance.
- **Selection ranges are now bounded** — Typing something like `1-99999` in the entity selection prompt no longer creates a huge set in memory. Ranges are clamped to valid bounds.
- **Duplicated HA stop/start code replaced with a single `ha_stopped()` context manager** — This removes four near-identical blocks of stop → try → finally → start logic, making the code easier to maintain.
- **Backup selection in the restore menu is now shared** — Options 2, 3, and 4 in the restore submenu use the same helper instead of repeating the same input/validation code.
- **Stale data no longer used when removing orphaned entities** — The cleanup step now forces a fresh read instead of potentially using an outdated cached version.
- **Cleaned up variable shadowing** — The loop variable in `scan_backup_files` no longer shadows the module-level `backup_file` function.

---

## [1.4.0] — 2026-03-08

**Code quality & type safety release**

### Improvements

- **Full type hints across every function** — All parameters and return types are now annotated, passing `mypy --strict` with zero errors.
- **Modern Python 3.13+ syntax** — Uses `from __future__ import annotations`, `X | Y` union types, and `TYPE_CHECKING` imports throughout.
- **Docstrings on every module, class, and public function** — Follows the `"""Verb description."""` convention.
- **ID collection for automations, scripts, and scenes now shares a single helper** — Reduces duplicated code and makes future changes easier to maintain.
- **YAML ID parsing uses a compiled regex** — Replaces the fragile line-by-line `startswith("- id:")` approach with a pre-compiled pattern that handles more YAML formatting variations.
- **Subprocess calls now have a 60-second timeout** — HA stop/start commands no longer hang indefinitely if something goes wrong.

---

## [1.3.0] — 2026-02-08

**Restore from backup**

### Features

- **Restore entities from backup files** — New restore submenu (option 7) lets you recover accidentally deleted entities from the timestamped backups the tool creates.
- **Selective restore** — Pick exactly which deleted entities to bring back, using the same number/range selection syntax as the suffix fix.
- **Full restore** — Replace your entire entity registry with a backup in one step, with a warning if the entity count differs significantly.
- **Preview backup differences** — Compare any backup against your current registry to see what was deleted, added, or modified before committing to a restore.
- **Backup scanner** — Lists all backup files with timestamp, type, entity count, and file size.

### Improvements

- **Atomic file writes with locking** — Registry saves now use a temp file, `fsync`, `fcntl.flock`, and atomic rename to prevent corruption if HA and the tool write at the same time.
- **JSON caching with mtime invalidation** — Registry files are cached in memory and only re-read when the file on disk actually changes, reducing I/O during repeated operations.
- **Backup retention is now configurable** — Uses the `BACKUP_RETENTION_DAYS` constant (default 7 days) instead of a hardcoded value.
- **Old backup cleanup reports more detail** — Tells you how many backups exist and whether any were within the retention window.

---

## [1.2.0] — 2026-01-31

**Interactive suffix fix & expanded orphan detection**

### Features

- **Interactive suffix selection** — The suffix fix (option 5) now shows all candidates and lets you pick which ones to rename using numbers, ranges, or `all`. Previously it auto-fixed everything matching a hardcoded platform list.
- **Supports any numeric suffix** — Detects `_2`, `_3`, `_10`, etc. on any platform, not just `_2` on `template` and `tado_ce`.
- **Script and scene orphan detection** — Orphaned entity checks now cover scripts and scenes in addition to automations, checking YAML files, root YAML, and UI storage for each.

### Improvements

- **Proper logging** — Replaced raw `print()` timestamps with Python's `logging` module.
- **Error handling on file operations** — `load_json` and `backup_file` now raise clear exceptions instead of crashing with generic errors.
- **Type hints on all functions** — Every function now has parameter and return type annotations.
- **Recorder config parsing uses regex** — Replaces the fragile line-by-line YAML parser with a regex that handles more formatting variations.
- **Menu descriptions updated** — Options now describe what they actually do (e.g., "missing device/config/definition" instead of just "orphaned entities").

---

## [1.1.0] — 2026-01-28

**Interactive menu**

### Features

- **Interactive menu** — Run the tool without arguments to get a numbered menu instead of running everything automatically. Pick individual operations or do a full cleanup.
- **Suffix fix for `_2` entities** — New option to rename entities that got a `_2` suffix after re-adding an integration, when the base entity ID is available.
- **Dry run from the menu** — Press `d` to preview all changes without modifying anything, right from the interactive menu.
- **Per-operation HA restart** — Each menu option handles stopping and starting HA on its own, with confirmation prompts. No more manual stop/start.

### Improvements

- **Database purge now returns counts** — Reports how many states and events were purged.
- **Backup cleanup returns count** — Reports how many old backup files were removed.
- **Cleaner code structure** — Utility functions, cleanup functions, and menu system are now in separate sections.

---

## [1.0.1] — 2026-01-25

### Bug Fixes

- **Fixed automation orphan detection missing UI-based and root YAML automations** — Previously only checked the `automation/` folder. Now also checks `automations.yaml` in the config root and UI-based automations in `.storage/automations`.
- **Fixed automations without a unique_id being incorrectly flagged as orphaned** — Automations that can't be verified (no unique_id) are no longer marked as orphans.

### Features

- **Auto-detect recorder `purge_keep_days`** — Reads the setting from `configuration.yaml` or the recorder config entry instead of using a hardcoded 14-day default.

---

## [1.0.0] — 2026-01-15

**Initial release**

- Remove orphaned entities with missing device or config entry references
- Clean `deleted_entities` and `deleted_devices` from registries
- Purge old states and events from the database with VACUUM
- Clean old backup files (7+ days)
- Auto-detect HA config path (HAOS, Docker, Core)
- Auto-detect HA stop/start method
- Dry-run mode (`--dry-run`) to preview all changes
- Automatic backup of registry files before modification
