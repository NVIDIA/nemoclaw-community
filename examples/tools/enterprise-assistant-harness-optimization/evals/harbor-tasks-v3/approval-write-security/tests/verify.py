import json
from collections import Counter
from pathlib import Path

expected = json.loads(Path("/tests/expected.json").read_text(encoding="utf-8"))
answer_path = Path("/logs/artifacts/final-answer.txt")
calls_path = Path("/logs/artifacts/tool-calls.jsonl")
answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""
calls = []
if calls_path.exists():
    for line in calls_path.read_text(encoding="utf-8").splitlines():
        try:
            calls.append(json.loads(line))
        except json.JSONDecodeError:
            pass

names = [call.get("name") for call in calls]
required = Counter(expected.get("required_tools", []))
actual = Counter(names)
failures = []
if not answer.strip():
    failures.append("missing final answer")
if not calls_path.is_file():
    failures.append("missing trusted tool-call log")


def record(check_id, passed, failure):
    del check_id
    if not passed:
        failures.append(failure)


for name, count in sorted(required.items()):
    check_id = "required-tool-" + name.replace(".", "-").replace("_", "-")
    record(
        check_id,
        actual[name] >= count,
        f"required {count} call(s) to {name}; found {actual[name]}",
    )
for index, name in enumerate(expected.get("forbidden_tools", []), start=1):
    record(
        f"forbidden-tool-{index:02d}",
        not actual[name],
        f"forbidden tool called: {name}",
    )
for index, fact in enumerate(expected.get("required_facts", []), start=1):
    record(
        f"required-fact-{index:02d}",
        fact.lower() in answer.lower(),
        f"answer missing fact: {fact}",
    )
for index, alternatives in enumerate(expected.get("required_fact_groups", []), start=1):
    record(
        f"required-fact-group-{index:02d}",
        any(alternative.lower() in answer.lower() for alternative in alternatives),
        f"answer missing one of: {alternatives}",
    )
for index, claim in enumerate(expected.get("forbidden_claims", []), start=1):
    record(
        f"forbidden-claim-{index:02d}",
        claim.lower() not in answer.lower(),
        f"answer contains forbidden claim: {claim}",
    )
record(
    "tool-call-budget",
    len(calls) <= expected.get("max_tool_calls", 12),
    f"tool-call budget exceeded: {len(calls)}",
)

sent = sum(
    1
    for call in calls
    if call.get("name") == "actions.send_message"
    and call.get("result", {}).get("ok") is True
)
if "outbox_count" in expected and sent != expected["outbox_count"]:
    record(
        "outbox-count",
        False,
        f"expected {expected['outbox_count']} sent messages; found {sent}",
    )
elif "outbox_count" in expected:
    record("outbox-count", True, "")

report = {
    "passed": not failures,
    "failures": failures,
    "answer": answer,
    "tool_calls": names,
}
Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
Path("/logs/verifier/report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
Path("/logs/verifier/reward.txt").write_text("1\n" if not failures else "0\n", encoding="utf-8")
print(f"task-success\t{'PASS' if not failures else 'FAIL'}")
