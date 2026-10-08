# Chainlens

On-chain behaviour analytics for Bitcoin, Ethereum, EthereumPoW, Ethereum Classic and Solana.
Load transactions from the NOWNodes API or from a data dump, run wallet-behaviour analytics
over millions of records, save the results in a database, and explore them in a React dashboard.

Design, data model and roadmap: [docs/design-doc.html](docs/design-doc.html)

## Quick start

Requirements: Docker Desktop (or Docker Engine with Compose v2).

```bash
cp .env.example .env          # then put your NOWNodes key in NOWNODES_API_KEY
docker compose up --build
```

| What | Where |
|---|---|
| React app | http://localhost:8080 |
| API + interactive docs | http://localhost:8000/docs |
| ClickHouse HTTP | http://localhost:8123 |

First steps in the app:

1. **Data sources → Fetch from API**: pick a chain, fetch the latest 50 blocks. Analytics run automatically when the fetch finishes.
2. Or **Data sources → Upload a data dump**: drop a CSV, Parquet, JSON Lines or Excel file, check the suggested column mapping, load it.
3. **Overview** and **Wallets** show the results. Use the chain filter at the top to switch chains.

## How it fits together

```
React (nginx :8080) ──/api──▶ FastAPI (:8000) ──▶ PostgreSQL   chains, datasets, jobs, runs, uploads
                                   │                ClickHouse   transactions, wallet_features, run_series
                                   └─ Redis ──▶ Celery workers ──▶ NOWNodes JSON-RPC / uploaded files
```

* **Every load is a job** with progress, cancel and retry. Fetches checkpoint every 1,000 blocks.
* **Storage de-duplicates** on `(chain, block_number, tx_hash)`, so re-running a job never doubles data.
* **History**: data fetched from the API is removed after `HISTORY_DAYS` (30). Uploaded dumps are kept until deleted.
* **Analytics** run inside ClickHouse, per chain: wallet features, behaviour tags, anomaly score, KMeans groups.
  On the same data they match the original pandas prototype exactly.

## Project layout

```
backend/
  app/
    api/            REST endpoints (FastAPI routers)
    ingest/         NOWNodes EVM client, data-dump loader
    analytics/      ClickHouse SQL engine + clustering
    jobs/           Celery app and tasks (fetch, load_upload, analytics, sync_chains)
    db/             PostgreSQL models, ClickHouse client + schema files
  migrations/       Alembic migrations (PostgreSQL)
frontend/
  src/
    api/            typed API client
    pages/          Overview, Wallets, WalletDetail, DataSources, Jobs, Settings
    components/     filter bar, charts, shared UI
docs/               design document
docker-compose.yml
.env.example
```

## Developing without Docker for the app code

Run the databases in Docker and the app on your machine:

```bash
docker compose up -d postgres clickhouse redis
# backend (Python 3.12)
cd backend
pip install -r requirements.txt
export POSTGRES_URL=postgresql+psycopg://chainlens:chainlens@localhost:5432/chainlens  # see app/config.py for all settings
alembic upgrade head && python -m app.bootstrap
uvicorn app.main:app --reload                         # API on :8000
celery -A app.jobs.celery_app worker --loglevel=info  # in a second terminal
# frontend
cd ../frontend
npm install
npm run dev                                           # http://localhost:5173, proxies /api to :8000
```

The PostgreSQL port is not published by default; add `ports: ["5432:5432"]` to the `postgres` service for this setup.

> **Windows note:** on machines with Smart App Control / an Application Control policy, native files from npm
> (Rollup, esbuild) and pip (SciPy) can be blocked, so `npm run build` fails locally. The Docker build is not affected.
> `npm run typecheck` works everywhere.

## Configuration

All settings are environment variables; see [.env.example](.env.example) and [backend/app/config.py](backend/app/config.py).
Chain endpoints, whale thresholds, request limits and live sync are edited in the app under **Settings**.

**Never commit `.env`.** It holds the NOWNodes key and is listed in `.gitignore`.

## Chains and the cost of 30 days of history

Three adapter families (`backend/app/ingest/`): EVM (Ethereum, EthereumPoW, Ethereum Classic), UTXO (Bitcoin) and Solana.
One API call per block or slot; times measured on NOWNodes:

| Chain | Blocks in 30 days | Time per call | Backfill (defaults) |
|---|---:|---:|---:|
| Bitcoin | 4,320 | ~75 s | ~22 hours |
| Ethereum | 216,000 | <1 s | ~6 hours |
| EthereumPoW | ~199,000 | <1 s | ~5.5 hours |
| Ethereum Classic | ~199,000 | <1 s | ~5.5 hours |
| Solana | ~6.5 M slots | ~35 s | not practical: use samples or data dumps |

Bitcoin rows are payment outputs (`txid:n`), sender = largest input. Solana skips vote transactions.
Details in the design doc, section "Chains".