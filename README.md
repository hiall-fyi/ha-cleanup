# Home Assistant Cleanup

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.3.0-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github)

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

---

## Features

| Feature | Description |
|---------|-------------|
| **Interactive Menu** | Easy-to-use menu for selecting cleanup operations |
| **Orphaned Entity Cleanup** | Removes entities with missing device/config/automation/script/scene |
| **Fix Numeric Suffix** | Interactive selection to fix `_2`, `_3` suffixes (with safety warnings) |
| **Deleted Registry Cleanup** | Clears `deleted_entities` and `deleted_devices` lists |
| **Database Purge** | Removes states/events older than your recorder setting + VACUUM |
| **Restore from Backup** | Selective or full restore of entities from backup files |
| **Auto-Detect Config** | Reads `purge_keep_days` from your HA recorder configuration |
| **Dry-Run Mode** | Preview all changes without modifying anything |
| **Auto Backup** | Backs up registry files before any modifications |

---

## Prerequisites

- **Home Assistant**: Any installation type (HAOS, Docker, Core)
- **Python**: 3.8 or higher
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
  Home Assistant Cleanup Tool
======================================================================
  Config: /homeassistant
  Database: 1215.6 MB
======================================================================

  1. Full cleanup (options 2-4, 6)
  2. Remove orphaned entities (missing device/config/definition)
  3. Clean deleted registry items (deleted_entities/devices)
  4. Purge old database records (auto-detect purge_keep_days)
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
[2026-01-28 14:46:08] ==================================================
[2026-01-28 14:46:08] Home Assistant Cleanup (DRY RUN)
[2026-01-28 14:46:08] ==================================================
[2026-01-28 14:46:08] Config path: /homeassistant
[2026-01-28 14:46:08] Database size: 1215.6 MB

[2026-01-28 14:46:08] ✓ No orphaned entities found
[2026-01-28 14:46:08] Would clean 3 deleted entities
[2026-01-28 14:46:08] Using purge_keep_days: 7
[2026-01-28 14:46:08] Would purge 139507 states, 5123 events older than 7 days
[2026-01-28 14:46:08] Found 5 entities with numeric suffix:
[2026-01-28 14:46:08]   - sensor.living_room_temperature_2 -> sensor.living_room_temperature (climate)
...

[2026-01-28 14:46:08] ==================================================
[2026-01-28 14:46:08] Summary:
[2026-01-28 14:46:08]   Orphaned entities: 0
[2026-01-28 14:46:08]   Deleted registry items: 3
[2026-01-28 14:46:08]   Suffix fixes: 5
[2026-01-28 14:46:08] ==================================================
```

### Numeric Suffix Fix (Interactive)

When you select option 5, you'll see an interactive selection:

```
Found 41 entities with numeric suffix:
======================================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
======================================================================

  [ 1] sensor.living_room_temperature_2
       -> sensor.living_room_temperature (climate)
  [ 2] sensor.tomorrow_io_home_pm2_5
       -> sensor.tomorrow_io_home_pm2 (tomorrowio)
  ...

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to fix all (DANGEROUS!)
  - 'none' or Enter to skip

Selection: 1
```

This allows you to manually review and select only the entities that are actually duplicates.

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

  b. Back to main menu
```

### Restore Options

#### 1. List Available Backups

Shows all backup files with timestamps, type, entity count, and file size:

```
Found 26 backup files:
======================================================================
#    Timestamp            Type               Entities   Size (MB)
------------------------------------------------------------
1    2026-02-08 11:40:23  entity_registry    1677       1.50
2    2026-02-08 11:40:23  device_registry    0          0.12
3    2026-02-07 21:17:00  entity_registry    1711       1.58
...
```

#### 2. Preview Backup Differences

Compare a backup with your current registry to see what changed:

```
Backup: core.entity_registry.backup.20260208_114023
Timestamp: 2026-02-08 11:40:23
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
Backup: core.entity_registry.backup.20260208_114023
Timestamp: 2026-02-08 11:40:23
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
4. Cleans old backup files (7+ days)

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-02-08 12:00:00] Stopping Home Assistant...
[2026-02-08 12:00:05] ✓ Removed 5 orphaned entities
[2026-02-08 12:00:06] ✓ Cleaned 3 deleted entities
[2026-02-08 12:00:07] Using purge_keep_days: 7
[2026-02-08 12:00:08] Purging 139507 states, 5123 events older than 7 days
[2026-02-08 12:00:45] ✓ Database purged and vacuumed
[2026-02-08 12:00:46] ✓ Removed 2 old backup files
[2026-02-08 12:00:46] Database: 1215.6 MB → 987.3 MB (228.3 MB saved)
[2026-02-08 12:00:46] Starting Home Assistant...
[2026-02-08 12:00:51] Done!

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
Found 5 orphaned entities:
  - mqtt: sensor.old_temperature (Old Temperature Sensor)
  - hue: light.deleted_bulb (Deleted Bulb)
  - homeassistant: switch.removed_switch (Removed Switch)
  - automation: automation.old_automation
  - script: script.deleted_script

⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-02-08 12:00:00] Stopping Home Assistant...
[2026-02-08 12:00:05] ✓ Removed 5 orphaned entities
[2026-02-08 12:00:05] Starting Home Assistant...
[2026-02-08 12:00:10] Done!
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
[2026-02-08 12:00:00] Stopping Home Assistant...
[2026-02-08 12:00:05] ✓ Cleaned 15 deleted entities
[2026-02-08 12:00:05] ✓ Cleaned 8 deleted devices
[2026-02-08 12:00:05] Starting Home Assistant...
[2026-02-08 12:00:10] Done!
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

1. Reads `purge_keep_days` from your recorder config (default: 14 days)
2. Deletes states older than X days
3. Deletes events older than X days
4. Cleans orphaned state_attributes and event_data
5. Runs VACUUM to reclaim disk space

**Example output:**

```
Using purge_keep_days: 7

⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-02-08 12:00:00] Stopping Home Assistant...
[2026-02-08 12:00:05] Purging 139507 states, 5123 events older than 7 days
[2026-02-08 12:00:45] ✓ Database purged and vacuumed
[2026-02-08 12:00:45] Database: 1215.6 MB → 987.3 MB (228.3 MB saved)
[2026-02-08 12:00:45] Starting Home Assistant...
[2026-02-08 12:00:50] Done!
```

**When to use:**
- Database file is getting too large
- Running low on disk space
- Want to speed up database queries
- Regular maintenance (monthly)

**Where purge_keep_days is read from:**

1. `configuration.yaml`:
   ```yaml
   recorder:
     purge_keep_days: 7
   ```

2. Recorder integration options in `.storage/core.config_entries`

3. Default: 14 days if not configured

**⚠️ Warning:** This permanently deletes historical data. Make sure your `purge_keep_days` setting is correct before running.

---

### Option 5: Fix Numeric Suffix

Interactively fix entity IDs with `_2`, `_3`, etc. suffixes.

**Why does this happen?**

When you remove and re-add an integration, HA sometimes appends a numeric suffix to prevent ID conflicts:
- `sensor.living_room_temperature` becomes `sensor.living_room_temperature_2`

This happens because the old entity ID is still in the "deleted_entities" list.

**How it works:**

1. Scans entity registry for entities ending with `_N` (where N >= 2)
2. Checks if the base entity ID (without suffix) exists
3. Only shows entities where the base ID is available
4. Lets you interactively select which ones to fix

**Example output:**

```
Found 41 entities with numeric suffix:
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
[2026-02-08 12:00:00] Stopping Home Assistant...
[2026-02-08 12:00:05] ✓ Fixed 2 entity suffixes
[2026-02-08 12:00:05] Starting Home Assistant...
[2026-02-08 12:00:10] Done!
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
- `core.entity_registry.backup.20260208_120000`
- `core.device_registry.backup.20260208_120000`

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
- Orphaned state_attributes and event_data
- Runs VACUUM to reclaim disk space

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

---

## Safety Features

| Feature | Description |
|---------|-------------|
| **Auto Backup** | Registry files backed up before modification |
| **Dry Run** | Preview all changes without risk |
| **Interactive Suffix Fix** | Manual selection prevents accidental changes |
| **Confirmation** | Asks before stopping HA |
| **Graceful Stop** | Properly stops HA before database operations |

---

## Support

For issues and questions:

1. Check the [Troubleshooting](#troubleshooting) section
2. Run with dry run (`d` option) first to preview changes
3. [Open an issue on GitHub](https://github.com/hiall-fyi/ha-cleanup/issues)

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

## Star History

If you find this script useful, please consider giving it a star!

[![Star History Chart](https://api.star-history.com/svg?repos=hiall-fyi/ha-cleanup&type=Date)](https://star-history.com/#hiall-fyi/ha-cleanup&Date)

---

<div align="center">

### Support This Project

If this script saved you from "ghost entity" headaches, consider supporting the project!

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Made with love by Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))**

</div>

---

**Version**: 1.3.0  
**Last Updated**: 2026-02-08  
**Tested On**: Home Assistant 2024.x (HAOS, Docker, Core)

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
