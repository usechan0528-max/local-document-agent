import argparse
import sys
from pathlib import Path
from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description="PDF/PNG/JPG를 Markdown과 JSON으로 변환")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lang", default="kor+eng")
    parser.add_argument("--vision-model", help="이미 설치된 로컬 Ollama 비전 모델 이름")
    args = parser.parse_args()
    try:
        result = run(args.source, args.output, args.lang, args.vision_model,
                     lambda n, total: print(f"페이지 {n}/{total}", flush=True))
    except Exception as exc:
        print(f"처리 실패: {exc}", file=sys.stderr)
        return 1
    print(f"{result['status']}: {args.output.resolve()}")
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
