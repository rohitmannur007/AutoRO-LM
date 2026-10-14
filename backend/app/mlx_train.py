"""Launch MLX-LM LoRA. A dry run writes the command and does not claim a trained model.

CUDA and bitsandbytes are not invoked. This module is the Apple Silicon path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULTS = {
    "lora_layers": 8,
    "lora_rank": 8,
    "learning_rate": 1e-5,
    "batch_size": 1,
    "iters": 20,
    "max_seq_length": 512,
    "seed": 42,
}


def mlx_available() -> tuple[bool, str]:
    if shutil.which(sys.executable) is None:
        return False, "Python executable is not available"
    try:
        import mlx_lm  # noqa: F401
    except Exception as exc:
        return False, f"mlx-lm is not installed ({exc.__class__.__name__}). pip install mlx-lm"
    return True, "mlx-lm imports"


def build_lora_command(
    *,
    python: str,
    model: str,
    data_dir: Path,
    adapter_path: Path,
    config: dict,
) -> list[str]:
    iters = int(config["iters"])
    report = max(1, min(10, iters))
    return [
        python,
        "-m",
        "mlx_lm.lora",
        "--model",
        model,
        "--train",
        "--data",
        str(data_dir),
        "--adapter-path",
        str(adapter_path),
        "--fine-tune-type",
        "lora",
        "--num-layers",
        str(config["lora_layers"]),
        "--batch-size",
        str(config["batch_size"]),
        "--iters",
        str(iters),
        "--learning-rate",
        str(config["learning_rate"]),
        "--steps-per-report",
        str(report),
        "--steps-per-eval",
        str(iters),
        "--save-every",
        str(iters),
        "--max-seq-length",
        str(config["max_seq_length"]),
        "--seed",
        str(config["seed"]),
        "--lora-parameters",
        json.dumps({"rank": int(config["lora_rank"]), "dropout": 0.0, "scale": 20.0}),
    ]


def launch_lora(
    *,
    model: str,
    data_dir: Path,
    adapter_path: Path,
    config: dict,
    dry_run: bool,
    log_path: Path,
) -> dict:
    command = build_lora_command(
        python=sys.executable,
        model=model,
        data_dir=data_dir,
        adapter_path=adapter_path,
        config=config,
    )
    adapter_path.mkdir(parents=True, exist_ok=True)
    record = {
        "trained": False,
        "dry_run": dry_run,
        "base_model": model,
        "adapter_path": str(adapter_path),
        "data_dir": str(data_dir),
        "command": command,
        "config": config,
        "started_at": datetime.now(UTC).isoformat(),
        "returncode": None,
        "hardware_note": "Apple Silicon MLX path. CUDA/QLoRA is not used.",
    }
    if dry_run:
        record["finished_at"] = datetime.now(UTC).isoformat()
        record["detail"] = "Dry run. mlx_lm.lora was not started and no adapter was saved."
        _write_manifest(adapter_path, record)
        return record
    ok, detail = mlx_available()
    if not ok:
        record["detail"] = detail
        record["finished_at"] = datetime.now(UTC).isoformat()
        _write_manifest(adapter_path, record)
        raise RuntimeError(detail)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=False)
    record["returncode"] = completed.returncode
    record["log_path"] = str(log_path)
    weights = list(adapter_path.glob("*.safetensors")) + list(adapter_path.glob("adapters.safetensors"))
    record["trained"] = completed.returncode == 0 and any(path.is_file() for path in weights)
    record["finished_at"] = datetime.now(UTC).isoformat()
    if not record["trained"]:
        tail = log_path.read_text(encoding="utf-8")[-2000:] if log_path.exists() else ""
        record["detail"] = "mlx_lm.lora did not produce an adapter. See the log."
        record["log_tail"] = tail
        _write_manifest(adapter_path, record)
        raise RuntimeError(record["detail"])
    record["detail"] = "Adapter weights were written by mlx_lm.lora."
    _write_manifest(adapter_path, record)
    return record


def read_manifest(adapter_path: Path) -> dict | None:
    path = adapter_path / "training_manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(adapter_path: Path, record: dict) -> None:
    adapter_path.mkdir(parents=True, exist_ok=True)
    (adapter_path / "training_manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
