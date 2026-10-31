# Read-only Appwrite companion Function

This is a separate Function, not a replacement for `labrelay_api`. Its only route
is `GET /export`. It never writes rows, creates a transaction, ensures a live feed,
changes permissions or invokes LabRelay commands. No deployment is performed by
the repository's test commands.

For a later isolated deployment, use this repository as the Function root,
`companion/function.mjs` as the entrypoint and `npm ci --omit=dev` as the build
command. Use a supported Node runtime >=22.12. Configure execution for authenticated
users and only the dynamic `rows.read` scope. Set `APPWRITE_DATABASE_ID` to an
existing database with the documented LabRelay tables and indexes. The platform
provides `APPWRITE_FUNCTION_API_ENDPOINT`, `APPWRITE_FUNCTION_PROJECT_ID`,
`x-appwrite-user-jwt` and the per-execution `x-appwrite-key`. No static database
or administrator API key is accepted by this Function.

The caller JWT is checked through Appwrite Account. Its active `memberships` row
determines the organization; the request cannot select it. Membership is checked
again before returning data. If membership is revoked or its organization changes,
the entire export is denied. The test-only injectable handler dependencies do not
change the deployed default handler's JWT verification.

## Export contract

```json
{
  "schemaVersion": 1,
  "orgId": "authorized-organization",
  "collectedAt": "2026-10-30T00:00:00.000Z",
  "complete": true,
  "consistency": "batch-revision-guarded",
  "attempts": 1,
  "issues": [],
  "coverage": {
    "eventsAndHandoffs": "reachable-from-current-samples",
    "orphanRowsChecked": false,
    "administratorEditsGuarded": false
  },
  "samples": [],
  "handoffs": [],
  "events": [],
  "receipts": [],
  "batches": []
}
```

Records retain application fields, with `id` derived from Appwrite `$id` and all
`$` platform metadata removed. Receipts contain parsed `details`, not
`detailsJson`. Malformed receipt JSON produces `details: null` plus an issue and
`complete: false`. Account properties and membership rows are not exported.

All collection queries use cursor pagination. Samples, batches and receipts are
queried by `orgId`; events/handoffs are queried by each authorized sample's
`sampleId` using the existing indexes, then checked for organization membership.
This covers records reachable from current samples. It does not scan orphan
events/handoffs whose sample has been deleted.

Samples and batch revisions are read before and after collection. Normal LabRelay
mutations advance the batch revision and trigger a bounded retry if they overlap
the export. This guard is not a database snapshot and cannot detect every direct
administrator edit that bypasses those revisions.

Defaults bound a query to 50 pages of 100 rows, an organization to 500 samples,
related records to 20,000, and JSON output to 4 MiB. At most two collection attempts
are made. A limit, malformed record, changing page set or ongoing mutation produces
`complete: false` with explanatory issue codes. Oversized responses omit all data
arrays and report `EXPORT_TOO_LARGE`. Consumers must treat every incomplete export
as inconclusive, even when its arrays contain no discrepancies. Server configuration
and the caller's execution/response limits can impose tighter bounds; a platform
timeout is a failed export, never a successful audit.

## Local checks

```powershell
npm ci
npm run test:exporter
```

Tests use an in-memory read-only database double. They do not read credentials,
contact Appwrite, create records or alter the existing application. Hosted Function
deployment and execution require separate real-platform verification.
