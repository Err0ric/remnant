### People & devices: faster person, address, and host pages, and a faster AI usage count (2026-11-17)

- A person's page loads in a fraction of the time: the entity pages' sign-in rule reads the Microsoft 365 error code only on Microsoft 365 sign-ins, instead of from every line in the range (the page went from 7.1 s to 0.9 s on the speed check's lake; the sign-in summary query alone from 6.7 s to 0.14 s); the person's activity chart counts failures the same way. Address and host pages gain the same way, and read only their own rows' records (1.5 s to about 0.5 s for an address over 30 days of the work install's volume).
- A person's lanes find their rows with a quick name match before the exact identity test, as the summary above them already did.
- The People & devices ranking reads who used an unreviewed AI service from the daily AI rollup for the day the range starts in too, as AI usage does, instead of reading that day's network logs again.
- The AI usage count in the side rail reads only services and MCP servers, the only items with a review status, and no longer the agents and Microsoft 365 apps.
- Every number, list, and link is the same as before.
- What you will notice: person, address, and host pages open much faster; the People & devices list itself is about as fast as before; nothing else changes.
- What changes for existing installs: nothing to do.
