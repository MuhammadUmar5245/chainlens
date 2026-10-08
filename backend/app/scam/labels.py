"""Address labels: CSV import (UI and CLI), lookup, and the MVP test set. Nothing is scraped."""

import csv
import io
import re
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ingest.base import norm_id
from app.scam.models import CATEGORIES, AddressLabel

TEST_SOURCE = "TEST-sample"
TEST_LABELS_CSV = Path(__file__).parent / "data" / "test_labels.csv"
ADDRESS = re.compile(r"[0-9A-Za-z]{14,100}")
CATEGORY_ALIASES = {"cex": "exchange", "sanction": "sanctioned", "ofac": "sanctioned", "scam": "scam_reported",
                    "phishing": "scam_reported", "tornado": "mixer", "dex": "defi", "contract": "other"}


def import_csv(db: Session, text: str, default_source: str, default_chain: str = "eth") -> dict:
    """Columns: address, label, category, [chain], [source]. Returns counts; bad rows are listed, not fatal."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    if not {"address", "label", "category"} <= fields:
        raise ValueError("The CSV needs the columns address, label and category (chain and source are optional).")
    rows, errors = [], []
    for i, raw in enumerate(reader, start=2):
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        address = norm_id(r.get("address"))
        category = r.get("category", "").lower()
        category = CATEGORY_ALIASES.get(category, category)
        if not ADDRESS.fullmatch(address or ""):
            errors.append(f"line {i}: address '{r.get('address')}' is not valid")
            continue
        if category not in CATEGORIES:
            errors.append(f"line {i}: category '{r.get('category')}' must be one of {', '.join(CATEGORIES)}")
            continue
        rows.append({"chain": (r.get("chain") or default_chain).lower(), "address": address,
                     "label": (r.get("label") or category)[:200], "category": category,
                     "source": (r.get("source") or default_source)[:100]})
    if rows:
        stmt = insert(AddressLabel).values(rows)
        stmt = stmt.on_conflict_do_update(constraint="uq_address_labels_chain_address_source",
                                          set_={"label": stmt.excluded.label, "category": stmt.excluded.category})
        db.execute(stmt)
        db.commit()
    return {"imported": len(rows), "rejected": len(errors), "errors": errors[:50]}


def load_test_labels(db: Session) -> dict:
    return import_csv(db, TEST_LABELS_CSV.read_text(encoding="utf-8"), default_source=TEST_SOURCE)


def remove_source(db: Session, source: str) -> int:
    n = db.execute(delete(AddressLabel).where(AddressLabel.source == source)).rowcount
    db.commit()
    return n


def labels_for_chain(db: Session, chain: str) -> dict[str, list[dict]]:
    """address -> list of {label, category, source} for one chain."""
    out: dict[str, list[dict]] = {}
    for l in db.query(AddressLabel).filter(AddressLabel.chain == chain):
        out.setdefault(l.address, []).append({"label": l.label, "category": l.category, "source": l.source})
    return out
