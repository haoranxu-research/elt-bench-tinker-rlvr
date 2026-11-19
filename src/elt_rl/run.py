"""Explicit opt-in entry point for credentialed runs."""

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from .contracts import EpisodeConfig
from .local import local_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one official rollout or one Tinker LoRA update.")
    parser.add_argument("mode", choices=("official-rollout", "train-one"))
    parser.add_argument("--allow-paid", action="store_true", help="Confirm authorized Tinker usage")
    parser.add_argument("--allow-warehouse", action="store_true", help="Confirm authorized Snowflake and Airbyte usage")
    parser.add_argument("--budget-usd", type=float, required=True, help="Maximum estimated Tinker token cost")
    parser.add_argument("--out", type=Path, required=True, help="New private directory for run evidence")
    parser.add_argument("--model", default=os.environ.get("TINKER_MODEL") or "Qwen/Qwen3.5-4B")
    parser.add_argument("--renderer", default="qwen3_5_disable_thinking")
    parser.add_argument("--seed", type=int, default=0, help="LoRA initialization seed")
    parser.add_argument("--group-size", type=int, choices=(2, 3, 4), default=3)
    args = parser.parse_args(argv)
    official = args.mode == "official-rollout"
    if not args.allow_paid or (official and not args.allow_warehouse):
        parser.error("explicit --allow-paid is required, plus --allow-warehouse for official-rollout")
    if not math.isfinite(args.budget_usd) or args.budget_usd <= 0:
        parser.error("--budget-usd must be finite and positive")
    if not os.environ.get("TINKER_API_KEY"):
        parser.error("set TINKER_API_KEY")

    out = args.out.resolve()
    out.mkdir(parents=True, mode=0o700)
    manifest = {"mode": args.mode, "status": "started"}

    def record(**updates: object) -> None:
        manifest.update(updates)
        manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()
        partial = out / "manifest.tmp"
        partial.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        partial.replace(out / "manifest.json")

    record(started_utc=datetime.now(timezone.utc).isoformat())
    try:
        if official:
            from .official import BENCH_SHA, OfficialConfig, snowflake_task
            task = snowflake_task(OfficialConfig.from_environment(out / "official"), allow_paid=True)
            record(benchmark_sha=BENCH_SHA)
        else:
            task = local_task()
        from .training import run_remote
        with TemporaryDirectory(prefix="elt-run-") as work_root:
            config = EpisodeConfig(
                Path(work_root), max_turns=24, max_tool_calls=32,
                execution_seconds=60 if official else 1,
                rollout_seconds=1800 if official else 120,
                max_submissions=1 if official else 2,
            )
            (out / "pipelines").mkdir(mode=0o700)
            return asyncio.run(run_remote(
                args.mode, task, config, out, args.model, args.renderer, 1 if official else args.group_size,
                args.budget_usd, record, seed=args.seed,
            ))
    except (KeyboardInterrupt, Exception) as exc:
        cause = type(exc).__name__
        record(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", error_type=cause)
        # Environments and connectors may include credentials in arbitrary exception text.
        detail = str(exc) if type(exc) is ValueError and not exc.__cause__ and not exc.__context__ else cause
        print(f"Run stopped ({detail}). Inspect the private manifest.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
