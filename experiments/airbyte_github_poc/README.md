# Airbyte GitHub capability proof of concept

## Decision

This proof of concept uses no Docker and no Airbyte Cloud.

- Locally, PyAirbyte runs the open-source GitHub source connector and persists records and connector state in a new DuckDB file.
- In Databricks, a notebook/job will run the same Python GitHub source connector, convert the results to Spark DataFrames, and `MERGE` them into Delta tables.
- Fetching happens only when the local command or Databricks job runs. Nothing runs continuously unless we later schedule the job.
- Airbyte's Docker-based Databricks destination connector is not part of this design.

The local DuckDB script is implemented. The Databricks notebook is the next implementation step documented below.

## Architecture

### Local capability test

```text
GitHub
  -> PyAirbyte GitHub source connector
  -> DuckDB cache and checkpoint state
```

### Databricks capability test

```text
Scheduled or manually triggered Databricks notebook
  -> GitHub PAT from Databricks Secrets
  -> PyAirbyte GitHub source connector
  -> temporary per-run records on the driver
  -> Spark MERGE
  -> persistent Unity Catalog Delta tables
```

The intended raw Delta tables are:

- `repositories`
- `pull_requests`
- `pull_request_stats`
- `reviews`
- `review_comments`

The standard connector supplies PR-level `additions`, `deletions`, and `changed_files`. It does not expose a pull-request-files stream, so path-filtered or per-file LOC remains custom project logic.

## Is a Databricks PyAirbyte cache supported?

No. PyAirbyte `0.53.3` does not provide a Databricks or Delta cache backend. Its built-in SQL cache implementations are DuckDB, MotherDuck, Postgres, Snowflake, and BigQuery.

This is different from Airbyte's Databricks destination connector. The destination can load tables into Databricks, but it is not a PyAirbyte cache, and running that Java destination through PyAirbyte requires Docker. We are not using it.

Databricks also has a feature called disk cache, formerly Delta cache. That cache accelerates repeated reads of Parquet and Delta files. It does not store GitHub connector checkpoints and does not control incremental ingestion.

For the first Databricks notebook test, we will avoid a durable PyAirbyte cache:

1. Fetch a small recent window, initially 30 days for one repository.
2. Stage the current run temporarily on the Databricks driver.
3. Use stable record keys to `MERGE` into the raw Delta tables.
4. Rerun the same window to prove the merge is idempotent.
5. Add a small Delta `sync_state` table and overlap window only if the connector proves useful.

The raw Delta tables are durable storage. They are not a cache.

## What is Airbyte Cloud?

Airbyte Cloud is Airbyte's fully managed hosted service. You configure source and destination credentials, and Airbyte operates the infrastructure that runs manual or scheduled syncs.

We are not using Airbyte Cloud in this proof of concept because the current security assumption is that an external managed service should not receive the GitHub or Databricks credentials or fetch the organization data. Running the open-source Python connector inside our local environment or Databricks keeps execution under our control.

## Official reading

- [PyAirbyte cache and destination overview](https://airbytehq.github.io/PyAirbyte/airbyte.html#writing-to-sql-caches)
- [PyAirbyte cache API and supported cache classes](https://airbytehq.github.io/PyAirbyte/airbyte/caches.html)
- [Airbyte Cloud product overview](https://airbyte.com/product/airbyte-cloud)
- [Airbyte GitHub source connector](https://docs.airbyte.com/integrations/sources/github)
- [Airbyte Databricks destination connector](https://docs.airbyte.com/integrations/destinations/databricks)
- [Databricks disk cache](https://docs.databricks.com/aws/en/optimizations/disk-cache)

## Versions used

- PyAirbyte `0.53.3`
- GitHub source connector `2.1.41`
- Python `3.10`, `3.11`, or `3.12`

Python `3.9` is not supported by this PyAirbyte version.

## Run the local DuckDB test

From the repository root, create an isolated environment:

```bash
uv venv --python 3.11 .venv-airbyte
source .venv-airbyte/bin/activate
uv pip install -r experiments/airbyte_github_poc/requirements.txt
```

Configure one repository and a GitHub PAT that can read it:

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN='replace-me'
export AIRBYTE_GITHUB_REPOSITORY='fegonaby/github-analysis'
export AIRBYTE_GITHUB_START_DATE='2026-01-01T00:00:00Z'
```

For GitHub Enterprise Server, also configure its base URL:

```bash
export AIRBYTE_GITHUB_API_URL='https://github.company.example'
```

Discover the connector catalog without loading records:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py --discover-only
```

Run the selected streams:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py
```

The script creates a separate database at:

```text
output/airbyte_poc/github_local.duckdb
```

Run the same command again to exercise the saved connector state. To request a clean historical read, use:

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

## Databricks notebook implementation plan

The notebook will:

1. Install or use a cluster-installed pinned PyAirbyte package.
2. Read `GITHUB_PERSONAL_ACCESS_TOKEN` from a Databricks secret scope.
3. Accept repository, start date, catalog, and schema as job parameters.
4. Run the five selected GitHub streams only when the notebook executes.
5. Convert each result stream into a Spark DataFrame.
6. Create raw Delta tables when absent.
7. `MERGE` records using stream-specific stable keys so reruns update records instead of duplicating them.
8. Print fetched, inserted, and updated record counts for comparison with the local run.

Because the notebook runs inside Databricks, it does not need a Databricks PAT to write tables. It uses the identity assigned to the notebook or job compute. That identity needs permission to create or modify the selected catalog and schema.

## What to evaluate

- Connector installation and discovery time
- Available versus selected streams
- Total API/runtime for the selected streams
- Record counts and inferred schemas
- GitHub rate-limit and retry messages
- PR statistics compared with the GitHub UI
- Behavior when the same local sync or Delta merge runs twice
- Whether the lack of per-file PR data is acceptable

## Troubleshooting

### PyAirbyte refuses to install

Run `python --version`. It must be Python `3.10` through `3.12` for the pinned release.

### GitHub returns HTTP 401

Create or refresh the GitHub token, confirm it can read the selected repository, and export it as `GITHUB_PERSONAL_ACCESS_TOKEN`.

### A selected stream returns no rows

Move `AIRBYTE_GITHUB_START_DATE` farther into the past and verify that the repository has activity in that period.

### GitHub Enterprise connection fails

Confirm `AIRBYTE_GITHUB_API_URL` is the enterprise base URL expected by the connector and that the runner trusts the enterprise TLS certificate.
