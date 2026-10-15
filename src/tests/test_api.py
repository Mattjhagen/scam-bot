import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _twilio_sig(form_data):
    from twilio.request_validator import RequestValidator
    from src.config import settings
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    url = "http://testserver/telephony/voice"
    return validator.compute_signature(url, form_data)


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ScamBot"
    assert "endpoints" in data


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "ok"


def test_register_user(client):
    response = client.post("/api/users", json={
        "phone_number": "+15555551234",
        "email": "test@example.com",
        "name": "Test User",
    }, headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 201
    data = response.json()
    assert data["phone_number"] == "+15555551234"


def test_register_user_no_api_key(client):
    response = client.post("/api/users", json={
        "phone_number": "+15555551234",
    })
    assert response.status_code == 403


def test_register_duplicate_user(client):
    client.post("/api/users", json={"phone_number": "+15555551235"}, headers={"X-API-Key": "test-api-key"})
    response = client.post("/api/users", json={"phone_number": "+15555551235"}, headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 400


def test_submit_scam_report(client):
    from src.core.rate_limiter import _report_limiter
    _report_limiter.reset()
    response = client.post("/api/scam-reports", json={
        "phone_number": "+15555551999",
        "scam_type": "bank_fraud",
        "notes": "Fake bank call",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["phone_number"] == "+15555551999"
    _report_limiter.reset()


def test_submit_scam_report_rate_limit(client):
    from src.core.rate_limiter import _report_limiter
    _report_limiter.reset()

    for i in range(5):
        response = client.post("/api/scam-reports", json={
            "phone_number": f"+1555500000{i}",
            "scam_type": "general",
        })
        assert response.status_code == 201, f"Request {i+1} failed"

    response = client.post("/api/scam-reports", json={
        "phone_number": "+15555000099",
        "scam_type": "general",
    })
    assert response.status_code == 429
    _report_limiter.reset()


def test_list_scam_numbers(client):
    response = client.get("/api/scam-numbers", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 12


def test_list_scam_numbers_no_api_key(client):
    response = client.get("/api/scam-numbers")
    assert response.status_code == 403


def test_list_scam_numbers_search(client):
    response = client.get("/api/scam-numbers?search=1800", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_voice_webhook_known_scam(client):
    form_data = {"From": "+18002311500", "CallSid": "CA_TEST"}
    signature = _twilio_sig(form_data)

    response = client.post("/telephony/voice", data=form_data, headers={
        "X-Twilio-Signature": signature,
    })
    assert response.status_code == 200
    content = response.text
    assert "<Response>" in content
    assert "scam" in content.lower()


def test_voice_webhook_invalid_signature(client):
    response = client.post("/telephony/voice", data={
        "From": "+18002311500",
        "CallSid": "CA_TEST",
    }, headers={
        "X-Twilio-Signature": "invalid_signature",
    })
    assert response.status_code == 403


def test_voice_webhook_unknown(client):
    form_data = {"From": "+15555551234", "CallSid": "CA_TEST2"}
    signature = _twilio_sig(form_data)

    response = client.post("/telephony/voice", data=form_data, headers={
        "X-Twilio-Signature": signature,
    })
    assert response.status_code == 200
    content = response.text
    assert "<Response>" in content


def test_get_call_detail_not_found(client):
    response = client.get("/api/calls/CA_NONEXISTENT", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 404


def test_list_calls_empty(client):
    response = client.get("/api/calls", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_scam_types(client):
    response = client.get("/api/scam-types")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 8


def test_export_call_transcript_not_found(client):
    response = client.get("/api/calls/CA_NONEXISTENT/export", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 404


def test_export_call_transcript(client):
    form_data = {"From": "+18002311500", "CallSid": "CA_EXPORT_TEST"}
    signature = _twilio_sig(form_data)
    client.post("/telephony/voice", data=form_data, headers={"X-Twilio-Signature": signature})

    response = client.get("/api/calls/CA_EXPORT_TEST/export", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    assert "ScamBot" in response.text
    assert "+18002311500" in response.text


def test_bulk_import_scam_numbers(client):
    response = client.post("/api/scam-numbers/bulk-import", json=[
        {"phone_number": "+15557654321", "scam_type": "tech_support", "caller_name": "Bulk Test"},
        {"phone_number": "+15557654322", "scam_type": "lottery", "caller_name": "Bulk Test 2"},
    ], headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["added"] == 2
    assert len(data["errors"]) == 0
