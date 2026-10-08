"""Single-wallet trace over data already loaded into Chainlens (native transfers + ERC-20 transfers).

Money-flow graph: breadth-first, up to `depth` hops in the chosen direction. Hubs are shown but not expanded:
labelled exchanges, bridges, token / DeFi contracts, known contracts, and wallets with more than
hub_degree_limit counterparties. At most max_nodes nodes. Results are indicators, not proof."""

import json
from datetime import datetime

from app.analytics.engine import CHAIN_KEY, _ts
from app.db.clickhouse import new_client
from app.db.models import AnalyticsRun
from app.db.postgres import SessionLocal
from app.ingest.base import norm_id
from app.scam.config import get_scam_settings
from app.scam.detectors.base import EXIT_CATEGORIES, SERVICE_CATEGORIES
from app.scam.labels import labels_for_chain
from app.scam.models import AddressCode, Token

SKIP = ("", "contract_creation", "coinbase")


def _time_filter(time_from: datetime | None, time_to: datetime | None) -> str:
    parts = []
    if time_from:
        parts.append(f"block_time >= toDateTime('{_ts(time_from)}', 'UTC')")
    if time_to:
        parts.append(f"block_time <= toDateTime('{_ts(time_to)}', 'UTC')")
    return (" AND " + " AND ".join(parts)) if parts else ""


def _rows(res) -> list[dict]:
    return [dict(zip(res.column_names, r)) for r in res.result_rows]


class Tracer:
    def __init__(self, chain: str, run_id: int | None = None):
        if not CHAIN_KEY.fullmatch(chain):
            raise ValueError(f"invalid chain key: {chain}")
        self.chain = chain
        self.cfg = get_scam_settings()
        self.ch = new_client()
        with SessionLocal() as s:
            self.labels = labels_for_chain(s, chain)
            self.contracts = {c.address for c in s.query(AddressCode).filter(AddressCode.chain == chain, AddressCode.is_contract.is_(True))}
            self.contracts |= {t.address for t in s.query(Token).filter(Token.chain == chain)}
            q = s.query(AnalyticsRun).filter(AnalyticsRun.status == "succeeded")
            run = s.get(AnalyticsRun, run_id) if run_id else next(
                (r for r in q.order_by(AnalyticsRun.id.desc()).limit(200) if chain in (r.chains or [])), None)
        self.run_id = run.id if run else None

    # ---- data access -------------------------------------------------------------------------
    def edges_touching(self, addresses: list[str], tf: str) -> list[dict]:
        """Aggregated value edges (native + tokens) where any side is in `addresses`."""
        p = {"c": self.chain, "a": addresses}
        native = _rows(self.ch.query(f"""
            SELECT from_addr AS src, to_addr AS dst, 'native' AS asset, sum(value_native) AS total, count() AS n,
                   min(block_time) AS first, max(block_time) AS last
            FROM transactions FINAL
            WHERE chain = {{c:String}} AND value_native > 0 AND (from_addr IN {{a:Array(String)}} OR to_addr IN {{a:Array(String)}}){tf}
            GROUP BY src, dst""", parameters=p))
        tokens = _rows(self.ch.query(f"""
            SELECT from_addr AS src, to_addr AS dst, token_symbol AS asset, sum(amount) AS total, count() AS n,
                   min(block_time) AS first, max(block_time) AS last
            FROM token_transfers FINAL
            WHERE chain = {{c:String}} AND amount > 0 AND (from_addr IN {{a:Array(String)}} OR to_addr IN {{a:Array(String)}}){tf}
            GROUP BY src, dst, asset""", parameters=p))
        return [e for e in native + tokens if e["src"] not in SKIP and e["dst"] not in SKIP]

    def degree(self, addresses: list[str], tf: str) -> dict[str, int]:
        if not addresses:
            return {}
        res = self.ch.query(f"""
            SELECT a, uniqExact(b) FROM (
                SELECT from_addr AS a, to_addr AS b FROM transactions WHERE chain = {{c:String}} AND from_addr IN {{x:Array(String)}}{tf}
                UNION ALL
                SELECT to_addr AS a, from_addr AS b FROM transactions WHERE chain = {{c:String}} AND to_addr IN {{x:Array(String)}}{tf}
            ) GROUP BY a""", parameters={"c": self.chain, "x": addresses})
        return {a: int(n) for a, n in res.result_rows}

    def hub_reason(self, address: str, degree: int) -> str | None:
        cats = {l["category"] for l in self.labels.get(address, [])}
        if cats & SERVICE_CATEGORIES:
            return f"labelled {', '.join(sorted(cats & SERVICE_CATEGORIES))}"
        if address in self.contracts:
            return "contract"
        if degree > self.cfg.trace_hub_degree_limit:
            return f"{degree:,} counterparties"
        return None

    # ---- the trace -----------------------------------------------------------------------------
    def trace(self, address: str, depth: int | None = None, direction: str = "both",
              time_from: datetime | None = None, time_to: datetime | None = None) -> dict:
        cfg = self.cfg
        root = norm_id(address)
        depth = max(1, min(depth or cfg.trace_default_depth, cfg.trace_max_depth))
        if direction not in ("in", "out", "both"):
            raise ValueError("direction must be in, out or both")
        tf = _time_filter(time_from, time_to)

        nodes: dict[str, dict] = {root: {"id": root, "level": 0}}
        edges: dict[tuple, dict] = {}
        frontier, truncated = [root], False
        for level in range(1, depth + 1):
            deg = self.degree(frontier, tf)
            expand = []
            for a in frontier:
                reason = self.hub_reason(a, deg.get(a, 0))
                nodes[a]["degree"] = deg.get(a, 0)
                if reason and a != root:
                    nodes[a]["hub"] = reason              # shown, not expanded
                else:
                    expand.append(a)
            if not expand:
                break
            nxt = []
            for e in self.edges_touching(expand, tf):
                out_edge = e["src"] in expand and direction in ("out", "both")
                in_edge = e["dst"] in expand and direction in ("in", "both")
                if not (out_edge or in_edge):
                    continue
                other = e["dst"] if out_edge and e["src"] in expand else e["src"]
                if other not in nodes:
                    if len(nodes) >= cfg.trace_max_nodes:
                        truncated = True
                        continue
                    nodes[other] = {"id": other, "level": level}
                    nxt.append(other)
                key = (e["src"], e["dst"], e["asset"])
                edges.setdefault(key, {"source": e["src"], "target": e["dst"], "asset": e["asset"], "amount": float(e["total"]),
                                       "count": int(e["n"]), "first": e["first"], "last": e["last"]})
            frontier = nxt
        # hub status for the outermost ring too
        outer = [a for a, n in nodes.items() if "degree" not in n]
        for a, d in self.degree(outer, tf).items():
            nodes[a]["degree"] = d
        for a in outer:
            reason = self.hub_reason(a, nodes[a].get("degree", 0))
            if reason:
                nodes[a]["hub"] = reason

        risk = self._risk(list(nodes))
        for a, n in nodes.items():
            n["labels"] = self.labels.get(a, [])
            n["exit"] = bool({l["category"] for l in n["labels"]} & EXIT_CATEGORIES)
            n["risk"] = risk.get(a)

        return {
            "chain": self.chain, "address": root, "depth": depth, "direction": direction, "run_id": self.run_id,
            "note": "Indicators, not proof. Built from data loaded into Chainlens only"
                    + ("" if not cfg.trace_use_blockbook else "; Blockbook history is enabled") + ".",
            "truncated": truncated, "limits": {"max_nodes": cfg.trace_max_nodes, "hub_degree_limit": cfg.trace_hub_degree_limit},
            "profile": self.profile(root, tf),
            "counterparties": self.counterparties(root, tf),
            "first_funder": self.first_funder(root, tf),
            "exit_points": self.exit_points(root, list(edges.values()), nodes),
            "graph": {"nodes": sorted(nodes.values(), key=lambda n: (n["level"], n["id"])),
                      "edges": sorted(edges.values(), key=lambda e: (-e["amount"], e["source"], e["target"]))},
            "timeline": self.timeline(root, tf),
            "findings": self.findings(root),
        }

    def _risk(self, addresses: list[str]) -> dict[str, dict]:
        if not self.run_id or not addresses:
            return {}
        res = self.ch.query("SELECT wallet, risk_score, severity FROM wallet_risk WHERE run_id = {r:UInt64} AND chain = {c:String} "
                            "AND wallet IN {a:Array(String)}", parameters={"r": self.run_id, "c": self.chain, "a": addresses})
        return {w: {"score": int(s), "severity": sev} for w, s, sev in res.result_rows}

    def profile(self, root: str, tf: str) -> dict:
        p = {"c": self.chain, "a": root}
        tx = _rows(self.ch.query(f"""
            SELECT count() AS transactions, min(block_time) AS first_seen, max(block_time) AS last_seen,
                   sumIf(value_native, to_addr = {{a:String}}) AS native_in, sumIf(value_native, from_addr = {{a:String}}) AS native_out,
                   countIf(from_addr = {{a:String}}) AS sent, countIf(to_addr = {{a:String}}) AS received,
                   uniqExact(toHour(block_time)) AS active_hours, uniqExact(block_number) AS active_blocks,
                   countIf(from_addr = {{a:String}} AND is_contract_call = 1) AS contract_calls
            FROM transactions FINAL WHERE chain = {{c:String}} AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}""",
            parameters=p))[0]
        tokens = _rows(self.ch.query(f"""
            SELECT token_symbol AS symbol, sumIf(amount, to_addr = {{a:String}}) AS received, sumIf(amount, from_addr = {{a:String}}) AS sent,
                   count() AS transfers
            FROM token_transfers FINAL WHERE chain = {{c:String}} AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}
            GROUP BY symbol ORDER BY transfers DESC LIMIT 8""", parameters=p))
        features = None
        if self.run_id:
            f = _rows(self.ch.query("SELECT tags, anomaly_score, tx_per_block, cluster FROM wallet_features "
                                    "WHERE run_id = {r:UInt64} AND chain = {c:String} AND wallet = {a:String}",
                                    parameters=p | {"r": self.run_id}))
            features = f[0] if f else None
        risk = self._risk([root]).get(root)
        per_block = tx["sent"] / max(tx["active_blocks"], 1)
        bot = (features and "high_frequency_bot" in features["tags"]) or per_block >= 1.5 or tx["active_hours"] >= 20
        return tx | {"tokens": tokens, "tags": features["tags"] if features else [],
                     "anomaly_score": features["anomaly_score"] if features else None,
                     "behaviour": "bot-like" if bot else "human-like", "risk": risk,
                     "labels": self.labels.get(root, [])}

    def counterparties(self, root: str, tf: str, limit: int = 100) -> list[dict]:
        rows = _rows(self.ch.query(f"""
            SELECT other, groupUniqArray(dir) AS directions, sum(n) AS transactions, sum(native) AS native_amount,
                   min(first) AS first, max(last) AS last FROM (
                SELECT if(from_addr = {{a:String}}, to_addr, from_addr) AS other, if(from_addr = {{a:String}}, 'out', 'in') AS dir,
                       count() AS n, sum(value_native) AS native, min(block_time) AS first, max(block_time) AS last
                FROM transactions FINAL WHERE chain = {{c:String}} AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}
                GROUP BY other, dir
                UNION ALL
                SELECT if(from_addr = {{a:String}}, to_addr, from_addr) AS other, if(from_addr = {{a:String}}, 'out', 'in') AS dir,
                       count() AS n, 0 AS native, min(block_time) AS first, max(block_time) AS last
                FROM token_transfers FINAL WHERE chain = {{c:String}} AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}
                GROUP BY other, dir
            ) WHERE other != {{a:String}} GROUP BY other ORDER BY transactions DESC, other LIMIT {int(limit)}""",
            parameters={"c": self.chain, "a": root}))
        for r in rows:
            dirs = r.pop("directions")
            r["direction"] = "both" if len(dirs) > 1 else dirs[0]
            r["labels"] = self.labels.get(r["other"], [])
        return rows

    def first_funder(self, root: str, tf: str) -> dict | None:
        rows = _rows(self.ch.query(f"""
            SELECT * FROM (
                SELECT block_time AS time, block_number AS block, tx_hash, from_addr AS funder, value_native AS amount, 'native' AS asset
                FROM transactions FINAL WHERE chain = {{c:String}} AND to_addr = {{a:String}} AND value_native > 0{tf}
                UNION ALL
                SELECT block_time, block_number, tx_hash, from_addr, amount, token_symbol
                FROM token_transfers FINAL WHERE chain = {{c:String}} AND to_addr = {{a:String}} AND amount > 0{tf}
            ) ORDER BY block, tx_hash LIMIT 1""", parameters={"c": self.chain, "a": root}))
        if not rows:
            return None
        r = rows[0]
        r["labels"] = self.labels.get(r["funder"], [])
        return r

    def exit_points(self, root: str, edges: list[dict], nodes: dict) -> list[dict]:
        """Labelled exchanges / bridges / mixers reached by money leaving the wallet (following edges outward)."""
        out_adj: dict[str, list[dict]] = {}
        for e in edges:
            out_adj.setdefault(e["source"], []).append(e)
        found, seen, frontier = {}, {root}, [root]
        while frontier:
            nxt = []
            for a in frontier:
                for e in out_adj.get(a, []):
                    b = e["target"]
                    if nodes.get(b, {}).get("exit") and b not in found:
                        found[b] = {"address": b, "labels": nodes[b]["labels"], "via": a, "asset": e["asset"], "amount": e["amount"]}
                    if b not in seen:
                        seen.add(b)
                        nxt.append(b)
            frontier = nxt
        return sorted(found.values(), key=lambda x: -x["amount"])

    def timeline(self, root: str, tf: str, limit: int = 500) -> list[dict]:
        return _rows(self.ch.query(f"""
            SELECT * FROM (
                SELECT block_time AS time, block_number AS block, tx_hash, if(from_addr = {{a:String}}, 'out', 'in') AS direction,
                       if(from_addr = {{a:String}}, to_addr, from_addr) AS counterparty, value_native AS amount, 'native' AS asset
                FROM transactions FINAL WHERE chain = {{c:String}} AND value_native > 0 AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}
                UNION ALL
                SELECT block_time, block_number, tx_hash, if(from_addr = {{a:String}}, 'out', 'in'),
                       if(from_addr = {{a:String}}, to_addr, from_addr), amount, token_symbol
                FROM token_transfers FINAL WHERE chain = {{c:String}} AND (from_addr = {{a:String}} OR to_addr = {{a:String}}){tf}
            ) ORDER BY block, tx_hash LIMIT {int(limit)}""", parameters={"c": self.chain, "a": root}))

    def findings(self, root: str) -> list[dict]:
        if not self.run_id:
            return []
        rows = _rows(self.ch.query("""
            SELECT detector, wallet, related_wallets, tx_hashes, score, severity, reason, details FROM risk_findings
            WHERE run_id = {r:UInt64} AND chain = {c:String} AND (wallet = {a:String} OR has(related_wallets, {a:String}))
            ORDER BY score DESC, detector LIMIT 100""", parameters={"r": self.run_id, "c": self.chain, "a": root}))
        for r in rows:
            r["details"] = json.loads(r["details"]) if r["details"] else {}
        return rows
