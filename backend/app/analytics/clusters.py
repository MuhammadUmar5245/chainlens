"""KMeans behaviour groups, fitted per chain on a sample and then applied to every wallet in batches,
so memory stays flat no matter how many wallets a chain has."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.preprocessing import StandardScaler

from app.config import settings
from app.db.clickhouse import new_client

FEATURES = ["tx_out", "tx_in", "native_sent", "native_received", "uniq_receivers",
            "uniq_senders", "avg_gas_gwei", "contract_call_ratio", "tx_per_block"]
SMALL = 50_000          # below this, use full KMeans like the prototype


def _x(df: pd.DataFrame) -> np.ndarray:
    return np.log1p(df[FEATURES].astype(float).clip(lower=0).to_numpy())


def cluster_chain(feats_table: str, out_table: str, chain: str, k: int, progress=None) -> int:
    reader, writer = new_client(), new_client()
    n = int(reader.command(f"SELECT count() FROM {feats_table} WHERE chain = {{c:String}}", parameters={"c": chain}))
    if n == 0:
        return 0
    k = max(1, min(k, n))
    cols = ", ".join(FEATURES)
    sample = reader.query_df(
        f"SELECT {cols} FROM {feats_table} WHERE chain = {{c:String}} ORDER BY cityHash64(wallet) LIMIT {{lim:UInt64}}",
        parameters={"c": chain, "lim": settings.cluster_sample_rows})
    scaler = StandardScaler().fit(_x(sample))
    xs = scaler.transform(_x(sample))
    if n <= SMALL:
        model = KMeans(n_clusters=k, n_init=10, random_state=42).fit(xs)
    else:
        model = MiniBatchKMeans(n_clusters=k, n_init=3, batch_size=8192, random_state=42).fit(xs)

    done = 0
    with reader.query_df_stream(f"SELECT wallet, {cols} FROM {feats_table} WHERE chain = {{c:String}}",
                                parameters={"c": chain}) as stream:
        for block in stream:
            if block.empty:
                continue
            labels = model.predict(scaler.transform(_x(block))).astype("uint8")
            writer.insert_df(out_table, pd.DataFrame({"chain": chain, "wallet": block["wallet"], "cluster": labels}))
            done += len(block)
            if progress:
                progress(done, n)
    return n
