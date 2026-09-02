# Credits

HA Cleanup is shaped by real user reports. This page recognises everyone who has contributed — through bug reports, feature requests, and testing.

---

## Per-Version Credits

Community members who helped shape each release through bug reports, feature requests, and testing.

### v1.8.0

- **[@comet424](https://github.com/comet424)** — Requested a way to run cleanup unattended from a scheduler ([Discussion #3](https://github.com/hiall-fyi/ha-cleanup/discussions/3)), which shipped as `--run=<option> --yes`. Also reported the script disappearing after Home Assistant updates, tracked down to being saved inside an SSH add-on's own container rather than `/config`.
- **[@AberDino](https://github.com/AberDino)** — Flagged a large backlog of orphaned long-term statistics that Spook had surfaced, with no bulk way to clear them ([Discussion #4](https://github.com/hiall-fyi/ha-cleanup/discussions/4)). That became the new option 5.

### v1.7.1

- **[@hapklaar](https://github.com/hapklaar)** — Reported real duplicate `_2`/`_3` suffixes getting buried under false positives from model numbers, MAC addresses, and port numbers ([#2](https://github.com/hiall-fyi/ha-cleanup/issues/2)), which drove the automatic false-positive filtering added in this release.

### v1.2.0

- **[@hapklaar](https://github.com/hapklaar)** — Reported the suffix fix renaming legitimate `_2`-style entity names (PM2.5 sensors, port numbers) alongside genuine duplicates ([#2](https://github.com/hiall-fyi/ha-cleanup/issues/2)), which is why the suffix fix became an interactive, manually-confirmed selection instead of an automatic one.

### v1.0.1

- **[@hapklaar](https://github.com/hapklaar)** — Reported every automation showing up as orphaned on a setup using `automations.yaml` and UI-based automations rather than the `automation/` folder ([#1](https://github.com/hiall-fyi/ha-cleanup/issues/1)), then confirmed the fix on his own registry.

---

## 🌟 Special Thanks

All community members who tested, reported issues, and shared their setups. You make HA Cleanup better every release.

---

**Made with ❤️ by Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))**
