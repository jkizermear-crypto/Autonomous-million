# Bounded experiment coordinator

The owner approved a revised scope on 2026-10-13: zero **additional** spending,
using existing subscriptions and free infrastructure. The $1 million / 180 day
mission remains aspirational. Existing subscription costs must be reported
separately from incremental cash expenses; neither funding nor wallet receipts
are automatically profit.

`experiment-board.json` is the initial task board. Its first real task is only
proposed: find an eligible funded opportunity and document source terms, AI-use
permission, ownership conditions, payout method and eligibility. An owner is
assigned only after explicit acceptance. No opportunity is yet established.

`tools/experiment_coordinator.py` is an offline orchestration prototype, not an
autonomous revenue engine. It consumes separately provided planner, researcher,
critic, builder and tester outputs, records hashes and role handoffs, stops on
missing evidence or blockers and permits at most five role turns. Text containment
checks are a minimal demonstration; actual software deliverables require real
execution tests and revenue opportunities require primary-source term review.
A researcher marking eligibility confirmed is an assertion, not verification.
The synthetic fixture must never be used as approval or payment evidence.

Run from the repository root:

```sh
python tools/experiment_coordinator.py --fixture tests/fixtures/experiment.json --output reports/experiment-offline-preview.json
python -m unittest discover -s tests -v
```

The report's awaiting_owner_approval status means only that the offline demonstration
passed its checks. It authorizes nothing. The ledger owners are labelled fixture
roles, not independent agents. The script cannot execute commands, make network
requests, use credentials, publish, accept terms or send payments. New live model
adapters, secure credential configuration and schedules require separate approval.
The existing Gemini integration, Moltbook checker, verification, email queue and
posting policies remain unchanged.

Next implementation gate: review a real opportunity, then design bounded provider
adapters with separate context per role, explicit output schemas, request/token
limits, durable progress checkpoints and no paid fallback. A second model may
provide a different critique but model agreement cannot replace external evidence.
Any actual submission needs approval of the exact deliverable and applicable terms.
Payment is recorded only after receipt verification; net profit also needs costs.
