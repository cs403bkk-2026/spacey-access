# Contributing to spacey-access

## Branch naming

| Type | Pattern | Example |
|------|---------|---------|
| New feature | `feat/<description>` | `feat/check-in-function` |
| Bug fix | `fix/<description>` | `fix/expiry-timestamp` |
| Migration | `chore/migration-<n>-<description>` | `chore/migration-002-add-space-id` |
| Tests | `test/<description>` | `test/check-out-edge-cases` |

## Workflow

```bash
git checkout main
git pull origin main
git checkout -b feat/your-feature
# make changes
git add .
git commit -m "feat: short description"
git push origin feat/your-feature
# open PR on GitHub
```

## PR checklist

- [ ] Tests pass locally (`pytest`)
- [ ] New functions have tests
- [ ] Migration SQL is idempotent (`CREATE TABLE IF NOT EXISTS`)
- [ ] No credentials committed
- [ ] PR description explains what changed and why

## Boundary rules

- Access owns the `access` table exclusively — never read `bookings` or other tables
- Eligibility comes in from Purchase — Access does not check it itself
- Contract tracked in [spacey-business-rules PR #20](https://github.com/cs403bkk-2026/spacey-business-rules/pull/20)