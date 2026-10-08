"""scam_detect job: load one analytics run's data, run D1-D10 per chain, store findings and wallet risk.
A failing detector is logged and marked failed; the others still run."""

import json
import logging
import time
import traceback

import pandas as pd

from app.analytics.engine import CHAIN_KEY, Scope
from app.db.clickhouse import new_client
from app.db.models import AnalyticsRun, Chain, Job
from app.db.postgres import SessionLocal
from app.jobs.progress import update_job
from app.scam.config import get_scam_settings
from app.scam.detectors import DETECTORS
from app.scam.detectors.base import Context, Finding
from app.scam.labels import labels_for_chain
from app.scam.models import AddressCode, Token
from app.scam.risk import wallet_risk

log = logging.getLogger(__name__)

# detectors that cannot work on a chain family, and why (shown as "skipped", never as a silent zero)
SKIPPED_FOR = {
    "utxo": {"D6": "needs account nonces (EVM only)", "D8": "Bitcoin has no token approvals"},
    "solana": {"D6": "needs account nonces (EVM only)", "D8": "SPL token approvals are not loaded yet"},
}

FINDING_COLUMNS = ["run_id", "job_id", "chain", "detector", "wallet", "related_wallets", "tx_hashes", "score", "severity",
                   "reason", "details"]
RISK_COLUMNS = ["run_id", "chain", "wallet", "risk_score", "severity", "detectors_hit", "top_reasons"]


def load_frames(ch, scope: Scope, chain: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not CHAIN_KEY.fullmatch(chain):
        raise ValueError(f"invalid chain key: {chain}")
    where = f"{scope.where()} AND chain = '{chain}'"
    tx = ch.query_df(f"SELECT block_number, block_time, tx_hash, from_addr, to_addr, value_native AS value, "
                     f"is_contract_call = 1 AS is_contract_call, nonce FROM transactions FINAL WHERE {where} "
                     f"ORDER BY block_number, tx_hash")
    if tx.empty:
        return tx, pd.DataFrame(), pd.DataFrame()
    tx["is_contract_call"] = tx["is_contract_call"].astype(bool)
    lo, hi = int(tx["block_number"].min()), int(tx["block_number"].max())
    rng = f"chain = '{chain}' AND block_number BETWEEN {lo} AND {hi}"
    tt = ch.query_df(f"SELECT block_number, block_time, tx_hash, log_index, token_address, from_addr, to_addr, amount, "
                     f"token_symbol FROM token_transfers FINAL WHERE {rng} ORDER BY block_number, tx_hash, log_index")
    ap = ch.query_df(f"SELECT block_number, tx_hash, token_address, owner, spender, is_unlimited = 1 AS is_unlimited, "
                     f"spender_is_contract FROM token_approvals FINAL WHERE {rng} ORDER BY block_number, tx_hash, log_index")
    return tx, tt, ap


def build_context(chain: str, tx: pd.DataFrame, family: str = "evm") -> Context:
    with SessionLocal() as s:
        labels = labels_for_chain(s, chain)
        known = {t.address: t.symbol for t in s.query(Token).filter(Token.chain == chain, Token.source == "builtin")}
        coded = {c.address for c in s.query(AddressCode).filter(AddressCode.chain == chain, AddressCode.is_contract.is_(True))}
    # addresses that receive contract calls but never send a transaction behave like contracts
    called = set(tx.loc[tx["is_contract_call"], "to_addr"])
    contracts = (called - set(tx["from_addr"])) | coded | set(known)
    # built-in labels name known non-wallets (token contracts, Bitcoin's pay-to-anchor output): treat like contracts
    contracts |= {a for a, ls in labels.items() if any(l["source"] == "builtin" for l in ls)}
    return Context(chain=chain, cfg=get_scam_settings().for_chain(chain), family=family, labels=labels,
                   contracts=contracts, known_tokens=known)


def run_detection(job: Job) -> None:
    with SessionLocal() as s:
        run = s.get(AnalyticsRun, job.run_id)
    if run is None:
        raise ValueError("analytics run not found")
    chains = list(job.params.get("chains") or run.chains)
    scope = Scope(run_id=run.id, chains=chains, dataset_id=run.dataset_id, time_from=run.time_from, time_to=run.time_to)
    cfg = get_scam_settings()
    with SessionLocal() as s:
        families = {c.key: c.family for c in s.query(Chain)}
    ch = new_client()
    ch.command(f"ALTER TABLE risk_findings DROP PARTITION {int(run.id)}")
    ch.command(f"ALTER TABLE wallet_risk DROP PARTITION {int(run.id)}")
    status: dict = {}
    total_findings = total_wallets = 0
    steps = len(chains) * len(DETECTORS)
    step = 0
    for chain in chains:
        family = families.get(chain, "evm")
        tx, tt, ap = load_frames(ch, scope, chain)
        ctx = build_context(chain, tx, family)
        chain_status, findings = {}, []
        for key, (name, fn) in DETECTORS.items():
            step += 1
            skip = SKIPPED_FOR.get(family, {}).get(key)
            if skip:
                chain_status[key] = {"status": "skipped", "reason": skip, "findings": 0}
                continue
            update_job(job.id, progress=step / (steps + 1), message=f"{chain}: {name}")
            t0 = time.time()
            try:
                found = fn(tx, tt, ap, ctx) if not tx.empty else []
                ctx.prior[key] = found
                findings += found
                chain_status[key] = {"status": "ok", "findings": len(found), "seconds": round(time.time() - t0, 2)}
            except Exception as e:                       # one detector failing must not fail the job
                log.error("detector %s failed on %s\n%s", key, chain, traceback.format_exc())
                chain_status[key] = {"status": "failed", "error": f"{type(e).__name__}: {e}"[:500], "findings": 0}
        _store(ch, run.id, job.id, chain, findings, ctx.cfg.risk_weights)
        status[chain] = {"transactions": int(len(tx)), "token_transfers": int(len(tt)), "approvals": int(len(ap)),
                         "detectors": chain_status}
        total_findings += len(findings)
        total_wallets += len({f.wallet for f in findings})
    failed = sum(1 for c in status.values() for d in c["detectors"].values() if d["status"] == "failed")
    update_job(job.id, detail={"chains": status, "findings": total_findings, "wallets_flagged": total_wallets},
               message=f"{total_findings:,} findings on {total_wallets:,} wallets"
                       + (f" · {failed} detector(s) failed" if failed else "") + " · indicators, not proof")


def _store(ch, run_id: int, job_id: int, chain: str, findings: list[Finding], weights: dict) -> None:
    if not findings:
        return
    rows = [[run_id, job_id, chain, f.detector, f.wallet, list(f.related), list(f.tx_hashes), int(f.score), f.severity,
             f.reason, json.dumps(f.details, default=str, sort_keys=True)] for f in findings]
    for i in range(0, len(rows), 10_000):
        ch.insert("risk_findings", rows[i:i + 10_000], column_names=FINDING_COLUMNS)
    risk = [[run_id, chain, r["wallet"], r["risk_score"], r["severity"], r["detectors_hit"], r["top_reasons"]]
            for r in wallet_risk(findings, weights)]
    for i in range(0, len(risk), 10_000):
        ch.insert("wallet_risk", risk[i:i + 10_000], column_names=RISK_COLUMNS)
