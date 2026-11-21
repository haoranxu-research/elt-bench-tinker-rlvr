"""Measure action-token use and reconstruct approximate phase timing from native receipts."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def phase(tool):
    name = tool["tool"]
    if name == "execute_pipeline":
        return "load" if tool["arguments"].get("stage") == "load" else "test"
    if name == "write_pipeline_file":
        return "write"
    if name == "submit_pipeline":
        return "submit"
    return "inspect_or_review"


def measure(run):
    manifest = json.loads((run / "manifest.json").read_bytes())
    (tool_path,) = (run / "pipelines").glob("*.tools.jsonl")
    (grade_path,) = (run / "official").glob("*/grade.json")
    samples = read_jsonl(run / "sampled-actions.jsonl")
    tools = defaultdict(list)
    for event in read_jsonl(tool_path):
        tools[event["turn"]].append(event)
    previous_remaining = None
    recorded_seconds = Counter()
    measured_tool_seconds = Counter()
    measured_sampling_seconds = Counter()
    token_counts = Counter()
    turns = []
    drafts = Counter()
    for number, sample in enumerate(samples, 1):
        turns_tools = tools[number]
        phases = {phase(event) for event in turns_tools}
        label = "+".join(sorted(phases)) or "no_dispatched_tool"
        actions = []
        seconds = None
        for event in turns_tools:
            if "elapsed_seconds" in event:
                measured_tool_seconds[phase(event)] += event["elapsed_seconds"]
            arguments = event["arguments"]
            target = arguments.get("path") or arguments.get("file") or arguments.get("table") or arguments.get("section")
            if event["tool"] == "write_pipeline_file":
                drafts[target] += 1
                if drafts[target] > 1:
                    label = label.replace("write", "revise")
            actions.append({"tool": event["tool"], "target": target, "error": event["feedback"].startswith("ERROR:"),
                            "open_check": "Public data check failed" in event["feedback"]})
            match = re.search(r"Agent action time left: (\d+)s\.", event["feedback"])
            if match:
                seconds = int(match[1])
        interval = previous_remaining - seconds if seconds is not None and previous_remaining is not None else None
        if seconds is not None:
            previous_remaining = seconds
        if interval is not None:
            recorded_seconds[label] += interval
        token_counts[label] += len(sample["tokens"])
        if "sampling_elapsed_seconds" in sample:
            measured_sampling_seconds[label] += sample["sampling_elapsed_seconds"]
        turns.append({"turn": number, "sampled_tokens": len(sample["tokens"]), "actions": actions,
                      "remaining_action_seconds": seconds, "receipt_interval_seconds": interval})

    loads = []
    for path in (run / "official").glob("*/airbyte-jobs-*.json"):
        jobs = json.loads(path.read_bytes())
        start = datetime.fromisoformat(jobs[0]["started_utc"])
        finish = datetime.fromisoformat(jobs[-1]["finished_utc"])
        loads.append({"start": start.isoformat(), "seconds": (finish - start).total_seconds(), "jobs": len(jobs)})
    started = datetime.fromisoformat(manifest["started_utc"])
    acceptance = next(event for events in tools.values() for event in events if event.get("accepted"))
    accepted = (datetime.fromisoformat(acceptance["finished_utc"]) if "finished_utc" in acceptance
                else datetime.fromtimestamp(tool_path.stat().st_mtime, timezone.utc))
    graded = datetime.fromtimestamp(grade_path.stat().st_mtime, timezone.utc)
    finished = datetime.fromisoformat(manifest["updated_utc"])
    return {"run": run.name, "turns": turns, "snapshot_loads": sorted(loads, key=lambda row: row["start"]),
            "sampled_tokens_by_turn_phase": token_counts, "receipt_intervals_by_turn_phase": recorded_seconds,
            "measured_tool_seconds": measured_tool_seconds, "measured_sampling_seconds": measured_sampling_seconds,
            "cli_start_to_accept_seconds": (accepted - started).total_seconds(),
            "accept_to_grade_seconds": (graded - accepted).total_seconds(),
            "grade_to_final_manifest_seconds": (finished - graded).total_seconds(),
            "usage": manifest["sampling_token_usage"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps([measure(path) for path in args.run], indent=2))
