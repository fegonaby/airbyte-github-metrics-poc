# Local Airbyte GitHub-to-DuckDB proof of concept

## Scope

This is a small, manual capability test for the open-source Airbyte GitHub source connector.

```text
GitHub
  -> PyAirbyte GitHub source connector
  -> new local DuckDB database
```

The script runs only when you invoke it. It does not create a schedule or continuously fetch data, and it does not modify the original project's database or normalized tables.

The test is limited to one repository and five useful streams:

- `repositories`
- `pull_requests`
- `pull_request_stats`
- `reviews`
- `review_comments`

It demonstrates:

- Connector installation and credential checks
- Catalog discovery and stream selection
- GitHub pagination, retry, and rate-limit behavior
- Typed DuckDB table creation
- Persistent connector state between local runs
- PR-level `additions`, `deletions`, and `changed_files`

It does not test path-filtered or per-file LOC because the standard connector does not expose a pull-request-files stream.

## Official reading

- [PyAirbyte overview](https://docs.airbyte.com/developers/pyairbyte)
- [PyAirbyte cache API](https://docs.airbyte.com/developers/pyairbyte/reference/airbyte/caches)
- [Airbyte GitHub source connector](https://docs.airbyte.com/integrations/sources/github)

## Versions

- PyAirbyte `0.53.3`
- GitHub source connector `2.1.41`
- Python `3.10`, `3.11`, or `3.12`

Python `3.9` is not supported by this PyAirbyte version.

## 1. Create an isolated environment

From the repository root:

```bash
uv venv --python 3.11 .venv-airbyte
source .venv-airbyte/bin/activate
uv pip install -r experiments/airbyte_github_poc/requirements.txt
```

The first execution is slower because PyAirbyte installs the pinned GitHub connector in its own environment.

## 2. Configure one repository

Create or use a GitHub PAT that can read the selected repository:

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN='replace-me'
export AIRBYTE_GITHUB_REPOSITORY='fegonaby/github-analysis'
export AIRBYTE_GITHUB_START_DATE='2026-01-01T00:00:00Z'
```

For GitHub Enterprise Server, also set its base URL:

```bash
export AIRBYTE_GITHUB_API_URL='https://github.company.example'
```

The optional example configuration is in `env.example`. To load your own `.env` file:

```bash
set -a
source .env
set +a
```

Do not commit `.env`; it is ignored by Git.

## 3. Discover the connector catalog

This checks the token and prints every stream exposed by the installed connector without loading records:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py --discover-only
```

## 4. Load the selected streams

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py
```

The script creates a separate database:

```text
output/airbyte_poc/github_local.duckdb
```

The selected tables are written under the `github_raw` schema. The command prints record counts, generated columns, and sample records.

Run the same command again to exercise the saved connector state:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py
```

Request a clean historical read without changing the default database path:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py --force-full-refresh
```

## 5. Inspect DuckDB manually

```bash
python - <<'PY'
import duckdb

con = duckdb.connect('output/airbyte_poc/github_local.duckdb', read_only=True)
print(con.sql('SHOW TABLES FROM github_raw'))
print(con.sql('''
    SELECT repository, number, additions, deletions, changed_files, updated_at
    FROM github_raw.pull_request_stats
    ORDER BY updated_at DESC
    LIMIT 10
'''))
con.close()
PY
```

The connector loads pull requests for the repository rather than restricting them to `main` or `master`. Apply the base-branch condition later when querying the results.

## 6. What to record during the test

- First-time connector installation duration
- Discovered and selected streams
- Total execution time
- Record count per stream
- Columns and nested-field representation
- GitHub retry or rate-limit log messages
- Difference between the first and second run
- A comparison of PR statistics with the GitHub UI
- Whether the absence of per-file data is acceptable

## Optional arguments

Use a different repository without changing the environment:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py \
  --repository owner/repository
```

Select fewer streams:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py \
  --streams pull_requests,pull_request_stats
```

Use a separate database file:

```bash
python experiments/airbyte_github_poc/sync_to_duckdb.py \
  --db output/airbyte_poc/another_repository.duckdb
```

After the one-repository test, `owner/*` can be used to inspect organization-wide behavior. Expect a longer run and higher API usage.

## Troubleshooting

### PyAirbyte refuses to install

Run `python --version`. It must be Python `3.10` through `3.12` for the pinned release.

### GitHub returns HTTP 401

Create or refresh the GitHub token, confirm it can read the selected repository, and export it as `GITHUB_PERSONAL_ACCESS_TOKEN`.

### A selected stream returns no rows

Move `AIRBYTE_GITHUB_START_DATE` farther into the past and verify that the repository has activity in that period.

### GitHub Enterprise connection fails

Confirm `AIRBYTE_GITHUB_API_URL` is the enterprise base URL expected by the connector and that the runner trusts the enterprise TLS certificate.

### Start over without deleting the result

Move the generated database aside, then rerun the command:

```bash
mv output/airbyte_poc/github_local.duckdb \
   output/airbyte_poc/github_local.previous.duckdb
```
