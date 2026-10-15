# Incident report template

ACC-14 (#44). Copy this file to `docs/operations/incidents/YYYY-MM-DD-<short-name>.md`
and fill it in.

**When a report is required:** every SEV1 and SEV2 (see [alerts.md](alerts.md)), within
two working days. Optional for SEV3, but worth it when the team learned something.

**Blameless:** describe what the system and the process allowed, not who made a
mistake. "The release deployed code without its migration" helps the next person;
"X forgot the migration" doesn't.

**Never include** an access code, a token, a password or a `DATABASE_URL`, not even
partly. Use booking IDs and revisions instead.

---

# <Title: what members or the team saw>

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Severity** | SEV1 / SEV2 / SEV3 |
| **Status** | Resolved / Monitoring / Open |
| **Duration** | from first impact to resolved, e.g. 2 h 10 min |
| **Detected by** | alert name / a person / a member |
| **Incident Commander** | who coordinated |
| **Report author** | |

## Summary

Two or three sentences: what broke, who was affected, and how it was fixed.

## Impact

- **Who:** members, other teams (Purchase, Frontend), or nobody yet
- **What they couldn't do:**
- **For how long:**
- **Data:** any records lost, wrong or exposed? (Records are never deleted, SP-R12.)

## Timeline

Times in UTC (or say which zone). Include when it started, when it was noticed, each
decision, and when it was resolved.

| Time | What happened |
|---|---|
| | |

## Root cause

What actually caused it, and why the existing checks didn't stop it. Ask "why?" until
the answer is something the team can change.

## What went well

-

## What went badly

-

## Where we got lucky

-

## Action items

Each one with an owner and an issue link. Prefer changes that make the same mistake
impossible over "be more careful".

| Action | Owner | Issue | Status |
|---|---|---|---|
| | | | |
