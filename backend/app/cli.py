"""Chainlens command line (scam tracing). Run inside the stack, e.g.:

    docker compose exec api python -m app.cli trace --wallet 0x... --chain eth --depth 2
    docker compose exec api python -m app.cli labels import my_list.csv --source ofac-2026-10
    docker compose exec api python -m app.cli labels test-set
    docker compose exec api python -m app.cli detect --run 5
    docker compose exec api python -m app.cli enrich --chain eth --dataset 6
    docker compose exec api python -m app.cli export --run 5 --out /data/uploads/scam_run5.xlsx
"""

import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="Chainlens scam tracing tools (results are indicators, not proof)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace", help="trace one wallet")
    t.add_argument("--wallet", required=True)
    t.add_argument("--chain", default="eth")
    t.add_argument("--depth", type=int, default=None)
    t.add_argument("--direction", choices=["in", "out", "both"], default="both")
    t.add_argument("--run", type=int, default=None, help="analytics run for risk scores (default: latest)")
    t.add_argument("--json", action="store_true", help="print the full result as JSON")
    t.add_argument("--xlsx", help="also write an Excel file to this path")

    lb = sub.add_parser("labels", help="manage address labels")
    lsub = lb.add_subparsers(dest="action", required=True)
    li = lsub.add_parser("import", help="import a CSV (address,label,category[,chain][,source])")
    li.add_argument("csv")
    li.add_argument("--source", default="")
    li.add_argument("--chain", default="eth")
    lsub.add_parser("test-set", help="load the clearly marked TEST labels (MVP only)")
    lr = lsub.add_parser("remove", help="remove all labels of one source")
    lr.add_argument("--source", required=True)

    d = sub.add_parser("detect", help="queue scam detection for an analytics run")
    d.add_argument("--run", type=int, required=True)

    e = sub.add_parser("enrich", help="queue ERC-20 transfer/approval loading")
    e.add_argument("--chain", default="eth")
    e.add_argument("--dataset", type=int)
    e.add_argument("--from-block", type=int)
    e.add_argument("--to-block", type=int)

    x = sub.add_parser("export", help="write the scam tracing Excel export")
    x.add_argument("--run", type=int, required=True)
    x.add_argument("--chains", default="btc,eth,ethw,etc,sol")
    x.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "trace":
        from app.scam.trace import Tracer
        r = Tracer(a.chain, a.run).trace(a.wallet, a.depth, a.direction)
        if a.xlsx:
            from app.scam.export import trace_workbook
            open(a.xlsx, "wb").write(trace_workbook(r))
        if a.json:
            print(json.dumps(r, default=str, indent=2))
            return
        p = r["profile"]
        print(f"{r['address']} on {r['chain']}  ({r['note']})")
        print(f"  seen {p['first_seen']} -> {p['last_seen']} · {p['transactions']} txs · {p['behaviour']} · tags {', '.join(p['tags']) or '-'}")
        print(f"  risk: {p['risk'] or 'none'} · anomaly score {p['anomaly_score']}")
        f = r["first_funder"]
        print(f"  first funder: {f['funder'] if f else '-'}")
        print(f"  counterparties: {len(r['counterparties'])} · graph {len(r['graph']['nodes'])} nodes / {len(r['graph']['edges'])} edges"
              + (" (truncated)" if r["truncated"] else ""))
        for x_ in r["exit_points"][:10]:
            print(f"  exit point: {x_['address']} ({'; '.join(l['label'] for l in x_['labels'])})")
        for fd in r["findings"][:10]:
            print(f"  [{fd['severity']}] {fd['detector']}: {fd['reason']}")
    elif a.cmd == "labels":
        from app.db.postgres import SessionLocal
        from app.scam import labels as L
        with SessionLocal() as s:
            if a.action == "import":
                print(L.import_csv(s, open(a.csv, encoding="utf-8").read(), default_source=a.source or a.csv, default_chain=a.chain))
            elif a.action == "test-set":
                print(L.load_test_labels(s))
            else:
                print({"removed": L.remove_source(s, a.source)})
    elif a.cmd in ("detect", "enrich"):
        from app.db.models import AnalyticsRun
        from app.db.postgres import SessionLocal
        from app.scam.tasks import _scam_chains, create_job, enqueue_scam_job
        with SessionLocal() as s:
            if a.cmd == "detect":
                run = s.get(AnalyticsRun, a.run)
                if run is None:
                    sys.exit("analytics run not found")
                job = create_job(s, "scam_detect", {"chains": _scam_chains(list(run.chains))}, dataset_id=run.dataset_id, run_id=run.id)
            else:
                params = {"chain": a.chain, "dataset_id": a.dataset, "from_block": a.from_block, "to_block": a.to_block}
                job = create_job(s, "enrich_tokens", params, dataset_id=a.dataset)
        enqueue_scam_job(job)
        print(f"queued job #{job.id} ({job.type}); follow it on the Jobs page")
    elif a.cmd == "export":
        from app.scam.export import scam_workbook
        open(a.out, "wb").write(scam_workbook(a.run, [c.strip() for c in a.chains.split(",") if c.strip()]))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
