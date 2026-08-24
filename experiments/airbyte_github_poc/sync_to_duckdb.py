#!/usr/bin/env python3
"""Exercise Airbyte's GitHub source and persistent local DuckDB cache."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List

import airbyte as ab
import duckdb
from airbyte.caches import DuckDBCache

from common import (
    ConfigurationError,
    GITHUB_SOURCE_VERSION,
    PYAIRBYTE_VERSION,
    build_github_config,
    default_start_date,
    ensure_parent,
    parse_streams,
)


DEFAULT_DB = "output/airbyte_poc/github_local.duckdb"
DEFAULT_SCHEMA = "github_raw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync one GitHub repository through PyAirbyte into DuckDB."
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("AIRBYTE_GITHUB_REPOSITORY"),
        help="GitHub selector owner/repo (or owner/* for a later org-wide test).",
    )
    parser.add_argument(
        "--start-date",
        default=os.environ.get("AIRBYTE_GITHUB_START_DATE", default_start_date()),
        help="UTC lower bound, formatted YYYY-MM-DDTHH:MM:SSZ (default: 30 days ago).",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("AIRBYTE_GITHUB_API_URL"),
        help="Optional GitHub Enterprise base URL.",
    )
    parser.add_argument(
        "--streams",
        default=os.environ.get("AIRBYTE_GITHUB_STREAMS"),
        help="Comma-delimited streams; defaults to the core PR capability set.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="Persistent DuckDB path.")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, help="DuckDB schema name.")
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Check credentials and print the connector catalog without syncing.",
    )
    parser.add_argument(
        "--force-full-refresh",
        action="store_true",
        help="Ignore saved stream state for this run.",
    )
    return parser.parse_args()


def quoted(identifier: str) -> str:
    """Safely quote a DuckDB identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def validate_streams(available: Iterable[str], requested: List[str]) -> None:
    available_set = set(available)
    missing = [name for name in requested if name not in available_set]
    if missing:
        raise ConfigurationError(
            f"Connector does not expose requested streams: {', '.join(missing)}"
        )


def print_catalog(available: List[str], selected: List[str]) -> None:
    print("\nDiscovered GitHub streams:")
    for stream in sorted(available):
        marker = "*" if stream in selected else " "
        print(f"  {marker} {stream}")
    print("\n* selected for this proof of concept")


def inspect_duckdb(db_path: Path, schema: str, selected: List[str]) -> None:
    """Show the materialized tables, counts, columns, and a small sample."""
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ?
            ORDER BY table_name
            """,
            [schema],
        ).fetchall()
        tables = [row[0] for row in rows]

        print(f"\nDuckDB tables in {schema} ({db_path}):")
        for table in tables:
            count = connection.execute(
                f"SELECT COUNT(*) FROM {quoted(schema)}.{quoted(table)}"
            ).fetchone()[0]
            selected_marker = " [selected stream]" if table in selected else ""
            print(f"  {table}: {count:,} rows{selected_marker}")

        sample_candidates = (
            "pull_request_stats",
            "pull_requests",
            "repositories",
        )
        sample_table = next((name for name in sample_candidates if name in tables), None)
        if sample_table:
            print(f"\nColumns in {sample_table}:")
            columns = connection.execute(
                f"DESCRIBE {quoted(schema)}.{quoted(sample_table)}"
            ).fetchall()
            for name, data_type, *_ in columns:
                print(f"  {name}: {data_type}")

            print(f"\nSample {sample_table} records:")
            frame = connection.execute(
                f"SELECT * FROM {quoted(schema)}.{quoted(sample_table)} LIMIT 3"
            ).fetchdf()
            if frame.empty:
                print("  (no records in the selected date range)")
            else:
                print(frame.to_string(index=False, max_cols=12))
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    try:
        token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        selected = parse_streams(args.streams)
        config = build_github_config(
            repository=args.repository,
            token=token,
            start_date=args.start_date,
            api_url=args.api_url,
        )

        print(f"PyAirbyte: {PYAIRBYTE_VERSION}")
        print(f"GitHub source connector: {GITHUB_SOURCE_VERSION}")
        print(f"Repository selector: {args.repository}")
        print(f"Start date: {args.start_date}")

        source = ab.get_source(
            "source-github",
            version=GITHUB_SOURCE_VERSION,
            config=config,
        )
        source.check()

        available = source.get_available_streams()
        validate_streams(available, selected)
        print_catalog(available, selected)
        if args.discover_only:
            return 0

        source.select_streams(selected)
        db_path = ensure_parent(args.db)
        cache_dir = db_path.parent / ".airbyte_cache"

        with DuckDBCache(
            db_path=db_path,
            schema_name=args.schema,
            cache_dir=cache_dir,
            cleanup=False,
        ) as cache:
            result = source.read(
                cache=cache,
                force_full_refresh=args.force_full_refresh,
            )
            print(f"\nProcessed records this run: {result.processed_records:,}")
            for name, records in result.streams.items():
                print(f"  {name}: {len(records):,} cached records")

        inspect_duckdb(db_path, args.schema, selected)
        print("\nRun the same command again to observe persisted incremental state.")
        return 0
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
