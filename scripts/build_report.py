"""Combine audit evidence; incomplete or unstable reads can never be clean."""
import csv
import json
from pathlib import Path


def build_report(data, custody, receipts):
    findings = custody["findings"] + receipts["findings"]
    complete = data.get("complete") is True and not data.get("issues")
    return {"schemaVersion": 1, "orgId": data["orgId"], "collectedAt": data["collectedAt"],
            "status": "inconclusive" if not complete else "findings" if findings else "clean",
            "complete": complete, "issues": data.get("issues", []), "coverage": data.get("coverage", {}),
            "checkedSamples": custody["checkedSamples"], "checkedReceipts": receipts["checkedReceipts"],
            "resolvedMissing": receipts["resolvedMissing"], "unresolvedMissing": receipts["unresolvedMissing"],
            "findings": findings,
            "scope": "Application record consistency; not proof of physical possession or absence of orphan records."}


def write_reports(report):
    Path("audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Include status/completeness on every finding; a summary row remains when there are no findings.
    fields = ["status", "complete", "code", "severity", "sampleId", "receiptId", "message"]
    rows = report["findings"] or [{"code": "audit_summary", "severity": "info",
        "message": report["scope"]}]
    with Path("audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for finding in rows:
            row = {"status": report["status"], "complete": report["complete"], **finding}
            # Prevent spreadsheet formula execution when these CSV fields are opened in Excel.
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                             else value for key, value in row.items()})


def main():
    from kestra import Kestra
    data = json.loads(Path("export.json").read_text(encoding="utf-8"))
    custody = json.loads(Path("custody.json").read_text(encoding="utf-8"))
    receipts = json.loads(Path("receipts.json").read_text(encoding="utf-8"))
    result = build_report(data, custody, receipts)
    write_reports(result)
    Kestra.outputs({"status": result["status"], "findingCount": len(result["findings"])})


if __name__ == "__main__":
    main()
