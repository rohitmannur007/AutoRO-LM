def test_health_and_status_do_not_leak_secrets(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["version"]
    assert body["secrets_exposed"] is False
    assert body["database"]["active_adapter"] == "sqlite"
    assert body["database"]["fallback"] is False
    assert body["demo_provider"] is True
    blob = health.text.lower()
    assert "api_key" not in blob
    status = client.get("/api/v1/status")
    assert status.status_code == 200
    counts = status.json()["counts"]
    assert counts["documents"] >= 1
    assert counts["demo_documents"] == counts["documents"]
    assert status.json()["demo_data"] is True


def test_extract_download_shape(client):
    response = client.post(
        "/api/v1/extract",
        json={
            "text": "2018 Honda Civic. Check engine light on. Stored DTC P0420. Customer reports a rotten egg smell at idle. Replaced the catalytic converter.",
            "vehicle": {},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_valid"] is True
    assert body["demo"] is True
    assert body["provider"]["is_llm"] is False
    assert body["dtc_codes"] == ["P0420"]
    assert body["component"] == "catalytic converter"
    assert "confidence" not in body


def test_extract_preserves_validation_error_for_empty(client):
    response = client.post("/api/v1/extract", json={"text": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_ask_cites_fixture_and_abstains(client):
    answer = client.post(
        "/api/v1/ask",
        json={"question": "What does DTC P0420 indicate, and does the code alone prove the catalytic converter failed?"},
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["abstained"] is False
    assert body["demo"] is True
    assert body["citations"]
    assert body["citations"][0]["chunk_id"] in body["retrieved_chunk_ids"]
    assert body["citations"][0]["document_id"] == "demo-obd-p0420"
    assert "not proof" in body["answer"].lower()
    assert "DEMO" in body["answer"]
    source = client.get(f"/api/v1/sources/{body['citations'][0]['document_id']}")
    assert source.status_code == 200
    assert source.json()["document"]["demo"] is True
    abstain = client.post(
        "/api/v1/ask",
        json={"question": "What is the cylinder head bolt torque specification for a 2019 Toyota Camry?"},
    )
    assert abstain.status_code == 200
    denied = abstain.json()
    assert denied["abstained"] is True
    assert "ft-lb" not in denied["answer"].lower()
    assert "evidence is not sufficient" in denied["answer"].lower()


def test_source_roundtrip_and_profile(client):
    listing = client.get("/api/v1/sources")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items
    assert all(item["demo"] for item in items)
    profile = client.get("/api/v1/sources/profile")
    assert profile.status_code == 200
    assert profile.json()["demo_count"] == profile.json()["record_count"]
    assert any("DEMO" in warning for warning in profile.json()["warnings"])


def test_ingestion_job_reloads_demo(client):
    response = client.post("/api/v1/ingestion/jobs", json={"source": "demo_fixtures"})
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "completed"
    assert job["counts"]["documents"] >= 1


def test_synthetic_review_and_export(client):
    started = client.post(
        "/api/v1/synthetic/jobs",
        json={"seed_document_ids": ["demo-civic-catalyst"], "variations": ["terse", "ccc"], "count": 2, "teacher": "deterministic_demo"},
    )
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["status"] == "completed", job
    assert job["metadata"]["is_llm"] is False
    examples = client.get("/api/v1/synthetic/examples").json()["items"]
    assert examples
    assert all(item["provenance_label"] == "synthetic" for item in examples)
    assert all(item["demo"] for item in examples)
    example_id = examples[0]["example_id"]
    reviewed = client.post(f"/api/v1/synthetic/examples/{example_id}/review", json={"status": "approved", "reason": "fixture review"})
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "approved"
    exported = client.get("/api/v1/synthetic/examples/export")
    assert exported.status_code == 200
    assert "sha256" in exported.text.splitlines()[0]


def test_synthetic_cannot_seed_holdout(client):
    response = client.post(
        "/api/v1/synthetic/jobs",
        json={"seed_document_ids": ["demo-camry-holdout"], "variations": ["terse"], "count": 1, "teacher": "deterministic_demo"},
    )
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "failed"
    assert job["counts"].get("created", 0) == 0


def test_evaluation_stores_measured_metrics_only(client):
    response = client.post("/api/v1/evaluations", json={"task": "extraction_rules"})
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "completed"
    run_id = job["metadata"]["run_id"]
    run = client.get(f"/api/v1/evaluations/{run_id}")
    assert run.status_code == 200
    metrics = run.json()["metrics"]
    assert metrics["support_test"] >= 1
    assert "f1" in metrics["dtc"]
    history = client.get("/api/v1/experiments")
    assert any(item["run_id"] == run_id for item in history.json()["items"])


def test_llm_synthetic_share_fails_closed(client):
    response = client.post("/api/v1/evaluations", json={"task": "synthetic_share_llm"})
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "failed"
    assert job["metadata"]["evaluation_status"] == "unavailable"
    assert job["metadata"]["model_provider"] == "mlx"


def test_training_dry_run_does_not_mark_a_model_trained(client):
    response = client.post("/api/v1/training/jobs", json={"dry_run": True, "mixture_share": 0})
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "completed"
    assert job["metadata"]["trained"] is False
    assert job["metadata"]["dry_run"] is True
    assert job["counts"]["train_rows"] > 0
    adapter = client.get("/api/v1/training/adapter")
    assert adapter.status_code == 200
    assert adapter.json()["trained"] is False


def test_missing_provider_is_503(client, monkeypatch):
    monkeypatch.setenv("AUTORO_OLLAMA_BASE_URL", "http://127.0.0.1:9")

    settings = client.app.state.autoro["settings"]
    settings.ollama_base_url = "http://127.0.0.1:9"
    response = client.post("/api/v1/extract", json={"text": "2018 Honda Civic check engine light P0420", "provider": "ollama"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_settings_roundtrip_hides_secrets(client):
    view = client.get("/api/v1/settings")
    assert view.status_code == 200
    assert "openai_compat_api_key" not in view.text
    updated = client.put("/api/v1/settings", json={"retrieval_mode": "lexical"})
    assert updated.status_code == 200
    assert updated.json()["retrieval_mode"] == "lexical"
    reset = client.post("/api/v1/settings/reset-demo", json={"confirm": "NO"})
    assert reset.status_code == 400
    reset_ok = client.post("/api/v1/settings/reset-demo", json={"confirm": "RESET_DEMO_DATA"})
    assert reset_ok.status_code == 200
    assert reset_ok.json()["label"] == "DEMO"
