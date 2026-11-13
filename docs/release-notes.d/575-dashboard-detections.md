### Design: the Dashboard's Detections section (2026-11-13)

- Console redesign, build row 18 (ADR-0052, DESIGN.md 6.3). The table of hosts and people involved also shows how many rules matched each one and when its last match was. The fourth number reads "People involved".
- A rule's name in "Matches by rule" opens Alerts > Rules with that name in the filter; its total opens the matched events in Logs, as every number does.
- When the system has paused detection, the section says so in its header ("Detection is not running for 1 schedule: ..."), and a number that would be zero reads "Not running" instead, so a quiet section is not mistaken for "nothing happened". A number above zero is still shown.
- With no rule enabled, an administrator sees "No rules are enabled." with Enable rules. Others see no section, as before.
- What you will notice: two more columns in the Detections table, rule names that open the rule list filtered by that name, and "Not running" in place of a zero while detection is paused.
- What changes for existing installs: nothing to do.
