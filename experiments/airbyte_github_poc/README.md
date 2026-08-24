# Airbyte GitHub capability proof of concept

This experiment exercises the released Airbyte GitHub source against one repository in two ways:

1. `sync_to_duckdb.py` uses PyAirbyte's persistent DuckDB cache.
2. `sync_to_databricks.py` uses Airbyte's Databricks Lakehouse destination connector to create final Delta tables in Unity Catalog.

It intentionally selects only five useful streams:

- `repositories`
- `pull_requests`
- `pull_request_stats`
- `reviews`
- `review_comments`

The test demonstrates connector installation, connection checks, catalog discovery, stream selection, typed table creation, saved incremental state, and destination loading. It does not modify the project's existing normalized tables.

Official references: [GitHub source connector](https://docs.airbyte.com/integrations/sources/github) and [Databricks Lakehouse destination](https://docs.airbyte.com/integrations/destinations/databricks).

## Versions used

- PyAirbyte `0.53.3`
- GitHub source connector `2.1.41`
- Databricks destination connector `4.0.2`
- Python `3.10`, `3.11`, or `3.12` (Python `3.9` is not supported by this PyAirbyte version)

## 1. Create the isolated environment

From the repository root:

```bash
uv venv --python 3.11 .venv-airbyte
source .venv-airbyte/bin/activate
uv pip install -r experiments/airbyte_github_poc/requirements.txt
```

The branch-level `.gitignore` excludes `.venv-airbyte`, local secrets, connector caches, and generated databases.

PyAirbyte installs the GitHub connector in an isolated connector environment during the first run. That first run is slower than subsequent runs.

## 2. Configure one GitHub repository

Use a token that can read the selected repository. For a private repository, it needs the appropriate repository read permission.

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN='replace-me'
export AIRBYTE_GITHUB_REPOSITORY='fegonaby/github-analysis'
export AIRBYTE_GITHUB_START_DATE='2026-01-01T00:00:00Z'
```

Alternatively, copy `experiments/airbyte_github_poc/env.example` to `.env`, replace the placeholders, and load it into your shell:

```bash
set -a
source .env
set +a
```

For GitHub Enterprise Server, also set its base URL:

```bash
export AIRBYTE_GITHUB_API_URL='https://github.company.example'
```

Start with a single repository. After the proof of concept, `owner/*` can be used to test Airbyte's organization repository discovery, but it can be significantly slower and consume more API quota.

## 3. Local DuckDB run

First, inspect Airbyte's entire discovered catalog without loading data:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py --discover-only
```

Then run the selected streams:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py
```

The persistent database is created at:

```text
output/airbyte_poc/github_local.duckdb
```

The script prints discovered streams, selected streams, processed-record counts, generated tables, column types, and three sample records. Run the same command again to exercise the saved Airbyte stream state.

Force a clean historical read without deleting the database:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py --force-full-refresh
```

Inspect the database manually:

```bash
python - <<'PY'
import duckdb

con = duckdb.connect('output/airbyte_poc/github_local.duckdb', read_only=True)
print(con.sql('SHOW TABLES FROM github_raw'))
print(con.sql('SELECT repository, number, additions, deletions, changed_files, updated_at FROM github_raw.pull_request_stats ORDER BY updated_at DESC LIMIT 10'))
con.close()
PY
```

The GitHub connector loads PRs for the selected repository; it does not restrict `pull_requests` to `main` or `master`. That branch condition is a downstream query/filter.

## 4. Databricks Delta run

The Databricks destination is a Java connector distributed as a Docker image. Run this script from a workstation, CI runner, or Airbyte host with Docker access; the resulting tables are created in Databricks. It is not intended to run inside a Databricks notebook.

Prerequisites:

- Docker is installed and running.
- Unity Catalog is enabled.
- A SQL warehouse or all-purpose compute endpoint is available.
- The principal can create schemas, tables, and Unity Catalog Volumes in the target catalog.
- You have reviewed and accepted the Databricks JDBC/ODBC driver license.

Configure the destination with a Databricks personal access token. This is a separate token from `GITHUB_PERSONAL_ACCESS_TOKEN`:

```bash
export DATABRICKS_SERVER_HOSTNAME='abc-12345678-wxyz.cloud.databricks.com'
export DATABRICKS_HTTP_PATH='sql/1.0/warehouses/0000-1111111-abcd90'
export DATABRICKS_CATALOG='main'
export DATABRICKS_SCHEMA='github_airbyte_poc'
export DATABRICKS_TOKEN='replace-me'
export AIRBYTE_ACCEPT_DATABRICKS_JDBC_TERMS='true'
```

Run the end-to-end source-to-destination sync:

```bash
python experiments/airbyte_github_poc/sync_to_databricks.py
```

The first run pulls the pinned destination image and can take several minutes. Source state is persisted locally at `output/airbyte_poc/github_databricks_state.duckdb`; rerunning the command demonstrates how the same connection state is reused.

In a Databricks SQL editor, validate the output:

```sql
SHOW TABLES IN main.github_airbyte_poc;

SELECT COUNT(*) AS pr_stat_rows
FROM main.github_airbyte_poc.pull_request_stats;

SELECT
  repository,
  number,
  additions,
  deletions,
  changed_files,
  updated_at
FROM main.github_airbyte_poc.pull_request_stats
ORDER BY updated_at DESC
LIMIT 20;

DESCRIBE DETAIL main.github_airbyte_poc.pull_request_stats;
```

`DESCRIBE DETAIL` should report `delta` as the table format. Airbyte also adds extraction metadata columns to the final table.

## 5. What to compare

Capture these results from both runs:

- Connector setup and discovery time
- Total API/runtime for the five selected streams
- Record counts per stream
- Schema and nested-field representation
- Result of the second incremental run
- GitHub API/rate-limit log messages
- DuckDB versus Databricks table naming and data types
- A sample comparison of `additions`, `deletions`, and `changed_files` against GitHub's PR page

This proof of concept evaluates Airbyte's framework and standard PR-level statistics. It does not test path-filtered LOC because the standard GitHub connector does not expose a pull-request-files stream.

## Troubleshooting

### PyAirbyte refuses to install

Verify the interpreter:

```bash
python --version
```

It must be Python `3.10` through `3.12` for the pinned PyAirbyte release.

### A selected stream returns no rows

Move `AIRBYTE_GITHUB_START_DATE` farther into the past, and verify that the repository has activity in that period.

### GitHub connection check returns HTTP 401

Create or refresh the GitHub token, confirm it can read the selected repository, and export it as `GITHUB_PERSONAL_ACCESS_TOKEN`. These scripts deliberately do not read the old project's `config.py`.

### GitHub Enterprise connection fails

Confirm `AIRBYTE_GITHUB_API_URL` is the enterprise base URL expected by the connector and that the runner trusts the enterprise TLS certificate.

### Databricks destination check fails

Confirm the server hostname and HTTP path from the compute resource's Connection Details page. Also verify catalog privileges for schemas, tables, and Volumes.

### Start over

The generated databases live under `output/`, which is already ignored by Git. Move them aside or delete the specific proof-of-concept files only after deciding you no longer need their saved state.
