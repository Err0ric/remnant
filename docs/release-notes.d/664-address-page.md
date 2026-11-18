### The address page answers who had it, what it looked up, how it signed in, and which AI services it reached (2026-11-17)

- Typing an address in the top bar search opens its page, even before the search has answered; it no longer drops into a raw SQL search in Logs.
- An address's page under People & devices has four new sections: DHCP and VPN history, the names it looked up in DNS with first and last seen, its sign-ins and firewall allows and denies by kind, and the AI services seen from it as AI usage counts them. Each reads only the sources you may read, says which sources it read, and says plainly when you have no source for it.
- On every person, host, and address page, a sign-out (such as sshd's "Disconnected from user") no longer counts as a sign-in, sign-ins in the activity lanes are one card per outcome, and firewall traffic in What it did reads Allowed or Denied. Outcome badges are the same everywhere; a success from an address is marked once, on its Succeeded number, in amber with a tooltip.
- With no events, an entity page shows one line and no empty numbers or lanes; "View all events in Logs" sits after the opening sentence and is not shown at 0.
- What you will notice: an address typed in the top bar opens its page, which has four new sections; sign-in counts on person, host, and address pages no longer include sign-outs, and empty pages are shorter.
- What changes for existing installs: nothing to do.
