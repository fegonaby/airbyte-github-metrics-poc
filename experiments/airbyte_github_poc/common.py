"""Shared configuration helpers for the Airbyte GitHub proof of concept."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional


PYAIRBYTE_VERSION = "0.53.3"
GITHUB_SOURCE_VERSION = "2.1.41"
DATABRICKS_DESTINATION_IMAGE = "airbyte/destination-databricks:4.0.2"

DEFAULT_STREAMS = [
    "repositories",
    "pull_requests",
    "pull_request_stats",
    "reviews",
    "review_comments",
]

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/(?:[A-Za-z0-9_.-]+|\*)$")


class ConfigurationError(ValueError):
    """Raised when required proof-of-concept configuration is missing or invalid."""


def default_start_date(days: int = 30) -> str:
    """Return a UTC Airbyte start date covering a small, recent demo window."""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    return start.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def require_value(value: Optional[str], description: str) -> str:
    """Return a stripped value or raise a user-facing configuration error."""
    if value is None or not value.strip():
        raise ConfigurationError(f"Missing {description}.")
    return value.strip()


def validate_repository(repository: str) -> str:
    """Validate an Airbyte GitHub repository selector such as owner/repo or owner/*."""
    repository = require_value(repository, "GitHub repository (owner/repo)")
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise ConfigurationError(
            "GitHub repository must look like 'owner/repo' or 'owner/*'."
        )
    return repository


def validate_start_date(start_date: str) -> str:
    """Validate the timestamp format required by the GitHub source connector."""
    start_date = require_value(start_date, "start date")
    try:
        datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ConfigurationError(
            "Start date must use UTC format YYYY-MM-DDTHH:MM:SSZ."
        ) from exc
    return start_date


def parse_streams(raw_streams: Optional[str]) -> List[str]:
    """Parse a comma-delimited stream list, preserving order and removing duplicates."""
    requested = raw_streams.split(",") if raw_streams else DEFAULT_STREAMS
    streams: List[str] = []
    for stream in requested:
        normalized = stream.strip()
        if normalized and normalized not in streams:
            streams.append(normalized)
    if not streams:
        raise ConfigurationError("Select at least one Airbyte stream.")
    return streams


def build_github_config(
    repository: str,
    token: str,
    start_date: str,
    api_url: Optional[str] = None,
) -> Dict[str, object]:
    """Build the current source-github connector configuration."""
    config: Dict[str, object] = {
        "repositories": [validate_repository(repository)],
        "start_date": validate_start_date(start_date),
        "credentials": {
            "option_title": "PAT Credentials",
            "personal_access_token": require_value(token, "GitHub access token"),
        },
        "max_waiting_time": 120,
    }
    if api_url and api_url.strip():
        config["api_url"] = api_url.strip()
    return config


def build_databricks_config(env: Mapping[str, str]) -> Dict[str, object]:
    """Build the current destination-databricks connector configuration."""
    accepted = env.get("AIRBYTE_ACCEPT_DATABRICKS_JDBC_TERMS", "").lower()
    if accepted not in {"1", "true", "yes"}:
        raise ConfigurationError(
            "Set AIRBYTE_ACCEPT_DATABRICKS_JDBC_TERMS=true after reviewing the "
            "Databricks JDBC/ODBC driver license."
        )

    client_id = env.get("DATABRICKS_CLIENT_ID", "").strip()
    client_secret = env.get("DATABRICKS_CLIENT_SECRET", "").strip()
    personal_access_token = env.get("DATABRICKS_TOKEN", "").strip()

    if client_id and client_secret:
        authentication: Dict[str, str] = {
            "auth_type": "OAUTH",
            "client_id": client_id,
            "secret": client_secret,
        }
    elif personal_access_token:
        authentication = {
            "auth_type": "BASIC",
            "personal_access_token": personal_access_token,
        }
    else:
        raise ConfigurationError(
            "Set DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET, or set "
            "DATABRICKS_TOKEN."
        )

    return {
        "hostname": require_value(
            env.get("DATABRICKS_SERVER_HOSTNAME"),
            "DATABRICKS_SERVER_HOSTNAME",
        ),
        "http_path": require_value(
            env.get("DATABRICKS_HTTP_PATH"),
            "DATABRICKS_HTTP_PATH",
        ),
        "port": require_value(env.get("DATABRICKS_PORT", "443"), "DATABRICKS_PORT"),
        "database": require_value(
            env.get("DATABRICKS_CATALOG"),
            "DATABRICKS_CATALOG",
        ),
        "schema": require_value(
            env.get("DATABRICKS_SCHEMA", "github_airbyte_poc"),
            "DATABRICKS_SCHEMA",
        ),
        "authentication": authentication,
        "purge_staging_data": True,
        "accept_terms": True,
        "cdc_deletion_mode": "Hard delete",
    }


def ensure_parent(path: str) -> Path:
    """Create the parent directory for a local cache/database path."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def environment(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an environment variable without ever logging its value."""
    return os.environ.get(name, default)
