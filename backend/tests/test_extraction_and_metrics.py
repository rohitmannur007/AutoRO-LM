from datetime import UTC

from app.extraction import extract_rules
from app.metrics import (
    abstention_counts,
    bootstrap_ci,
    dtc_counts,
    mrr,
    prf,
    recall_at_k,
    scalar_counts,
)
from app.ml_baseline import plan_mixture
from app.providers import validate_citations
from app.schemas import Citation
from app.splits import assert_same_split, assign_group_splits
from app.synthetic import generate_from_document
from app.textutil import find_dtcs, jaccard, normalize_dtc

NOTE = (
    "2018 Honda Civic. Check engine light on. Stored DTC P0420. "
    "Customer reports a rotten egg smell at idle. Replaced the catalytic converter."
)


def test_rules_extract_supported_fields_only():
    result = extract_rules(NOTE)
    assert result.schema_valid
    assert result.demo is True
    assert result.provider.is_llm is False
    assert result.vehicle.make == "Honda"
    assert result.vehicle.model == "Civic"
    assert result.vehicle.model_year == 2018
    assert result.dtc_codes == ["P0420"]
    assert result.component == "catalytic converter"
    assert result.complaint
    assert result.repair_action == "replaced catalytic converter"
    assert "confidence" not in result.model_dump()
    for span in result.evidence:
        assert span.quoted_text
        assert span.start is not None
    assert "component" not in result.unknown_fields


def test_dtc_alone_does_not_fill_component():
    result = extract_rules("P0420 stored. No repair described.")
    assert result.dtc_codes == ["P0420"]
    assert result.component is None
    assert result.suspected_component is None
    assert "component" in result.unknown_fields
    assert any("not proof" in caveat for caveat in result.provider.caveats)


def test_suspect_is_not_a_confirmed_component():
    result = extract_rules("Suspect a faulty wheel speed sensor. C0035. No parts replaced.")
    assert result.dtc_codes == ["C0035"]
    assert result.suspected_component == "wheel speed sensor"
    assert result.component is None


def test_dtc_normalization():
    assert normalize_dtc("p-0420") == "P0420"
    assert find_dtcs("codes P 0300 and p0420") == ["P0300", "P0420"]


def test_scalar_f1_known_answer():
    stats = scalar_counts(["noise", "leak"], ["noise", None])
    assert stats["precision"] == 1
    assert stats["recall"] == 0.5
    assert stats["f1"] == 2 / 3


def test_dtc_micro_f1():
    stats = dtc_counts([["P0420", "P0171"]], [["P0420"]])
    assert stats["tp"] == 1
    assert stats["fn"] == 1
    assert stats["fp"] == 0


def test_prf_undefined_when_empty():
    assert prf(0, 0, 0)["precision"] is None
    assert prf(0, 0, 0)["f1"] is None


def test_retrieval_metrics_known():
    assert recall_at_k({"a", "b"}, ["a", "c", "b"], 2) == 0.5
    assert mrr({"b"}, ["a", "b"]) == 0.5


def test_abstention_counts():
    stats = abstention_counts([True, False], [False, True])
    assert stats["tp"] == 1
    assert stats["fp"] == 0
    assert stats["fn"] == 0
    assert stats["precision"] == 1


def test_bootstrap_contains_mean():
    interval = bootstrap_ci([0.0, 1.0, 1.0], n_resamples=200, seed=1)
    assert interval["low"] <= interval["mean"] <= interval["high"]


def test_split_groups_stay_together_and_holdout_is_test():
    groups = ["a", "a", "b", "c", "hold"]
    mapping = assign_group_splits(groups, seed=3, holdout_groups=["hold"])
    assert mapping["hold"] == "test"
    assert_same_split([(name, mapping[name]) for name in groups])


def test_citation_must_be_retrieved():
    citation = Citation(citation_id="c1", chunk_id="missing", document_id="d", quote="x")
    assert validate_citations([citation], {"real"}) == ["citation c1 is not in the retrieved set"]


def test_synthetic_refuses_test_split():
    from datetime import datetime

    from app.schemas import SourceDocument

    document = SourceDocument(
        document_id="secret-test",
        source_type="demo_note",
        source_name="test",
        text="2018 Honda Civic. Replaced the catalytic converter.",
        raw_text="2018 Honda Civic. Replaced the catalytic converter.",
        checksum="abc",
        split="test",
        allow_synthetic_seed=True,
        source_group="grp-test",
        demo=True,
    )
    document.retrieved_at = datetime.now(UTC)
    try:
        generate_from_document(document, ["terse"], teacher="deterministic_demo", limit=1)
    except Exception as exc:
        assert "test" in str(exc).lower() or "split" in str(exc).lower()
    else:
        raise AssertionError("expected split leakage")


def test_near_duplicate_detector():
    assert jaccard("replaced the catalytic converter", "replaced the catalytic converter") == 1


def test_mixture_plan_refuses_impossible_share():
    plan, reason = plan_mixture(4, 0, 0.5, 4)
    assert plan is None
    assert "synthetic" in reason
    plan, reason = plan_mixture(4, 0, 0.0, 4)
    assert plan == (4, 0)
    assert reason is None
