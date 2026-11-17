### One "to review" number on AI usage (2026-11-16)

- The header, the AI usage count in the left menu, the Inventory's Unreviewed rows, and the Needs attention line now all show the same number of items to review, counted once on the server. Before, Needs attention counted AI services only, over the page's time range, so it could say 1 while the rest said 2.
- Needs attention reads the same on Services, People, and Inventory: open alerts, items to review, items marked Not approved (each opening the Inventory on that list), and sensitive-data signals in the time chosen on Services and People. Following one of these links keeps that time choice.
- The Inventory tab no longer shows the "not approved in use" and "sensitive-data signals" tags beside the time control: they count the time chosen on the other tabs, and that tab has no time control.
- The Dashboard's AI services tile now says "N of them unreviewed": AI services in its time range only.
- The Inventory tab has no time control any more: it always shows the last 30 days, as its card says. The other tabs keep the time you chose.
- The Inventory's filters are one row; Export CSV and Export JSON are in the page header and are off when there is nothing to export. Type lists only the kinds of item in the view, and Group by only groupings that make more than one group. The card under the tab is titled "Everything AI seen" instead of repeating "Inventory".
- What you will notice: AI usage states one "to review" number everywhere, and the Inventory tab shows only the controls that do something there.
- What changes for existing installs: nothing to do.
