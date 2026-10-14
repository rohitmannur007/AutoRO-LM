"""Metric definitions used by evaluation.

Undefined ratios (empty denominator) are returned as None and must be labeled
unavailable. This module never invents a score.

Field F1 treats a non-null gold value as the positive class. A null gold value
with a non-null prediction is a false positive (unsupported field). A non-null
gold value with a null prediction is a false negative. Null/null is a true
negative and is excluded from precision and recall.

List fields (DTC codes) use micro-averaged set overlap across examples.
"""

from __future__ import annotations

import random
from typing import Any

from app.schemas import ExtractionTarget


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int | None]:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.lower().split())
    return text or None


def scalar_counts(gold: list[str | None], pred: list[str | None]) -> dict[str, float | int | None]:
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")
    tp = fp = fn = 0
    for g, p in zip(gold, pred, strict=True):
        g_n, p_n = _norm(g), _norm(p)
        if g_n is None and p_n is None:
            continue
        if g_n is not None and p_n == g_n:
            tp += 1
        elif g_n is None and p_n is not None:
            fp += 1
        elif g_n is not None and p_n is None:
            fn += 1
        else:
            fp += 1
            fn += 1
    return prf(tp, fp, fn)


def dtc_counts(gold: list[list[str]], pred: list[list[str]]) -> dict[str, float | int | None]:
    tp = fp = fn = 0
    for g, p in zip(gold, pred, strict=True):
        gs, ps = set(g), set(p)
        tp += len(gs & ps)
        fp += len(ps - gs)
        fn += len(gs - ps)
    return prf(tp, fp, fn)


def exact_match_rate(pairs: list[tuple[ExtractionTarget, ExtractionTarget]]) -> dict[str, float | int | None]:
    if not pairs:
        return {"exact_match": None, "support": 0, "reason": "no examples"}
    hits = 0
    for gold, pred in pairs:
        if gold.model_dump() == pred.model_dump():
            hits += 1
    return {"exact_match": hits / len(pairs), "support": len(pairs)}


def schema_valid_rate(flags: list[bool]) -> dict[str, float | int | None]:
    if not flags:
        return {"schema_valid_rate": None, "support": 0, "reason": "no examples"}
    return {"schema_valid_rate": sum(1 for flag in flags if flag) / len(flags), "support": len(flags)}


def hallucination_rate(gold: list[ExtractionTarget], pred: list[ExtractionTarget]) -> dict[str, float | int | None]:
    """Share of predicted non-null scalar fields that are unsupported by gold."""
    fields = ["symptom", "component", "suspected_component", "repair_action", "complaint", "cause", "correction"]
    unsupported = 0
    predicted = 0
    for g, p in zip(gold, pred, strict=True):
        for field in fields:
            pv = _norm(getattr(p, field))
            gv = _norm(getattr(g, field))
            if pv is None:
                continue
            predicted += 1
            if gv is None or gv != pv:
                unsupported += 1
        extra = set(p.dtc_codes) - set(g.dtc_codes)
        predicted += len(p.dtc_codes)
        unsupported += len(extra)
    if predicted == 0:
        return {"hallucination_rate": None, "support": 0, "reason": "no non-null predictions"}
    return {"hallucination_rate": unsupported / predicted, "unsupported": unsupported, "predicted_fields": predicted}


def recall_at_k(relevant: set[str], ranked: list[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(relevant & set(ranked[:k])) / len(relevant)


def precision_at_k(relevant: set[str], ranked: list[str], k: int) -> float | None:
    if k <= 0:
        return None
    return len(relevant & set(ranked[:k])) / k


def mrr(relevant: set[str], ranked: list[str]) -> float | None:
    if not relevant:
        return None
    for index, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def mean_defined(values: list[float | None]) -> dict[str, float | int | None]:
    usable = [value for value in values if value is not None]
    if not usable:
        return {"mean": None, "support": 0, "reason": "no defined example scores"}
    return {"mean": sum(usable) / len(usable), "support": len(usable)}


def citation_correct(cited: list[str], relevant: set[str], retrieved: set[str]) -> bool:
    if not cited:
        return False
    return set(cited).issubset(retrieved) and set(cited).issubset(relevant)


def abstention_counts(gold_answerable: list[bool], pred_abstained: list[bool]) -> dict[str, float | int | None]:
    """Abstention is the positive class: gold unanswerable and system abstained."""
    tp = fp = fn = 0
    for answerable, abstained in zip(gold_answerable, pred_abstained, strict=True):
        should = not answerable
        if should and abstained:
            tp += 1
        elif (not should) and abstained:
            fp += 1
        elif should and not abstained:
            fn += 1
    result = prf(tp, fp, fn)
    result["support"] = len(gold_answerable)
    return result


def bootstrap_ci(
    values: list[float],
    *,
    n_resamples: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Percentile bootstrap of the mean. Assumes i.i.d. example scores.

    With a tiny fixture set this interval is a description of that set under
    resampling, not a population claim about automotive text.
    """
    if len(values) < 2:
        return {
            "mean": values[0] if values else None,
            "low": None,
            "high": None,
            "n": len(values),
            "reason": "fewer than 2 example scores",
        }
    rng = random.Random(seed)
    point = sum(values) / len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(sample) / len(sample))
    means.sort()
    low_i = int((alpha / 2) * (n_resamples - 1))
    high_i = int((1 - alpha / 2) * (n_resamples - 1))
    return {
        "mean": point,
        "low": means[low_i],
        "high": means[high_i],
        "n": len(values),
        "resamples": n_resamples,
        "alpha": alpha,
        "assumption": "i.i.d. percentile bootstrap of the mean; fixture-scale only",
    }


def macro_f1(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    if not y_true:
        return {"macro_f1": None, "support": 0, "reason": "no examples", "per_label": {}}
    per_label = {}
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for g, p in zip(y_true, y_pred, strict=True) if g == label and p == label)
        fp = sum(1 for g, p in zip(y_true, y_pred, strict=True) if g != label and p == label)
        fn = sum(1 for g, p in zip(y_true, y_pred, strict=True) if g == label and p != label)
        stats = prf(tp, fp, fn)
        per_label[label] = stats
        if stats["f1"] is not None and any(g == label for g in y_true):
            f1s.append(float(stats["f1"]))
    return {
        "macro_f1": (sum(f1s) / len(f1s)) if f1s else None,
        "support": len(y_true),
        "per_label": per_label,
    }


def confusion(y_true: list[str], y_pred: list[str]) -> dict[str, dict[str, int]]:
    labels = sorted(set(y_true) | set(y_pred))
    table = {gold: {pred: 0 for pred in labels} for gold in labels}
    for gold, pred in zip(y_true, y_pred, strict=True):
        table[gold][pred] += 1
    return table
