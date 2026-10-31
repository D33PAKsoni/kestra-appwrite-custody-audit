"""Offline behavior checks against fictional Appwrite export records."""

import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_custody import analyze as analyze_custody
from audit_receipts import analyze as analyze_receipts
from build_report import build_report


def fixture(name):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def audit(data):
    custody = analyze_custody(data)
    receipts = analyze_receipts(data)
    return custody, receipts, build_report(data, custody, receipts)


def still_missing():
    data = fixture("missing-then-received.json")
    data["samples"][0].update(status="in_transit", custodianId="courier-001",
                               pendingHandoffId="handoff-lab", version=5)
    data["events"] = data["events"][:-1]
    data["handoffs"][1].update(status="offered", acceptedAt=None)
    data["batches"][0]["version"] = 6
    return data


class AuditBehaviorTests(unittest.TestCase):
    def assert_error(self, findings):
        self.assertTrue(any(item["severity"] == "error" for item in findings), findings)

    def test_registered_sample_is_clean_without_receipts(self):
        custody, receipts, report = audit(fixture("clean-ready.json"))
        self.assertEqual(custody["checkedSamples"], 1)
        self.assertEqual(receipts["checkedReceipts"], 0)
        self.assertEqual(report["status"], "clean")
        self.assertEqual(report["findings"], [])

    def test_later_individual_acceptance_resolves_historical_missing(self):
        data = fixture("missing-then-received.json")
        original = copy.deepcopy(data)
        custody, receipts, report = audit(data)
        self.assertEqual(custody["findings"], [])
        self.assertEqual(receipts["checkedReceipts"], 1)
        self.assertEqual(receipts["resolvedMissing"], 1)
        self.assertEqual(receipts["unresolvedMissing"], 0)
        self.assertEqual(report["status"], "clean")
        self.assertEqual(data, original, "An audit must not rewrite the earlier missing receipt.")

    def test_current_custodian_cannot_disagree_with_history(self):
        data = fixture("missing-then-received.json")
        data["samples"][0]["custodianId"] = "forged-custodian"
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertEqual(report["status"], "findings")

    def test_missing_revision_is_detected_even_when_latest_matches(self):
        data = fixture("missing-then-received.json")
        data["events"] = [event for event in data["events"] if event["version"] != 2]
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertEqual(report["status"], "findings")

    def test_duplicate_revision_is_detected(self):
        data = fixture("missing-then-received.json")
        duplicate = copy.deepcopy(data["events"][2])
        duplicate["id"] = "duplicate-event"
        data["events"].append(duplicate)
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertEqual(report["status"], "findings")

    def test_pending_handoff_must_exist(self):
        data = still_missing()
        data["samples"][0]["pendingHandoffId"] = "not-a-handoff"
        custody, _, _ = audit(data)
        self.assert_error(custody["findings"])

    def test_pending_handoff_must_be_from_current_custodian(self):
        data = still_missing()
        data["handoffs"][1]["fromUserId"] = "unrelated-person"
        custody, _, _ = audit(data)
        self.assert_error(custody["findings"])

    def test_received_count_must_match_receipt_items(self):
        data = fixture("missing-then-received.json")
        data["receipts"][0]["receivedCount"] = 1
        _, receipts, report = audit(data)
        self.assert_error(receipts["findings"])
        self.assertEqual(report["status"], "findings")

    def test_missing_sample_remains_unresolved_without_acceptance(self):
        custody, receipts, report = audit(still_missing())
        self.assertEqual(custody["findings"], [])
        self.assertEqual(receipts["resolvedMissing"], 0)
        self.assertEqual(receipts["unresolvedMissing"], 1)
        self.assertTrue(any(item["severity"] == "warning" for item in receipts["findings"]))
        self.assertEqual(report["status"], "findings")

    def test_observation_timestamp_does_not_resolve_missing_sample(self):
        data = still_missing()
        observation = copy.deepcopy(data["events"][-1])
        observation.update(id="event-observe", version=6, kind="observe", actorId="courier-001",
                           capturedAt="2026-10-29T11:30:00.000Z", recordedAt="2026-10-29T11:30:00.000Z",
                           note="Fictional note: courier still holds the sample.")
        data["events"].append(observation)
        data["samples"][0]["version"] = 6
        data["batches"][0]["version"] = 7
        _, receipts, _ = audit(data)
        self.assertEqual(receipts["resolvedMissing"], 0)
        self.assertEqual(receipts["unresolvedMissing"], 1)

    def test_received_status_alone_is_not_evidence_of_later_acceptance(self):
        data = fixture("missing-then-received.json")
        data["events"][-1]["kind"] = "observe"
        _, receipts, _ = audit(data)
        self.assertEqual(receipts["resolvedMissing"], 0)
        self.assertEqual(receipts["unresolvedMissing"], 1)

    def test_incomplete_export_never_reports_clean(self):
        data = fixture("clean-ready.json")
        data["complete"] = False
        data["issues"] = [{"code": "EXPORT_LIMIT_REACHED", "message": "Fictional page limit."}]
        _, _, report = audit(data)
        self.assertEqual(report["status"], "inconclusive")

    def test_incomplete_export_dominates_detected_inconsistency(self):
        data = fixture("clean-ready.json")
        data["samples"][0]["custodianId"] = "forged-custodian"
        data["complete"] = False
        data["issues"] = [{"code": "CONCURRENT_CHANGE", "message": "Fictional concurrent mutation."}]
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertEqual(report["status"], "inconclusive")

    def test_unparseable_receipt_details_preserve_inconclusive_result(self):
        data = fixture("missing-then-received.json")
        data["receipts"][0]["details"] = None
        data.update(complete=False, issues=[{
            "code": "INVALID_RECEIPT_DETAILS", "message": "Fictional malformed stored JSON."}])
        _, receipts, report = audit(data)
        self.assert_error(receipts["findings"])
        self.assertEqual(report["status"], "inconclusive")

    def test_mixed_revision_types_produce_findings_without_sorting_failure(self):
        data = fixture("missing-then-received.json")
        data["events"][2]["version"] = "not-an-integer"
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertIn(report["status"], ("findings", "inconclusive"))

    def test_boolean_received_count_is_not_a_valid_integer_count(self):
        data = fixture("missing-then-received.json")
        data["events"] = data["events"][:-1]
        data["events"][-1].update(kind="receipt_accepted", toCustodianId="receiver-001")
        data["samples"][0]["version"] = 5
        data["batches"][0]["version"] = 6
        data["handoffs"][1]["acceptedAt"] = "2026-10-29T10:30:00.000Z"
        receipt = data["receipts"][0]
        receipt.update(status="matched", receivedCount=1, missingCount=0)
        receipt["details"].update(scannedIds=["water-001"], missing=[])
        receipt["details"]["items"][0].update(outcome="received", toCustodianId="receiver-001")
        self.assertEqual(audit(data)[2]["status"], "clean", "The integer-count control must be valid.")
        receipt["receivedCount"] = True
        _, receipts, report = audit(data)
        self.assert_error(receipts["findings"])
        self.assertEqual(report["status"], "findings")

    def test_receipt_event_actor_must_match_recording_receiver(self):
        data = fixture("missing-then-received.json")
        data["events"][5]["actorId"] = "unrelated-actor"
        _, receipts, report = audit(data)
        self.assert_error(receipts["findings"])
        self.assertEqual(report["status"], "findings")

    def test_each_sample_must_have_a_corresponding_batch_guard_record(self):
        data = fixture("clean-ready.json")
        data["batches"] = []
        custody, _, report = audit(data)
        self.assert_error(custody["findings"])
        self.assertEqual(report["status"], "findings")


if __name__ == "__main__":
    unittest.main()
