"""Structural checks and local execution of the exact packaged task scripts.

This is deliberately NOT a substitute for validating/executing on a Kestra engine.
"""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".local" / "python"))
import yaml


def flattened(tasks):
    for task in tasks:
        yield task
        for key in ("tasks", "then", "else"):
            yield from flattened(task.get(key, []))


def run_task(task, directory):
    captured = []
    fake = types.ModuleType("kestra")
    fake.Kestra = types.SimpleNamespace(outputs=lambda value: captured.append(value))
    previous_module = sys.modules.get("kestra")
    previous_directory = Path.cwd()
    try:
        sys.modules["kestra"] = fake
        os.chdir(directory)
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(task["script"], task["id"], "exec"), {"__name__": "__main__"})
    finally:
        os.chdir(previous_directory)
        if previous_module is None:
            del sys.modules["kestra"]
        else:
            sys.modules["kestra"] = previous_module
    return captured


def main():
    packaged = (ROOT / "flows" / "appwrite-custody-audit.yaml").read_text(encoding="utf-8")
    assert not any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(packaged)), \
        "Kestra inputFiles must be expanded explicitly, without YAML aliases."
    flow = yaml.safe_load(packaged)
    tasks = {task["id"]: task for task in flattened(flow["tasks"])}
    allowed = {"io.kestra.plugin.scripts.python.Script", "io.kestra.plugin.core.flow.Parallel",
               "io.kestra.plugin.core.flow.If", "io.kestra.plugin.core.execution.Fail"}
    assert all(task["type"] in allowed for task in tasks.values())
    assert len([task for task in tasks.values() if task["type"].endswith(".Script")]) >= 3
    assert flow["triggers"][0]["type"] == "io.kestra.plugin.core.trigger.Schedule"
    assert flow["triggers"][0]["disabled"] is True
    metadata = flow["extend"]
    assert len(metadata["metaDescription"]) <= 160
    assert metadata["demo"] is False and metadata["ee"] is False
    assert set(metadata) == {"title", "metaTitle", "shortDescription", "metaDescription", "description", "tags", "subTags", "ee", "demo"}
    for heading in ("How it works", "What you get", "Who it's for", "Why orchestrate this with Kestra",
                    "Prerequisites", "Quick start", "How to extend", "Links"):
        assert "## " + heading in metadata["description"]
    for task in tasks.values():
        if "script" in task:
            source = (ROOT / "scripts" / (task["id"] + ".py")).read_text(encoding="utf-8")
            assert task["script"] == source, f"Rebuild stale inline source for {task['id']}"
            compile(task["script"], task["id"], "exec")
    scenarios = []
    for fixture in (ROOT / "fixtures").glob("*.json"):
        scenarios.append((fixture.stem, json.loads(fixture.read_text(encoding="utf-8")), "clean"))
    inconsistent = copy.deepcopy(scenarios[0][1])
    inconsistent["samples"][0]["custodianId"] = "fictional-wrong-custodian"
    scenarios.append(("inconsistent", inconsistent, "findings"))
    incomplete = copy.deepcopy(scenarios[0][1])
    incomplete.update(complete=False, issues=[{"code": "CONCURRENT_CHANGE", "message": "Fictional overlapping update."}])
    scenarios.append(("incomplete", incomplete, "inconclusive"))
    evidence = []
    for name, data, expected in scenarios:
        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as temp:
            folder = Path(temp)
            (folder / "export.json").write_text(json.dumps(data), encoding="utf-8")
            for task_id in ("audit_custody", "audit_receipts", "build_report"):
                run_task(tasks[task_id], folder)
            report = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
            assert report["status"] == expected, (name, report)
            assert (folder / "audit.csv").is_file()
            destination = ROOT / "reports" / "local-scenarios" / name
            destination.mkdir(parents=True, exist_ok=True)
            for output in ("audit.json", "audit.csv"):
                (destination / output).write_bytes((folder / output).read_bytes())
            evidence.append({"scenario": name, "status": report["status"], "findingCount": len(report["findings"])})
    result = {"scope": "Structural checks plus exact inline audit/report scripts, fictional local data and a stubbed Kestra output collector. No engine or live Appwrite execution.",
              "metadataDescriptionCharacters": len(metadata["description"]), "scenarios": evidence}
    (ROOT / "reports" / "blueprint-local-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    (ROOT / ".local").mkdir(exist_ok=True)
    main()
