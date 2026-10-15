import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ScamBot"
    assert "endpoints" in data


def test_register_user(client):
    response = client.post("/api/users", json={
        "phone_number": "+15555551234",
        "email": "test@example.com",
        "name": "Test User",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["phone_number"] == "+15555551234"


def test_register_duplicate_user(client):
    client.post("/api/users", json={"phone_number": "+15555551235"})
    response = client.post("/api/users", json={"phone_number": "+15555551235"})
    assert response.status_code == 400


def test_submit_scam_report(client):
    response = client.post("/api/scam-reports", json={
        "phone_number": "+15555551999",
        "scam_type": "bank_fraud",
        "notes": "Fake bank call",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["phone_number"] == "+15555551999"


def test_list_scam_numbers(client):
    response = client.get("/api/scam-numbers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 10


def test_list_scam_numbers_search(client):
    response = client.get("/api/scam-numbers?search=1800")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_voice_webhook_known_scam(client):
    response = client.post("/telephony/voice", data={
        "From": "+18002311500",
        "CallSid": "CA_TEST",
    })
    assert response.status_code == 200
    content = response.text
    assert "<Response>" in content
    assert "scam" in content.lower()


def test_voice_webhook_unknown(client):
    response = client.post("/telephony/voice", data={
        "From": "+15555551234",
        "CallSid": "CA_TEST2",
    })
    assert response.status_code == 200
    content = response.text
    assert "<Response>" in content


def test_get_call_detail_not_found(client):
    response = client.get("/api/calls/CA_NONEXISTENT")
    assert response.status_code == 404


def test_list_calls_empty(client):
    response = client.get("/api/calls")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
