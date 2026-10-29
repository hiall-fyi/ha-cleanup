# Home Assistant Cleanup

<div align="center">

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.6+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white) ![Stable](https://img.shields.io/badge/Stable-1.8.3-brightgreen?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-lightgrey?style=for-the-badge)

![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) [![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Interactive cleanup tool for Home Assistant. It removes orphaned entities, fixes entity suffixes, cleans registries, purges old database records and restores from backups, and the automatable options can run unattended from cron.**

[Features](#features) • [Quick Start](#quick-start) • [Usage](#usage) • [Troubleshooting](#troubleshooting) • [Features Guide](FEATURES_GUIDE.md)

</div>

---

## Why HA Cleanup?

Home Assistant accumulates "ghost entities" over time: entities that stay behind after you remove an integration or a device. They clutter your entity list and make it harder to tell what is real.

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
| **Interactive Menu** | Menu for selecting cleanup operations |
| **Scheduled Runs** | Run one cleanup option unattended from cron or a systemd timer with `--run=<option> --yes`, exiting non-zero so a failure is visible to whatever's watching |
| **Orphaned Entity Cleanup** | Removes entities with missing device/config/automation/script/scene |
| **Fix Numeric Suffix** | Interactive selection to fix `_2`, `_3` suffixes. Limited to the range Home Assistant actually generates, so model numbers, MAC addresses and port numbers are left alone, with collision detection so you can't accidentally rename two entities to the same ID |
| **Deleted Registry Cleanup** | Clears `deleted_entities` and `deleted_devices` lists |
| **Database Purge** | Removes states/events older than your recorder setting, with optimised batch deletes, adaptive batch sizing, and real-time progress |
| **Orphaned Statistics Cleanup** | Removes long-term statistics for entities no longer in the registry, leaving external statistics (utility meters, energy-dashboard cost sensors) untouched |
| **Smart VACUUM** | Checks disk space before running VACUUM, skips if there's not enough room |
| **Restore from Backup** | Selective or full restore of entities from backup files, safe against concurrent HA writes |
| **Auto-Detect Config** | Reads `purge_keep_days` from `configuration.yaml`, `packages/*.yaml`, or the recorder config entry, and logs which source it used |
| **Dry-Run Mode** | Preview all changes (including old backup cleanup) without changing any data |
| **Auto Backup** | Backs up each registry file before changing it, with sub-second collision protection. The recorder database is not backed up |

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
  Home Assistant Cleanup Tool  v1.8.3
======================================================================
  Config: /homeassistant
  Database: 5229.8 MB
----------------------------------------------------------------------
  ⚠️  This tool modifies HA registries and database.
     Always back up first.
  💡 DB purge on large DBs may take several minutes,
     progress will be shown.
======================================================================

  1. Full cleanup (options 2-4, 6, optimised)
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

Each option is described step by step in the [Features Guide](FEATURES_GUIDE.md#detailed-feature-guide), and the restore menu in [Restore from Backup](FEATURES_GUIDE.md#restore-from-backup).

### Dry Run Preview

Select `d` from the menu to preview all changes:

```
[2026-09-04 05:57:23] ==================================================
[2026-09-04 05:57:23] Home Assistant Cleanup (DRY RUN)
[2026-09-04 05:57:23] ==================================================
[2026-09-04 05:57:23] Config path: /homeassistant
[2026-09-04 05:57:23] Database size: 5229.8 MB
[2026-09-04 05:57:23] ✓ No orphaned entities found
[2026-09-04 05:57:23] Would clean 143 deleted entities
[2026-09-04 05:57:23] Would clean 1 deleted devices
[2026-09-04 05:57:23] Using purge_keep_days: 14 (from default)
[2026-09-04 05:57:23]   [Count] Starting...
[2026-09-04 05:57:24]   [Count] Done in 0.5s (6,721,762 states, 60,169 events)
[2026-09-04 05:57:24] Would purge 6,721,762 states, 60,169 events older than 14 days
[2026-09-04 05:57:24] Would VACUUM (DB: 5229.8 MB, free: 9147.7 MB, est. 52s)
[2026-09-04 05:57:24] Found 12 entities with numeric suffix:
[2026-09-04 05:57:24]   - device_tracker.cronus_clients_pixel_6 -> device_tracker.cronus_clients_pixel (mikrotik_ce)
[2026-09-04 05:57:24]   - sensor.met_office_pm2_5 -> sensor.met_office_pm2 (atmos_ce)
[2026-09-04 05:57:24]   - button.cronus_wake_pixel_6 -> button.cronus_wake_pixel (mikrotik_ce)
...
[2026-09-04 05:57:24] 
==================================================
[2026-09-04 05:57:24] Summary:
[2026-09-04 05:57:24]   Orphaned entities: 0
[2026-09-04 05:57:24]   Deleted registry items: 144
[2026-09-04 05:57:24]   DB states to purge: 6,721,762
[2026-09-04 05:57:24]   DB events to purge: 60,169
[2026-09-04 05:57:24]   Suffix fixes: 12
[2026-09-04 05:57:24]   Old backup files: 0
[2026-09-04 05:57:24]   Orphaned statistics: 0
[2026-09-04 05:57:24] ==================================================
```

### Scheduled / Non-Interactive Runs

Options 1 to 6 can run without the menu. `--run=<option>` picks one and `--yes` skips the confirmation prompt:

```bash
python3 ha-cleanup.py --run=3 --yes
```

Nothing prompts. The exit code is `0` on success, `1` if the option failed, and `2` if `--run` was pointed at option 7 or 8, which need you to pick entities or a backup. Cron's own failure notification, a systemd `OnFailure=` or a healthcheck ping can pick that up. Add `--dry-run` to preview a single option instead of everything:

```bash
python3 ha-cleanup.py --run=3 --dry-run
```

Once a week at 4am from cron:

```cron
0 4 * * 0 cd /path/to/config && python3 ha-cleanup.py --run=3 --yes >> /var/log/ha-cleanup.log 2>&1
```

**Options 1 to 5 need to stop Home Assistant**, so run them from somewhere that can: a host-level cron job or systemd timer, or a scheduler add-on that runs outside HA's own container. Home Assistant's `shell_command:` runs inside HA Core's container, which has none of `ha`, `systemctl` or `docker`, so those options abort there with "Could not stop HA automatically". **Option 6 doesn't stop HA**, so it is the one that's safe to trigger from `shell_command:`.

The full `shell_command:` automation with exit-code alerting, running from a separate host over SSH, and the interactive suffix-fix walkthrough are in the [Features Guide](FEATURES_GUIDE.md#usage-details).

---

## Documentation

| Document | Purpose |
|----------|---------|
| [FEATURES_GUIDE.md](FEATURES_GUIDE.md) | Every option in detail, the restore menu, unattended and remote runs, what gets cleaned, verification record |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CREDITS.md](CREDITS.md) | Who helped shape each release |
| [SECURITY.md](SECURITY.md) | How to report a vulnerability |

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

The script has to write to the `.storage` folder in your config directory and stop Home Assistant. If you get a permission error, run it as a user that can do both:

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
nothing to prompt, so the run aborts safely instead of hanging, and the
process exits non-zero so the failure is visible to whatever's watching
the cron job.

### Database Locked

A `database is locked` error means Home Assistant hasn't fully stopped yet. Stop it completely, then run the cleanup again.

### VACUUM Skipped Due to Disk Space

```
⚠️  Skipping VACUUM: not enough disk space (DB: 5920.3 MB, free: 3000.0 MB, need: 6512.3 MB)
```

VACUUM needs roughly the same amount of free space as your database file. Free up disk space or skip VACUUM. The purge itself still works without it.

---

## Safety Features

| Feature | Description |
|---------|-------------|
| **Auto Backup** | Each registry file is backed up before it is changed, with sub-second collision protection |
| **Dry Run** | Preview all changes without deleting or rewriting anything |
| **Interactive Suffix Fix** | Manual selection prevents accidental changes |
| **Suffix Collision Detection** | Skips candidates that would rewrite two entities to the same ID |
| **Fresh Registry Read on Restore** | Re-reads the registry after HA stops so concurrent HA writes aren't lost |
| **Confirmation** | Asks before stopping HA (skipped with `--yes`) |
| **Unattended Failure Visibility** | Under `--run`, exits non-zero on any failure (declined or failed auto-stop, a failed operation) so cron or a healthcheck notices |
| **Graceful Stop** | Stops HA before the options that change registries or the database, and starts it again afterwards |
| **VACUUM Disk Check** | Checks free disk space before VACUUM, skips if not enough room |
| **Progress Feedback** | Each purge phase logs how long it took, and the row deletes show batch progress |

---

## Support

For issues and questions:

1. Check the [Troubleshooting](#troubleshooting) section
2. Run with dry run (`d` option) first to preview changes
3. For usage questions, ask in [Discussions](https://github.com/hiall-fyi/ha-cleanup/discussions)
4. For a bug or a feature idea, [open an issue](https://github.com/hiall-fyi/ha-cleanup/issues/new/choose). The form asks for a few things up front, including your dry-run output, which is read-only and the most useful thing to include.

---

## Credits

See [CREDITS.md](CREDITS.md) for everyone who's helped shape this tool through bug reports, feature requests, and testing.

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Contributing

Most changes here start from a GitHub Issue or Discussion. If you've hit a problem, [open a bug report](https://github.com/hiall-fyi/ha-cleanup/issues/new/choose) with your dry-run output. If you have an idea, float it in [Discussions](https://github.com/hiall-fyi/ha-cleanup/discussions) first.

Code contributions are welcome too: fork, branch, commit, and open a pull request. The tool deliberately stays a single file with no dependencies beyond the Python standard library, so changes that need an installed package are unlikely to land.

---

**Version**: 1.8.3  
**Last Updated**: 2026-10-29  
**Tested On**: see the [verification record](FEATURES_GUIDE.md#verification-record)

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
