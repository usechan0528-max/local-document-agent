import io
import json
import tempfile
import zipfile
from pathlib import Path
import streamlit as st
from docagent.pipeline import run, markdown, UPLOAD_EXTENSIONS

st.set_page_config(page_title="문서 전처리 에이전트", page_icon="📄", layout="wide")
st.title("문서를 AI가 읽기 좋은 형태로")
st.write("PDF·사진(HEIC·JPEG·PNG·WebP 등)을 업로드하면 원문 근거를 보존한 Markdown과 JSON을 만듭니다.")
st.caption("로컬 처리 · 최대 25MB / 30페이지 / 이미지 6천만 픽셀 · 점수는 정확도 확률이 아닙니다.")
with st.sidebar:
    st.header("처리 설정")
    lang = st.selectbox("OCR 언어", ["kor+eng", "eng", "kor"])
    use_vision = st.checkbox("로컬 Ollama 비전 분석 사용")
    model = st.text_input("설치된 비전 모델 이름", placeholder="Ollama에 설치된 모델 이름") if use_vision else ""
    st.caption("비전 분석은 127.0.0.1:11434로만 연결합니다. 미검증 설명을 별도 저장합니다.")
file = st.file_uploader("문서 선택", type=UPLOAD_EXTENSIONS)
if st.button("문서 분석", type="primary", disabled=file is None):
    st.session_state.pop("result", None)
    if use_vision and not model.strip():
        st.error("설치된 비전 모델 이름을 입력하세요.")
    else:
        progress = st.progress(0, text="파일 확인 중")
        try:
            with tempfile.TemporaryDirectory(prefix="docagent-") as temp:
                root = Path(temp)
                # Never use an uploaded path as a filesystem destination.
                source = root / ("input" + Path(file.name).suffix.lower())
                source.write_bytes(file.getvalue())
                output = root / "result"
                result = run(source, output, lang, model.strip() if use_vision else None,
                             lambda n, t: progress.progress(n/t, text=f"페이지 {n}/{t} 완료"))
                # Retain original display name as data only.
                result["uploaded_filename"] = file.name
                result["filename"] = file.name
                (output / "document.md").write_text(markdown(result), encoding="utf-8")
                (output / "document.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                    for path in output.rglob("*"):
                        if path.is_file():
                            z.write(path, path.relative_to(output).as_posix())
                st.session_state.result = {"data": result, "zip": archive.getvalue(),
                    "md": (output / "document.md").read_text(encoding="utf-8"),
                    "json": (output / "document.json").read_bytes(),
                    "images": {p.relative_to(output).as_posix(): p.read_bytes() for p in (output / "assets").glob("*.png")}}
        except Exception as exc:
            st.error(str(exc))
        finally:
            progress.empty()
if "result" in st.session_state:
    saved = st.session_state.result
    data = saved["data"]
    status_label = {"completed": "처리 완료", "partial": "일부 페이지 처리 실패", "failed": "처리 실패"}[data["status"]]
    st.subheader(f"결과: {status_label}")
    st.caption(f"파일: {data.get('uploaded_filename', data['filename'])}")
    c1, c2, c3 = st.columns(3)
    c1.metric("페이지", len(data["pages"]))
    c2.metric("검토 점수 (휴리스틱)", f"{data['confidence']:.2f}")
    c3.metric("원본 확인 필요", len(data["pages"]))
    if any(p["status"] == "needs_review" for p in data["pages"]):
        st.warning("인식 불량·재분석 필요: 결과가 생성됐어도 내용을 정확히 읽었다는 뜻은 아닙니다.")
    a, b, c = st.columns(3)
    a.download_button("전체 결과 ZIP", saved["zip"], "document-result.zip", "application/zip")
    b.download_button("Markdown", saved["md"], "document.md", "text/markdown")
    c.download_button("JSON", saved["json"], "document.json", "application/json")
    st.caption("Markdown의 원본 이미지 링크를 사용하려면 전체 ZIP을 내려받아 압축을 풀어주세요.")
    inspect, md, js = st.tabs(["원본 대조", "Markdown", "JSON"])
    with inspect:
        page = st.selectbox("페이지", data["pages"], format_func=lambda p: str(p["number"]))
        if page["status"] == "error":
            st.error(page["error"])
        else:
            left, right = st.columns(2)
            left.image(saved["images"][page["original_image"]], caption="원본 페이지")
            right.image(saved["images"][page["selected_image"]], caption="영역 OCR 좌표 기준 원본" if page["preprocessing"]["selected"] == "regions" else "선택된 OCR 입력")
            extraction = page.get("region_extraction", {})
            if extraction.get("regions"):
                st.subheader("자동 추출한 문서 영역")
                st.caption("사각형은 여백을 포함한 잘라내기 범위입니다. 누락된 영역이나 잘린 글자가 없는지 확인하세요.")
                st.image(saved["images"][extraction["overlay_image"]], caption="원본 위의 영역 위치")
                for region in extraction["regions"]:
                    with st.expander(f"{region['id']} · {'결과에 반영' if region['selected'] else '참고 후보'}", expanded=True):
                        st.image(saved["images"][region["image"]])
                        st.text(region.get("text", "인식된 글자가 없습니다."))
                        if region["touches_image_edge"]:
                            st.warning("사진 가장자리에 걸친 영역으로, 촬영 시 내용이 잘렸을 수 있습니다.")
            st.write("OCR 입력 선택:", {"original": "원본", "adaptive": "보정본", "regions": "문서 영역별 OCR"}.get(page["preprocessing"]["selected"], "기타"))
            with st.expander("전처리 후보 비교 상세"):
                st.json(page["preprocessing"])
            for warning in page["validation"]["warnings"]:
                st.warning(warning)
            st.json(page["elements"], expanded=False)
    with md:
        st.code(saved["md"], language="markdown")
    with js:
        st.json(data, expanded=False)
