"""Unit tests for proof-of-concept configuration without external services."""

from __future__ import annotations

import unittest

from common import (
    ConfigurationError,
    build_databricks_config,
    build_github_config,
    parse_streams,
)


class CommonConfigurationTests(unittest.TestCase):
    def test_builds_github_config(self) -> None:
        config = build_github_config(
            repository="owner/repo",
            token="secret",
            start_date="2026-01-01T00:00:00Z",
        )
        self.assertEqual(config["repositories"], ["owner/repo"])
        self.assertEqual(
            config["credentials"]["personal_access_token"],  # type: ignore[index]
            "secret",
        )

    def test_rejects_invalid_repository(self) -> None:
        with self.assertRaises(ConfigurationError):
            build_github_config(
                repository="not-a-repository",
                token="secret",
                start_date="2026-01-01T00:00:00Z",
            )

    def test_stream_parser_deduplicates(self) -> None:
        self.assertEqual(
            parse_streams("pull_requests, reviews,pull_requests"),
            ["pull_requests", "reviews"],
        )

    def test_builds_oauth_databricks_config(self) -> None:
        config = build_databricks_config(
            {
                "AIRBYTE_ACCEPT_DATABRICKS_JDBC_TERMS": "true",
                "DATABRICKS_SERVER_HOSTNAME": "workspace.cloud.databricks.com",
                "DATABRICKS_HTTP_PATH": "sql/1.0/warehouses/abc",
                "DATABRICKS_CATALOG": "main",
                "DATABRICKS_CLIENT_ID": "client",
                "DATABRICKS_CLIENT_SECRET": "secret",
            }
        )
        self.assertEqual(config["authentication"]["auth_type"], "OAUTH")  # type: ignore[index]
        self.assertEqual(config["schema"], "github_airbyte_poc")

    def test_requires_databricks_terms_acceptance(self) -> None:
        with self.assertRaises(ConfigurationError):
            build_databricks_config({})

    def test_rejects_blank_databricks_schema(self) -> None:
        with self.assertRaises(ConfigurationError):
            build_databricks_config(
                {
                    "AIRBYTE_ACCEPT_DATABRICKS_JDBC_TERMS": "true",
                    "DATABRICKS_SERVER_HOSTNAME": "workspace.cloud.databricks.com",
                    "DATABRICKS_HTTP_PATH": "sql/1.0/warehouses/abc",
                    "DATABRICKS_CATALOG": "main",
                    "DATABRICKS_SCHEMA": " ",
                    "DATABRICKS_TOKEN": "secret",
                }
            )


if __name__ == "__main__":
    unittest.main()
