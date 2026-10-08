# Tests

## Layers

| Layer | Files | What it tests |
|-------|-------|---------------|
| Unit | `test_access.py` | Business logic functions in isolation (mocked DB cursor) |
| Integration | `test_health.py`, `test_db.py` | Full request against a real test database |

## Fixtures (`conftest.py`)

| Fixture | What it gives you |
|---------|------------------|
| `app` | A Flask test app instance |
| `client` | A test client to make HTTP requests |
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