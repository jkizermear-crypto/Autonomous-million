# Revenue opportunity screen — 2026-10-13

Status: research completed; no eligible executable opportunity established. No account registration, secret creation, submissions, spending or model calls occurred.

## Findings

- Superteam Earn explicitly supports AGENT_ALLOWED / AGENT_ONLY submissions. Its discovery API returned Unauthorized without an agent credential. Payout requires a human to sign in and complete a talent profile. Listing-specific terms, deadline, rewards, IP, geography and network must still be checked. Official source: https://superteam.fun/earn/agents . No permission to register or submit is inferred from provider documentation.
- Steve Agent Arena advertises 500 USDC total prizes, but the published deadline is October 1, and it requires five qualifying mainnet trades plus an X post. Rejected: expired and violates our no-transactions scope. Source: https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc/ . Rewards are USDC on Solana, not our Base receiving destination.
- Algora pays for accepted open-source contributions; https://algora.io/pricing/ . No explicit general AI submission permission established. SCIBASE.AI's advertised open bounties show no completed payouts on its board and many competing claims; do not start its broad MVP tasks without current issue requirements and payment confirmation. Source: https://algora.io/SCIBASE.AI/home . Advertised rewards are not verified funding or guaranteed payment.
- Opire documents direct sponsor-arranged payments rather than automatic platform payment. Requires agreeing payment details first, making it a weaker fit for minimal direct interaction. Source: https://docs.opire.dev/rewards/pricing .

## Decision

Do not build a speculative bounty deliverable yet. First verify one current AI-eligible listing with no upfront expense, acceptable terms, bounded deliverable and payout route. Superteam is a candidate channel, not an approved revenue experiment. A human talent profile is not a seller storefront, but does require owner involvement and account/terms approval. Identity requirements depend on sponsor. Never use a Base address for Solana payouts.

Next gate: owner decides whether a payout profile is acceptable. Registration requires explicit approval and secure credential handling. Existing project remains offline; no new schedules or provider integrations enabled.
