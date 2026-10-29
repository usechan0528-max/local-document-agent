from PIL import Image, ImageDraw
from docagent.imaging import document_regions
from docagent.regions import analyze_regions


def scene():
    im = Image.new('RGB', (1000, 1400), '#965920')
    d = ImageDraw.Draw(im)
    d.polygon([(200,200),(700,150),(720,700),(220,800)], fill='white')
    d.polygon([(230,900),(720,830),(720,1250),(240,1350)], fill='white')
    return im


def test_separate_papers_and_deduplicate_thresholds():
    regions = document_regions(scene())
    assert len(regions) == 2
    assert regions[0]['bbox'][1] < regions[1]['bbox'][1]
    assert regions[0]['bbox'][0] < 200 and regions[0]['bbox'][2] > 720
    assert all(0 <= r['bbox'][0] < r['bbox'][2] <= 1000 for r in regions)


def test_full_white_page_is_not_a_scene_crop():
    assert document_regions(Image.new('RGB', (1000, 1400), 'white')) == []


def test_region_coordinates_map_back_and_low_quality_excluded(tmp_path, monkeypatch):
    import docagent.regions as module
    (tmp_path/'assets').mkdir()
    monkeypatch.setattr(module, 'document_regions', lambda im: [
        {'id':'region-1', 'bbox':[100,200,2100,3200], 'touches_image_edge':False}])
    def fake(im, lang, psm):
        return {'text':'This is enough recognized text', 'confidence':.8,
                'elements':[{'text':'This', 'bbox':[60,60,120,120], 'type':'text'}]}
    monkeypatch.setattr(module, 'recognize', fake)
    extraction, aggregate = analyze_regions(Image.new('RGB',(2400,3500),'white'),tmp_path,'page','eng')
    assert aggregate['elements'][0]['bbox'] == [200,300,300,400]
    assert aggregate['elements'][0]['coordinate_space'] == 'original_image_pixels'
    assert (tmp_path/extraction['regions'][0]['image']).is_file()
    monkeypatch.setattr(module, 'recognize', lambda *a, **kw: {'text':'nonsense '*10, 'confidence':.51,'elements':[]})
    extraction, aggregate = analyze_regions(Image.new('RGB',(2400,3500),'white'),tmp_path,'bad','eng')
    assert aggregate is None
    assert extraction['regions'][0]['text']
