### Quieter quiet alerts for Claude Code (2026-11-02)

- "Stopped sending" now fires once per source each time it goes quiet; two checks at the same minute no longer both alert.
- When you add an OpenTelemetry source, you choose who sends to it. For **Claude Code (telemetry or the hooks plugin)** the source-level quiet alert starts off, because Claude Code sends only while people use it and evenings would alert every day. Agents and collectors keep the 1-hour quiet alert.
- **Health > Endpoint agents** no longer flags a hooks plugin machine just for being quiet. It flags a machine whose plugin has records waiting and delivered none for 3 days (`agents.queue_stuck_days`), and raises one alert for it.
- What changes for existing installs: existing quiet alerts stay as they are. To stop the evening alerts on a Claude Code source you already have, turn its quiet alert off on **Sources**.
