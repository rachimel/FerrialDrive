"""에셋 도구의 AI·자동화 진입점. JSON 요청 1개를 실행하고 JSON 결과 1개를 출력한다."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--request", help="UTF-8 JSON 파일. -는 표준 입력. 생략하면 지원 작업 조회")
    operation = None
    try:
        args = parser.parse_args(argv)
        if args.request == "-":
            content = sys.stdin.buffer.read().decode("utf-8-sig") if hasattr(sys.stdin, "buffer") else sys.stdin.read()
            request, base = json.loads(content), Path.cwd()
        elif args.request:
            path = Path(args.request).resolve()
            request, base = json.loads(path.read_text(encoding="utf-8-sig")), path.parent
        else:
            request, base = {"version": 1, "operation": "describe"}, Path.cwd()
        if isinstance(request, dict) and isinstance(request.get("operation"), str):
            operation = request["operation"]
        from Tools.asset_loader.automation import execute
        with redirect_stdout(sys.stderr):
            result = execute(request, base_dir=base)
        response = {"version": 1, "ok": True, "operation": operation, "result": result}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError,
            StopIteration, RuntimeError, ImportError) as error:
        code = ("timeout" if isinstance(error, TimeoutError) else
                "not_found" if isinstance(error, FileNotFoundError) else
                "already_exists" if isinstance(error, FileExistsError) else
                "dependency_error" if isinstance(error, ImportError) else
                "io_error" if isinstance(error, OSError) else
                "operation_failed" if isinstance(error, RuntimeError) else "invalid_request")
        response = {"version": 1, "ok": False, "operation": operation,
                    "error": {"code": code, "message": str(error) or type(error).__name__}}
    except KeyboardInterrupt:
        response = {"version": 1, "ok": False, "operation": operation,
                    "error": {"code": "cancelled", "message": "요청이 중단되었다."}}
    # Windows 기본 코드 페이지와 무관한 UTF-8 JSON. 라이브러리 진단은 stderr로 분리한다.
    payload = json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n"
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(payload.encode("utf-8"))
    else:
        sys.stdout.write(payload)
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
