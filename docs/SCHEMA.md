# Appwrite schema used by the custody audit

This is a reference for an **independent fictional verification project** or an existing compatible LabRelay database. The companion reads the six tables below; it creates no tables, columns, indexes or records. Do not run migrations against the existing LabRelay submission for this integration.

The definitions were read from LabRelay's `scripts/schema.ts` and `src/domain/types.ts`. They document that application's contract, not a generic Appwrite database schema. Existing LabRelay has other tables needed by the application; their omission here is not an instruction to remove them.

## Common conventions

Every row has an Appwrite `$id`. The export renames this to `id` and removes other platform `$...` fields. `varchar(n)` indicates the declared maximum length; all fields are required unless marked nullable. Integers have a minimum of zero. Timestamps are Appwrite `datetime` columns exported as ISO 8601 strings. `orgId` is an application identifier, not an Appwrite database or project ID.

Key indexes below are ordinary, non-unique indexes unless explicitly marked unique. Appwrite maintains the platform row-ID index used for cursor pagination. The companion uses organization filters for samples, batches and receipts; history and handoffs are read by `sampleId` and then filtered to the authorized organization. It does not require a new org-only index on history or handoffs.

## `memberships`

| Column | Type | Meaning |
| --- | --- | --- |
| `$id` | Appwrite row ID | Must equal the verified Appwrite Account user ID |
| `orgId` | `varchar(36)` | Server-managed organization membership |
| `role` | `varchar(16)` | Application role: `collector`, `courier`, or `receiver` |
| `active` | `boolean` | Must be true before an export is authorized |

Index: `org_active` on `(orgId, active)`.

The companion looks up the caller's membership by `$id`, checks `active`, and derives the export organization from that row. Membership records are not included in the export. Do not allow the automation account to edit its own membership.

## `samples`

| Columns | Type |
| --- | --- |
| `orgId`, `batchId`, `siteId`, `custodianId` | `varchar(36)` |
| `label` | `varchar(120)` |
| `status` | `varchar(16)`; application values `ready`, `assigned`, `in_transit`, `received` |
| `assignedCourierId`, `pendingHandoffId` | Nullable `varchar(36)` |
| `version` | Nonnegative integer |

Indexes: `org_status` on `(orgId, status)`; `org_batch` on `(orgId, batchId)`.

Registration starts at version zero. Each committed sample mutation creates exactly one event at its next revision. Reserving or offering a handoff does not itself change the confirmed custodian.

## `handoffs`

| Columns | Type |
| --- | --- |
| `orgId`, `sampleId`, `fromUserId`, `toUserId` | `varchar(36)` |
| `status` | `varchar(16)`; `offered` or `accepted` |
| `offeredAt` | `datetime` |
| `acceptedAt` | Nullable `datetime` |

Indexes: `sample` on `(sampleId)`; `recipient_status` on `(toUserId, status)`.

A pending handoff must belong to the sample and organization, remain offered, and identify the sample's current custodian as its sender. The audit reads handoffs reachable through current samples; orphan handoffs are outside its coverage.

## `events`

| Columns | Type |
| --- | --- |
| `orgId`, `sampleId`, `actorId`, `fromCustodianId`, `toCustodianId` | `varchar(36)` |
| `version` | Nonnegative integer |
| `kind` | `varchar(24)` |
| `capturedAt`, `recordedAt` | `datetime` |
| `note` | `varchar(500)` |

Unique index: `sample_revision` on `(sampleId, version)`.

Kinds are `register_sample`, `claim`, `offer_handoff`, `accept_handoff`, `observe`, `receipt_missing`, and `receipt_accepted`. A sample history begins with registration at revision zero. Only acceptance changes recorded custody. `capturedAt` may describe an earlier offline observation; revision order determines the committed history. Orphan events are outside the export's coverage.

## `batch_receipts`

| Columns | Type |
| --- | --- |
| `orgId`, `batchId`, `actorId` | `varchar(36)` |
| `recordedAt` | `datetime` |
| `status` | `varchar(16)`; `matched` or `discrepancy` |
| `expectedCount`, `receivedCount`, `missingCount`, `unexpectedCount`, `duplicateCount` | Nonnegative integers |
| `detailsJson` | `text`; JSON serialized as a string |

Indexes: `org_recorded` on `(orgId, recordedAt)`; `org_batch` on `(orgId, batchId)`.

The `detailsJson` object contains:

- `scannedIds`, `missing`, `unexpected`, `duplicateScans`: arrays of strings.
- `items`: an array of objects with string `sampleId`, `label`, `fromCustodianId`, `toCustodianId`, and `outcome` (`received` or `missing`), plus integer `versionBefore` and `versionAfter`.

The companion parses `detailsJson` into export field `details`. Failed parsing yields an incomplete export. Receipts preserve the historical check-in result: later acceptance does not rewrite an earlier missing item. The audit uses later acceptance events and current sample state to classify resolution.

## `batches`

| Columns | Type |
| --- | --- |
| `orgId`, `batchId` | `varchar(36)` |
| `version` | Nonnegative integer |

Unique index: `org_batch` on `(orgId, batchId)`.

LabRelay advances the corresponding batch revision for every application-mediated sample mutation. The companion compares samples and batch guard records before and after its paginated reads, with bounded retries. This is not a transaction snapshot or a guard against direct administrator edits. A sample without its corresponding batch record is an audit finding.

## Using the fictional JSON fixtures

Files under `fixtures/` are **complete export documents for offline tests**, not database import files. They include envelope fields such as `schemaVersion`, `complete`, `coverage`, and collection arrays. They omit membership rows. Their row objects use `id` rather than Appwrite `$id`, and their receipts use parsed `details` rather than stored `detailsJson`.

For a real verification project, provision the schema separately, associate a dedicated authenticated account with a server-managed active membership, and seed only invented records with consistent IDs and revisions. Convert export fixture objects to the database representation deliberately; do not import an envelope as a row or paste fixtures into the live LabRelay database. Configure the separate companion Function with `rows.read` and authenticated execution. Keep client row grants private and keep administrative credentials outside Kestra.
