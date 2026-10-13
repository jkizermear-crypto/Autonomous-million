# Payout destination

The owner-approved payment destination is in `config/payout-destination.json`:
native USDC on Base mainnet (chain ID 8453). This is the receiving address,
not the USDC token contract. The token contract is separately recorded using
Circle's official native USDC address for Base:
https://www.circle.com/blog/usdc-now-available-natively-on-base

The owner explicitly approved publishing the receiving address in this public
repository. It is a Coinbase deposit address, not an agent-controlled signing
wallet. No private keys, seed phrases, signing credentials, or outgoing transfers
are configured. Payers must support native USDC on Base and must use the exact
receiving address and network. This configuration cannot convert fiat payments,
change a payer's supported network, or collect money automatically from them.

Coordination previews include the destination as payment instructions for review.
It is not automatically added to public replies or posted on Moltbook. A future
payout agreement or submission can reference it within its approved scope.

No receipt-verification pipeline has been implemented yet. Incoming transfers,
confirmed payments, revenue attribution, expenses, and net profit must be checked
separately. An unrelated deposit, promised payout, or wallet balance is not proof
of project earnings. Stablecoin token units must not be treated as a guaranteed
USD valuation. Current verified project revenue remains zero.
