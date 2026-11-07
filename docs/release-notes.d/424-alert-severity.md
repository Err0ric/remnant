### One severity per alert (2026-11-06)

- An alert now has one severity, stored on the alert, and every place reads that one value: Needs attention on the Dashboard, the Alerts list, its detail pane, the "Open by severity" counts, and the messages sent to alert targets. Before, source gap alerts showed High on the Dashboard while the Alerts page showed Medium or no severity and its counts said "High 0".
- Messages to Slack, Teams, email, and webhooks name the severity of a source gap alert; webhooks get a `severity` field when the alert has one.
- What changes for existing installs: on the next start, source gap alerts saved without a severity get Medium, the severity source gaps carry today, and the Dashboard shows source gap alerts as Medium.
