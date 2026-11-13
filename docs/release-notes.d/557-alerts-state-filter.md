### Design: Alerts has three tabs; Open, Closed, and Muted are a State filter (2026-11-12)

- Console redesign, build row 5 (ADR-0052 sections 3.3 and 3.4, D246). The Alerts tabs are Queue, Rules, and Schedules. Open, Closed, and Muted are no longer tabs: they are the State filter, first in the row of filters on the Queue, with Open as the default and the open count beside it.
- The address shows the choice (`/alerts#state=closed`). Old addresses still work: `/alerts/closed`, `/alerts/muted`, and `/alerts/open` open the Queue with that state, without adding a step to Back, and a link to one alert (`#item=<id>`) opens it as before, closed ones too.
- What you will notice: two fewer tabs on Alerts, and a State menu where Closed and Muted now are.
- What changes for existing installs: nothing to do. Bookmarks and links in alert messages keep working.
