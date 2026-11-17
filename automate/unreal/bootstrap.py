"""사용자 Unreal 프로젝트에서 루트 자동화 런타임을 시작한다."""
import json
import os
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "automate/runtime/unreal/python"
STATE = ROOT / "automate/workspace/unreal"


def start_server(project):
    if os.environ.get("FD_UNREAL_BATCH_WORKER") == "1":
        return None
    project = Path(project).resolve()
    allowed = ROOT / "Tools/unreal_pipeline/workspace"
    if not project.is_relative_to(allowed) or not (project / "MechAnimationLab.uproject").is_file():
        raise ValueError("메카 작업본의 Unreal 프로젝트만 시작한다.")
    if not RUNTIME.is_dir():
        raise FileNotFoundError("Unreal 자동화 런타임이 없다: " + str(RUNTIME))
    sys.path.insert(0, str(RUNTIME))
    os.environ["DCC_MCP_DISABLE_UPDATE_CHECK"] = "true"
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        import dcc_mcp_unreal
        import unreal
        server = dcc_mcp_unreal.start_server(server_name="FerrialDrive Animation Lab",
            extra_skill_paths=[str(ROOT / "Tools/unreal_pipeline/skills")])
        result = {"pid": os.getpid(), "mcp_url": server.mcp_url(),
                  "engine": unreal.SystemLibrary.get_engine_version(),
                  "adapter": dcc_mcp_unreal.__version__}
        payload = json.dumps(result, indent=2)
        (STATE / "mcp_ready.json").write_text(payload, encoding="utf-8")
        # 기존 사용자 작업본 조회와 호환되는 생성 메타데이터다.
        (project.parent / "mcp_ready.json").write_text(payload, encoding="utf-8")
        unreal.log("메카 자동화 MCP 준비: " + result["mcp_url"])
        return server
    except Exception:
        (STATE / "mcp_start_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
