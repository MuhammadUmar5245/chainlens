-- Wallet pairs per analytics run: how often two wallets transacted with each other, in each direction.
-- a < b alphabetically, so each pair is stored once. Only pairs with 2+ transactions are kept.
CREATE TABLE IF NOT EXISTS wallet_pairs
(
    run_id         UInt64,
    chain          LowCardinality(String),
    a              String,
    b              String,
    txs            UInt64,
    a_to_b         UInt64,
    b_to_a         UInt64,
    value_a_to_b   Float64,
    value_b_to_a   Float64,
    contract_calls UInt64,
    blocks         UInt64,
    first_seen     DateTime('UTC'),
    last_seen      DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY run_id
ORDER BY (run_id, chain, a, b);
