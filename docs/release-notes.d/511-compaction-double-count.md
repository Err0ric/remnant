### A read during compaction never counts events twice (2026-11-11)

- When a whole merge of small lake files started and finished while a read was listing a day's files, that read could include both the merged file and the files it replaced, so counts and lists on any page could briefly show some events twice. A read now also rechecks the retired list after listing and looks again when it changed.
- What you will notice: nothing visible, except that a rare, brief double count on busy installs no longer happens.
- What changes for existing installs: nothing stored changes; no action needed.
