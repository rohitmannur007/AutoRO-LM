"""Launch an Apple Silicon MLX-LM LoRA run, or stop with a real error.

Exit 2 when mlx-lm is missing and training was requested or no flag was passed.
A dry run prints the command and writes no adapter weights.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mlx_train import DEFAULTS, build_lora_command, launch_lora, mlx_available  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoRO-LM MLX LoRA launcher")
    parser.add_argument("--data", type=Path, help="Directory containing train.jsonl")
    parser.add_argument("--adapter", type=Path, help="Adapter output directory")
    parser.add_argument("--model", default="mlx-community/Llama-3.2-1B-Instruct-4bit")
    parser.add_argument("--iters", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ok, detail = mlx_available()
    if args.dry_run and args.data and args.adapter:
        config = {**DEFAULTS, "iters": args.iters}
        command = build_lora_command(
            python=sys.executable,
            model=args.model,
            data_dir=args.data,
            adapter_path=args.adapter,
            config=config,
        )
        print("Dry run. This command was not executed:")
        print(" ".join(command))
        return 0
    if not ok:
        print(detail)
        print("CUDA/QLoRA is not part of this path and is not expected to run on an M2 Mac.")
        return 2
    if not args.data or not args.adapter:
        print("mlx-lm imports. Pass --data and --adapter to train, or add --dry-run to print the command.")
        return 0
    try:
        record = launch_lora(
            model=args.model,
            data_dir=args.data,
            adapter_path=args.adapter,
            config={**DEFAULTS, "iters": args.iters},
            dry_run=False,
            log_path=args.adapter / "train.log",
        )
    except Exception as exc:
        print(exc)
        return 1
    print(record.get("detail"))
    return 0 if record.get("trained") else 1


if __name__ == "__main__":
    raise SystemExit(main())
