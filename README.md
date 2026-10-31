# Appwrite custody audit for Kestra

A reusable read-only blueprint for auditing an Appwrite sample-custody dataset. Extraction, parallel custody/receipt checks and JSON/CSV reporting are separate tasks. Historical missing observations can be resolved by later acceptance without rewriting the original receipt. Incomplete exports are inconclusive.

Licensed under [MIT](LICENSE); [development disclosure](ATTRIBUTION.md).

## Configure

1. Prepare an independent fictional Appwrite project using [the documented schema](docs/SCHEMA.md).
2. Deploy the [separate companion Function](companion/README.md) with authenticated execution and only rows.read. Never replace an existing application Function.
3. Store APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_AUDIT_FUNCTION_ID, APPWRITE_AUDIT_EMAIL and APPWRITE_AUDIT_PASSWORD in your own Kestra secrets. Never use a setup/admin key in Kestra.
4. Run npm run build:blueprint and import .local/appwrite-custody-audit.runtime.yaml. The catalog file under flows/ retains extend metadata; the runtime copy omits it.
5. Execute manually and inspect build_report artifacts. A failed attention gate can still have valid saved reports. Enable the daily schedule only after verifying configuration.

## Checks

Use Node 22.12+ and Python 3.10+ (3.12 recommended).

```sh
npm ci
python -m pip install --target .local/python -r requirements-dev.txt
npm test
npm run build:blueprint
```

The Docker verification workflow is prepared in .github/workflows/docker-verification.yml. It uses a fictional loopback service, no real Appwrite secrets, and host networking only for test containers. Its execution status is available on the repository Actions page; do not infer a pass from configuration alone.

See [verification scope](reports/VERIFICATION.md) and [Docker CI design](docs/DOCKER_CI.md). Read private-data handling and coverage limits in the companion guide. Raw cloud identifiers, account credentials, private execution configuration and live setup scripts are deliberately excluded from this public repository.
