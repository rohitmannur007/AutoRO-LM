"""TF-IDF + logistic regression baseline for component category only.

This classifier does not perform full JSON extraction.
"""

from __future__ import annotations

from app.metrics import confusion, macro_f1


def plan_mixture(n_real: int, n_synthetic: int, share: float, target_n: int) -> tuple[tuple[int, int] | None, str | None]:
    if target_n <= 0:
        return None, "target training size is 0"
    if share < 0 or share > 1:
        return None, "synthetic share must be between 0 and 1"
    n_syn = int(round(share * target_n))
    n_real_take = target_n - n_syn
    if n_real_take > n_real:
        return None, f"need {n_real_take} real training examples for share {share}, have {n_real}"
    if n_syn > n_synthetic:
        return None, f"need {n_syn} synthetic examples for share {share}, have {n_synthetic}"
    if n_real_take == 0 and n_real == 0 and share < 1:
        return None, "no real training examples"
    return (n_real_take, n_syn), None


def train_component_classifier(texts: list[str], labels: list[str], test_texts: list[str], test_labels: list[str], *, seed: int = 42) -> dict:
    if len(texts) != len(labels) or len(test_texts) != len(test_labels):
        raise ValueError("texts and labels must align")
    if len(set(labels)) < 2 or len(texts) < 4:
        return {
            "status": "unavailable",
            "reason": "need at least 4 training rows and 2 classes",
            "macro_f1": None,
            "support_train": len(texts),
            "support_test": len(test_labels),
        }
    if len(test_labels) < 1:
        return {
            "status": "unavailable",
            "reason": "no held-out test labels",
            "macro_f1": None,
            "support_train": len(texts),
            "support_test": 0,
        }
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            ("clf", LogisticRegression(max_iter=500, random_state=seed)),
        ]
    )
    pipeline.fit(texts, labels)
    predictions = list(pipeline.predict(test_texts))
    scores = macro_f1(test_labels, predictions)
    return {
        "status": "measured",
        "macro_f1": scores["macro_f1"],
        "per_label": scores["per_label"],
        "confusion": confusion(test_labels, predictions),
        "support_train": len(texts),
        "support_test": len(test_labels),
        "predictions": predictions,
        "labels": test_labels,
        "model": "tfidf_logistic_regression",
        "caveat": "Fixture-scale component category baseline. Not full JSON extraction and not a published benchmark.",
    }
