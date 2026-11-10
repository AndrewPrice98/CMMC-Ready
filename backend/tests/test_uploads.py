import json
from pathlib import Path

import pytest

from cmmcready.uploads import UploadError, decode_json_upload

FIXTURES = Path(__file__).parent / "fixtures"
WINDOWS = (FIXTURES / "windows-compliant.json").read_bytes()


def test_bom_and_crlf_accepted():
    assert decode_json_upload(b'\xef\xbb\xbf{"a": 1}\r\n') == '{"a": 1}\r\n'


def test_nul_rejected():
    with pytest.raises(UploadError) as e:
        decode_json_upload(b'{"a":\x001}')
    assert e.value.status == 415


def test_invalid_utf8_rejected():
    with pytest.raises(UploadError) as e:
        decode_json_upload(b"\xff\xfe\xfa")
    assert e.value.status == 415


def test_long_line_rejected_with_line_number():
    with pytest.raises(UploadError) as e:
        decode_json_upload(b"{\n" + b" " * 9000 + b"}")
    assert e.value.status == 413 and "Line 2" in str(e.value)


def post(client, content, name="evidence.json", assessment=2):
    return client.post(f"/api/assessments/{assessment}/evidence", files={"file": (name, content)})


def test_valid_collector_file_stores_evidence_and_returns_findings(client):
    before = len(client.get("/api/assessments/2/evidence").json())
    r = post(client, WINDOWS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["collector"] == "windows" and body["assessment_id"] == 2
    assert body["findings"] and {"objective_id", "result", "check_id", "detail"} <= set(body["findings"][0])
    assert len(client.get("/api/assessments/2/evidence").json()) == before + 1


def test_bom_prefixed_upload_accepted(client):
    assert post(client, b"\xef\xbb\xbf" + WINDOWS).status_code == 200


def test_non_json_is_400(client):
    assert post(client, b"this is not json").status_code == 400
    assert post(client, b"[1, 2]").status_code == 400  # JSON, but not a collector file


def test_deeply_nested_json_is_400_not_500(client):
    assert post(client, b"[\n" * 5000).status_code == 400


@pytest.mark.parametrize("payload", [
    {"collector": "linux", "version": 1, "checks": {}},
    {"collector": "windows", "version": 99, "checks": {}},
    {"collector": "m365", "version": 99, "checks": {}},
    {"version": 1, "checks": {}},
])
def test_unknown_collector_or_version_is_400(client, payload):
    r = post(client, json.dumps(payload, indent=2).encode())
    assert r.status_code == 400
    assert len(client.get("/api/assessments/2/evidence").json()) == 3  # nothing stored (demo has 3)


def test_nul_is_415(client):
    assert post(client, WINDOWS[:20] + b"\x00" + WINDOWS[20:]).status_code == 415


def test_invalid_utf8_is_415(client):
    assert post(client, b"\xff\xfe\xfa").status_code == 415


def test_long_line_is_413(client):
    minified = json.dumps({"collector": "windows", "pad": "x" * 70000}).encode()
    r = post(client, minified)
    assert r.status_code == 413 and "Line 1" in r.text and "65536" in r.text


def test_oversize_is_413(client, monkeypatch):
    monkeypatch.setenv("CMMCREADY_MAX_UPLOAD_MB", "0")
    assert post(client, b"{}").status_code == 413


def test_unknown_assessment_is_404(client):
    assert post(client, WINDOWS, assessment=999).status_code == 404


def test_line_between_old_and_new_limit_is_accepted_as_line_length(client):
    # 9000 characters on one line is fine for evidence JSON now; it fails later as "not a collector".
    padded = json.dumps({"collector": "linux", "pad": "x" * 9000}).encode()
    assert post(client, padded).status_code == 400


def test_declared_content_length_over_cap_is_413_before_reading(client, monkeypatch):
    monkeypatch.setenv("CMMCREADY_MAX_UPLOAD_MB", "1")
    big = b"x" * (1024 * 1024 + 70_000)
    r = client.post("/api/assessments/2/evidence", files={"file": ("e.json", big)})
    assert r.status_code == 413 and "too large" in r.text.lower()


def test_chunked_body_over_cap_is_413_without_content_length(client, monkeypatch):
    monkeypatch.setenv("CMMCREADY_MAX_UPLOAD_MB", "1")

    def chunks():
        yield (b'--zz\r\nContent-Disposition: form-data; name="file"; filename="e.json"\r\n'
               b"Content-Type: application/json\r\n\r\n")
        for _ in range(40):
            yield b"x" * 65536  # 2.5 MB in total, no Content-Length

    r = client.post("/api/assessments/2/evidence", content=chunks(),
                    headers={"Content-Type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413 and "too large" in r.text.lower()
    assert "content-length" not in r.request.headers


def test_chunked_body_under_cap_still_works(client):
    def chunks():
        yield b'{"a": '
        yield b"1}"

    r = client.post("/api/assessments/2/organization", content=chunks(),
                    headers={"Content-Type": "application/json"})
    assert r.status_code != 413
