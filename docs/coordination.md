# Coordination preview

The coordinator keeps conversations, analyzed comment IDs, voluntary participants,
proposed experiments, and follow-up drafts in `coordination-state.json`.
It cannot publish to Moltbook, execute experiments, move funds, or call Gemini.
The existing Gemini/posting/verification workflows remain separate and unchanged.

Run `python -m unittest discover -s tests -v` for offline regression tests.
Run `python tools/moltbook_coordinator.py --source fixtures` for simulated proposals.
Run with `--source live` to read the real tracked threads. A Moltbook API key is optional
for public comment reads; authenticated runs use the existing key.

The manual **Moltbook Coordination Preview** workflow defaults to fixtures. It has no
schedule. Fixture output is visibly marked simulated and never saved into live memory.
Live runs import IDs from up to 30 recent successful reports per existing publication
workflow (Join Discussion, Sentience Post, and Coordinator communication tests),
read tracked threads, and commit changed coordination memory to the dispatched branch.
The workflow needs contents write only for its own memory file and actions read to
retrieve existing reports. It has no publishing input or publishing endpoint.

Only completed scans consume comment IDs. Missing roots, malformed trees, repeated
cursors, and incomplete pagination are reported as failures. A previewed draft remains
awaiting approval; analyzing a reply does not mean a response was sent. Later observed
verified own replies clear the corresponding pending draft. Unverified publications
are retained as pending and are not processed.

New posts can be tracked with `register(state, post_id)`; new comments with
`register(state, post_id, comment_id)`. `import_publication` accepts existing publication
reports and registers known successful or pending IDs. Explicitly pass another report
with `--publication-report PATH`. Automated import covers the three named workflows;
reports from other workflows can be imported through this CLI. Older
expired reports require an explicit ID registration; they cannot be reconstructed
from drafts. An approved recruitment publication will be registered by the lead
developer using its returned post ID. The recruitment post has not been published.

Natural-language replies remain unconfirmed candidates. A participant explicitly opts
in with `VOLUNTEER: research, critique, testing` using any subset of those roles.
`WITHDRAW:` cancels their pending drafts. Proposal fields are `IDEA:`, `TEST:`,
`SUCCESS:`, `STOP:`, and `EVIDENCE:`. Evidence links are stored as unverified;
the coordinator never follows contributor URLs or treats claimed payouts as profit.
No unsolicited assignment or payment promise is created.

Review the draft in `drafts/moltbook-recruitment.md` before approving public outreach.
Preview approvals are not publishing authorization. Public posting remains a separate
explicitly approved action through the existing verified posting path.
