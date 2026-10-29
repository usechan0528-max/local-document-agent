import re
import shutil
from collections import defaultdict
from difflib import SequenceMatcher
import pytesseract


def languages(requested):
    if not shutil.which("tesseract"):
        raise RuntimeError("Tesseract가 없습니다. README의 설치 단계를 실행하세요.")
    installed = set(pytesseract.get_languages(config=""))
    missing = set(requested.split("+")) - installed
    if missing:
        raise RuntimeError(f"OCR 언어 데이터가 없습니다: {', '.join(sorted(missing))}")


def recognize(image, lang, psm=3):
    data = pytesseract.image_to_data(image, lang=lang, config=f"--psm {psm}",
                                    output_type=pytesseract.Output.DICT, timeout=60)
    groups = defaultdict(list)
    scores = []
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        confidence = float(data["conf"][i])
        if not text or confidence < 0:
            continue
        x, y, w, h = (int(data[k][i]) for k in ("left", "top", "width", "height"))
        groups[(data["block_num"][i], data["par_num"][i], data["line_num"][i])].append(
            (text, [x, y, x+w, y+h], confidence/100))
        scores.extend([confidence/100] * len(text))
    elements = []
    for words in groups.values():
        box = [min(w[1][0] for w in words), min(w[1][1] for w in words),
               max(w[1][2] for w in words), max(w[1][3] for w in words)]
        elements.append({"type": "text", "text": " ".join(w[0] for w in words),
                         "bbox": box, "confidence": round(sum(w[2] for w in words)/len(words), 3),
                         "source": "tesseract", "coordinate_space": "selected_image_pixels"})
    text = "\n".join(e["text"] for e in elements)
    return {"text": text, "elements": elements,
            "confidence": sum(scores)/len(scores) if scores else 0.0}


def agreement(a, b):
    a, b = (re.sub(r"\s+", "", s).casefold() for s in (a, b))
    if not a or not b:
        return None
    # Bound quadratic matching cost on very large pages.
    return round(SequenceMatcher(None, a[:20000], b[:20000], autojunk=True).ratio(), 3)


def select_candidate(results):
    baseline = results[0]
    selected = baseline
    for result in results[1:]:
        # Avoid choosing a cleaner-looking fragment that lost most of the text.
        enough_text = len(result["text"].strip()) >= .8 * len(baseline["text"].strip())
        if enough_text and result["confidence"] > selected["confidence"] + .02:
            selected = result
    return selected
