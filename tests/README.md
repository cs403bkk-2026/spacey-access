# Tests

## Layers

| Layer | Files | What it tests |
|-------|-------|---------------|
| Contract | `test_openapi.py` | `openapi.yaml` is valid OpenAPI 3.0 (0.2.0), every example passes as the request or response it documents, and the app serves exactly its routes |
| API | `test_api.py`, `test_health.py` | Each route's status codes and the service token on all 6 access calls (`src/db.py` patched in `test_api.py`) |
| Database | `test_db.py`, `test_migration_002.py`, `test_migrate_from_spacey.py` | The real SQL, migration 002 and the data copy on Postgres, inside transactions that are rolled back |

## Fixtures (`conftest.py`)

| Fixture | What it gives you |
|---------|------------------|
| `app` | A Flask test app instance |
| `client` | A test client to make HTTP requests |
| `service_token` | Sets `SERVICE_TOKEN=test-token` for every test (autouse) |
| `auth` | The `Authorization: Bearer` header `spacey` sends on all 6 access calls |
| `check_schema` | Helper to assert status code and JSON content type |

## Naming

- Test files: `test_<module>.py`
- Test functions: `test_<what>_<condition>` e.g. `test_health_returns_ok`

## How to run

```bash
# All tests
pytest

# One file
pytest tests/test_health.py

# Verbose
pytest -v
```

Requires a local Postgres database. Start it with:
```bash
docker compose up db -d
```

Never run against production — use `DATABASE_URL` pointing to the local test database only.