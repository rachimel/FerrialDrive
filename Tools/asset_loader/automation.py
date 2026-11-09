"""화면 없이 에셋 도구의 공통 작업을 호출하는 JSON API. import 시 작업을 시작하지 않는다."""

from contextlib import redirect_stdout
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

from ferrial_drive.assets import AssetCatalog, AssetDefinition, detect_kind
from ferrial_drive.assets.catalog import read_document
from .assembly import SpriteAssembly
from .library import DEFAULT_CATALOG, ROOT, store_asset
from .mech_export import build_mech, copy_mech, import_mech
from .mech_plan import (DIRECTIONS, EVENTS, MOTIONS, default_plan, load_plan, plan_path,
                        save_plan, validate_plan)
from .mech_presets import apply_all_directions, apply_mapping, apply_order_preset
from .part_model import add_part, add_state, remove_part, remove_state


API_VERSION = 1
# 필수 필드는 '?' 없이 표기한다. describe와 요청 검증이 같은 정의를 사용한다.
OPERATIONS = {
    "describe": {"summary": "지원 작업·필드·편집 예제 조회", "fields": {}},
    "catalog.list": {"summary": "카탈로그 목록 조회", "fields": {"catalog?": "path"}},
    "asset.inspect": {"summary": "메타데이터·실제 이미지 크기·클립 검증 및 조회",
                      "fields": {"source": "path", "kind?": "string", "include_frames?": "boolean"}},
    "catalog.register": {"summary": "검증 후 ID 등록. 기본 카탈로그는 필요한 파일을 복사",
                         "fields": {"source": "path", "asset_id": "string", "catalog?": "path", "kind?": "string"}},
    "sprite.assemble": {"summary": "프레임 순서·FPS·피봇 편집 후 새 폴더에 저장",
                        "fields": {"source": "path", "asset_id": "string", "output": "path", "edits": "array"}},
    "map.import": {"summary": "맵 번들과 실제 이미지를 검증하여 편집 데이터 조회. 선택 output에 복사",
                   "fields": {"source": "path", "output?": "path"}},
    "map.export": {"summary": "맵 원본 또는 data와 배경·바닥·합성 결과를 새 번들로 출력",
                   "fields": {"source?": "path", "data?": "any", "output": "path"}},
    "plan.create": {"summary": "GUI와 같은 메카 작업본 생성. 기존 파일은 거절",
                    "fields": {"source": "path", "asset_id": "string", "output?": "path", "preset?": "string"}},
    "plan.read": {"summary": "GUI 작업본 전체 조회", "fields": {"plan": "path"}},
    "plan.update": {"summary": "파츠·상태·순서·필드 편집을 검증 후 한 번에 저장",
                    "fields": {"plan": "path", "edits": "array", "output?": "path"}},
    "plan.validate": {"summary": "작업본 구조 검증. check_sheets로 내보내기 정합도 확인",
                      "fields": {"plan": "path", "check_sheets?": "boolean"}},
    "plan.export": {"summary": "색상·마스크·상태 시트를 분리한 메카 번들 출력",
                    "fields": {"plan": "path", "output": "path"}},
    "render.run": {"summary": "기존 Blender 백그라운드 렌더·패킹 실행. 완료까지 대기",
                   "fields": {"config": "path", "source_blend?": "path", "blender?": "path",
                              "output_root?": "path", "sample?": "boolean", "timeout_seconds?": "number"}},
}
EDIT_FIELDS = {
    "set": {"path": "array", "value": "any"},
    "part.add": {"id": "string", "name": "string", "duplicate?": "string", "template?": "string"},
    "part.remove": {"id": "string"},
    "state.add": {"part": "string", "id": "string", "name": "string"},
    "state.remove": {"part": "string", "id": "string"},
    "order.preset": {"motion": "string", "direction": "string", "preset": "string", "frame?": "integer"},
    "order.copy_all": {"motion": "string", "direction": "string", "frame?": "integer"},
    "mapping.apply": {"preset": "string"},
}
SPRITE_FIELDS = {"source_clip": "string", "name": "string", "order": "array", "fps?": "number", "durations_ms?": "array",
                 "pivot?": "array|null", "all_directions?": "boolean"}


def describe():
    return {"api_version": API_VERSION, "operations": deepcopy(OPERATIONS),
            "plan_edits": deepcopy(EDIT_FIELDS), "sprite_edit_fields": deepcopy(SPRITE_FIELDS),
            "path_rules": {"request_paths": "JSON 요청 파일의 폴더 기준. stdin은 현재 폴더 기준",
                           "sheet_paths": "작업본 source의 상위 폴더 기준. GUI와 동일",
                           "default_plan": "GUI와 같은 asset_id/source별 workspace/mech_plans 경로"},
            "enums": {"directions": list(DIRECTIONS), "motions": dict(MOTIONS), "events": dict(EVENTS),
                      "mapping_presets": ["default", "mech", "npc"], "order_presets": ["front", "back", "directional"],
                      "part_templates": ["thrusters"]},
            "examples": {
                "inspect": {"version": 1, "operation": "asset.inspect", "source": "bundle.json"},
                "update": {"version": 1, "operation": "plan.update", "plan": "plan.json", "edits": [
                    {"action": "part.add", "id": "antenna", "name": "안테나"},
                    {"action": "set", "path": ["layers", "antenna", "objects"], "value": "Antenna"},
                    {"action": "order.preset", "motion": "equipped_idle", "direction": "s", "preset": "front"}]}},
            "limits": ["실행 중 GUI의 저장하지 않은 편집 내용은 읽지 않는다. 파일 저장/다시 불러오기로 교환한다.",
                       "plan.validate 기본은 구조만 검증한다. check_sheets=true가 분리 시트 정합을 검사한다.",
                       "Blender 메카 레이어별 렌더·게임 전투 연동은 이 진입점에서 새로 구현하지 않는다."]}


def check_fields(data, fields, *, discriminator):
    if not isinstance(data, dict):
        raise ValueError("요청과 편집 항목은 JSON 객체여야 한다.")
    allowed = {key.rstrip("?") for key in fields} | set(discriminator)
    unknown = set(data) - allowed
    if unknown:
        raise ValueError("알 수 없는 필드: " + ", ".join(sorted(unknown)))
    for key, kind in fields.items():
        name = key.rstrip("?")
        if name not in data:
            if key.endswith("?"):
                continue
            raise ValueError("필수 필드 누락: " + name)
        value = data[name]
        valid = (kind == "any" or kind == "array|null" and value is None
                 or kind in ("path", "string") and isinstance(value, str) and bool(value.strip())
                 or kind == "boolean" and type(value) is bool
                 or kind == "integer" and type(value) is int
                 or kind == "number" and type(value) in (int, float)
                 or kind in ("array", "array|null") and isinstance(value, list))
        if not valid:
            raise ValueError(f"필드 자료형 오류: {name} ({kind})")


def image_sizes(document):
    # GUI와 같은 SDL 디코더를 사용하지만 창·렌더러는 만들지 않는다.
    with redirect_stdout(sys.stderr):
        import pico2d.pico2d as pico
    result = {}
    paths = {sheet.image_path for sheet in document.sheets.values()}
    if not paths:
        paths.add(document.definition.source)
    for path in paths:
        surface = pico.IMG_Load(str(path).encode("utf-8"))
        if not surface:
            raise ValueError(f"이미지를 읽을 수 없다: {path}")
        try:
            result[path] = (surface.contents.w, surface.contents.h)
        finally:
            pico.SDL_FreeSurface(surface)
    for sheet in document.sheets.values():
        if result[sheet.image_path] != sheet.size:
            raise ValueError(f"메타데이터와 실제 이미지 크기가 다르다: {sheet.image_path}")
    return result


def inspect_asset(definition, *, include_frames=False):
    document = read_document(definition)
    sizes = image_sizes(document)
    clips = document.map_bundle.clips if document.map_bundle else document.mech.clips if document.mech else document.sheets.get("body")
    if clips is not None and not document.mech and not document.map_bundle:
        clips = clips.clips
    rows = {}
    if definition.kind == "image":
        width, height = sizes[definition.source]
        rows["image"] = {"fps": 1, "frame_count": 1}
        if include_frames:
            rows["image"]["frames"] = [{"rect": [0, 0, width, height], "pivot": [width / 2, 0]}]
    for name, clip in (clips or {}).items():
        rows[name] = {"fps": clip.fps, "frame_count": len(clip.frames), "duration_ms": clip.duration_ms}
        if include_frames:
            rows[name]["frames"] = [{"rect": list(frame.rect), "pivot": list(frame.pivot), "duration_ms": duration}
                                    for frame, duration in zip(clip.frames, clip.durations_ms)]
    return {"asset_id": document.suggested_id or definition.asset_id, "kind": definition.kind,
            "source": str(definition.source), "default_clip": document.default_clip or next(iter(rows), None),
            "dependencies": [str(path) for path in document.dependencies], "clips": rows,
            "images": [{"path": str(path), "size": list(size)} for path, size in sorted(sizes.items())],
            "layers": list(document.mech.layer_rows) if document.mech else list(document.sheets)}


def read_working_plan(path):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return load_plan(path, asset_id=raw["asset_id"], source=raw["source"])


def edit_plan(plan, edits, resolve):
    for edit in edits:
        if not isinstance(edit, dict) or edit.get("action") not in EDIT_FIELDS:
            raise ValueError("지원하지 않는 작업본 편집이다. describe의 plan_edits를 확인한다.")
        action = edit["action"]
        check_fields(edit, EDIT_FIELDS[action], discriminator=("action",))
        if action == "set":
            path = edit["path"]
            if not path or any(not isinstance(key, str) for key in path) or path[0] in ("version", "asset_id", "source"):
                raise ValueError("편집 경로는 기존 필드의 문자열 목록이며 작업본 ID·원본·버전은 변경할 수 없다.")
            target = plan
            for key in path[:-1]:
                target = target[key]
            if not isinstance(target, dict) or path[-1] not in target:
                raise ValueError("존재하지 않는 편집 경로다.")
            target[path[-1]] = deepcopy(edit["value"])
        elif action == "part.add":
            if edit.get("template") not in (None, "thrusters"):
                raise ValueError("지원하지 않는 파츠 템플릿")
            add_part(plan, edit["id"], edit["name"], duplicate=edit.get("duplicate"), template=edit.get("template"))
        elif action == "part.remove":
            remove_part(plan, edit["id"])
        elif action == "state.add":
            add_state(plan, edit["part"], edit["id"], edit["name"])
        elif action == "state.remove":
            remove_state(plan, edit["part"], edit["id"])
        elif action in ("order.preset", "order.copy_all"):
            if edit["motion"] not in plan["motions"] or edit["direction"] not in DIRECTIONS:
                raise ValueError("동작·방향 참조 오류")
            args = (plan, edit["motion"], edit["direction"])
            if action == "order.preset":
                apply_order_preset(*args, edit["preset"], frame=edit.get("frame"))
            else:
                apply_all_directions(*args, frame=edit.get("frame"))
        elif action == "mapping.apply":
            preset = edit["preset"]
            apply_mapping(plan, preset if preset in ("default", "mech", "npc") else str(resolve(preset)))
    validate_plan(plan, asset_id=plan["asset_id"], source=plan["source"])


def execute(request, *, base_dir=None):
    """1개 요청을 실행한다. 반환값은 JSON 직렬화 가능한 결과이며 오류는 예외로 전달한다."""
    json.dumps(request, allow_nan=False)
    if not isinstance(request, dict) or type(request.get("version")) is not int or request["version"] != API_VERSION:
        raise ValueError("요청 version은 1이어야 한다.")
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError("지원하지 않는 operation이다. 인자 없이 실행하면 지원 작업을 조회한다.")
    check_fields(request, OPERATIONS[operation]["fields"], discriminator=("version", "operation"))
    base = Path(base_dir or Path.cwd()).resolve()

    def resolve(value):
        return (base / value).resolve()

    def source_definition():
        source = resolve(request["source"])
        return AssetDefinition(request.get("asset_id", "preview"), request.get("kind") or detect_kind(source), source)

    if operation == "describe":
        return describe()
    if operation == "catalog.list":
        path = resolve(request["catalog"]) if "catalog" in request else DEFAULT_CATALOG
        catalog = AssetCatalog.load(path)
        return {"catalog": str(path), "assets": [{"asset_id": row.asset_id, "kind": row.kind, "source": str(row.source)}
                                                 for row in catalog.definitions.values()]}
    if operation == "asset.inspect":
        return inspect_asset(source_definition(), include_frames=request.get("include_frames", False))
    if operation in ('map.import', 'map.export'):
        from ferrial_drive.assets.maps import MapBundle
        from .map_export import export_map
        if operation == 'map.export' and ('source' in request) == ('data' in request):
            raise ValueError('source 또는 data 중 하나를 지정한다.')
        if 'source' in request:
            source = resolve(request['source'])
            bundle = MapBundle.load(source)
            inspect_asset(AssetDefinition(bundle.data['asset_id'], 'map', source))
            data, base_dir = bundle.data, source.parent
        else:
            data, base_dir = request['data'], base
            bundle = MapBundle.from_data(data, base_dir)
        if 'output' in request:
            source = export_map(data, resolve(request['output']), base_dir=base_dir)
            bundle = MapBundle.load(source)
        editable = deepcopy(bundle.data)
        for key, path in bundle.paths.items():
            editable[key] = str(path)
        return {'source': str(source), 'data': editable, 'type': 'map'}
    if operation == "catalog.register":
        path = resolve(request["catalog"]) if "catalog" in request else DEFAULT_CATALOG
        if ROOT / "samples" in path.parents:
            raise ValueError("샘플 카탈로그는 읽기 전용이다. 작업용 catalog 경로를 지정한다.")
        catalog = AssetCatalog.load(path) if path.exists() else AssetCatalog(path=path)
        definition = source_definition()
        catalog.add(definition)
        inspect_asset(definition)
        if path == DEFAULT_CATALOG:
            definition = store_asset(definition)
            inspect_asset(definition)
            catalog.definitions[definition.asset_id] = definition
        catalog.save()
        return {"catalog": str(path), "asset_id": definition.asset_id, "source": str(definition.source)}
    if operation == "sprite.assemble":
        definition = source_definition()
        if definition.kind in ("mech", "map"):
            raise ValueError("분리 메카는 plan 작업으로 편집한다.")
        document = read_document(definition)
        sizes = image_sizes(document)
        assembly = SpriteAssembly(definition, image_size=sizes.get(definition.source))
        if not request["edits"]:
            raise ValueError("조립할 편집 항목을 하나 이상 지정한다.")
        for edit in request["edits"]:
            check_fields(edit, SPRITE_FIELDS, discriminator=())
            if 'fps' not in edit and 'durations_ms' not in edit:
                raise ValueError('출력 프레임별 durations_ms가 필요하다.')
            assembly.apply(edit["source_clip"], edit["name"], edit["order"], edit.get("fps"), edit.get("pivot"),
                           all_directions=edit.get("all_directions", True), durations_ms=edit.get('durations_ms'))
        output = assembly.save(resolve(request["output"]), asset_id=definition.asset_id)
        return {"source": str(output), "clips": assembly.names}
    if operation == "plan.create":
        source = resolve(request["source"])
        AssetDefinition(request["asset_id"], "image", source)
        if not source.is_file():
            raise FileNotFoundError(source)
        plan = default_plan(request["asset_id"], source)
        if source.suffix.lower() != ".blend":
            definition = source_definition()
            document = read_document(definition)
            if document.mech:
                import_mech(plan, document.mech)
        if "preset" in request:
            preset = request["preset"]
            apply_mapping(plan, preset if preset in ("default", "mech", "npc") else str(resolve(preset)))
        path = resolve(request["output"]) if "output" in request else plan_path(plan["asset_id"], source)
        if path.exists():
            raise FileExistsError("작업본이 이미 존재한다. plan.read/update를 사용한다: " + str(path))
        save_plan(path, plan)
        return {"plan": str(path), "data": plan}
    if operation.startswith("plan."):
        path = resolve(request["plan"])
        plan = read_working_plan(path)
        if operation == "plan.read":
            return {"plan": str(path), "data": plan}
        if operation == "plan.update":
            candidate = deepcopy(plan)
            edit_plan(candidate, request["edits"], resolve)
            output = resolve(request["output"]) if "output" in request else path
            if output != path and output.exists():
                raise FileExistsError("다른 작업본은 덮어쓰지 않는다: " + str(output))
            save_plan(output, candidate)
            return {"plan": str(output), "data": candidate}
        if operation == "plan.validate":
            check_sheets = request.get("check_sheets", False)
            if check_sheets:
                mech = build_mech(plan)
                image_sizes(read_document_for_mech(mech, plan))
            return {"plan": str(path), "structure_valid": True, "sheets_checked": check_sheets}
        if operation == "plan.export":
            mech = build_mech(plan)
            image_sizes(read_document_for_mech(mech, plan))
            return {"source": str(copy_mech(mech, resolve(request["output"])))}
    if operation == "render.run":
        return run_render(request, resolve)
    raise ValueError("지원하지 않는 작업")


def read_document_for_mech(mech, plan):
    from ferrial_drive.assets.catalog import AssetDocument
    return AssetDocument(AssetDefinition(plan["asset_id"], "mech", plan["source"]), mech.sheets,
                         mech.dependencies, mech.asset_id, next(iter(mech.clips)), mech)


def run_render(request, resolve):
    from math import isfinite
    from Tools.blender_pipeline.asset_build import AssetBuild
    from .production import load_render_preset

    config = resolve(request["config"])
    _, source = load_render_preset(config)
    if "source_blend" in request:
        source = resolve(request["source_blend"])
    if source is None and not request.get("sample", False):
        raise ValueError("렌더할 source_blend 또는 명시적인 sample=true가 필요하다.")
    if source is not None and (not source.is_file() or source.suffix.lower() != ".blend"):
        raise ValueError("렌더할 .blend 파일이 없다.")
    seconds = request.get("timeout_seconds", 300)
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout_seconds는 유한한 양수여야 한다.")
    build = AssetBuild(config, source_blend=source,
                       blender=resolve(request["blender"]) if "blender" in request else None,
                       output_root=resolve(request["output_root"]) if "output_root" in request else ROOT / "output/asset_loader/renders")
    try:
        build.start()
        started = time.monotonic()
        while True:
            status = build.poll()
            if status is not None:
                if not status:
                    raise RuntimeError(build.error)
                return {"source": str(build.result), "directory": str(build.directory),
                        "completed_images": build.completed_images, "total_images": build.total_images}
            if time.monotonic() - started >= seconds:
                raise TimeoutError(f"렌더 제한 시간 초과. 작업을 정리한다: {build.directory}")
            time.sleep(0.1)
    finally:
        build.close()
