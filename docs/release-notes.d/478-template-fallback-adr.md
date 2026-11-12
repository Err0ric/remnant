### Template fallback decided, and threat numbers checked (2026-11-10)

- ADR-0050 accepted: a source whose parser template cannot load will keep storing its events, say so on Health, and send one alert; the events can be reparsed later and the rules re-run over them. Built in the next three changes.
- The release tooling now refuses a design record that reuses a threat number another one already owns.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.
