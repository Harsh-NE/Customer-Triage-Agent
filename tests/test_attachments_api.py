"""Screenshot attachments through the HTTP API: upload + OCR preview, a message that carries it, access control, and the logged event.
Offline: the OCR reader is a fake that returns the text of the sample screenshot."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_api import RATE_LIMIT, last, login, make_settings, offline_factory
from triage.api.app import create_app
from triage.ocr import OcrResult

FIXTURE = Path(__file__).parent / "fixtures" / "screenshot_oomkilled.png"
OOM_TEXT = "ERROR: OOMKilled - container exceeded memory limit. Exit code 137.\nDocker inspect shows \"OOMKilled\": true"
RATE_LIMIT_TEXT = "ERROR: You have reached your pull rate limit. HTTP 429 from Docker Hub"


def fake_reader(text=OOM_TEXT, conf=0.92):
    def read(data: bytes) -> OcrResult:
        return OcrResult(ok=bool(text), text=text, confidence=conf, engine="fake", reason=None if text else "no_text", latency_ms=12.5,
                         error_messages=[text.splitlines()[0]] if text else [], exit_codes=[])
    return read


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), offline_factory(), ocr_reader=fake_reader())) as c:
        yield c


def upload(client, h, data=None, name="shot.png", ctype="image/png"):
    return client.post("/api/attachments", files={"file": (name, data if data is not None else FIXTURE.read_bytes(), ctype)}, headers=h)


def test_upload_returns_what_was_read_for_the_customer_to_check(client):
    h = login(client, "alice")
    r = upload(client, h)
    assert r.status_code == 201
    body = r.json()
    assert body["id"].endswith(".png") and len(body["id"]) == 16 + 4
    assert body["ocr"]["ok"] and body["ocr"]["text"].startswith("ERROR: OOMKilled") and body["ocr"]["confidence"] == 0.92
    assert upload(client, h).json()["id"] == body["id"]                    # same image, same id (content-derived)


def test_upload_rejects_non_images_and_engineers_and_anonymous(client):
    h = login(client, "alice")
    assert upload(client, h, b"MZ\x90 definitely not a png", "evil.png").status_code == 422
    assert upload(client, h, b"").status_code == 422
    assert client.post("/api/attachments", files={"file": ("a.png", FIXTURE.read_bytes(), "image/png")}).status_code == 401
    assert upload(client, login(client, "enid", "engineer")).status_code == 403


def test_message_with_a_screenshot_reaches_the_agents_as_words_plus_an_excerpt(client):
    h = login(client, "alice")
    att = upload(client, h).json()
    view = client.post("/api/conversations", json={"message": "my container keeps dying", "attachment_id": att["id"]}, headers=h).json()
    first = view["messages"][0]
    assert first["role"] == "customer" and first["content"] == "my container keeps dying"          # the chat shows what they typed
    assert first["payload"]["attachment"]["id"] == att["id"] and first["payload"]["attachment"]["text"].startswith("ERROR: OOMKilled")
    assert view["title"] == "my container keeps dying"


def test_screenshot_alone_is_enough_and_the_customers_edit_wins(client):
    h = login(client, "alice")
    att = upload(client, h).json()
    view = client.post("/api/conversations", json={"message": "", "attachment_id": att["id"], "screenshot_text": RATE_LIMIT_TEXT}, headers=h).json()
    first = view["messages"][0]
    assert first["content"] == "(screenshot attached)"
    assert first["payload"]["attachment"]["edited"] and "429" in first["payload"]["attachment"]["text"]
    assert "rate limit" in view["title"].lower()                          # titled from the screenshot's error line
    assert last(view)["kind"] == "fix"                                    # the agent worked from the screenshot's text


def test_nothing_to_send_is_refused(client):
    h = login(client, "alice")
    assert client.post("/api/conversations", json={"message": ""}, headers=h).status_code == 422
    att = upload(client, h).json()
    assert client.post("/api/conversations", json={"message": "", "attachment_id": att["id"], "screenshot_text": ""}, headers=h).status_code == 422


def test_secrets_in_the_confirmed_text_are_masked_before_anything_is_stored(client):
    h = login(client, "alice")
    att = upload(client, h).json()
    view = client.post("/api/conversations", json={"message": RATE_LIMIT, "attachment_id": att["id"],
                                                   "screenshot_text": "docker login failed password: hunter2 ghp_abcdefghijklmnop1234"}, headers=h).json()
    stored = view["messages"][0]["payload"]["attachment"]["text"]
    assert "hunter2" not in stored and "ghp_" not in stored


def test_a_reply_can_carry_a_screenshot_too(client):
    h = login(client, "alice")
    view = client.post("/api/conversations", json={"message": RATE_LIMIT}, headers=h).json()
    att = upload(client, h).json()
    view = client.post(f"/api/conversations/{view['id']}/messages",
                       json={"text": "still failing, here is the screen", "attachment_id": att["id"]}, headers=h).json()
    mine = [m for m in view["messages"] if m["role"] == "customer"]
    assert mine[-1]["payload"]["attachment"]["id"] == att["id"]


def test_ids_that_are_not_yours_or_not_ids_are_not_found(client):
    h = login(client, "alice")
    bob = login(client, "bob")
    att = upload(client, h).json()
    assert client.post("/api/conversations", json={"message": RATE_LIMIT, "attachment_id": att["id"]}, headers=bob).status_code == 404   # alice's file
    for bad in ("../../app.db", "..%2f..%2fapp.db", "abc.png", "0123456789abcdef.exe"):
        assert client.post("/api/conversations", json={"message": RATE_LIMIT, "attachment_id": bad}, headers=h).status_code == 404


def test_image_is_served_to_the_owner_and_engineers_only_through_a_message_that_carries_it(client):
    h, bob, enid = login(client, "alice"), login(client, "bob"), login(client, "enid", "engineer")
    att = upload(client, h).json()
    unused = upload(client, h, _other_png()).json()
    cid = client.post("/api/conversations", json={"message": RATE_LIMIT, "attachment_id": att["id"]}, headers=h).json()["id"]
    url = f"/api/conversations/{cid}/attachments/{att['id']}"
    ok = client.get(url, headers=h)
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png" and ok.content == FIXTURE.read_bytes()
    assert client.get(url, headers=enid).status_code == 200                                  # an engineer reading the case
    assert client.get(url, headers=bob).status_code == 404                                   # another customer
    assert client.get(url).status_code == 401
    assert client.get(f"/api/conversations/{cid}/attachments/{unused['id']}", headers=h).status_code == 404    # uploaded but never sent


def test_the_ocr_step_is_logged_with_latency_and_confidence_but_not_the_text(client):
    h, enid = login(client, "alice"), login(client, "enid", "engineer")
    att = upload(client, h).json()
    cid = client.post("/api/conversations", json={"message": "dies", "attachment_id": att["id"]}, headers=h).json()["id"]
    detail = client.get(f"/api/cases/{cid}", headers=enid).json()
    steps = [a for a in detail["activity"] if a["event"] == "ocr"]
    assert len(steps) == 1 and steps[0]["latency_ms"] == 12.5 and "fake" in steps[0]["label"] and "0.92" in steps[0]["label"]
    assert "OOMKilled" not in str(steps)                                       # the text itself stays out of the event log

def test_agents_receive_the_customers_words_then_the_screenshots_error_lines_unlabelled():
    from triage.api.service import compose
    att = {"text": "docker run\nERROR: OOMKilled - Exit code 137\nsome noise\n\"OOMKilled\": true"}
    shown, agent, title = compose("my container dies", att)
    assert shown == "my container dies" and agent == "my container dies\n\ndocker run\nERROR: OOMKilled - Exit code 137\n\"OOMKilled\": true"   # the command, then both error-looking lines; "some noise" is left out
    assert compose("", att)[0] == "(screenshot attached)" and compose("", att)[1].startswith("docker run\nERROR: OOMKilled")
    assert compose("just words", None) == ("just words", "just words", "just words")


def _other_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "black").save(buf, format="PNG")
    return buf.getvalue()
