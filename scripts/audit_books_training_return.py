"""Audit an archived Books return and its offline Cookbook datums."""

import argparse
import json
from pathlib import Path

import tinker
from tinker_cookbook.completers import TokensWithLogprobs
from tinker_cookbook.rl.types import Trajectory, TrajectoryGroup, Transition

from elt_rl.official import _pack_grade, check_checkout
from elt_rl.rendering import make_renderer
from elt_rl.training import OFFICIAL_BASELINE, alignment_evidence, datums_for_group, verified_official_training_reward


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def audit(run: Path, local_checkout: Path | None = None) -> dict:
    manifest = json.loads((run / "manifest.json").read_bytes())
    official = manifest["mode"] in {"official-rollout", "train-official-one"}
    (recorded,) = manifest["trajectories"]
    (submission_path,) = (run / "pipelines").glob("*.submission.json")
    submission = json.loads(submission_path.read_bytes())
    if official:
        (receipt_path,) = (run / "pipelines").glob("*.grade.json")
        receipt = json.loads(receipt_path.read_bytes())
    elif local_checkout is not None:
        check_checkout(local_checkout)
        expected = json.loads((local_checkout / "evaluation/table.json").read_bytes())["books"]
        directory = run / "grading/agent_results/graded"
        grade = _pack_grade((directory / "results.log").read_text(encoding="utf-8"),
                            json.loads((directory / "stage2.json").read_bytes()), frozenset(expected))
        receipt = {**grade.metrics(), "reward": grade.reward}
    else:
        raise ValueError("pass --local-checkout to audit an archived local rehearsal")
    prompts = read_jsonl(run / "prompt-inputs.jsonl")
    actions = read_jsonl(run / "sampled-actions.jsonl")
    reward = receipt["reward"]
    if reward != recorded["reward"] or manifest["rewards"] != [reward] or not receipt["submitted"]:
        raise ValueError("the recorded return and submission grade disagree")
    if official:
        (native_grade_path,) = (run / "official").glob("*/grade.json")
        native_grade = json.loads(native_grade_path.read_bytes())
        if any(native_grade[name] != value for name, value in receipt.items()):
            raise ValueError("the native grade and submission grade disagree")
        if not recorded["turns"][-1]["metrics"].get("submission_accepted"):
            raise ValueError("the native trajectory lacks an accepted submission")

    transitions = []
    for prompt, action, turn in zip(prompts, actions, recorded["turns"], strict=True):
        if len(prompt["prompt_token_ids"]) != turn["prompt_tokens"] or len(action["tokens"]) != turn["sampled_tokens"]:
            raise ValueError("the saved sampling receipt and trajectory disagree")
        transitions.append(Transition(
            tinker.ModelInput.from_ints(prompt["prompt_token_ids"]),
            TokensWithLogprobs(action["tokens"], action["logprobs"], sequence_id=action["sequence_id"],
                               stop_reason=action["stop_reason"], prompt_cache_hit_tokens=action["prefill_cached_tokens"]),
            0.0, False, turn["metrics"],
        ))
    renderer = make_renderer(manifest["model"], manifest["renderer"], offline=True)
    decoded, termination = renderer.parse_response(transitions[-1].ac.tokens)
    if (not termination.is_clean or not any(call.function.name == "submit_pipeline"
            for call in decoded.get("tool_calls", ()))):
        raise ValueError("the terminal receipt is missing a sampled submit_pipeline call")
    transitions[-1].reward = reward
    transitions[-1].episode_done = True
    empty = tinker.ModelInput.empty()
    actual = Trajectory(transitions, empty, recorded["stop_reason"])
    singleton = TrajectoryGroup([actual], [0.0], [{}])
    if singleton.get_total_rewards() != [reward] or datums_for_group(singleton, require_provenance=True):
        raise ValueError("unpaired Books trajectory has an invalid return or training signal")

    if official and verified_official_training_reward(singleton, run) != reward:
        raise ValueError("the official training gate returned a different reward")
    datums = datums_for_group(singleton, require_provenance=True, fixed_baseline=OFFICIAL_BASELINE)
    if reward and not datums:
        raise ValueError("the graded sample did not produce any aligned training datums")
    return {"warehouse": manifest["mode"], "grade": receipt,
            "submitted_files": submission["transforms"], "training_interface_returns": singleton.get_total_rewards(),
            "fixed_baseline": OFFICIAL_BASELINE, "advantage": reward - OFFICIAL_BASELINE,
            "offline_datum_count": len(datums), "optimization_executed": False,
            **alignment_evidence(datums)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--local-checkout", type=Path)
    args = parser.parse_args()
    evidence = json.dumps(audit(args.run, args.local_checkout), indent=2) + "\n"
    (args.run / "fixed-baseline-audit.json").write_text(evidence, encoding="utf-8")
    print(evidence, end="")


if __name__ == "__main__":
    main()
