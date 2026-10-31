# Fictional audit fixtures

These JSON files contain invented water-sample records for offline tests. They contain no production credentials or real laboratory data.

- `clean-ready.json`: one registered sample still held by its collector.
- `missing-then-received.json`: a courier's sample is recorded missing at a laboratory check-in, then individually accepted later. The earlier receipt correctly retains its missing snapshot; the sample's current state is received.

The tests derive deliberately inconsistent and incomplete variants in memory. The base fixtures are not evidence of a real Appwrite export, a deployed companion Function, or a successful Kestra execution. They exercise the schema and algorithm without writing to either service.

`consistency: batch-revision-guarded` describes the export contract. It does not make these files transactional database snapshots, independent proof of physical possession, or a check of orphan rows and administrator edits.
