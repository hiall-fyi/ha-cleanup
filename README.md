# Home Assistant Cleanup

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.6+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.8.1-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github)

<!-- Support -->
[![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Interactive cleanup tool for Home Assistant - Remove orphaned entities, fix entity suffixes, clean registries, purge old database records, restore from backups, or run the automatable ones unattended from cron.**

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
| **Scheduled Runs** | Run one cleanup option unattended from cron or a systemd timer with `--run=<option> --yes`, exiting non-zero so a failure is visible to whatever's watching |
| **Orphaned Entity Cleanup** | Removes entities with missing device/config/automation/script/scene |
| **Fix Numeric Suffix** | Interactive selection to fix `_2`, `_3` suffixes. Limited to the range Home Assistant actually generates, so model numbers, MAC addresses and port numbers are left alone, with collision detection so you can't accidentally rename two entities to the same ID |
| **Deleted Registry Cleanup** | Clears `deleted_entities` and `deleted_devices` lists |
| **Database Purge** | Removes states/events older than your recorder setting, with optimised batch deletes, adaptive batch sizing, and real-time progress |
| **Orphaned Statistics Cleanup** | Removes long-term statistics for entities no longer in the registry, leaving external statistics (utility meters, energy-dashboard cost sensors) untouched |
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

Run this from inside your Home Assistant config directory (`cd /config` first if you're connected via an SSH or Terminal add-on). That folder is a persistent volume, and the script survives add-on and Core updates there. Saved anywhere else inside an add-on's own container, it can vanish the next time that add-on rebuilds.

### 2. Run

```bash
python3 ha-cleanup.py
```

---

## Usage

### Interactive Menu

```
======================================================================
  Home Assistant Cleanup Tool  v1.8.1
======================================================================
  Config: /homeassistant
  Database: 5938.4 MB
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
  5. Remove orphaned long-term statistics (entity no longer exists)
  6. Clean old backup files (>7 days)
  7. Fix numeric suffix (_2, _3, etc.) - interactive
  8. Restore from backup (selective or full)

  d. Dry run (preview all)
  q. Quit

  Select option:
```

### Menu Options

| Option | Description | Requires HA Restart |
|--------|-------------|---------------------|
| **1** | Run cleanup operations 2-4, 6 (excludes interactive suffix fix and the standalone statistics cleanup) | Yes |
| **2** | Remove orphaned entities (missing device/config/definition) | Yes |
| **3** | Clean deleted_entities and deleted_devices from registries | Yes |
| **4** | Purge old database records (auto-detects purge_keep_days) | Yes |
| **5** | Remove orphaned long-term statistics (entity no longer exists) | Yes |
| **6** | Clean backup files older than 7 days | No |
| **7** | Fix numeric suffix like _2, _3 (interactive selection) | Yes |
| **8** | Restore from backup (selective or full restore) | Yes |
| **d** | Dry run - preview all changes without modifying | No |
| **q** | Quit | - |

### Dry Run Preview

Select `d` from the menu to preview all changes:

```
[2026-08-22 12:42:09] ==================================================
[2026-08-22 12:42:09] Home Assistant Cleanup (DRY RUN)
[2026-08-22 12:42:09] ==================================================
[2026-08-22 12:42:09] Config path: /homeassistant
[2026-08-22 12:42:09] Database size: 5938.4 MB
[2026-08-22 12:42:09] ✓ No orphaned entities found
[2026-08-22 12:42:09] ✓ No deleted registry items to clean
[2026-08-22 12:42:09] Using purge_keep_days: 14 (from default)
[2026-08-22 12:42:09]   [Count] Starting...
[2026-08-22 12:42:09]   [Count] Done in 0.3s — 8,399,813 states, 101,774 events
[2026-08-22 12:42:09] Would purge 8,399,813 states, 101,774 events older than 14 days
[2026-08-22 12:42:09] Would VACUUM (DB: 5938.4 MB, free: 8613.2 MB, est. 59s)
[2026-08-22 12:42:09] Found 12 entities with numeric suffix:
[2026-08-22 12:42:09]   - device_tracker.cronus_clients_pixel_6 -> device_tracker.cronus_clients_pixel (mikrotik_ce)
[2026-08-22 12:42:09]   - sensor.met_office_pm2_5 -> sensor.met_office_pm2 (atmos_ce)
[2026-08-22 12:42:09]   - button.cronus_wake_pixel_6 -> button.cronus_wake_pixel (mikrotik_ce)
...
[2026-08-22 12:42:09] 
==================================================
[2026-08-22 12:42:09] Summary:
[2026-08-22 12:42:09]   Orphaned entities: 0
[2026-08-22 12:42:09]   Deleted registry items: 0
[2026-08-22 12:42:09]   DB states to purge: 8,399,813
[2026-08-22 12:42:09]   DB events to purge: 101,774
[2026-08-22 12:42:09]   Suffix fixes: 12
[2026-08-22 12:42:09]   Old backup files: 0
[2026-08-22 12:42:09]   Orphaned statistics: 0
[2026-08-22 12:42:09] ==================================================
```

### Scheduled / Non-Interactive Runs

Options 1-4, 5 and 6 can run without the menu, using `--run=<option>` plus
`--yes` to skip the confirmation prompt:

```bash
python3 ha-cleanup.py --run=3 --yes
```

```
[2026-08-22 12:38:01] Stopping Home Assistant...
[2026-08-22 12:38:10] ✓ Cleaned 49 deleted entities
[2026-08-22 12:38:10] ✓ Cleaned 4 deleted devices
[2026-08-22 12:38:10] ✓ Removed 2 old backup files (older than 7 days)
[2026-08-22 12:38:10] Database: 5932.1 MB → 5927.2 MB (4.9 MB saved)
[2026-08-22 12:38:10] Starting Home Assistant...
[2026-08-22 12:38:21] Done!
```

This is the flag combination for a cron job or systemd timer — nothing
prompts, and the process exits `0` on success or non-zero if anything
failed, so cron's own failure notification (mail, `OnFailure=`, a
healthcheck ping) picks it up. Options 7 and 8 need you to pick specific
entities or a specific backup, so they're rejected with an explanation
rather than run unattended:

```
$ python3 ha-cleanup.py --run=7 --yes
[2026-08-22 12:36:27] Option 7 requires interactive selection and can't be automated.
$ echo $?
2
```

`--dry-run` combines with `--run` to preview a single option instead of
everything:

```bash
python3 ha-cleanup.py --run=3 --dry-run
```

```
[2026-08-22 12:36:27] Would clean 49 deleted entities
[2026-08-22 12:36:27] Would clean 4 deleted devices
```

**Cron**, once a week at 4am:

```cron
0 4 * * 0 cd /path/to/config && python3 ha-cleanup.py --run=3 --yes >> /var/log/ha-cleanup.log 2>&1
```

**Options 1-4 and 5 need to stop Home Assistant, so they need to run from
somewhere that actually can stop it**: a host-level cron job or systemd
timer, as above, or a scheduler add-on that runs outside HA's own container
(the SSH & Terminal add-on's own cron, for example). Home Assistant's
`shell_command:` runs *inside* HA Core's own container, and that container
has none of `ha`, `systemctl` or `docker` available to it. Every way this
tool tries to stop HA fails from in there, so options 1-4 and 5 triggered
this way always abort with "Could not stop HA automatically", whatever you
pass on the command line.

**Option 6 doesn't stop HA at all**, so it's the one that's actually safe to
trigger from `shell_command:`:

```yaml
shell_command:
  ha_cleanup_old_backups: "python3 /path/to/ha-cleanup.py --run=6 --yes"
```

```yaml
automation:
  - alias: "Weekly Backup Cleanup"
    trigger:
      - platform: time
        at: "04:00:00"
    condition:
      - condition: time
        weekday:
          - sun
    action:
      - action: shell_command.ha_cleanup_old_backups
        response_variable: cleanup_result
      - if: "{{ cleanup_result['returncode'] != 0 }}"
        then:
          - action: notify.persistent_notification
            data:
              message: >-
                ha-cleanup failed (exit {{ cleanup_result['returncode'] }}):
                {{ cleanup_result['stderr'] }}
```

`response_variable` is what makes the exit code visible to HA at all — without
it, `shell_command:` is fire-and-forget and a failed run just quietly doesn't
happen. `returncode` is `0` for success, `1` if the option itself failed, `2`
if `--run` was pointed at an option that needs interactive selection.

### Numeric Suffix Fix (Interactive)

When you select option 7, you'll see an interactive selection:

```
Found 12 entities with numeric suffix:
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

Select option **8** from the main menu to access the restore submenu:

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

⚠️  Suffix fix requires manual selection. Run option 7 separately.
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
[2026-08-22 12:46:23] Stopping Home Assistant...
[2026-08-22 12:46:32] ✓ No orphaned entities found
[2026-08-22 12:46:32] ✓ No old backup files to remove (found 2 backups, all within 7 days)
[2026-08-22 12:46:32] Starting Home Assistant...
[2026-08-22 12:46:47] Done!
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
[2026-08-22 12:38:01] Stopping Home Assistant...
[2026-08-22 12:38:10] ✓ Cleaned 49 deleted entities
[2026-08-22 12:38:10] ✓ Cleaned 4 deleted devices
[2026-08-22 12:38:10] ✓ Removed 2 old backup files (older than 7 days)
[2026-08-22 12:38:10] Starting Home Assistant...
[2026-08-22 12:38:21] Done!
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
[2026-08-22 12:46:55] Stopping Home Assistant...
[2026-08-22 12:47:04] Using purge_keep_days: 14 (from default)
[2026-08-22 12:47:04]   [Count] Starting...
[2026-08-22 12:47:04]   [Count] Done in 0.3s — 8,401,505 states, 101,796 events
[2026-08-22 12:47:04] Purging 8,401,505 states, 101,796 events older than 14 days
[2026-08-22 12:47:04]   [States] Starting...
[2026-08-22 12:47:38]     Unlinked 8,293,904 old_state_id references
[2026-08-22 12:47:39]     Batch 1/85: deleted 100,000/8,401,505 (1%)
...
[2026-08-22 12:49:34]     Batch 85/85: deleted 8,401,505/8,401,505 (100%)
[2026-08-22 12:49:34]   [States] Done in 149.9s — deleted 8,401,505 rows
[2026-08-22 12:49:34]   [Events] Starting...
[2026-08-22 12:49:35]   [Events] Done in 0.7s — deleted 101,796 rows
[2026-08-22 12:49:35]   [Orphan Attributes] Starting...
[2026-08-22 12:49:35]     Counting orphans...
[2026-08-22 12:49:43]     Found 3,018,013 orphan rows
[2026-08-22 12:59:35]   [Orphan Attributes] Done in 600.1s — deleted 3,018,013 rows
[2026-08-22 12:59:35]   [Orphan Event Data] Starting...
[2026-08-22 12:59:35]     Counting orphans...
[2026-08-22 12:59:35]     Found 995 orphan rows
[2026-08-22 12:59:35]   [Orphan Event Data] Done in 0.0s — deleted 995 rows
[2026-08-22 12:59:35]   [VACUUM] Starting...
[2026-08-22 12:59:35]     DB size before: 5927.2 MB
[2026-08-22 13:00:38]   [VACUUM] Done in 63.3s — DB: 5927.2 → 2839.9 MB (3087.3 MB saved)
[2026-08-22 13:00:38] ✓ Database purged
[2026-08-22 13:00:38] Database: 5938.5 MB → 2839.9 MB (3098.6 MB saved)
[2026-08-22 13:00:38] Starting Home Assistant...
[2026-08-22 13:00:55] Done!
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

### Option 5: Remove Orphaned Long-Term Statistics

Removes long-term statistics for entities that no longer exist in the registry.

**Why does this happen?**

Home Assistant keeps long-term statistics in the database independently of the entity registry. Deleting an entity, or removing the integration that provided it, doesn't touch its old `statistics_meta` row or the hourly/5-minute data linked to it — the numbers just sit there under an entity ID nothing points to any more. Core Home Assistant has no UI for finding these; a diagnostics add-on like Spook is usually how people first notice they exist.

**How it works:**

1. Reads every `statistics_meta` row where `source = 'recorder'` — the ones keyed by a real entity_id
2. Checks each row's `statistic_id` against the current entity registry
3. For anything absent from the registry, also checks whether it's still writing new statistics within the last 7 days. A YAML `template:`, `mqtt:`, `command_line`, or `sql` sensor with `state_class` set but no `unique_id` is live but never appears in the registry, so without this check it would look identical to a genuinely deleted entity
4. For anything both absent from the registry and with no recent statistics, deletes its rows from `statistics` and `statistics_short_term` first, then the `statistics_meta` row itself
5. Logs the total number of orphaned statistics removed

**What it leaves alone:**

Statistics with any `source` other than `recorder` — utility meter helpers, energy-dashboard cost sensors, and other externally-computed statistics — use a different `statistic_id` shape and are never evaluated against the registry. They're left exactly as they are, whether or not the entity behind them still exists.

Entities absent from the registry but still writing new statistics. A YAML `template:`, `mqtt:`, `command_line`, or `sql` sensor with `state_class` set but no `unique_id` never gets a registry entry, even though it's live and still recording data. As long as its `statistics` table has a row newer than 7 days, it's treated as live and left alone.

**A note on timing:**

If a diagnostics tool like Spook already lists something as an orphaned statistic, this option might not remove it straight away — it's most likely still inside that 7-day window. Spook flags a statistic the moment its entity is gone; this tool waits until the data itself has gone quiet too, as the safety margin described above. Run it again in a few days and it'll catch up.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-09-01 06:50:36] Stopping Home Assistant...
[2026-09-01 06:50:46]   [Orphan statistics] Starting...
[2026-09-01 06:50:46]     Batch 1/1: deleted 44/44 (100%)
[2026-09-01 06:50:46]   [Orphan statistics] Done in 0.0s — deleted 44 rows
[2026-09-01 06:50:46]   [Orphan statistics_short_term] Starting...
[2026-09-01 06:50:46]   [Orphan statistics_short_term] Done in 0.0s — deleted 0 rows
[2026-09-01 06:50:46] ✓ Removed 4 orphaned statistics
[2026-09-01 06:50:46] ✓ Removed 2 old backup files (older than 7 days)
[2026-09-01 06:50:46] Database: 4684.3 MB → 4678.8 MB (5.5 MB saved)
[2026-09-01 06:50:46] Starting Home Assistant...
[2026-09-01 06:51:01] Done!
```

`statistics_short_term` only holds a rolling few days, so it's common for it to have nothing left to delete by the time an entity's been gone long enough to show up here — that's what the zero above is.

**When to use:**
- After removing an integration that had months or years of history — its graphs are gone from the UI, but the numbers are still in the database
- Alongside regular database maintenance (option 4) — the purge only touches `states`/`events`, this is the same idea for long-term statistics
- Before or after running a diagnostics add-on like Spook, if you want the statistics side of things already clean

---

### Option 6: Clean Old Backup Files

Removes backup files older than 7 days.

**What are backup files?**

Every time you run options 2, 3, or 7, the script creates timestamped backups:
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

### Option 7: Fix Numeric Suffix

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

### Option 8: Restore from Backup

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

### Script Disappears After an Update

Likely saved inside an SSH or Terminal add-on's own container rather than `/config`. Those add-ons run as their own container, separate from Home Assistant Core, and get rebuilt from scratch on their own updates, not just Core's, taking anything outside `/config` with them.

**Solution**: Save `ha-cleanup.py` directly under `/config`. It's a persistent volume, so it survives both Core and add-on updates.

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

Under `--run`/`--yes` with no terminal attached (a cron job), there's
nothing to prompt — the run aborts safely instead of hanging, and the
process exits non-zero so the failure is visible to whatever's watching
the cron job.

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
| **Unattended Failure Visibility** | Under `--run`, exits non-zero on any failure (declined or failed auto-stop, a failed operation) so cron or a healthcheck notices |
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

## Credits

See [CREDITS.md](CREDITS.md) for everyone who's helped shape this tool through bug reports, feature requests, and testing.

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

**Version**: 1.8.1  
**Last Updated**: 2026-09-03  
**Tested On**: Home Assistant 2026.8.2, `--run=2/3/4 --yes` (and interactively) on a live 5.9 GB database — 49 deleted entities + 4 deleted devices cleaned, 8.4M states + 3M orphan rows purged and VACUUMed (5938.5 → 2839.9 MB), registry and DB integrity verified before/after, HA restarted clean each time. Option 5 tested separately on 2026.8.3, same box: found and removed 4 orphaned statistics (44 long-term rows, left over from a retired device) after confirming all four were genuinely absent from the entity registry, then a follow-up dry run found nothing left, and HA restarted clean. The 1.8.1 fix confirmed on that same box's real Python 3.14.7 on 2026-09-03: `sys.stdin.isatty()` reports `False` under a `shell_command:`-style non-interactive invocation, which is what the fix relies on to tell that case apart from a real terminal.

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
