### Detection never stops silently (2026-11-10)

- When something that feeds detection stops on its own, your alert targets hear about it: a source or connector that cannot read for 15 minutes, an AI Watch check failing for 15 minutes, a threat feed that cannot update for a day, a schedule that pauses itself, and a failed integrity check. Each sends "Detection stopped" once and "Detection running again" once when it recovers.
- Only real errors count (a failed fetch, a listener that is down, a full spool, a missing parser), never a quiet period or a connector running behind. A source whose spool is full now shows that on Health.
- Something that keeps failing and recovering sends one stop and one recovery message an hour at most, then one "still flapping" message until it settles for an hour.
- Anything with no alert targets of its own now tells every alert target instead of nobody.
- Settings > Backups waits for its saved settings before showing the form, so an edit made while they load is no longer lost (found as a flaky test).
- What you will notice: "Detection stopped", "Detection running again", and "Detection flapping" messages, a "Spool full" error on Health when a spool refuses messages, and schedule pause messages even for schedules with no targets chosen.
- What changes for existing installs: three new settings tables, added on start. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`); the extra tables are ignored by the older version.
