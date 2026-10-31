"""Reconcile receipt snapshots, preserving historical missing outcomes."""
import json
from pathlib import Path


def analyze(data):
    findings = []
    resolved = unresolved = 0
    samples = {sample["id"]: sample for sample in data["samples"]}
    valid_events = [event for event in data["events"] if isinstance(event, dict) and
                    type(event.get("version")) is int and event["version"] >= 0]
    events = {(event["sampleId"], event["version"]): event for event in valid_events}

    def add(code, receipt, message, sample_id="", severity="error"):
        findings.append({"code": code, "severity": severity, "sampleId": sample_id,
                         "receiptId": receipt["id"], "message": message})

    seen_receipts = set()
    for receipt in data["receipts"]:
        if receipt["id"] in seen_receipts:
            add("duplicate_receipt", receipt, "Export contains a repeated receipt ID.")
        seen_receipts.add(receipt["id"])
        details = receipt["details"]
        arrays = ("items", "scannedIds", "missing", "unexpected", "duplicateScans")
        if not isinstance(details, dict) or not all(isinstance(details.get(key), list) for key in arrays) or \
                not all(isinstance(value, str) for key in arrays[1:] for value in details[key]) or \
                not all(isinstance(item, dict) and isinstance(item.get("sampleId"), str) and
                        type(item.get("versionBefore")) is int and type(item.get("versionAfter")) is int and
                        item["versionBefore"] >= 0 and item["versionAfter"] >= 0 and
                        all(isinstance(item.get(key), str) for key in ("fromCustodianId", "toCustodianId", "outcome"))
                        for item in details["items"]):
            add("malformed_receipt", receipt, "Receipt details are unavailable or malformed; inspect the export issues.")
            continue
        items = details["items"]
        expected = [item["sampleId"] for item in items]
        scans = details["scannedIds"]
        scan_set = set(scans)
        missing = [sid for sid in expected if sid not in scan_set]
        unexpected = list(dict.fromkeys(sid for sid in scans if sid not in set(expected)))
        seen = set()
        duplicates = set()
        for sid in scans:
            if sid in seen:
                duplicates.add(sid)
            seen.add(sid)
        counts = {"expectedCount": len(items), "receivedCount": len(expected) - len(missing),
                  "missingCount": len(missing), "unexpectedCount": len(unexpected), "duplicateCount": len(duplicates)}
        if receipt["orgId"] != data["orgId"]:
            add("receipt_scope", receipt, "Receipt does not belong to the exported organization.")
        if len(set(expected)) != len(expected) or any(type(receipt.get(key)) is not int or receipt[key] != value
                                                     for key, value in counts.items()):
            add("receipt_counts", receipt, "Receipt counts or expected sample IDs disagree with its scans.")
        if sorted(details["missing"]) != sorted(missing) or sorted(details["unexpected"]) != sorted(unexpected) or \
                sorted(details["duplicateScans"]) != sorted(duplicates):
            add("receipt_details", receipt, "Stored discrepancy lists disagree with expected IDs and scans.")
        expected_status = "discrepancy" if missing or unexpected or duplicates else "matched"
        if receipt["status"] != expected_status:
            add("receipt_status", receipt, "Receipt status disagrees with its recorded discrepancy lists.")
        for item in items:
            sid = item["sampleId"]
            sample = samples.get(sid)
            accepted = sid in scan_set
            outcome = "received" if accepted else "missing"
            event = events.get((sid, item["versionAfter"]))
            expected_kind = "receipt_accepted" if accepted else "receipt_missing"
            if not sample or sample["batchId"] != receipt["batchId"] or item["outcome"] != outcome or \
                    item["versionAfter"] != item["versionBefore"] + 1 or \
                    sample["version"] < item["versionAfter"] or not event or event["kind"] != expected_kind or \
                    event["actorId"] != receipt["actorId"] or event["orgId"] != data["orgId"] or \
                    event["fromCustodianId"] != item["fromCustodianId"] or event["toCustodianId"] != item["toCustodianId"] or \
                    (not accepted and item["fromCustodianId"] != item["toCustodianId"]) or \
                    (accepted and item["toCustodianId"] != receipt["actorId"]):
                add("receipt_event", receipt, "Receipt item disagrees with its sample revision or recorded custody event.", sid)
            if not accepted and sample:
                later_acceptance = any(e["sampleId"] == sid and e["version"] > item["versionAfter"] and
                    e["kind"] in ("accept_handoff", "receipt_accepted") and e["toCustodianId"] == sample["custodianId"]
                    for e in valid_events)
                if sample["status"] == "received" and later_acceptance:
                    resolved += 1
                else:
                    unresolved += 1
                    add("missing_unresolved", receipt, "Missing at this receipt with no confirmed later laboratory acceptance.", sid, "warning")
    return {"findings": findings, "checkedReceipts": len(data["receipts"]),
            "resolvedMissing": resolved, "unresolvedMissing": unresolved}


def main():
    from kestra import Kestra
    result = analyze(json.loads(Path("export.json").read_text(encoding="utf-8")))
    Path("receipts.json").write_text(json.dumps(result), encoding="utf-8")
    Kestra.outputs({"findingCount": len(result["findings"]), "resolvedMissing": result["resolvedMissing"],
                    "unresolvedMissing": result["unresolvedMissing"]})


if __name__ == "__main__":
    main()
