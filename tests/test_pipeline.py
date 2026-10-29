import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from docagent.imaging import rgb_image
from docagent.ocr import select_candidate, agreement
from docagent.pipeline import run, text_integrity
from docagent.vision import describe


def image_document():
    image = Image.new("RGB", (1400, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=42)
    for y, text in zip((100, 200, 300, 400),
        ("DOCUMENT TEST 2026", "Revenue 1200 USD", "Cost 400 USD", "Total 800 USD")):
        draw.text((100, y), text, fill="black", font=font)
    return image


@pytest.fixture
def pdf_file(tmp_path):
    path = tmp_path / "sample.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(600, 800))
    pdf.setFont("Helvetica", 24)
    pdf.drawString(60, 730, "Financial sample report")
    pdf.setFont("Helvetica", 14)
    pdf.drawString(60, 685, "Revenue is 1200 USD and cost is 400 USD.")
    for y in (500, 540, 580):
        pdf.line(60, y, 360, y)
    for x in (60, 210, 360):
        pdf.line(x, 500, x, 580)
    pdf.drawString(70, 550, "Item")
    pdf.drawString(220, 550, "Value")
    pdf.drawString(70, 510, "Total")
    pdf.drawString(220, 510, "800")
    pdf.save()
    return path


requires_ocr = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract required")


@requires_ocr
def test_pdf_table_and_provenance(pdf_file, tmp_path):
    out = tmp_path / "out"
    result = run(pdf_file, out, "eng")
    assert result["status"] == "completed"
    page = result["pages"][0]
    assert page["method"] == "native_pdf"
    assert "1200" in page["evidence"]["native_text"]
    tables = [e for e in page["elements"] if e["type"] == "table"]
    assert tables and tables[0]["rows"] == [["Item", "Value"], ["Total", "800"]]
    assert (out / page["original_image"]).exists()
    assert (out / "source.pdf").read_bytes() == pdf_file.read_bytes()
    assert "열 1" in (out / "document.md").read_text()
    assert json.loads((out / "document.json").read_text())["sha256"] == result["sha256"]
    assert page["validation"]["semantic_verified"] is False


@requires_ocr
@pytest.mark.parametrize("suffix", ["png", "jpg"])
def test_image_ocr(tmp_path, suffix):
    source = tmp_path / f"image.{suffix}"
    image_document().save(source)
    result = run(source, tmp_path / "result", "eng")
    page = result["pages"][0]
    assert page["method"] == "ocr"
    text = " ".join(e["text"] for e in page["elements"])
    assert "1200" in text and "800" in text
    assert len(page["preprocessing"]["candidates"]) == 2
    assert 0 <= result["confidence"] <= 1


@requires_ocr
def test_scan_pdf(tmp_path):
    from reportlab.lib.utils import ImageReader
    source = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(700, 350))
    pdf.drawImage(ImageReader(image_document()), 0, 0, 700, 350)
    pdf.save()
    result = run(source, tmp_path / "out", "eng")
    assert result["pages"][0]["method"] == "ocr"
    assert "1200" in " ".join(e["text"] for e in result["pages"][0]["elements"])


@requires_ocr
def test_blank_not_confident(tmp_path):
    source = tmp_path / "blank.png"
    Image.new("RGB", (500, 500), "white").save(source)
    result = run(source, tmp_path / "out", "eng")
    assert result["confidence"] == 0
    assert result["pages"][0]["status"] == "needs_review"


def test_reject_text_loss():
    original = {"text": "A long paragraph about revenue 1200", "confidence": .70}
    shortened = {"text": "1200", "confidence": .99}
    assert select_candidate([original, shortened]) is original


def test_transparency_on_white():
    image = rgb_image(Image.new("RGBA", (20, 20), (0, 0, 0, 0)))
    assert image.getpixel((0, 0)) == (255, 255, 255)


def test_integrity_and_empty_agreement():
    assert text_integrity("\ufffd" * 10) == 0
    assert agreement("", "") is None


def test_invalid_format(tmp_path):
    source = tmp_path / "x.exe"
    source.write_text("hello")
    with pytest.raises(ValueError, match="지원"):
        run(source, tmp_path / "out", "eng")


@requires_ocr
def test_disguised_pdf(tmp_path):
    source = tmp_path / "x.pdf"
    source.write_text("not pdf")
    with pytest.raises(ValueError, match="일치"):
        run(source, tmp_path / "out", "eng")


def test_existing_output_not_overwritten(tmp_path):
    source = tmp_path / "x.png"
    image_document().save(source)
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="비어"):
        run(source, out, "eng")
    assert marker.read_text() == "keep"


def test_missing_ocr(tmp_path, monkeypatch):
    source = tmp_path / "x.png"
    image_document().save(source)
    monkeypatch.setattr("docagent.ocr.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="Tesseract"):
        run(source, tmp_path / "out", "eng")


def test_vision_schema_rejection(monkeypatch):
    class Response(io.BytesIO):
        pass
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw:
                        Response(json.dumps({"response": '{"figures": "bad"}'}).encode()))
    with pytest.raises(ValueError, match="스키마"):
        describe(image_document(), "test-model")


@requires_ocr
def test_optional_vision_failure_preserves_ocr(tmp_path, monkeypatch):
    source = tmp_path / "x.png"
    image_document().save(source)
    def fail(*args):
        raise ConnectionError("offline")
    monkeypatch.setattr("docagent.pipeline.describe", fail)
    result = run(source, tmp_path / "out", "eng", "missing-model")
    page = result["pages"][0]
    assert page["vision"]["status"] == "failed"
    assert page["elements"]


def test_ui_starts():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run()
    assert not app.exception
    assert app.button[0].disabled


@requires_ocr
def test_korean_sample(tmp_path):
    import pytesseract
    if 'kor' not in pytesseract.get_languages():
        pytest.skip('Korean language data required')
    source = Path(__file__).parents[1] / 'examples' / 'korean-sample.png'
    result = run(source, tmp_path / 'korean', 'kor+eng')
    text = ' '.join(e['text'] for e in result['pages'][0]['elements'])
    assert '매출' in text and '1200' in text and '800' in text


@requires_ocr
def test_page_failure_does_not_hide_other_pages(tmp_path, monkeypatch):
    import docagent.pipeline as pipeline
    source = tmp_path / 'two.pdf'
    pdf = canvas.Canvas(str(source))
    for i in range(2):
        pdf.drawString(70, 700, 'A sufficiently long document for native text extraction')
        pdf.showPage()
    pdf.save()
    original = pipeline.process_page
    def injected(image, page, number, *args):
        if number == 1:
            raise RuntimeError('simulated page failure')
        return original(image, page, number, *args)
    monkeypatch.setattr(pipeline, 'process_page', injected)
    result = run(source, tmp_path / 'out', 'eng')
    assert result['status'] == 'partial'
    assert result['pages'][0]['status'] == 'error'
    assert result['pages'][1]['status'] == 'ok'
    assert '처리 실패' in (tmp_path / 'out' / 'document.md').read_text()


@requires_ocr
def test_mixed_pdf_preserves_image_text(tmp_path):
    from reportlab.lib.utils import ImageReader
    source = tmp_path / 'mixed.pdf'
    pdf = canvas.Canvas(str(source), pagesize=(700, 600))
    pdf.drawString(50, 550, 'Native heading with enough characters for routing')
    pdf.drawImage(ImageReader(image_document()), 0, 0, 700, 350)
    pdf.save()
    result = run(source, tmp_path / 'out', 'eng')
    page = result['pages'][0]
    assert page['document_type'] == 'mixed_pdf'
    assert '1200' in page['evidence']['ocr_candidates'][0]['text']
    assert '1200' in (tmp_path / 'out' / 'document.md').read_text()


@requires_ocr
def test_all_ocr_attempts_fail(tmp_path, monkeypatch):
    source = tmp_path / 'x.png'
    image_document().save(source)
    def fail(*args):
        raise RuntimeError('simulated OCR timeout')
    monkeypatch.setattr('docagent.pipeline.recognize', fail)
    result = run(source, tmp_path / 'out', 'eng')
    assert result['status'] == 'failed'
    assert result['confidence'] == 0
    assert 'OCR' in result['pages'][0]['error']


@requires_ocr
@pytest.mark.parametrize('fmt,suffix', [('WEBP', 'jpg'), ('HEIF', 'heic'), ('HEIF', 'jpg'), ('MPO', 'jpg')])
def test_gallery_formats_and_misleading_extension(tmp_path, fmt, suffix):
    source = tmp_path / f'gallery.{suffix}'
    image = image_document()
    options = {'save_all': True, 'append_images': [image.copy()]} if fmt == 'MPO' else {}
    image.save(source, format=fmt, **options)
    result = run(source, tmp_path / 'out', 'eng')
    assert result['status'] == 'completed'
    assert result['input_image']['detected_format'] == fmt
    assert '1200' in ' '.join(e['text'] for e in result['pages'][0]['elements'])
    assert (tmp_path / 'out' / result['source']).read_bytes() == source.read_bytes()
    if fmt == 'MPO':
        assert result['input_image']['frame_count'] == 2
        assert any('첫 프레임' in w for w in result['pages'][0]['validation']['warnings'])
