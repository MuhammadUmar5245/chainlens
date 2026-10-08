# Scam tracing & wallet tracing (MVP)

All results are **risk indicators, not proof**. The UI, exports and API say "suspicious", "possible" or "indicator".

## What it adds

| Part | Where |
|---|---|
| ERC-20 transfers + approvals (Transfer / Approval logs) | job `enrich_tokens`, tables `token_transfers`, `token_approvals` (ClickHouse) |
| Token metadata cache, contract check cache | `tokens`, `address_code` (PostgreSQL) |
| Address labels (CSV import, TEST set, built-in tokens) | `address_labels` (PostgreSQL), page **Scam tracing → Labels**, `python -m app.cli labels …` |
| Detectors D1–D10 + wallet risk | job `scam_detect`, tables `risk_findings`, `wallet_risk`, page **Scam tracing** |
| Single-wallet trace | page **Trace**, `GET /api/v1/trace/{chain}/{address}`, `python -m app.cli trace` |
| Excel exports | `GET /api/v1/scam/export.xlsx?run_id=…`, `GET /api/v1/trace/{chain}/{address}/export.xlsx` |

Flow: EVM fetch → analytics (existing) and `enrich_tokens` (new) → `scam_detect` (new, waits up to 30 min for enrichment).
Detectors can be re-run any time: **Run detectors again** on the page, `POST /api/v1/scam/runs/{run}/detect`, or `python -m app.cli detect --run N`.

Chains: the detectors run on **all five chains** (Bitcoin, Ethereum, EthereumPoW, Ethereum Classic, Solana); the trace works on every chain.
Token enrichment (ERC-20) is EVM only. On Bitcoin and Solana two detectors are shown as **skipped** with the reason:
D6 needs account nonces (EVM only) and D8 needs token approvals (none on Bitcoin; SPL approvals not loaded yet).

### Bitcoin and Solana specifics
- Look-alike addresses (D1) compare the first 4 characters after the prefix (`0x`, `bc1q`/`bc1p`, legacy `1`/`3`; Solana has none) and the last 4.
- The nonce-0 severity rule in D1 applies to EVM only.
- D4 drops "mostly contract calls" receivers on EVM only (almost every Solana transaction is a program call).
- Amount and block-window thresholds are set per chain (`SCAM_CHAIN_OVERRIDES`, defaults in `config.py`). The amounts are rough
  starting points in each chain's own coin; adjust them to your needs:

| Setting | ETH (requirements) | BTC | SOL |
|---|---:|---:|---:|
| poison real min / fake max | 0.001 / 0.0001 | 0.0005 / 0.00002 (2,000 sats) | 0.01 / 0.0001 |
| poison "fast" window | 30 blocks | 3 blocks | 1,500 slots |
| pass-through min in | 1.0 | 1.0, and forwarded within 6 blocks | 20 |
| hop min | 0.5 | 0.5 | 10 |
| dust max | 0.0001 | 0.00002 | 0.0001 |
| linked: same-destination window / min group | 10 blocks / 3 | 1 block / 5 | 50 slots / 3 |

Why Bitcoin needs the hold limit: Bitcoin spends whole coins and sends change to a fresh address, so almost every wallet
"forwards" most of what it receives. Only fast forwarding of larger amounts is a useful pass-through signal there.
All chains: a wallet with more than 10 matching payouts is treated as an endpoint (batch payer) in D3, not a hop.

## Field mapping (requirements → Chainlens)

| Requirements | Chainlens |
|---|---|
| `value_eth` | `transactions.value_native` |
| `ts` | `transactions.block_time` |
| `wallets` | `wallet_features` (one set per analytics run) |
| `job_id` in findings | `risk_findings.job_id` (the `scam_detect` job) + `run_id` (analytics run) |
| `GET /api/trace/{address}` | `GET /api/v1/trace/{chain}/{address}` |

## Configuration

New keys only, read from environment variables (see `backend/app/scam/config.py`). A dotted key maps to upper case with underscores:
`scam.poison.real_min_eth` → `SCAM_POISON_REAL_MIN_ETH`, `trace.max_nodes` → `TRACE_MAX_NODES`,
`risk.weights.*` → `RISK_WEIGHTS='{"D1":0.9,…}'`.
Additions beyond the requirements: `SCAM_POISON_REAL_MIN_TOKEN`, `SCAM_POISON_FAKE_MAX_TOKEN`, `SCAM_POISON_FAST_BLOCKS`,
`SCAM_HOPS_MAX_PATHS`, `SCAM_FANIN_MAX_CONTRACT_SHARE`, `SCAM_NEWWALLET_MIN_STABLE`, `SCAM_NEWWALLET_FORWARD_RATIO`,
`SCAM_NEWWALLET_WINDOW_BLOCKS`, `SCAM_APPROVAL_NEW_SPENDER_BLOCKS`, `SCAM_LINKED_*`, `ENRICH_CHUNK_BLOCKS`.

## Sample results (nownodes_data.xlsx, 50 Ethereum blocks)

Raw definitions (no label exclusions) reproduce every baseline number in requirements §9.2
(`tests/test_scam_regression.py`). Fake-sender nonce-0 share is 29 / 37 = 78 % ("80 %" in the requirements).

After exclusions (known contracts, built-in token labels, the 7 TEST labels) and with token data loaded (20,119 transfers, 1,855 approvals):

| Detector | Raw | With exclusions | Findings (MVP run) |
|---|---:|---:|---:|
| D1 poisoning (native coin matches) | 41 | 41 | 730 incl. token variant (405 wallets) |
| D2 pass-through wallets | 101 | 99 | 99 |
| D3 2-hop chains / maximal paths | 131 | – | 58 paths |
| D4 collectors | 40 | 5 | 5 |
| D5 distributors | 19 | 19 | 19 |
| D6 new wallet, big money | – | – | 7 |
| D7 dust spam senders | – | – | 11 |
| D8 approval phishing | – | – | 21 |
| D9 blacklist (TEST labels) | – | – | 14 |
| D10 linked wallets | – | – | 1,466 (low severity) |

D4 drops most: 35 of 40 "collectors" mainly receive contract calls (token and DeFi contracts).
D1's token variant finds counterfeit look-alike tokens such as `U⁯S⁯DΤ` and `ꓴ឵ՏᎠ឵Ⲧ` (fake "USDT" with hidden characters).
All ten detectors together take under 2 seconds on the sample.

## All five chains (analytics run #44)

Run time for all detectors over ~370,000 rows: about 10 seconds.

| Chain | Rows | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---|---:|---:|
| Bitcoin | 328,225 | 0 | 582 | 1,949 | 89 | 771 | skipped | 43 | skipped | 0 | 26,966 |
| Ethereum | 41,388 | 793 | 176 | 137 | 24 | 56 | 12 | 17 | 21 | 48 | 3,504 |
| EthereumPoW | 353 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 9 |
| Ethereum Classic | 78 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 48 |
| Solana | 2,703 | 0 | 0 | 0 | 0 | 0 | skipped | 0 | skipped | 0 | 4 |

Bitcoin D5 (distributors) and D10 (linked, low severity) stay high until exchange labels are loaded: exchange payouts fan out
to many addresses and fund many new ones at once. With exchange labels those wallets are excluded.

## Labels

Built-in: USDT, USDC, WETH, DAI (token) and Bitcoin's pay-to-anchor output `bc1pfeessrawgf` (other).
**TEST labels** (`source = TEST-sample`, 5 busy hubs as "exchange", 2 look-alike senders as "scam_reported") exist only to
try the MVP; they are not real reports. Remove them on the Labels tab or with `python -m app.cli labels remove --source TEST-sample`.
Real lists (OFAC, Chainabuse / ScamSniffer exports, exchange hot wallets) are imported as CSV: `address,label,category[,chain][,source]`.

## Not in the MVP

- AI agent tools (`get_findings`, `get_wallet_risk`, `trace_wallet`): Chainlens has no agent yet; the agent lives in the old script.
- Blockbook full history for traces (`TRACE_USE_BLOCKBOOK`, off): the endpoint still needs confirming with NOWNodes.
- Solana SPL token transfers and approvals (so D1 token variant and D8 do not cover Solana tokens yet).

## Tests

```
docker compose run --rm -v "$PWD/backend:/app" api sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```
Baseline (non-regression) tests: `test_baseline_analytics.py` (byte-for-byte analytics snapshot), `test_api_smoke.py`.
