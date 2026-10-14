"""Split assignment by source group, before any synthetic generation."""

import hashlib
import random
from collections import defaultdict

from app.errors import SplitLeakageError

ALLOWED_SEED_SPLITS = {"train"}


def group_key(make: str | None, model: str | None, model_year: int | None, explicit: str = "") -> str:
    if explicit:
        return explicit.strip().lower()
    parts = [
        (make or "unknown").strip().lower(),
        (model or "unknown").strip().lower(),
        str(model_year or "na"),
    ]
    return "|".join(parts)


def assign_group_splits(
    groups: list[str],
    *,
    seed: int = 42,
    train_ratio: float = 0.7,
    validation_ratio: float = 0.15,
    holdout_groups: list[str] | None = None,
) -> dict[str, str]:
    """Assign every member of a group to the same split.

    `holdout_groups` are forced to test (model-year or vehicle holdout).
    Remaining groups are shuffled with `seed`. If fewer than 3 groups remain,
    the fallback is: 1 group -> train, 2 groups -> train and test. The caller
    should record that validation is unavailable.
    """
    unique = sorted(set(groups))
    mapping: dict[str, str] = {}
    holdout = set(holdout_groups or [])
    for name in unique:
        if name in holdout:
            mapping[name] = "test"
    rest = [name for name in unique if name not in mapping]
    rng = random.Random(seed)
    rng.shuffle(rest)
    if len(rest) < 3:
        if len(rest) == 1:
            mapping[rest[0]] = "train"
        elif len(rest) == 2:
            mapping[rest[0]] = "train"
            mapping[rest[1]] = "test"
        return mapping
    n = len(rest)
    n_train = max(1, int(round(n * train_ratio)))
    n_val = max(1, int(round(n * validation_ratio)))
    if n_train + n_val >= n:
        n_train = max(1, n - 2)
        n_val = 1
    for index, name in enumerate(rest):
        if index < n_train:
            mapping[name] = "train"
        elif index < n_train + n_val:
            mapping[name] = "validation"
        else:
            mapping[name] = "test"
    return mapping


def assert_same_split(members: list[tuple[str, str]]) -> None:
    by_group: dict[str, set[str]] = defaultdict(set)
    for group, split in members:
        by_group[group].add(split)
    leaked = {group: splits for group, splits in by_group.items() if len(splits) > 1}
    if leaked:
        raise SplitLeakageError(f"source group assigned to multiple splits: {leaked}")


def assert_seed_allowed(split: str, *, document_id: str) -> None:
    if split not in ALLOWED_SEED_SPLITS:
        raise SplitLeakageError(
            f"Refusing to synthesize from document {document_id} in split '{split}'. "
            "Only train-split sources may seed synthetic examples."
        )


def stable_bucket(text: str, modulo: int = 100) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo
