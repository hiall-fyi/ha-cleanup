# Home Assistant Cleanup

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue?style=for-the-badge&logo=home-assistant) ![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.0.1-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/ha-cleanup?style=for-the-badge&logo=github)

**Automated cleanup script for Home Assistant - Remove orphaned entities, clean registries, purge old database records.**

[Features](#features) • [Quick Start](#quick-start) • [Usage](#usage) • [Troubleshooting](#troubleshooting)

</div>

---

## Why HA Cleanup?

Home Assistant accumulates "ghost entities" over time - entities that persist after removing integrations or devices. These clutter your entity list and can cause confusion.

**Common issues this solves:**

- Orphaned entities from deleted integrations
- Deleted devices still appearing in registries
- Database bloat from old states/events
- Stale automation references

---

## Features

| Feature | Description |
|---------|-------------|
| **Orphaned Entity Cleanup** | Removes entities with missing device/config/automation definitions |
| **Deleted Registry Cleanup** | Clears `deleted_entities` and `deleted_devices` lists |
| **Database Purge** | Removes states/events older than 14 days + VACUUM |
| **Old Backup Cleanup** | Removes backup files older than 7 days |
| **Auto Backup** | Backs up registry files before any modifications |
| **Dry-Run Mode** | Preview all changes without modifying anything |

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

### 2. Preview Changes (Dry Run)

```bash
python3 ha-cleanup.py --dry-run
```

### 3. Execute Cleanup

```bash
python3 ha-cleanup.py
```

---

## Usage

### Dry Run Mode (Safe Preview)

Preview what would be removed without making any changes:

```bash
python3 ha-cleanup.py --dry-run
```

**Example Output:**

```
[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Home Assistant Cleanup (DRY RUN)
[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Config path: /homeassistant
[2026-01-15 20:00:00] Database size: 256.3 MB

[2026-01-15 20:00:00] Found 12 orphaned entities:
[2026-01-15 20:00:00]   - hue: light.deleted_bulb (Deleted Bulb)
[2026-01-15 20:00:00]   - mqtt: sensor.orphaned_sensor (Orphaned Sensor)
...
[2026-01-15 20:00:00] Would clean 45 deleted entities
[2026-01-15 20:00:00] Would clean 8 deleted devices
[2026-01-15 20:00:00] Using recorder purge_keep_days from configuration.yaml: 7
[2026-01-15 20:00:00] Would purge 125000 states, 89000 events older than 7 days

[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Summary:
[2026-01-15 20:00:00]   Orphaned entities: 12
[2026-01-15 20:00:00]   Deleted registry items: 53
[2026-01-15 20:00:00] ==================================================
```

### Execute Cleanup

Run the actual cleanup (will stop/start HA automatically):

```bash
python3 ha-cleanup.py
```

**What happens:**

1. Stops Home Assistant
2. Backs up registry files
3. Removes orphaned entities
4. Cleans deleted registry items
5. Purges old database records
6. Vacuums database
7. Removes old backup files
8. Starts Home Assistant

---

## Config Path Detection

The script automatically detects your Home Assistant config directory:

| Installation | Config Path |
|--------------|-------------|
| **HAOS** | `/homeassistant` |
| **Docker** | `/config` |
| **Core** | `~/.homeassistant` |

---

## Automation (Optional)

### Cron Job Example

Run cleanup weekly on Sunday at 3 AM:

```bash
crontab -e

# Add this line
0 3 * * 0 /usr/bin/python3 /homeassistant/ha-cleanup.py >> /var/log/ha-cleanup.log 2>&1
```

### Home Assistant Shell Command

Add to `configuration.yaml`:

```yaml
shell_command:
  ha_cleanup_dry_run: "python3 /config/ha-cleanup.py --dry-run"
  ha_cleanup: "python3 /config/ha-cleanup.py"
```

---

## Troubleshooting

### Script Can't Find Config Directory

```
Error: Could not find Home Assistant config directory
```

**Solution**: Run from within the config directory or modify `CONFIG_PATHS` in the script.

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
| **Graceful Stop** | Properly stops HA before database operations |
| **Error Handling** | Continues on individual failures, reports at end |

---

## Support

For issues and questions:

1. Check the [Troubleshooting](#troubleshooting) section
2. Run with `--dry-run` first to preview changes
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

**Version**: 1.0.1  
**Last Updated**: 2026-01-25  
**Tested On**: Home Assistant 2024.x (HAOS, Docker, Core)

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Nabu Casa, Inc. or the Home Assistant project.

- **Home Assistant** is a trademark of Nabu Casa, Inc.
- All product names, logos, and brands are property of their respective owners.

This script is provided "as is" without warranty of any kind. Use at your own risk. The authors are not responsible for any damages or issues arising from the use of this software, including but not limited to data loss, registry corruption, or system instability.

This is an independent, community-developed project created to help Home Assistant users clean up orphaned entities and maintain their systems.
