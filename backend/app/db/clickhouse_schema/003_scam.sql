-- Scam tracing tables (new; nothing existing is changed).

-- ERC-20 Transfer logs. Same de-duplication and history rules as transactions.
CREATE TABLE IF NOT EXISTS token_transfers
(
    chain          LowCardinality(String),
    dataset_id     UInt64,
    source         LowCardinality(String),
    block_number   UInt64,
    block_time     DateTime('UTC'),
    tx_hash        String,
    log_index      UInt32,
    token_address  String,
    from_addr      String,
    to_addr        String,
    raw_amount     String,
    amount         Float64,
    token_symbol   LowCardinality(String),
    token_decimals UInt8,
    ingested_at    DateTime('UTC') DEFAULT now(),
    INDEX idx_tf_from from_addr TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_tf_to   to_addr   TYPE bloom_filter(0.01) GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (chain, toYYYYMM(block_time))
ORDER BY (chain, block_number, tx_hash, log_index)
TTL block_time + INTERVAL {{HISTORY_DAYS}} DAY DELETE WHERE source = 'api';

-- ERC-20 Approval logs (for approval phishing).
CREATE TABLE IF NOT EXISTS token_approvals
(
    chain               LowCardinality(String),
    dataset_id          UInt64,
    source              LowCardinality(String),
    block_number        UInt64,
    block_time          DateTime('UTC'),
    tx_hash             String,
    log_index           UInt32,
    token_address       String,
    owner               String,
    spender             String,
    raw_amount          String,
    is_unlimited        UInt8,
    spender_is_contract Int8,          -- 1 contract, 0 wallet (EOA), -1 not checked
    ingested_at         DateTime('UTC') DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (chain, toYYYYMM(block_time))
ORDER BY (chain, block_number, tx_hash, log_index)
TTL block_time + INTERVAL {{HISTORY_DAYS}} DAY DELETE WHERE source = 'api';

-- One row per detector finding. run_id = the analytics run it was computed for.
CREATE TABLE IF NOT EXISTS risk_findings
(
    id              UUID DEFAULT generateUUIDv4(),
    run_id          UInt64,
    job_id          UInt64,
    chain           LowCardinality(String),
    detector        LowCardinality(String),
    wallet          String,
    related_wallets Array(String),
    tx_hashes       Array(String),
    score           UInt8,
    severity        LowCardinality(String),
    reason          String,
    details         String,
    created_at      DateTime('UTC') DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY run_id
ORDER BY (run_id, chain, detector, wallet);

-- Combined, explainable risk per wallet.
CREATE TABLE IF NOT EXISTS wallet_risk
(
    run_id        UInt64,
    chain         LowCardinality(String),
    wallet        String,
    risk_score    UInt8,
    severity      LowCardinality(String),
    detectors_hit Array(String),
    top_reasons   Array(String),
    updated_at    DateTime('UTC') DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY run_id
ORDER BY (run_id, chain, wallet);
