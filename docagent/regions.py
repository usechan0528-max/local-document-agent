"""Region OCR remains evidence alongside the full-page OCR."""
from PIL import ImageDraw
from .imaging import document_regions
from .ocr import recognize, select_candidate


def analyze_regions(image, out, prefix, lang):
    regions = document_regions(image)
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    accepted = []
    for region in regions:
        x0, y0, x1, y1 = region['bbox']
        crop = image.crop((x0, y0, x1, y1))
        crop.thumbnail((1800, 1800))
        path = f"assets/{prefix}-{region['id']}.png"
        crop.save(out / path)
        region.update(image=path, ocr_size=list(crop.size), attempts=[], selected=False)
        for psm in (3, 6):
            try:
                result = recognize(crop, lang, psm=psm)
                result['psm'] = psm
                region['attempts'].append(result)
            except Exception as exc:
                region.setdefault('errors', []).append(f"{type(exc).__name__}: {exc}")
        if region['attempts']:
            chosen = select_candidate(region['attempts'])
            region['chosen_psm'] = chosen['psm']
            region['confidence'] = round(chosen['confidence'], 3)
            region['text'] = chosen['text']
            region['usable'] = len(chosen['text'].strip()) >= 20 and chosen['confidence'] >= .65
            if region['usable']:
                sx, sy = (x1-x0)/crop.width, (y1-y0)/crop.height
                elements = []
                for e in chosen['elements']:
                    a, b, c, d = e['bbox']
                    elements.append({**e, 'bbox': [round(x0+a*sx), round(y0+b*sy),
                        round(x0+c*sx), round(y0+d*sy)], 'coordinate_space': 'original_image_pixels',
                        'source': 'tesseract_region', 'region_id': region['id']})
                accepted.append((region, chosen, elements))
        draw.rectangle((x0, y0, x1-1, y1-1), outline='#e94b35', width=max(3, image.width//400))
    overlay_path = f"assets/{prefix}-regions.png" if regions else None
    if regions:
        # Bound overlay size for UI; JSON coordinates still refer to full original.
        overlay.thumbnail((1800, 1800))
        overlay.save(out / overlay_path)
    aggregate = None
    if accepted:
        total = sum(len(item[1]['text']) for item in accepted)
        aggregate = {'name': 'regions', 'actions': ['paper_region_detection', 'crop', 'resize_max_1800'],
            'text': '\n\n'.join(item[1]['text'] for item in accepted),
            'confidence': sum(len(c['text'])*c['confidence'] for _, c, _ in accepted)/total,
            'elements': [e for _, _, es in accepted for e in es]}
    return {'regions': regions, 'overlay_image': overlay_path,
            'note': '밝은 종이 영역 후보입니다. 모든 문서 영역의 탐지나 내용의 완전성을 보장하지 않습니다.'}, aggregate
