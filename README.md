# Home Assistant Cleanup

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.2.0-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github)

**Interactive cleanup tool for Home Assistant - Remove orphaned entities, fix entity suffixes, clean registries, purge old database records.**

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
==================================================
  Home Assistant Cleanup Tool
==================================================
  Config: /homeassistant
  Database: 1215.6 MB
==================================================

  1. Full cleanup (all operations)
  2. Remove orphaned entities
  3. Clean deleted registry items
  4. Purge old database records
  5. Fix numeric suffix (_2, _3, etc.)
  6. Clean old backup files

  d. Dry run (preview all)
  q. Quit

  Select option:
```

### Menu Options

| Option | Description | Requires HA Restart |
|--------|-------------|---------------------|
| **1** | Run all cleanup operations (except suffix fix) | Yes |
| **2** | Remove orphaned entities only | Yes |
| **3** | Clean deleted registry items only | Yes |
| **4** | Purge old database records only | Yes |
| **5** | Fix numeric suffix (interactive selection) | Yes |
| **6** | Clean old backup files (7+ days) | No |
| **d** | Dry run - preview all changes | No |
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
============================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
============================================================

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

**Version**: 1.2.0  
**Last Updated**: 2026-01-31  
**Tested On**: Home Assistant 2024.x (HAOS, Docker, Core)

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
