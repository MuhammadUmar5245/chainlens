"""Scam tracing Excel export (separate from the existing export). Every sheet says: indicators, not proof."""

import io
import json
from datetime import datetime

import pandas as pd

from app.db.clickhouse import new_client
from app.scam.detectors import DETECTORS

NOTE = "Risk indicators, not proof. 'Suspicious' and 'possible' describe patterns in the data, not confirmed wrongdoing."
SHEETS = {"D1": "poisoning", "D2": "pass_through", "D3": "hop_chains", "D4": "collectors", "D5": "distributors",
          "D6": "new_wallets", "D7": "dust", "D8": "approvals", "D9": "blacklist", "D10": "linked"}
MAX_CELL = 32_000


def _clean(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        v = json.dumps(v, default=str)
    if isinstance(v, str) and len(v) > MAX_CELL:
        return v[:MAX_CELL] + " …"
    return v


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{k: _clean(v) for k, v in r.items()} for r in rows])


def scam_workbook(run_id: int, chains: list[str]) -> bytes:
    ch = new_client()
    p = {"r": run_id, "c": chains}
    res = ch.query("SELECT chain, detector, wallet, severity, score, reason, related_wallets, tx_hashes, details FROM risk_findings "
                   "WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)} ORDER BY detector, score DESC, wallet", parameters=p)
    findings = [dict(zip(res.column_names, r)) for r in res.result_rows]
    risk = ch.query("SELECT chain, wallet, risk_score, severity, detectors_hit, top_reasons FROM wallet_risk "
                    "WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)} ORDER BY risk_score DESC, wallet", parameters=p)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary = [{"metric": "note", "value": NOTE}, {"metric": "analytics run", "value": run_id},
                   {"metric": "chains", "value": ", ".join(chains)}, {"metric": "exported (UTC)", "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M")}]
        for key, (name, _) in DETECTORS.items():
            rows = [f for f in findings if f["detector"] == key]
            summary.append({"metric": f"{key} {name}", "value": f"{len(rows)} findings on {len({r['wallet'] for r in rows})} wallets"})
        pd.DataFrame(summary).to_excel(xw, sheet_name="summary", index=False)
        for key, sheet in SHEETS.items():
            rows = []
            for f in (f for f in findings if f["detector"] == key):
                details = json.loads(f["details"]) if f["details"] else {}
                rows.append({"chain": f["chain"], "wallet": f["wallet"], "severity": f["severity"], "score": f["score"],
                             "indicator": f["reason"], "related_wallets": f["related_wallets"], "tx_hashes": f["tx_hashes"]}
                            | {f"detail_{k}": v for k, v in details.items()})
            (_frame(rows) if rows else pd.DataFrame([{"note": "No findings for this detector."}])).to_excel(xw, sheet_name=sheet, index=False)
        risk_rows = [dict(zip(risk.column_names, r)) for r in risk.result_rows]
        (_frame(risk_rows) if risk_rows else pd.DataFrame([{"note": "No wallet risk scores."}])).to_excel(xw, sheet_name="wallet_risk", index=False)
    return buf.getvalue()


def trace_workbook(t: dict) -> bytes:
    buf = io.BytesIO()
    name = f"trace_{t['address'][:22]}"[:31]
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        prof = {k: v for k, v in t["profile"].items() if k not in ("tokens",)}
        head = [{"field": "note", "value": NOTE}, {"field": "chain", "value": t["chain"]}, {"field": "address", "value": t["address"]},
                {"field": "depth", "value": t["depth"]}, {"field": "direction", "value": t["direction"]},
                {"field": "first funder", "value": (t["first_funder"] or {}).get("funder", "–")}]
        head += [{"field": k, "value": _clean(v)} for k, v in prof.items()]
        pd.DataFrame(head).to_excel(xw, sheet_name=name, index=False)
        _frame(t["counterparties"] or [{"note": "none"}]).to_excel(xw, sheet_name="counterparties", index=False)
        _frame(t["exit_points"] or [{"note": "No labelled exchange, bridge or mixer reached."}]).to_excel(xw, sheet_name="exit_points", index=False)
        _frame(t["graph"]["edges"] or [{"note": "none"}]).to_excel(xw, sheet_name="flow_edges", index=False)
        _frame(t["graph"]["nodes"] or [{"note": "none"}]).to_excel(xw, sheet_name="flow_nodes", index=False)
        _frame(t["timeline"] or [{"note": "none"}]).to_excel(xw, sheet_name="timeline", index=False)
        _frame(t["findings"] or [{"note": "No findings involve this wallet."}]).to_excel(xw, sheet_name="findings", index=False)
    return buf.getvalue()
