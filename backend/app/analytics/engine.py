"""Analytics run: the prototype's rules, executed inside ClickHouse.

  1. wallet features   one GROUP BY over the scoped transactions (sent side + received side)
  2. per-chain stats   percentiles for the bot/hub thresholds, mean + std of log features for z-scores
  3. clusters          Python KMeans per chain (see clusters.py)
  4. final results     tags, anomaly score and cluster joined into wallet_features
  5. series            per-minute activity for the charts

Every statistic is computed per chain, so a busy chain never defines "unusual" for a quiet one.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.analytics.clusters import cluster_chain
from app.db.clickhouse import new_client

CHAIN_KEY = re.compile(r"[a-z0-9_]{1,32}")
ANOMALY_COLS = ["tx_out", "tx_in", "native_sent", "native_received", "uniq_receivers", "uniq_senders", "avg_gas_gwei"]


@dataclass
class Scope:
    run_id: int
    chains: list[str]
    dataset_id: int | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None

    def where(self) -> str:
        # rendered as literals (query parameters are not reliable inside CREATE TABLE ... AS SELECT);
        # every value is validated or typed first, so nothing user-written reaches the SQL text
        parts = [f"chain IN ({', '.join(_chain_lit(c) for c in self.chains)})"]
        if self.dataset_id is not None:
            parts.append(f"dataset_id = {int(self.dataset_id)}")
        if self.time_from is not None:
            parts.append(f"block_time >= toDateTime('{_ts(self.time_from)}', 'UTC')")
        if self.time_to is not None:
            parts.append(f"block_time <= toDateTime('{_ts(self.time_to)}', 'UTC')")
        return " AND ".join(parts)


def _chain_lit(key: str) -> str:
    if not CHAIN_KEY.fullmatch(key):
        raise ValueError(f"invalid chain key: {key!r}")
    return f"'{key}'"


def _ts(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def run(scope: Scope, whale: dict[str, float], k: int, anomaly_z: float, progress=lambda p, msg: None) -> dict:
    ch = new_client()
    rid = scope.run_id
    feats, stats, clus = f"tmp_feats_{rid}", f"tmp_stats_{rid}", f"tmp_clusters_{rid}"
    where = scope.where()
    try:
        for t in (feats, stats, clus):
            ch.command(f"DROP TABLE IF EXISTS {t}")
        ch.command(f"ALTER TABLE wallet_features DROP PARTITION {rid}")
        ch.command(f"ALTER TABLE run_series DROP PARTITION {rid}")
        ch.command(f"ALTER TABLE wallet_pairs DROP PARTITION {rid}")

        # 1. wallet features ------------------------------------------------------------------
        progress(0.05, "Building wallet features")
        ch.command(f"""
            CREATE TABLE {feats} ENGINE = MergeTree ORDER BY (chain, wallet) AS
            WITH base AS (
                SELECT chain, block_number, block_time, from_addr, to_addr, value_native, gas_price_gwei, is_contract_call
                FROM transactions FINAL WHERE {where}
            )
            SELECT chain, wallet,
                   tx_out, tx_in, native_sent, native_received, uniq_receivers, uniq_senders,
                   avg_gas_gwei, contract_call_ratio, active_blocks,
                   tx_out / greatest(active_blocks, 1)          AS tx_per_block,
                   native_received - native_sent                AS net_flow,
                   native_received + native_sent                AS volume,
                   if(tx_out = 0, first_in, if(tx_in = 0, first_out, least(first_out, first_in)))  AS first_seen,
                   if(tx_out = 0, last_in,  if(tx_in = 0, last_out,  greatest(last_out, last_in))) AS last_seen
            FROM (
                SELECT chain, from_addr AS wallet,
                       count() AS tx_out, sum(value_native) AS native_sent, uniqExact(to_addr) AS uniq_receivers,
                       avg(gas_price_gwei) AS avg_gas_gwei, avg(is_contract_call) AS contract_call_ratio,
                       uniqExact(block_number) AS active_blocks, min(block_time) AS first_out, max(block_time) AS last_out
                FROM base GROUP BY chain, wallet
            ) AS s
            FULL OUTER JOIN (
                SELECT chain, to_addr AS wallet,
                       count() AS tx_in, sum(value_native) AS native_received, uniqExact(from_addr) AS uniq_senders,
                       min(block_time) AS first_in, max(block_time) AS last_in
                FROM base GROUP BY chain, wallet
            ) AS r USING (chain, wallet)
            WHERE wallet NOT IN ('', 'contract_creation', 'coinbase')
        """)
        wallets = int(ch.command(f"SELECT count() FROM {feats}"))
        if wallets == 0:
            raise ValueError("no transactions found for this scope - fetch or upload data first")

        # 2. per-chain thresholds and z-score parameters --------------------------------------
        progress(0.35, "Computing per-chain thresholds")
        moments = ",\n".join(
            f"avg(log1p({c})) AS m_{c}, if(isNaN(stddevSamp(log1p({c}))) OR stddevSamp(log1p({c})) = 0, 1, stddevSamp(log1p({c}))) AS s_{c}"
            for c in ANOMALY_COLS)
        keys = [c for c in whale if CHAIN_KEY.fullmatch(c)]
        wk = ", ".join(f"'{c}'" for c in keys)
        wv = ", ".join(repr(float(whale[c])) for c in keys)
        ch.command(f"""
            CREATE TABLE {stats} ENGINE = MergeTree ORDER BY chain AS
            SELECT chain,
                   greatest(quantileExactInclusive(0.95)(tx_out), 5)                AS bot_min,
                   greatest(quantileExactInclusive(0.99)(uniq_receivers),
                            quantileExactInclusive(0.99)(uniq_senders), 10)         AS hub_min,
                   CAST(transform(CAST(chain AS String), [{wk}], [{wv}], 100.) AS Float64) AS whale_min,
                   {moments}
            FROM {feats} GROUP BY chain
        """)

        # 3. clusters per chain -----------------------------------------------------------------
        ch.command(f"CREATE TABLE {clus} (chain LowCardinality(String), wallet String, cluster UInt8) "
                   f"ENGINE = MergeTree ORDER BY (chain, wallet)")
        for i, c in enumerate(scope.chains):
            base_p = 0.40 + 0.40 * i / len(scope.chains)
            span = 0.40 / len(scope.chains)
            progress(base_p, f"Clustering {c}")
            cluster_chain(feats, clus, c, k,
                          progress=lambda d, n, b=base_p, s=span, c=c: progress(b + s * d / n, f"Clustering {c}: {d:,} of {n:,} wallets"))

        # 4. final results ------------------------------------------------------------------------
        progress(0.82, "Saving wallet results")
        z = " + ".join(f"pow((log1p(f.{c}) - st.m_{c}) / st.s_{c}, 2)" for c in ANOMALY_COLS)
        ch.command(f"""
            INSERT INTO wallet_features
            SELECT {rid} AS run_id, f.chain, f.wallet,
                   f.tx_out, f.tx_in, f.native_sent, f.native_received, f.uniq_receivers, f.uniq_senders,
                   f.avg_gas_gwei, f.contract_call_ratio, f.active_blocks, f.tx_per_block, f.net_flow, f.volume,
                   f.first_seen, f.last_seen,
                   arrayFilter(x -> x != '', [
                       if(f.volume >= st.whale_min, 'whale', ''),
                       if(f.tx_out >= st.bot_min AND f.tx_per_block >= 1.5, 'high_frequency_bot', ''),
                       if(f.uniq_senders >= st.hub_min OR f.uniq_receivers >= st.hub_min, 'hub_exchange_like', ''),
                       if(f.tx_out >= 3 AND f.contract_call_ratio >= 0.9, 'contract_heavy', ''),
                       if(f.tx_out + f.tx_in = 1, 'one_off', '')
                   ]) AS tags,
                   round(sqrt(({z}) / {len(ANOMALY_COLS)}), 3) AS anomaly_score,
                   anomaly_score >= {float(anomaly_z)} AS is_anomaly,
                   c.cluster
            FROM {feats} AS f
            INNER JOIN {stats} AS st ON st.chain = f.chain
            LEFT JOIN {clus} AS c ON c.chain = f.chain AND c.wallet = f.wallet
        """)

        # 5. per-minute series ------------------------------------------------------------------------
        progress(0.92, "Building activity series")
        ch.command(f"""
            INSERT INTO run_series
            SELECT {rid}, chain, toStartOfMinute(block_time) AS minute,
                   count(), uniqExact(block_number), sum(value_native), sum(is_contract_call),
                   quantileTDigestState(gas_price_gwei)
            FROM transactions FINAL WHERE {where}
            GROUP BY chain, minute
        """)
        # 6. wallet pairs: who transacts with whom, and how often ------------------------------------
        progress(0.96, "Finding connected wallets")
        skip = "('', 'contract_creation', 'coinbase')"
        ch.command(f"""
            INSERT INTO wallet_pairs
            SELECT {rid}, chain, least(from_addr, to_addr) AS pa, greatest(from_addr, to_addr) AS pb,
                   count(), countIf(from_addr = pa), countIf(from_addr = pb),
                   sumIf(value_native, from_addr = pa), sumIf(value_native, from_addr = pb),
                   sum(is_contract_call), uniqExact(block_number), min(block_time), max(block_time)
            FROM transactions FINAL
            WHERE {where} AND from_addr NOT IN {skip} AND to_addr NOT IN {skip} AND from_addr != to_addr
            GROUP BY chain, pa, pb
            HAVING count() >= 2
        """)
        transactions = int(ch.command(f"SELECT sum(txs) FROM run_series WHERE run_id = {rid}"))
        return {"wallets": wallets, "transactions": transactions}
    finally:
        for t in (feats, stats, clus):
            ch.command(f"DROP TABLE IF EXISTS {t}")
