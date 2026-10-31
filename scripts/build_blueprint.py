"""Package reviewed Python task sources into one self-contained contribution YAML."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".local" / "python"))
import yaml


class Literal(str):
    pass


class BlueprintDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        # Kestra's runtime inputFiles parser does not resolve YAML aliases.
        return True


def represent_literal(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")


BlueprintDumper.add_representer(Literal, represent_literal)


def script_task(task_id, source, inputs=None, env=None, outputs=None):
    task = {"id": task_id, "type": "io.kestra.plugin.scripts.python.Script",
            "containerImage": "python:3.12-slim", "dependencies": ["kestra"]}
    if inputs:
        task["inputFiles"] = inputs
    if env:
        task["env"] = env
    task["outputFiles"] = outputs or []
    task["script"] = Literal((ROOT / "scripts" / source).read_text(encoding="utf-8"))
    return task


def build():
    exported = {"export.json": "{{ outputs.fetch_export.outputFiles['export.json'] }}"}
    secrets = {key: "{{ secret('" + key + "') }}" for key in (
        "APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_AUDIT_FUNCTION_ID",
        "APPWRITE_AUDIT_EMAIL", "APPWRITE_AUDIT_PASSWORD")}
    description = """Audit an Appwrite-backed sample-custody dataset through an authenticated, read-only companion Function. Detect inconsistent history and receipt records while preserving historical delivery discrepancies.

## How it works
1. A disabled-by-default daily schedule starts the flow after configuration.
2. Fetch signs in, creates a short-lived JWT, calls GET /export through Appwrite executions, then revokes its session.
3. Parallel Python tasks check custody revisions and reconcile receipt snapshots with later acceptance events.
4. Combine emits JSON/CSV reports. An If gate fails executions with findings or incomplete reads after artifacts are saved.

## What you get
- Downloadable reports with completeness, counts and record-level findings.
- Historical missing observations distinguished from confirmed later arrivals.
- No custody updates, receipt rewrites or database administrator key in Kestra.

## Who it's for
Engineers maintaining Appwrite sample-tracking or similar event-history applications.

## Why orchestrate this with Kestra
Keep authenticated extraction, independent checks, reporting and failure routing observable as separate tasks. Scheduled runs retain execution evidence without embedding audit logic in the product UI.

## Prerequisites
Kestra with the Python plugin and Docker-capable workers; an Appwrite project using the documented LabRelay schema; a separately deployed read-only audit Function with rows.read; and a dedicated active organization member. Export coverage excludes orphan records and administrator edits bypassing revision guards. Incomplete or unstable data is inconclusive, never clean.

### Secrets
- APPWRITE_ENDPOINT: exact HTTPS API endpoint including /v1.
- APPWRITE_PROJECT_ID: target project ID.
- APPWRITE_AUDIT_FUNCTION_ID: separate companion Function ID.
- APPWRITE_AUDIT_EMAIL and APPWRITE_AUDIT_PASSWORD: dedicated member credentials.

## Quick start
1. Configure the schema and companion Function from the accompanying setup guide.
2. Store the five secrets and execute manually against fictional records.
3. Inspect audit.json and audit.csv; verify a later arrival and an incomplete export.
4. Enable the schedule only after a verified integration run. Reports contain private identifiers; limit access and retention.

## How to extend
Add an alert channel after reporting, or adapt the export contract to another event-history schema. Keep source records read-only.

## Links
- [Companion and setup](https://github.com/D33PAKsoni/kestra-appwrite-custody-audit)
- [Schema](https://github.com/D33PAKsoni/kestra-appwrite-custody-audit/blob/main/docs/SCHEMA.md)
- [Python plugin](https://kestra.io/plugins/plugin-script-python)
- [Appwrite executions](https://appwrite.io/docs/references/cloud/client-web/functions)
- [Appwrite Function development](https://appwrite.io/docs/products/functions/develop)
"""
    flow = {
        "id": "appwrite-custody-audit", "namespace": "company.labrelay",
        "description": "Read-only Appwrite custody and receipt consistency audit.",
        "tasks": [
            script_task("fetch_export", "fetch_export.py", env=secrets, outputs=["export.json"]),
            {"id": "check_records", "type": "io.kestra.plugin.core.flow.Parallel", "tasks": [
                script_task("audit_custody", "audit_custody.py", inputs=exported, outputs=["custody.json"]),
                script_task("audit_receipts", "audit_receipts.py", inputs=exported, outputs=["receipts.json"])]},
            script_task("build_report", "build_report.py", inputs={**exported,
                "custody.json": "{{ outputs.audit_custody.outputFiles['custody.json'] }}",
                "receipts.json": "{{ outputs.audit_receipts.outputFiles['receipts.json'] }}"}, outputs=["audit.json", "audit.csv"]),
            {"id": "require_complete_clean_audit", "type": "io.kestra.plugin.core.flow.If",
             "condition": "{{ outputs.build_report.vars.status != 'clean' }}",
             "then": [{"id": "audit_requires_attention", "type": "io.kestra.plugin.core.execution.Fail",
                       "errorMessage": "Audit findings or incomplete data: inspect build_report artifacts."}]}
        ],
        "triggers": [{"id": "daily_audit", "type": "io.kestra.plugin.core.trigger.Schedule",
                      "cron": "0 6 * * *", "timezone": "UTC", "disabled": True}],
        "extend": {
            "title": "Audit Appwrite sample custody and laboratory receipts",
            "metaTitle": "Appwrite Custody and Receipt Audit | Kestra",
            "shortDescription": "Check sample-custody history and receipt consistency in Appwrite, preserving historical discrepancies and reporting incomplete reads.",
            "metaDescription": "Audit Appwrite sample custody and receipt consistency with parallel checks, scheduled runs, JSON/CSV reports and incomplete-read safeguards.",
            "description": Literal(description), "tags": ["Data"], "subTags": ["Testing & Quality"],
            "ee": False, "demo": False}}
    destination = ROOT / "flows" / "appwrite-custody-audit.yaml"
    destination.write_text(yaml.dump(flow, Dumper=BlueprintDumper, sort_keys=False, width=110, allow_unicode=True), encoding="utf-8")
    runtime_flow = {key: value for key, value in flow.items() if key != "extend"}
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    (local / "appwrite-custody-audit.runtime.yaml").write_text(
        yaml.dump(runtime_flow, Dumper=BlueprintDumper, sort_keys=False, width=110, allow_unicode=True), encoding="utf-8")
    return flow


if __name__ == "__main__":
    flow = build()
    print(f"Packaged {flow['id']} from reviewed Python sources.")
