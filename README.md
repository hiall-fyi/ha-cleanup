# Home Assistant Cleanup

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.6+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.7.1-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github)

<!-- Support -->
[![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Interactive cleanup tool for Home Assistant - Remove orphaned entities, fix entity suffixes, clean registries, purge old database records, and restore from backups.**

[Features](#features) • [Quick Start](#quick-start) • [Usage](#usage) • [Troubleshooting](#troubleshooting)

</div>

---

## Why HA Cleanup?

Home Assistant accumulates "ghost entities" over time - entities that persist after removing integrations or devices. These clutter your entity list and can cause confusion.

**Common issues this solves:**

- Orphaned entities from deleted integrations
- Entity names with `_2` suffix after re-adding integrations
- Deleted devices still appearing in registries
- Database bloat from old states/events
- Database purge taking forever with no feedback on large installations

---

## Features

| Feature | Description |
|---------|-------------|
| **Interactive Menu** | Easy-to-use menu for selecting cleanup operations |
| **Orphaned Entity Cleanup** | Removes entities with missing device/config/automation/script/scene |
| **Fix Numeric Suffix** | Interactive selection to fix `_2`, `_3` suffixes. Limited to the range Home Assistant actually generates, so model numbers, MAC addresses and port numbers are left alone, with collision detection so you can't accidentally rename two entities to the same ID |
| **Deleted Registry Cleanup** | Clears `deleted_entities` and `deleted_devices` lists |
| **Database Purge** | Removes states/events older than your recorder setting, with optimised batch deletes, adaptive batch sizing, and real-time progress |
| **Smart VACUUM** | Checks disk space before running VACUUM, skips if there's not enough room |
| **Restore from Backup** | Selective or full restore of entities from backup files, safe against concurrent HA writes |
| **Auto-Detect Config** | Reads `purge_keep_days` from `configuration.yaml`, `packages/*.yaml`, or the recorder config entry, and logs which source it used |
| **Dry-Run Mode** | Preview all changes (including old backup cleanup) without modifying anything |
| **Auto Backup** | Backs up registry files before any modifications, with sub-second collision protection |

---

## Prerequisites

- **Home Assistant**: Any installation type (HAOS, Docker, Core)
- **Python**: 3.13 or higher
- **Access**: SSH or terminal access to HA config directory

---

## Quick Start

### 1. Download

```bash
wget -O ha-cleanup.py https://raw.githubusercontent.com/hiall-fyi/ha-cleanup/main/ha-cleanup.py
chmod +x ha-cleanup.py
```

### 2. Run

```bash
python3 ha-cleanup.py
```

---

## Usage

### Interactive Menu

```
======================================================================
  Home Assistant Cleanup Tool  v1.7.1
======================================================================
  Config: /homeassistant
  Database: 5924.3 MB
----------------------------------------------------------------------
  ⚠️  This tool modifies HA registries and database.
     Always back up first.
  💡 DB purge on large DBs may take several minutes —
     progress will be shown.
======================================================================

  1. Full cleanup (options 2-4, 6 — optimised)
  2. Remove orphaned entities (missing device/config/definition)
  3. Clean deleted registry items (deleted_entities/devices)
  4. Purge old database records (optimised batch + progress)
  5. Fix numeric suffix (_2, _3, etc.) - interactive
  6. Clean old backup files (>7 days)
  7. Restore from backup (selective or full)

  d. Dry run (preview all)
  q. Quit

  Select option:
```

### Menu Options

| Option | Description | Requires HA Restart |
|--------|-------------|---------------------|
| **1** | Run cleanup operations 2-4, 6 (excludes interactive suffix fix) | Yes |
| **2** | Remove orphaned entities (missing device/config/definition) | Yes |
| **3** | Clean deleted_entities and deleted_devices from registries | Yes |
| **4** | Purge old database records (auto-detects purge_keep_days) | Yes |
| **5** | Fix numeric suffix like _2, _3 (interactive selection) | Yes |
| **6** | Clean backup files older than 7 days | No |
| **7** | Restore from backup (selective or full restore) | Yes |
| **d** | Dry run - preview all changes without modifying | No |
| **q** | Quit | - |

### Dry Run Preview

Select `d` from the menu to preview all changes:

```
[2026-08-01 14:22:25] ==================================================
[2026-08-01 14:22:25] Home Assistant Cleanup (DRY RUN)
[2026-08-01 14:22:25] ==================================================
[2026-08-01 14:22:25] Config path: /homeassistant
[2026-08-01 14:22:25] Database size: 5924.3 MB

[2026-08-01 14:22:25] ✓ No orphaned entities found
[2026-08-01 14:22:25] Would clean 89 deleted entities
[2026-08-01 14:22:25] Would clean 1 deleted devices
[2026-08-01 14:22:25] Using purge_keep_days: 14 (from default)
[2026-08-01 14:22:25]   [Count] Starting...
[2026-08-01 14:22:25]   [Count] Done in 0.3s — 8,082,958 states, 77,557 events
[2026-08-01 14:22:25] Would purge 8,082,958 states, 77,557 events older than 14 days
[2026-08-01 14:22:25] Would VACUUM (DB: 5924.3 MB, free: 8652.6 MB, est. 59s)
[2026-08-01 14:22:26] Found 8 entities with numeric suffix:
[2026-08-01 14:22:26]   - device_tracker.cronus_clients_pixel_6 -> device_tracker.cronus_clients_pixel (mikrotik_ce)
[2026-08-01 14:22:26]   - sensor.met_office_pm2_5 -> sensor.met_office_pm2 (atmos_ce)
[2026-08-01 14:22:26]   - button.cronus_wake_pixel_6 -> button.cronus_wake_pixel (mikrotik_ce)
...
[2026-08-01 14:22:26] Would remove 6 old backup files
[2026-08-01 14:22:26] 
==================================================
[2026-08-01 14:22:26] Summary:
[2026-08-01 14:22:26]   Orphaned entities: 0
[2026-08-01 14:22:26]   Deleted registry items: 90
[2026-08-01 14:22:26]   DB states to purge: 8,082,958
[2026-08-01 14:22:26]   DB events to purge: 77,557
[2026-08-01 14:22:26]   Suffix fixes: 8
[2026-08-01 14:22:26]   Old backup files: 6
[2026-08-01 14:22:26] ==================================================
```

### Numeric Suffix Fix (Interactive)

When you select option 5, you'll see an interactive selection:

```
Found 8 entities with numeric suffix:
======================================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
======================================================================

  [ 1] device_tracker.cronus_clients_pixel_6
       -> device_tracker.cronus_clients_pixel (mikrotik_ce)
  [ 2] sensor.met_office_pm2_5
       -> sensor.met_office_pm2 (atmos_ce)
  [ 3] button.cronus_wake_pixel_6
       -> button.cronus_wake_pixel (mikrotik_ce)
  ...

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to fix all (DANGEROUS!)
  - 'none' or Enter to skip

Selection: 1
```

This lets you manually review and pick only the entities that are actually duplicates.

**Collision protection:** If two entities would both rename to the same target (e.g. both `sensor.x_2` and `sensor.x_3` with no existing `sensor.x`), the tool automatically excludes both from the list to prevent registry corruption.

**What isn't offered:** entities ending in a number Home Assistant could never have generated. Its numbering counts up from `_2`, so anything past `_99` (or a model number like `sensor.inverter_2400`) is skipped, as is any run with a `_1` sibling, which means the device did the numbering. Network integrations are the other big source of noise, so a tail that continues a MAC address (`..._01_da_12`) or a port number after `tcp` / `udp` (`..._dns_udp_53`) is skipped too. On a 2223-entity setup these filters take the list from 45 candidates down to 8. Genuine suffixes that look identical to duplicates, such as `button_4` or `pm2_5`, are still listed, which is why selection stays manual.

---

## Restore from Backup

The restore feature allows you to recover accidentally deleted entities from backup files.

### Restore Menu

Select option **7** from the main menu to access the restore submenu:

```
======================================================================
  Restore from Backup
======================================================================

  1. List available backups
  2. Preview backup differences
  3. Selective restore entities
  4. Full restore registry

  d. Toggle dry-run (currently OFF)
  r. Refresh backup list
  b. Back to main menu
```

### Restore Options

#### 1. List Available Backups

Shows all backup files with timestamps, type, record count (entities or devices), and file size:

```
Found 6 backup files:
======================================================================
#    Timestamp            Type               Entities   Size (MB)
------------------------------------------------------------
1    2026-04-03 11:09:11  entity_registry    1677       1.50
2    2026-04-03 11:09:11  device_registry    142        0.12
3    2026-04-01 21:17:00  entity_registry    1711       1.58
...
```

#### 2. Preview Backup Differences

Compare a backup with your current registry to see what changed:

```
Backup: core.entity_registry.backup.20260403_110911
Timestamp: 2026-04-03 11:09:11
Entities in backup: 1677

======================================================================
DELETED ENTITIES (in backup but not in current): 3
======================================================================
  1. sensor.living_room_temperature (mqtt)
     Name: Living Room Temperature
  2. light.bedroom_lamp (hue)
  3. switch.garage_door (homeassistant)

======================================================================
NEW ENTITIES (in current but not in backup): 1
======================================================================
  1. sensor.new_sensor (homeassistant)

======================================================================
MODIFIED ENTITIES: 2
======================================================================
  1. sensor.test
     disabled_by: None → user
```

#### 3. Selective Restore Entities

Restore only specific entities from a backup:

1. Select a backup file
2. View deleted entities (entities in backup but not in current)
3. Select which entities to restore using the same syntax as suffix fix:
   - Numbers: `1,3,5` or `1-5` or `1,3-5,8`
   - `all` to restore all deleted entities
   - `none` or Enter to skip
4. Confirm selection
5. Script automatically stops HA, restores entities, and starts HA

**Example:**

```
Found 3 deleted entities:
======================================================================
  [ 1] sensor.living_room_temperature (mqtt)
       Name: Living Room Temperature
  [ 2] light.bedroom_lamp (hue)
  [ 3] switch.garage_door (homeassistant)

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to restore all
  - 'none' or Enter to skip

Selection: 1,3

Will restore 2 entities:
  - sensor.living_room_temperature (mqtt)
  - switch.garage_door (homeassistant)

⚠️  Restore these 2 entities? [y/N]: y
```

#### 4. Full Restore Registry

Completely restore the entire registry from a backup:

```
Backup: core.entity_registry.backup.20260403_110911
Timestamp: 2026-04-03 11:09:11
Entities in backup: 1677
Entities in current: 1680
Difference: -3

⚠️  Fully restore registry from this backup? [y/N]: y
```

**⚠️ Warning:** This replaces your entire entity registry. Use with caution!

### When to Use Restore

- **Accidentally deleted entities**: Use selective restore to bring back specific entities
- **Integration removal gone wrong**: Preview differences to see what was lost
- **Testing rollback**: Full restore to revert to a previous state
- **Entity corruption**: Restore from a known-good backup

### Safety Features

- **Auto-backup before restore**: Current registry is backed up before any restore operation
- **Preview before restore**: See exactly what will change
- **Interactive selection**: Choose specific entities to restore
- **Confirmation prompts**: Asks before making changes

---

## Detailed Feature Guide

### Option 1: Full Cleanup

Runs all cleanup operations in sequence (except suffix fix which requires manual selection):

**What it does:**
1. Removes orphaned entities
2. Cleans deleted registry items
3. Purges old database records

It then cleans old backup files (7+ days) before starting Home Assistant again.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-01 14:30:13] Stopping Home Assistant...
[2026-08-01 14:30:22] ✓ No orphaned entities found
[2026-08-01 14:30:22] ✓ Cleaned 89 deleted entities
[2026-08-01 14:30:22] ✓ Cleaned 1 deleted devices
[2026-08-01 14:30:22] Using purge_keep_days: 14 (from default)
[2026-08-01 14:30:22]   [Count] Starting...
[2026-08-01 14:30:23]   [Count] Done in 0.3s — 8,085,627 states, 77,573 events
[2026-08-01 14:30:23] Purging 8,085,627 states, 77,573 events older than 14 days
[2026-08-01 14:30:23]   [States] Starting...
[2026-08-01 14:31:09]     Unlinked 8,029,055 old_state_id references
[2026-08-01 14:31:10]     Batch 1/81: deleted 100,000/8,085,627 (1%)
...
[2026-08-01 14:33:51]   [States] Done in 208.6s — deleted 8,085,627 rows
[2026-08-01 14:33:52]   [Events] Done in 0.9s — deleted 77,573 rows
[2026-08-01 14:46:19]   [Orphan Attributes] Done in 746.9s — deleted 3,205,456 rows
[2026-08-01 14:46:19]   [Orphan Event Data] Done in 0.0s — deleted 568 rows
[2026-08-01 14:46:19]   [VACUUM] Starting...
[2026-08-01 14:47:09]   [VACUUM] Done in 49.3s — DB: 5920.3 → 2748.5 MB (3171.8 MB saved)
[2026-08-01 14:47:09] ✓ Database purged
[2026-08-01 14:47:09] ✓ Removed 6 old backup files (older than 7 days)
[2026-08-01 14:47:09] Database: 5924.4 MB → 2748.5 MB (3175.9 MB saved)
[2026-08-01 14:47:09] Starting Home Assistant...
[2026-08-01 14:47:24] Done!

⚠️  Suffix fix requires manual selection. Run option 5 separately.
```

**When to use:**
- Regular maintenance (monthly recommended)
- After removing multiple integrations
- When database is getting large

---

### Option 2: Remove Orphaned Entities

Removes entities that reference deleted devices, config entries, or definitions.

**How it works:**

1. Scans entity registry for broken references
2. Checks if device_id exists in device registry
3. Checks if config_entry_id exists in config entries
4. For automations/scripts/scenes, checks if ID exists in YAML or UI storage
5. Removes entities with missing references

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-01 14:30:13] Stopping Home Assistant...
[2026-08-01 14:30:22] ✓ No orphaned entities found
[2026-08-01 14:47:09] ✓ Removed 6 old backup files (older than 7 days)
[2026-08-01 14:47:09] Starting Home Assistant...
[2026-08-01 14:47:24] Done!
```

**When to use:**
- After removing integrations
- After deleting devices
- When you see "unavailable" entities that won't go away
- After cleaning up automations/scripts/scenes

**Safety:**
- Backs up entity registry before removal
- Only removes entities with confirmed broken references
- Does NOT remove entities if unique_id cannot be verified

---

### Option 3: Clean Deleted Registry Items

Clears the "soft-deleted" items from entity and device registries.

**What are deleted registry items?**

When you delete an entity or device in HA, it's not immediately removed from the registry files. Instead, it's moved to a `deleted_entities` or `deleted_devices` list. This allows HA to track what was deleted and prevent ID conflicts.

Over time, these lists can grow large and are safe to clean.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-01 14:30:13] Stopping Home Assistant...
[2026-08-01 14:30:22] ✓ Cleaned 89 deleted entities
[2026-08-01 14:30:22] ✓ Cleaned 1 deleted devices
[2026-08-01 14:47:09] ✓ Removed 6 old backup files (older than 7 days)
[2026-08-01 14:47:09] Starting Home Assistant...
[2026-08-01 14:47:24] Done!
```

**When to use:**
- After deleting many entities/devices
- Regular maintenance (quarterly)
- When registry files are getting large

**Files affected:**
- `.storage/core.entity_registry` (deleted_entities list)
- `.storage/core.device_registry` (deleted_devices list)

---

### Option 4: Purge Old Database Records

Removes old states and events from the database based on your recorder configuration.

**How it works:**

1. Reads `purge_keep_days` from your recorder config and logs where it found it (default: 14 days)
2. Tunes SQLite settings (cache size, memory-mapped I/O) for faster deletes
3. Counts purgeable states and events
4. Clears the links old state rows hold to each other, so removing them doesn't leave broken internal references
5. Batch deletes states older than X days (adaptive batch size with progress)
6. Batch deletes events older than X days
7. Cleans orphaned state_attributes using optimised LEFT JOIN queries
8. Cleans orphaned event_data the same way
9. Restores the SQLite settings from step 2, folds the write-ahead log back into the database, and puts the journal mode back to whatever your database started in
10. Checks disk space, then runs VACUUM to reclaim space (skips if not enough room). Because step 9 already folded the log back in, the size it reports is the size on your disk

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-01 14:30:13] Stopping Home Assistant...
[2026-08-01 14:30:22] Using purge_keep_days: 14 (from default)
[2026-08-01 14:30:22]   [Count] Starting...
[2026-08-01 14:30:23]   [Count] Done in 0.3s — 8,085,627 states, 77,573 events
[2026-08-01 14:30:23] Purging 8,085,627 states, 77,573 events older than 14 days
[2026-08-01 14:30:23]   [States] Starting...
[2026-08-01 14:31:09]     Unlinked 8,029,055 old_state_id references
[2026-08-01 14:31:10]     Batch 1/81: deleted 100,000/8,085,627 (1%)
...
[2026-08-01 14:33:51]     Batch 81/81: deleted 8,085,627/8,085,627 (100%)
[2026-08-01 14:33:51]   [States] Done in 208.6s — deleted 8,085,627 rows
[2026-08-01 14:33:51]   [Events] Starting...
[2026-08-01 14:33:52]   [Events] Done in 0.9s — deleted 77,573 rows
[2026-08-01 14:33:52]   [Orphan Attributes] Starting...
[2026-08-01 14:33:52]     Counting orphans...
[2026-08-01 14:33:58]     Found 3,205,456 orphan rows
[2026-08-01 14:46:19]   [Orphan Attributes] Done in 746.9s — deleted 3,205,456 rows
[2026-08-01 14:46:19]   [Orphan Event Data] Starting...
[2026-08-01 14:46:19]     Counting orphans...
[2026-08-01 14:46:19]     Found 568 orphan rows
[2026-08-01 14:46:19]   [Orphan Event Data] Done in 0.0s — deleted 568 rows
[2026-08-01 14:46:19]   [VACUUM] Starting...
[2026-08-01 14:46:19]     DB size before: 5920.3 MB
[2026-08-01 14:47:09]   [VACUUM] Done in 49.3s — DB: 5920.3 → 2748.5 MB (3171.8 MB saved)
[2026-08-01 14:47:09] ✓ Database purged
[2026-08-01 14:47:09] Database: 5924.4 MB → 2748.5 MB (3175.9 MB saved)
[2026-08-01 14:47:09] Starting Home Assistant...
[2026-08-01 14:47:24] Done!
```

**When to use:**
- Database file is getting too large
- Running low on disk space
- Want to speed up database queries
- Regular maintenance (monthly)

**Where purge_keep_days is read from** (checked in this order):

1. `configuration.yaml`:
   ```yaml
   recorder:
     purge_keep_days: 14
   ```

2. `packages/*.yaml` — if you split your config with `packages: !include_dir_named packages/` and put `recorder:` in there

3. Recorder integration options in `.storage/core.config_entries`

4. Default: 14 days if not configured

The log line tells you which one was used, e.g. `Using purge_keep_days: 14 (from packages/*.yaml)`. If it says `(from default)` and you expected it to find your setting, that's your cue to check where `recorder:` actually lives.

**⚠️ Warning:** This permanently deletes historical data. Make sure your `purge_keep_days` setting is correct before running.

---

### Option 5: Fix Numeric Suffix

Interactively fix entity IDs with `_2`, `_3`, etc. suffixes.

**Why does this happen?**

When you remove and re-add an integration, HA sometimes appends a numeric suffix to prevent ID conflicts:
- `sensor.living_room_temperature` becomes `sensor.living_room_temperature_2`

This happens because the old entity ID is still in the "deleted_entities" list.

**How it works:**

1. Scans entity registry for entities ending in `_2` through `_99`, the range Home Assistant's own numbering produces (it counts up from 2, so a longer number like `sensor.solar_5000` was never something HA generated)
2. Checks if the base entity ID (without suffix) exists
3. Only shows entities where the base ID is available
4. Skips runs where a `_1` sibling exists, since that means the device or integration did the numbering rather than Home Assistant (`sensor.relay_1` alongside `sensor.relay_2`)
5. Skips tails that continue a MAC address (`device_tracker.athena_clients_0c_80_2f_01_da_12`) or a port number after `tcp` / `udp` (`switch.block_dns_udp_53`)
6. Skips any candidate that would collide with another (e.g. both `sensor.x_2` and `sensor.x_3` targeting the same missing `sensor.x`)
7. Lets you interactively select which ones to fix

**Example output:**

```
Found 8 entities with numeric suffix:
======================================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
======================================================================

  [ 1] sensor.living_room_temperature_2
       -> sensor.living_room_temperature (mqtt)
  [ 2] light.bedroom_lamp_3
       -> light.bedroom_lamp (hue)
  [ 3] sensor.tomorrow_io_home_pm2_5
       -> sensor.tomorrow_io_home_pm2 (tomorrowio)  ⚠️ LEGITIMATE!
  [ 4] button.remote_button_4
       -> button.remote_button (zigbee)  ⚠️ LEGITIMATE!
  ...

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to fix all (DANGEROUS!)
  - 'none' or Enter to skip

Selection: 1,2

Will fix 2 entities:
  - sensor.living_room_temperature_2 -> sensor.living_room_temperature
  - light.bedroom_lamp_3 -> light.bedroom_lamp

⚠️  Fix these 2 entities? [y/N]: y
[2026-05-09 12:00:00] Stopping Home Assistant...
[2026-05-09 12:00:05] ✓ Fixed 2 entity suffixes
[2026-05-09 12:00:05] Starting Home Assistant...
[2026-05-09 12:00:10] Done!
```

**Selection syntax:**
- Single: `1` or `5`
- Multiple: `1,3,5`
- Range: `1-5` (fixes 1, 2, 3, 4, 5)
- Mixed: `1,3-5,8` (fixes 1, 3, 4, 5, 8)
- All: `all` (⚠️ dangerous!)
- None: `none` or just press Enter

**⚠️ Important:** Always review the list carefully! Some suffixes are legitimate:
- `button_4` - button number 4 on a remote
- `sim_2` - SIM card slot 2
- `pm2_5` - PM2.5 air quality sensor
- `co2_2` - CO2 sensor (not a duplicate)

**When to use:**
- After removing and re-adding an integration
- When you see duplicate-looking entity IDs
- After running option 3 (clean deleted registry items)

**Pro tip:** Run option 3 first to clean deleted_entities, then re-add your integration. This often prevents the suffix from appearing in the first place.

---

### Option 6: Clean Old Backup Files

Removes backup files older than 7 days.

**What are backup files?**

Every time you run options 2, 3, or 5, the script creates timestamped backups:
- `core.entity_registry.backup.20260403_110911`
- `core.device_registry.backup.20260403_110911`

These accumulate over time and can be safely deleted after 7 days.

**Example output:**

```
✓ Removed 5 old backup files
```

or

```
✓ No old backup files to remove
```

**When to use:**
- Regular maintenance (monthly)
- Running low on disk space
- After multiple cleanup operations

**⚠️ Note:** This does NOT require HA restart and runs immediately.

**Files cleaned:**
- `.storage/*.backup.*` files older than 7 days

---

### Option 7: Restore from Backup

See the [Restore from Backup](#restore-from-backup) section above for full details.

---

## What Gets Cleaned

### Orphaned Entities
Entities that reference:
- Deleted devices (device_id no longer exists)
- Deleted config entries (integration removed)
- Deleted automations/scripts/scenes (ID not found in YAML or UI)

### Numeric Suffix Fix
When you remove and re-add an integration, HA sometimes appends `_2` to entity IDs:
- `sensor.living_room_temperature_2` → `sensor.living_room_temperature`

**⚠️ Important:** Not all `_N` suffixes are duplicates! Some are legitimate:
- `button_4` - button number 4
- `sim_2` - SIM slot 2
- `pm2_5` - PM2.5 sensor

That's why this feature uses interactive selection.

### Deleted Registry Items
Soft-deleted entries in:
- `core.entity_registry` (deleted_entities)
- `core.device_registry` (deleted_devices)

### Database Purge
Old records based on your `recorder.purge_keep_days` setting:
- States older than X days
- Events older than X days
- Orphaned state_attributes and event_data (cleaned with optimised queries)
- VACUUM to reclaim disk space (with disk space check)

---

## Config Path Detection

The script automatically detects your Home Assistant config directory:

| Installation | Config Path |
|--------------|-------------|
| **HAOS** | `/homeassistant` |
| **Docker** | `/config` |
| **Core** | `~/.homeassistant` |

---

## Troubleshooting

### Script Can't Find Config Directory

```
Error: Could not find Home Assistant config directory
```

**Solution**: Run from within the config directory.

### Permission Denied

```bash
sudo python3 ha-cleanup.py
```

### Home Assistant Won't Stop/Start

The script tries multiple methods to stop/start HA:
- `ha core stop/start` (HAOS)
- `systemctl stop/start home-assistant@homeassistant` (Core)
- `docker stop/start homeassistant` (Docker)

If none work, the script will prompt you to stop/start HA manually.

### Database Locked

Ensure Home Assistant is fully stopped before running cleanup.

### VACUUM Skipped Due to Disk Space

```
⚠️  Skipping VACUUM — not enough disk space (DB: 5920.3 MB, free: 3000.0 MB, need: 6512.3 MB)
```

VACUUM needs roughly the same amount of free space as your database file. Free up disk space or skip VACUUM — the purge itself still works without it.

---

## Safety Features

| Feature | Description |
|---------|-------------|
| **Auto Backup** | Registry files backed up before modification, with sub-second collision protection |
| **Dry Run** | Preview all changes without risk |
| **Interactive Suffix Fix** | Manual selection prevents accidental changes |
| **Suffix Collision Detection** | Skips candidates that would rewrite two entities to the same ID |
| **Fresh Registry Read on Restore** | Re-reads the registry after HA stops so concurrent HA writes aren't lost |
| **Confirmation** | Asks before stopping HA |
| **Graceful Stop** | Properly stops HA before database operations |
| **VACUUM Disk Check** | Checks free disk space before VACUUM, skips if not enough room |
| **Progress Feedback** | Every purge phase shows elapsed time and batch progress |

---

## Support

For issues and questions:

1. Check the [Troubleshooting](#troubleshooting) section
2. Run with dry run (`d` option) first to preview changes
3. For usage questions, ask in [Discussions](https://github.com/hiall-fyi/ha-cleanup/discussions)
4. For a bug or a feature idea, [open an issue](https://github.com/hiall-fyi/ha-cleanup/issues/new/choose). The form asks for a few things up front, including your dry-run output, which is read-only and usually enough to pin the problem down.

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

<div align="center">

**Made with ❤️ by Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))**

</div>

---

**Version**: 1.7.1  
**Last Updated**: 2026-08-01  
**Tested On**: Home Assistant 2026.7.4, full cleanup on a live 5.9 GB database

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
