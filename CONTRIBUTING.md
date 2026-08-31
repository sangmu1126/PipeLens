# Contributing to PipeLens

## Before opening an issue

- Search existing issues and confirm the behavior on the latest `main` or release.
- Use the bug form for reproducible defects and the feature form for scoped proposals.
- Report vulnerabilities and exposed secrets through the private process in [SECURITY.md](SECURITY.md).
- Reduce logs to the first relevant error and redact tokens, credentials, repository names, user data,
  internal URLs, and unrelated workflow output.

## Local setup

PipeLens supports Python 3.12 through 3.14 and Node.js 22 or 24. Follow the complete runtime and Docker
instructions in [README.md](README.md). A typical backend setup is:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Before submitting a change, run the checks relevant to it:

```bash
ruff check .
pytest -q
pipelens-evaluate --minimum-accuracy 0.8
npm --prefix frontend test
npm --prefix frontend run build
```

Changes to OAuth, session, proxy, or dashboard navigation should also run the Playwright E2E suite.
Changes to PostgreSQL, Redis, images, observability, or upgrade drills should use the corresponding Docker
validation documented in `README.md` and `docs/`.

## Change and pull request rules

1. Branch from the latest `main` and keep unrelated work in separate commits.
2. Add or update tests for behavior changes. Evaluation fixtures must contain minimal, synthetic or
   anonymized logs with no secrets.
3. Update decisions, readiness, and development history when a support boundary or operational contract
   changes.
4. Complete the pull request template with evidence and exact commands or run URLs.
5. Wait for every required check. Use rebase or squash merge so `main` remains linear.

The enforced repository procedure and required check names are documented in
[repository governance](docs/repository-governance.md).
