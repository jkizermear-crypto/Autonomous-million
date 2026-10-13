# Automation readiness

`config/reply-policy.json` currently disables execution and does not grant standing
public-reply approval for unreviewed replies. The owner approved hourly read-only reply checks
and the separate exact-draft email approval loop described in `docs/email-approvals.md`. The
**Moltbook Hourly Reply Check and Preview** workflow runs at minute 17 of each
hour (UTC), scans tracked conversations, saves coordination memory and fixed
template drafts, and uploads a preview artifact. GitHub may delay scheduled runs.
It also validates changes to its own workflow file using the same read-only scan.
This workflow never invokes the publishing dispatcher or Gemini. Novel replies
still need individual drafting and review. The manual workflow
**Moltbook Automation Check - Manual** defaults to preview; choosing execute still
cannot send anything while either policy flag is false.

The prepared policy allows one reply per run, only in the recruitment thread,
only for explicit volunteers, only a welcome or experiment-review template, and
at most one attempt per author per 24 hours. Existing Gemini integrations are
unchanged; this dispatcher uses no Gemini calls. It cannot create top-level posts,
send arbitrary drafts, transfer funds, or run contributor code.

Run `python tools/reply_dispatcher.py` to inspect current eligible candidates.
The dispatcher re-reads complete comment trees, checks source identity and content
against the analyzed comment, honors fresh withdrawals, and rejects simulated,
modified, deleted, unverified or already-answered drafts.

Public reply execution must be separately authorized before enabling the policy.
The approved hourly schedule does not grant permission to publish replies. When eventually enabled, a durable GitHub state commit must succeed
before a comment POST. A timed-out submission is never automatically repeated.
If a matching own reply later becomes visible, it is reconciled into memory.
Unknown outcomes remain blocked for review.

Known verification challenges are checkpointed into an expiring recovery artifact
and linked to the workflow run in memory, without exposing the verification code
in public reports. Simple arithmetic can be solved without an API charge: two
unambiguous operands with plus, minus, multiplied by, divided by, or a single
operand doubled/tripled. The parser handles the tested noisy 32-times-3 challenge;
it is a restricted grammar, not a general mathematical reasoner. Unsupported or
ambiguous questions stop for review. Expired recovery artifacts do not trigger
another comment submission. The workflow can resume a matching known pending
verification within its validity period.

Replies currently use fixed mission templates. Novel critiques and unstructured
conversation need individual review; automatic personalized reasoning is not
implemented. Template dispatch and zero-cost verification are a useful first
unattended loop, not a claim that the agent can independently generate income.

The manual workflow also runs the read-only receipt verifier described in
`docs/payments.md`. It does not sign transactions, count deposits as earnings,
change secrets, or publish replies. All new behavior is tested offline;
unreviewed public execution remains disabled. Explicit email approval can authorize
one exact draft through the separate email publication workflow.

Current validation: 54 tests pass locally and in GitHub Actions. The first real
recruitment reply was saved as an unconfirmed candidate with a preview draft;
it did not qualify for automatic dispatch. Both live Base RPC transport checks
returned HTTP 403, so payment receipt verification is offline-tested but blocked
for real transactions. The temporary validation trigger was removed afterward.
