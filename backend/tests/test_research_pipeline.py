"""Training data, model adoption, splits, and honest unavailable LLM runs."""

from datetime import UTC, datetime

import pytest
from app.mlx_train import build_lora_command
from app.model_extract import adopt_model_extraction
from app.providers import lexical_claims
from app.research import assign_complaint_splits, enable_train_seeds, save_gold_example
from app.schemas import Citation, ExtractionTarget, GoldExample, SourceDocument, VehicleInfo
from app.training_data import build_training_dataset


def test_model_extraction_drops_invented_dtc_and_does_not_copy_rules():
    text = "2018 Honda Civic. Check engine light on. Stored DTC P0420. Rotten egg smell."
    result = adopt_model_extraction(
        text,
        {
            "symptom": "check engine light",
            "dtc_codes": ["P0420", "P0300"],
            "component": "catalytic converter",
            "repair_action": "replaced the catalytic converter",
            "vehicle": {"make": "Honda", "model": "Civic", "model_year": 2018},
        },
        None,
        provider_name="mlx",
        model="fixture",
    )
    assert result.dtc_codes == ["P0420"]
    assert result.component is None
    assert result.repair_action is None
    assert result.symptom == "check engine light"
    assert result.provider.is_llm is True
    assert any("rules extractor was not used" in item for item in result.provider.caveats)
    assert any("P0300" in item for item in result.validation_errors)


def test_suspect_component_is_not_stored_as_failed():
    text = "Suspect a faulty wheel speed sensor. No repair completed."
    result = adopt_model_extraction(
        text,
        {"component": "wheel speed sensor", "repair_action": "replaced wheel bearing"},
        None,
        provider_name="ollama",
        model="fixture",
    )
    assert result.component is None
    assert result.suspected_component == "wheel speed sensor"
    assert result.repair_action is None


def test_lora_command_points_at_the_train_directory():
    command = build_lora_command(
        python="python",
        model="mlx-community/example",
        data_dir=__import__("pathlib").Path("/tmp/train-only"),
        adapter_path=__import__("pathlib").Path("/tmp/adapter"),
        config={"lora_layers": 4, "lora_rank": 8, "learning_rate": 1e-5, "batch_size": 1, "iters": 5, "max_seq_length": 256, "seed": 7},
    )
    assert "--train" in command
    assert "/tmp/train-only" in command
    assert command[command.index("--seed") + 1] == "7"
    assert "bitsandbytes" not in " ".join(command)


def test_lexical_claim_overlap_is_not_marked_as_entailment():
    claims = lexical_claims(
        "The passage says the code is not proof.",
        [Citation(citation_id="c1", chunk_id="k", document_id="d", quote="The passage says the code is not proof.")],
    )
    assert claims[0]["support_status"] == "lexical_overlap"
    assert claims[0]["entailment_judged"] is False


@pytest.mark.asyncio
async def test_training_jsonl_excludes_test_gold(tmp_path):
    class Repo:
        async def list_gold(self, split=None):
            rows = [
                _gold("g-train", "train", "group-a", "Civic P0420 check engine light"),
                _gold("g-test", "test", "group-b", "Camry holdout pulsation"),
            ]
            return [item for item in rows if split in (None, item.split)]

        async def list_synthetic(self, limit=50, status=None):
            del limit, status
            return []

        async def all_documents(self):
            return []

    manifest = await build_training_dataset(Repo(), tmp_path, mixture_share=0)
    text = (tmp_path / "train.jsonl").read_text(encoding="utf-8")
    assert "g-test" not in text
    assert "Civic P0420" in text
    assert "Camry holdout" not in text
    assert manifest["gold_test_included"] is False
    assert "g-test" in manifest["test_ids_excluded"]


@pytest.mark.asyncio
async def test_real_complaints_can_be_enabled_only_after_train_split(tmp_path):
    store = {}

    class Repo:
        async def all_documents(self):
            return list(store.values())

        async def upsert_document(self, document):
            store[document.document_id] = document
            return "upserted"

        async def add_audit(self, action, metadata):
            del action, metadata

        async def get_document(self, document_id):
            return store.get(document_id)

        async def list_gold(self, split=None):
            del split
            return []

        async def save_gold(self, example):
            store[example.example_id] = example

    train = _doc("c1", "alpha|civic|2018", "train")
    test = _doc("c2", "beta|camry|2019", "test")
    store[train.document_id] = train
    store[test.document_id] = test
    refused = await enable_train_seeds(Repo(), confirm="ENABLE_TRAIN_SEEDS", document_ids=["c2"])
    assert refused["enabled"] == []
    assert store["c2"].allow_synthetic_seed is False
    enabled = await enable_train_seeds(Repo(), confirm="ENABLE_TRAIN_SEEDS", document_ids=["c1"])
    assert enabled["enabled"] == ["c1"]
    assert store["c1"].allow_synthetic_seed is True

    complaints = [
        _doc("n1", "", "train", make="Honda", model="Civic", year=2018),
        _doc("n2", "", "train", make="Toyota", model="Camry", year=2019),
        _doc("n3", "", "train", make="Ford", model="F-150", year=2020),
    ]
    for item in complaints:
        item.demo = False
        item.source_type = "nhtsa_complaint"
        store[item.document_id] = item
    manifest = await assign_complaint_splits(Repo(), tmp_path, seed=1)
    splits = {store[doc_id].split for doc_id in ("c1", "c2", "n1", "n2", "n3")}
    assert store["n1"].allow_synthetic_seed is False
    assert "train" in splits and "test" in splits
    assert manifest["complaint_documents"] >= 3


@pytest.mark.asyncio
async def test_gold_cannot_attach_a_test_document_to_train():
    document = _doc("held", "group-hold", "test")

    class Repo:
        async def get_document(self, document_id):
            return document if document_id == "held" else None

        async def list_gold(self, split=None):
            del split
            return []

        async def save_gold(self, example):
            raise AssertionError("should not save")

    example = _gold("bad", "train", "group-hold", "text")
    example.source_document_ids = ["held"]
    with pytest.raises(Exception):
        await save_gold_example(Repo(), example)


def _gold(example_id: str, split: str, group: str, text: str) -> GoldExample:
    return GoldExample(
        example_id=example_id,
        source_group=group,
        input_text=text,
        target=ExtractionTarget(symptom="check engine light", dtc_codes=["P0420"], vehicle=VehicleInfo()),
        split=split,
        created_at=datetime.now(UTC),
        demo=True,
    )


def _doc(document_id: str, group: str, split: str, make: str | None = None, model: str | None = None, year: int | None = None) -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        source_type="nhtsa_complaint",
        source_name=document_id,
        text="consumer complaint text",
        raw_text="consumer complaint text",
        checksum=document_id,
        source_group=group,
        split=split,
        make=make,
        model=model,
        model_year=year,
        demo=False,
        allow_synthetic_seed=False,
    )
