"""Unit tests for proof-of-concept configuration without external services."""

from __future__ import annotations

import unittest

from common import (
    ConfigurationError,
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


if __name__ == "__main__":
    unittest.main()
