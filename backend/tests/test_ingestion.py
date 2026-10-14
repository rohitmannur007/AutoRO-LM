from datetime import UTC, datetime

import pytest
from app.ingestion import (
    IngestionFormatError,
    parse_complaint_payload,
    parse_mfr_csv,
    parse_recall_payload,
    safe_zip_csv,
)


def test_complaint_parser_drops_vin_and_requires_fields():
    payload = {
        "count": 1,
        "results": [
            {
                "odiNumber": "999",
                "summary": "The contact wrote a short fictional schema example about a light.",
                "vin": "1HGCM82633A004352",
                "components": "ELECTRICAL SYSTEM",
                "products": [{"productYear": "2018", "productMake": "HONDA", "productModel": "CIVIC"}],
            }
        ],
    }
    docs = parse_complaint_payload(payload, retrieved_at=datetime.now(UTC), max_records=10)
    assert len(docs) == 1
    assert docs[0].document_id == "nhtsa-complaint-999"
    assert "1HGCM82633A004352" not in docs[0].text
    assert docs[0].narrative_kind == "consumer_complaint"
    assert docs[0].demo is False
    assert docs[0].provenance["access_date"]
    with pytest.raises(IngestionFormatError):
        parse_complaint_payload({"results": [{"summary": "no id"}]}, retrieved_at=datetime.now(UTC), max_records=5)


def test_recall_parser_uses_observed_pascal_case():
    payload = {
        "Count": 1,
        "results": [
            {
                "NHTSACampaignNumber": "00V000000",
                "Summary": "Schema example only. Not a real campaign.",
                "Remedy": "None in this fixture.",
                "Consequence": "None.",
                "Make": "ACURA",
                "Model": "RDX",
                "ModelYear": "2012",
                "Component": "AIR BAGS",
            }
        ],
    }
    docs = parse_recall_payload(payload, retrieved_at=datetime.now(UTC), max_records=5)
    assert docs[0].source_type == "nhtsa_recall"
    assert docs[0].model_year == 2012
    assert "00V000000" in docs[0].text


def test_mfr_csv_rejects_drift_and_parses_header():
    csv_text = (
        '"TSB/Document ID","Make","Model","Model Year","Concise Summary"\n'
        '"DEMO1","HONDA","CIVIC","2018","SCHEMA FIXTURE ONLY. Not a real communication."\n'
        '"DEMO2","FORD","F-150","9999","Unknown year fixture."\n'
    )
    docs = parse_mfr_csv(csv_text, retrieved_at=datetime.now(UTC), source_url="https://static.nhtsa.gov/example.zip", max_records=10)
    assert len(docs) == 2
    assert docs[0].model_year == 2018
    assert docs[1].model_year is None
    with pytest.raises(IngestionFormatError):
        parse_mfr_csv("a,b\n1,2\n", retrieved_at=datetime.now(UTC), source_url="https://static.nhtsa.gov/x", max_records=1)


def test_zip_rejects_path_traversal(tmp_path):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.csv", "TSB/Document ID,Concise Summary\n1,x\n")
    with pytest.raises(IngestionFormatError):
        safe_zip_csv(buffer.getvalue(), max_uncompressed=10000)
