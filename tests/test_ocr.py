"""triage/ocr.py: what is accepted, what comes back when no engine is installed, secrets masked, error lines found. Offline: the engines
are replaced by fakes (one test reads the sample screenshot for real, when Tesseract or rapidocr happens to be installed)."""

import io
from pathlib import Path

import pytest
from PIL import Image

from triage import ocr

FIXTURE = Path(__file__).parent / "fixtures" / "screenshot_oomkilled.png"
OOM = "ERROR: OOMKilled - container exceeded memory limit. Exit code 137. Docker inspect shows\n\"OOMKilled\": true"


def png(size=(40, 20), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def fake_engine(monkeypatch):
    """ocr.ENGINES -> one engine that returns what the test says."""
    def install(text="", conf=0.9, exc=None):
        def engine(img, lang):
            if exc:
                raise exc
            return text, conf
        monkeypatch.setattr(ocr, "ENGINES", {"fake": engine})
        monkeypatch.delenv("OCR_ENGINE", raising=False)
    return install


def test_validate_accepts_real_images_and_names_the_extension():
    _, ext = ocr.validate_image(FIXTURE.read_bytes())
    assert ext == "png"
    assert ocr.validate_image(png(fmt="JPEG"))[1] == "jpg"


@pytest.mark.parametrize("data,why", [pytest.param(b"", "empty", id="empty"), pytest.param(b"not an image at all", "not an image", id="text"),
                                      pytest.param(png(fmt="GIF"), "PNG, JPG", id="gif"),
                                      pytest.param(png(size=(ocr.MAX_SIDE + 1, 8)), "pixels", id="too-wide"),
                                      pytest.param(b"x" * (ocr.MAX_BYTES + 1), "larger", id="too-big")])
def test_validate_refuses_bad_files_with_a_customer_safe_message(data, why):
    with pytest.raises(ocr.OcrError) as e:
        ocr.validate_image(data)
    assert why.lower() in str(e.value).lower()


def test_format_is_judged_by_content_not_by_file_name():
    with pytest.raises(ocr.OcrError):
        ocr.validate_image(b"MZ\x90\x00" + b"\x00" * 100)         # an executable renamed to .png is still not an image


def test_secrets_are_masked_in_what_is_read(fake_engine):
    fake_engine("login failed password: hunter2 token=ghp_abcdefghijklmnop1234 mail me at a@b.com\nERROR: denied")
    r = ocr.read_screenshot(png())
    assert "hunter2" not in r.text and "ghp_" not in r.text and "a@b.com" not in r.text
    assert "<TOKEN>" in r.text or "<REDACTED>" in r.text


def test_docker_login_passwords_are_masked_but_port_mappings_are_not():
    assert "hunter2" not in ocr.redact("$ docker login -u demo -p hunter2")
    assert "hunter2" not in ocr.redact("docker login --password=hunter2 registry.example.com")
    assert "-p 8080:80" in ocr.redact("$ docker run -d -p 8080:80 nginx")


def test_result_carries_error_lines_exit_codes_and_confidence(fake_engine):
    fake_engine(OOM, conf=0.93)
    r = ocr.read_screenshot(png())
    assert r.ok and r.engine == "fake" and r.confidence == 0.93 and not r.low_confidence
    assert any("OOMKilled" in line for line in r.error_messages)
    assert r.exit_codes == ["exit code 137"]
    assert ocr.message_excerpt(r.text).startswith("ERROR: OOMKilled")


def test_excerpt_keeps_the_command_that_produced_the_error_and_drops_other_lines():
    text = ("$ docker pull nginx\nError response from daemon: toomanyrequests: You have reached your pull rate limit.\n"
            "You may increase the limit by authenticating and upgrading:\nhttps: //www.docker.com/increase-rate-limits")
    assert ocr.message_excerpt(text) == "$ docker pull nginx\nError response from daemon: toomanyrequests: You have reached your pull rate limit."
    no_error = "Docker Desktop - WSL 2 installation is incomplete\nPress Restart"
    assert ocr.message_excerpt(no_error) == "Docker Desktop - WSL 2 installation is incomplete Press Restart"       # no error line: the start of the text


def test_low_confidence_is_flagged(fake_engine):
    fake_engine("d0cker 3rror", conf=0.31)
    assert ocr.read_screenshot(png()).low_confidence


def test_no_engine_installed_is_an_answer_not_a_crash(monkeypatch):
    def missing(img, lang):
        raise ImportError("not installed")
    monkeypatch.setattr(ocr, "ENGINES", {"a": missing, "b": missing})
    r = ocr.read_screenshot(png())
    assert not r.ok and r.reason == "no_engine" and r.text == ""


def test_a_broken_engine_is_reported_and_the_next_one_is_tried(monkeypatch):
    def broken(img, lang):
        raise RuntimeError("boom")
    monkeypatch.setattr(ocr, "ENGINES", {"a": broken, "b": lambda img, lang: ("ERROR: x failed", 0.8)})
    r = ocr.read_screenshot(png())
    assert r.ok and r.engine == "b"
    monkeypatch.setattr(ocr, "ENGINES", {"a": broken})
    assert ocr.read_screenshot(png()).reason == "engine_error"


def test_blank_image_gives_no_text(fake_engine):
    fake_engine("   \n")
    r = ocr.read_screenshot(png())
    assert not r.ok and r.reason == "no_text"


def test_real_engine_reads_the_sample_screenshot_when_one_is_installed():
    r = ocr.read_screenshot(FIXTURE.read_bytes())
    if r.reason == "no_engine":
        pytest.skip("no OCR engine installed (Tesseract + pytesseract, or rapidocr-onnxruntime)")
    assert r.ok and "oomkilled" in r.text.lower().replace(" ", "")
