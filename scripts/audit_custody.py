"""Check recorded custody invariants without mutating application records."""
import json
from pathlib import Path


def analyze(data):
    findings = []

    def add(code, sample_id, message):
        findings.append({"code": code, "severity": "error", "sampleId": sample_id,
                         "receiptId": "", "message": message})

    org = data["orgId"]
    samples = {sample["id"]: sample for sample in data["samples"]}
    handoffs = {handoff["id"]: handoff for handoff in data["handoffs"]}
    batches = {}
    for batch in data["batches"]:
        if batch.get("orgId") == org:
            batches.setdefault(batch.get("batchId"), []).append(batch)
    if len(samples) != len(data["samples"]) or len(handoffs) != len(data["handoffs"]):
        add("duplicate_record", "", "Export contains duplicate sample or handoff IDs.")
    events_by_sample = {}
    for event in data["events"]:
        if not isinstance(event, dict) or type(event.get("version")) is not int or event["version"] < 0 or \
                not all(isinstance(event.get(key), str) and event[key] for key in
                        ("sampleId", "orgId", "kind", "fromCustodianId", "toCustodianId")):
            add("malformed_event", "", "History contains an invalid revision or incomplete custody fields.")
            continue
        events_by_sample.setdefault(event["sampleId"], []).append(event)
        if event["orgId"] != org or event["sampleId"] not in samples:
            add("event_scope", event["sampleId"], "Event is outside the exported sample scope.")
    for sample in data["samples"]:
        sid = sample["id"]
        if len(batches.get(sample["batchId"], [])) != 1:
            add("batch_reference", sid, "Sample must have exactly one batch revision record in its organization.")
        if sample["orgId"] != org:
            add("sample_scope", sid, "Sample does not belong to the exported organization.")
        events = sorted(events_by_sample.get(sid, []), key=lambda event: event["version"])
        version = sample["version"]
        if type(version) is not int or version < 0:
            add("invalid_version", sid, "Sample revision must be a nonnegative integer.")
            continue
        if len(events) != version + 1 or any(type(event["version"]) is not int or event["version"] != index
                                               for index, event in enumerate(events)):
            add("revision_gap", sid, "History must contain exactly one event for each revision from zero through current.")
        if not events or events[-1]["version"] != version or events[-1]["toCustodianId"] != sample["custodianId"]:
            add("current_custody", sid, "Current sample custody or revision disagrees with its latest history event.")
        if events and (events[0]["kind"] != "register_sample" or
                       events[0]["fromCustodianId"] != events[0]["toCustodianId"]):
            add("registration", sid, "History must start with registration without a custody transfer.")
        for previous, current in zip(events, events[1:]):
            if previous["toCustodianId"] != current["fromCustodianId"]:
                add("custody_chain", sid, "Successive history events disagree about the prior custodian.")
        for event in events:
            if event["kind"] not in ("accept_handoff", "receipt_accepted") and event["fromCustodianId"] != event["toCustodianId"]:
                add("unauthorized_transfer", sid, "Only recorded acceptance may change the confirmed custodian.")
        pending = sample.get("pendingHandoffId")
        if pending:
            handoff = handoffs.get(pending)
            if not handoff or handoff["orgId"] != org or handoff["sampleId"] != sid or \
                    handoff["fromUserId"] != sample["custodianId"] or handoff["status"] != "offered" or \
                    handoff["toUserId"] == sample["custodianId"] or sample["status"] not in ("assigned", "in_transit"):
                add("pending_handoff", sid, "Pending handoff is missing or disagrees with the sample's current custody.")
        if sample["status"] == "received" and pending:
            add("received_pending", sid, "A received sample still has a pending handoff.")
    for handoff in data["handoffs"]:
        sample = samples.get(handoff["sampleId"])
        if handoff["orgId"] != org or sample is None:
            add("handoff_scope", handoff["sampleId"], "Handoff is outside the exported sample scope.")
        elif handoff["status"] == "offered" and sample.get("pendingHandoffId") != handoff["id"]:
            add("unreferenced_offer", sample["id"], "An open handoff is not the sample's pending offer.")
    return {"findings": findings, "checkedSamples": len(samples)}


def main():
    from kestra import Kestra
    result = analyze(json.loads(Path("export.json").read_text(encoding="utf-8")))
    Path("custody.json").write_text(json.dumps(result), encoding="utf-8")
    Kestra.outputs({"findingCount": len(result["findings"]), "checkedSamples": result["checkedSamples"]})


if __name__ == "__main__":
    main()
