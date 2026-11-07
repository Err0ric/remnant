### The Sources line agrees with the gap alerts (2026-11-06)

- The Sources line at the bottom of the Dashboard and the Sources tile on Health now count every source with an open source gap alert, from the same state the alerts use. Before, they could say "6 of 6 flowing, no gaps" while two gap alerts were open and a source had sent nothing for days.
- When gaps are open the line names them, for example "4 of 6 flowing, 2 gaps: server_events quiet 4 d, win_dc quiet 3 h", and opens those alerts (the one alert when there is one).
- A gap alert stays counted after its source's quiet alert is turned off, until the source sends again or someone closes the alert.
- What changes for existing installs: nothing to do; open source gap alerts show on the Dashboard and Health at once.
