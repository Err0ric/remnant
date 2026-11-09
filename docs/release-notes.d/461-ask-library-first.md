### Ask answers library questions without waiting for the model (2026-11-08)

- Ask now matches a question to the library in code first. When one library query is a confident match (its own example question, in the same words once synonyms, time words, and the people, addresses, and machines named are set aside), it answers with no model call. Before, every first question waited on a routing call to the model, about 25 s on a CPU-only local model.
- Every other question goes to the model exactly as before: a near miss, a question shaped like general guidance ("how do I", "what is"), and a library query that takes its own values.
- How I got this says "A data question, matched to the library without the model" for these answers.
- The Ask audit row's route now records which route answered (`via`: `library` or `model`, with the library entry when one was used) and how long routing took (`ms`), so the two can be compared later. A library answer is audited as an Ask with no model call.
- What you will notice: library questions in Ask answer in a couple of seconds, without waiting for the model.
- What changes for existing installs: nothing to do. No data, settings, or update steps change; the audit row details gain two fields. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
