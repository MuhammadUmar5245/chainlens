"""Run once before the API and workers start: waits for the databases, creates the
ClickHouse schema and writes the default chains. Safe to run again."""

import time

from sqlalchemy import text

from app.chains import seed_chains
from app.db.clickhouse import apply_schema
from app.db.postgres import SessionLocal


def wait_for(name, check, attempts=60):
    for i in range(attempts):
        try:
            check()
            return
        except Exception as e:  # database still starting
            if i == attempts - 1:
                raise RuntimeError(f"{name} not reachable: {e}") from e
            time.sleep(2)


def main():
    def pg_ok():
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))

    wait_for("PostgreSQL", pg_ok)
    wait_for("ClickHouse", apply_schema)
    with SessionLocal() as s:
        seed_chains(s)
    print("bootstrap: ClickHouse schema applied, chains seeded")


if __name__ == "__main__":
    main()
