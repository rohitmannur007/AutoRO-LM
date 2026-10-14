import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTORO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTORO_JOBS_INLINE", "1")
    monkeypatch.setenv("AUTORO_DATABASE_URL", "")
    monkeypatch.setenv("AUTORO_PROVIDER", "demo")
    monkeypatch.setenv("AUTORO_TEACHER_PROVIDER", "deterministic_demo")
    monkeypatch.setenv("AUTORO_RATE_LIMIT_PER_MINUTE", "1000")
    monkeypatch.setenv("AUTORO_ENV", "test")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()
