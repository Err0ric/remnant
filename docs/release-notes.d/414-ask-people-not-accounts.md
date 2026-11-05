### Ask: people, not accounts (2026-11-04)

- **Who uses Claude Code** counts people: accounts linked to the same person in **Identities** are one row, with an **accounts** column ("dana@example.com (work), dana@example.org (personal)"), and the answer reads "1 person, 2 accounts".
- A personal account counts as the same person only after an administrator links it in Identities; nothing is linked by a similar name. A session with no account shows "(no account reported)" and is not counted as a person.
- Saved and library searches can use `{{person:actor_user_name}}` and `{{org_domains}}`, filled from Identities each time they run.
- What changes for existing installs: link a person's personal Claude account to them in **Identities** to count it as theirs. A saved search with a parameter named `org_domains` must rename it.
