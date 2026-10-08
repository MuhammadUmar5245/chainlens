-- Raw transactions from every source, one normalised format for all chains.
-- ReplacingMergeTree keeps one copy per (chain, block_number, tx_hash), so re-running a job never duplicates data.
-- Data fetched from the API is removed after {{HISTORY_DAYS}} days; uploaded dumps are kept until their dataset is deleted.
CREATE TABLE IF NOT EXISTS transactions
(
    chain            LowCardinality(String),
    dataset_id       UInt64,
    source           LowCardinality(String),
    block_number     UInt64,
    block_time       DateTime('UTC'),
    tx_hash          String,
    from_addr        String,
    to_addr          String,
    value_native     Float64,
    gas_limit        UInt64,
    gas_price_gwei   Float64,
    is_contract_call UInt8,
    nonce            UInt64,
    ingested_at      DateTime('UTC') DEFAULT now(),
    INDEX idx_from from_addr TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_to   to_addr   TYPE bloom_filter(0.01) GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (chain, toYYYYMM(block_time))
ORDER BY (chain, block_number, tx_hash)
TTL block_time + INTERVAL {{HISTORY_DAYS}} DAY DELETE WHERE source = 'api';

-- One row per analytics run x chain x wallet. Partitioned by run so old runs can be dropped cheaply.
CREATE TABLE IF NOT EXISTS wallet_features
(
    run_id              UInt64,
    chain               LowCardinality(String),
    wallet              String,
    tx_out              UInt64,
    tx_in               UInt64,
    native_sent         Float64,
    native_received     Float64,
    uniq_receivers      UInt64,
    uniq_senders        UInt64,
    avg_gas_gwei        Float64,
    contract_call_ratio Float64,
    active_blocks       UInt64,
    tx_per_block        Float64,
    net_flow            Float64,
    volume              Float64,
    first_seen          DateTime('UTC'),
    last_seen           DateTime('UTC'),
    tags                Array(LowCardinality(String)),
    anomaly_score       Float64,
    is_anomaly          UInt8,
    cluster             UInt8
)
ENGINE = MergeTree
PARTITION BY run_id
ORDER BY (run_id, chain, wallet);

-- Per-minute activity for each run, used by the charts. Gas keeps a t-digest state so
-- medians stay correct when minutes are rolled up into hours or days.
CREATE TABLE IF NOT EXISTS run_series
(
    run_id         UInt64,
    chain          LowCardinality(String),
    minute         DateTime('UTC'),
    txs            UInt64,
    blocks         UInt64,
    value          Float64,
    contract_calls UInt64,
    gas            AggregateFunction(quantileTDigest, Float64)
)
ENGINE = MergeTree
PARTITION BY run_id
ORDER BY (run_id, chain, minute);
