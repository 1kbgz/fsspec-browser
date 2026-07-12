from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import superstore

DEFAULT_OUTPUT = Path(__file__).with_name("superstore.duckdb")


def create_database(output: Path, seed: int, count: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    rows = superstore.superstore(seed=seed, count=count)
    with duckdb.connect(str(output)) as connection:
        connection.register("superstore_rows", rows)
        connection.execute("CREATE TABLE orders AS SELECT * FROM superstore_rows")
        connection.execute('CREATE INDEX idx_orders_region ON orders ("Region")')
        connection.execute(
            '''
            CREATE VIEW sales_by_region AS
            SELECT "Region", COUNT(*) AS order_count, SUM("Sales") AS total_sales,
                   SUM("Profit") AS total_profit, AVG("Discount") AS average_discount
            FROM orders GROUP BY "Region"
            '''
        )
        connection.execute(
            '''
            CREATE VIEW profit_by_category AS
            SELECT "Category", "Sub-Category", COUNT(*) AS order_count,
                   SUM("Quantity") AS total_quantity, SUM("Sales") AS total_sales,
                   SUM("Profit") AS total_profit
            FROM orders GROUP BY "Category", "Sub-Category"
            '''
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a DuckDB Superstore browser fixture.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    create_database(args.output, args.seed, args.count)
    print(args.output)


if __name__ == "__main__":
    main()
