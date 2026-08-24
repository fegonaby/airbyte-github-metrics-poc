#!/usr/bin/env python3
"""Exercise Airbyte's GitHub source and Databricks Lakehouse destination."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

import airbyte as ab
from airbyte.caches import DuckDBCache

from common import (
    ConfigurationError,
    DATABRICKS_DESTINATION_IMAGE,
    GITHUB_SOURCE_VERSION,
    PYAIRBYTE_VERSION,
    build_databricks_config,
    build_github_config,
    default_start_date,
    ensure_parent,
    parse_streams,
)


DEFAULT_STATE_DB = "output/airbyte_poc/github_databricks_state.duckdb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync one GitHub repository through PyAirbyte into Databricks Delta tables."
        )
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("AIRBYTE_GITHUB_REPOSITORY"),
        help="GitHub selector owner/repo.",
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
    parser.add_argument(
        "--state-db",
        default=DEFAULT_STATE_DB,
        help="Local DuckDB cache used for source state and safe replay.",
    )
    parser.add_argument(
        "--docker-image",
        default=os.environ.get(
            "AIRBYTE_DATABRICKS_DOCKER_IMAGE", DATABRICKS_DESTINATION_IMAGE
        ),
        help="Pinned Airbyte Databricks destination image.",
    )
    parser.add_argument(
        "--force-full-refresh",
        action="store_true",
        help="Ignore saved source state and request a full refresh.",
    )
    return parser.parse_args()


def require_docker() -> None:
    """Fail early with a clear message when the Java destination cannot run."""
    if not shutil.which("docker"):
        raise ConfigurationError(
            "Docker is required to run Airbyte's Java Databricks destination connector."
        )
    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        raise ConfigurationError("Docker is installed but its daemon is not running.")


def main() -> int:
    args = parse_args()
    try:
        require_docker()
        selected = parse_streams(args.streams)
        github_config = build_github_config(
            repository=args.repository,
            token=os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", ""),
            start_date=args.start_date,
            api_url=args.api_url,
        )
        databricks_config = build_databricks_config(os.environ)

        print(f"PyAirbyte: {PYAIRBYTE_VERSION}")
        print(f"GitHub source connector: {GITHUB_SOURCE_VERSION}")
        print(f"Airbyte destination image: {args.docker_image}")
        print(f"Repository selector: {args.repository}")
        print(
            "Databricks target: "
            f"{databricks_config['database']}.{databricks_config['schema']}"
        )

        source = ab.get_source(
            "source-github",
            version=GITHUB_SOURCE_VERSION,
            config=github_config,
        )
        source.check()
        available = set(source.get_available_streams())
        missing = [stream for stream in selected if stream not in available]
        if missing:
            raise ConfigurationError(
                f"Connector does not expose requested streams: {', '.join(missing)}"
            )
        source.select_streams(selected)

        destination = ab.get_destination(
            "destination-databricks",
            config=databricks_config,
            docker_image=args.docker_image,
        )
        destination.check()

        state_db = ensure_parent(args.state_db)
        with DuckDBCache(
            db_path=state_db,
            schema_name="github_databricks_state",
            cache_dir=state_db.parent / ".airbyte_databricks_cache",
            cleanup=False,
        ) as cache:
            result = destination.write(
                source_data=source,
                streams=selected,
                cache=cache,
                force_full_refresh=args.force_full_refresh,
            )

        print(f"\nProcessed destination records: {result.processed_records:,}")
        print("Expected Delta tables:")
        for stream in selected:
            print(
                f"  {databricks_config['database']}."
                f"{databricks_config['schema']}.{stream.lower()}"
            )
        print("\nRun the validation SQL from README.md in a Databricks SQL editor.")
        return 0
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
