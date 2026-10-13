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

The read-only verifier is `tools/verify_receipts.py`. Add explicit transaction
hashes to `payment-claims.json` under `claims`, with an `id`, `transaction_hash`,
and optional `expected_sender` and `expected_amount_usdc`. Run
`python tools/verify_receipts.py` to obtain a receipt audit. The default claims
list is empty, so it performs no network calls and does not scan wallet history.

The verifier uses Base's free, best-effort public RPC at https://mainnet.base.org.
It only permits eth_chainId, eth_getTransactionReceipt and eth_getBlockByNumber.
It checks the chain, successful transaction status, canonical block hash,
finalization, native USDC contract, transfer recipient, and any supplied expected
sender/amount. Duplicate transfer event IDs are counted once. Pending, failed,
wrong-network, wrong-token, removed or malformed receipts never count.
RPC failures stay unverified; no paid provider is selected automatically.

Confirmed token receipts still require independent revenue attribution, expense
accounting, and USD valuation. An unrelated deposit, promised payout, or wallet
balance is not proof of project earnings. This audit reports zero attributed
revenue and net profit; it never overwrites the project's earnings ledger.
Stablecoin units are not treated as a guaranteed USD valuation.

Reference: https://ethereum.org/developers/docs/apis/json-rpc/
