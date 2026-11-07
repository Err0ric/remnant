### People and devices lists sprayed usernames apart (2026-11-06)

- Users now lists only accounts with a successful sign-in, a Microsoft 365 identity, or an Identities link. Names that were only ever tried in failed sign-ins (root, ubuntu, oracle, and the like) move to a new Targeted usernames tab with the attempts, sources, top attacking countries and networks (when GeoIP enrichment is on), and the hosts they were tried on.
- A targeted name that later signs in successfully moves back to Users.
- What changes for existing installs: brute-force usernames leave the Users tab and appear under Targeted usernames; nothing to set up.
