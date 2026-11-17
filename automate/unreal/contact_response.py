"""Unreal 메시 접촉을 해소하는 최소 관절 회전을 계산한다."""
import itertools
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
MESH_CACHE = {}


def separation_angle(collides, maximum, step=2.0, tolerance=0.025):
    """닫힌 상태가 비접촉이면 0, 접촉이면 처음 분리되는 구간을 찾는다."""
    if not 0 < tolerance <= step <= maximum <= 180:
        raise ValueError("회전 탐색 범위가 잘못됐다.")
    if not collides(0.0):
        return 0.0
    low = 0.0
    while low < maximum:
        high = min(maximum, low + step)
        if not collides(high):
            while high - low > tolerance:
                middle = (low + high) / 2
                if collides(middle):
                    low = middle
                else:
                    high = middle
            return high
        low = high
    raise ValueError("허용 탐색 범위에서 접촉을 분리할 수 없다.")


def vector(value):
    return [value.x, value.y, value.z]


def world_box(bounds, transform):
    from pose_math import add, rotate
    q = transform.rotation
    rotation = [q.x, q.y, q.z, q.w]
    position = vector(transform.translation)
    points = [add(position, rotate(rotation, point)) for point in itertools.product(
        *[(bounds[0][i], bounds[1][i]) for i in range(3)])]
    return ([min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)])


def boxes_overlap(a, b):
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


class CollisionMesh:
    def __init__(self, mesh, witnesses):
        import unreal
        self.mesh = mesh
        _, positions, gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
        if gaps:
            raise ValueError("충돌 메시의 정점 ID가 연속되어야 한다.")
        points = [vector(p) for p in positions.convert_vector_list_to_array()]
        if not points:
            raise ValueError("빈 충돌 메시")
        self.bounds = ([min(p[i] for p in points) for i in range(3)],
                       [max(p[i] for p in points) for i in range(3)])
        self.witnesses = witnesses
        _, self.bvh = unreal.GeometryScript_MeshSpatial.build_bvh_for_mesh(mesh)


def mesh_overlap(a, ta, b, tb, counters, box_b=None):
    """경계 상자는 후보만 거른다. 실제 삼각형 교차와 체적 포함을 판정한다."""
    import unreal
    box_a = world_box(a.bounds, ta)
    if not boxes_overlap(box_a, box_b or world_box(b.bounds, tb)):
        return False
    counters["triangle_queries"] += 1
    _, intersects = unreal.GeometryScript_MeshComparison.is_intersecting_mesh(a.mesh, ta, b.mesh, tb)
    if intersects:
        return True
    options = unreal.GeometryScriptSpatialQueryOptions()
    for source, source_transform, target, target_transform in ((a, ta, b, tb), (b, tb, a, ta)):
        for point in source.witnesses:
            position = unreal.MathLibrary.transform_location(source_transform, unreal.Vector(*point))
            local = unreal.MathLibrary.inverse_transform_location(target_transform, position)
            values = vector(local)
            if any(values[i] < target.bounds[0][i] or values[i] > target.bounds[1][i] for i in range(3)):
                continue
            counters["containment_queries"] += 1
            _, inside, _ = unreal.GeometryScript_MeshSpatial.is_point_inside_mesh(
                target.mesh, target.bvh, local, options)
            if inside:
                return True
    return False


def load_collision_meshes(plan_path, bone_names):
    import unreal
    key = (str(plan_path), tuple(sorted(bone_names)))
    if key in MESH_CACHE:
        return MESH_CACHE[key]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    bind = {row["name"]: row["position_cm"] for row in plan["bones"]}
    result = {}
    for bone in bone_names:
        parts = [part for part in plan["parts"] if part["bone"] == bone]
        if not parts or any(part.get("deformation") or part.get("axis_binding") for part in parts):
            raise ValueError("강체 부품만 지원한다: " + bone)
        merged, witnesses = unreal.DynamicMesh(), []
        for part in parts:
            asset = unreal.load_asset(part["asset"])
            if not isinstance(asset, unreal.StaticMesh):
                raise ValueError("리그 없는 원본 형상이 필요하다: " + part["asset"])
            mesh, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(
                asset, unreal.DynamicMesh(), unreal.GeometryScriptCopyMeshFromAssetOptions(),
                unreal.GeometryScriptMeshReadLOD())
            if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
                raise ValueError("원본 형상 읽기 실패: " + part["asset"])
            unreal.GeometryScript_MeshTransforms.translate_mesh(mesh, unreal.Vector(*[-v for v in bind[bone]]))
            _, positions, gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
            points = positions.convert_vector_list_to_array()
            if gaps or not points:
                raise ValueError("충돌 부품 정점이 필요하다.")
            witnesses.append(vector(points[0]))
            unreal.GeometryScript_MeshEdits.append_mesh(merged, mesh, unreal.Transform())
        result[bone] = CollisionMesh(merged, witnesses)
    MESH_CACHE[key] = result
    return result


class ContactResponse:
    def __init__(self, settings, base, parents, poses):
        self.settings, self.base, self.parents = settings, base, parents
        self.panels = settings["panels"]
        self.colliders = settings["collider_bones"]
        controlled = {panel["bone"] for panel in self.panels}
        if (len(controlled) != len(self.panels) or controlled & set(self.colliders)
                or not controlled or not self.colliders or not (controlled | set(self.colliders)) <= set(base)):
            raise ValueError("패널과 충돌 본 설정이 잘못됐다.")
        if any(parent in controlled for parent in parents.values()):
            raise ValueError("접촉 제어 대상은 말단 본이어야 한다.")
        for pose in poses:
            for name in controlled:
                if any(abs(v) > 1e-9 for values in pose["controls"].get(name, {}).values() for v in values):
                    raise ValueError("기존 패널 수동 키와 접촉 제어를 함께 사용할 수 없다.")
        for panel in self.panels:
            axis = panel["axis_deg"]
            if len(axis) != 3 or sum(abs(v) for v in axis) != 1 or not set(axis) <= {-1, 0, 1}:
                raise ValueError("한 회전축만 지원한다.")
            if abs(base[panel["bone"]].rotation.w) < 1 - 1e-6:
                raise ValueError("기본 회전이 없는 강체 제어점이 필요하다.")
        self.meshes = load_collision_meshes((ROOT / settings["rig_plan"]).resolve(), controlled | set(self.colliders))
        self.rows = []
        self.started = time.perf_counter()
        self.counters = {"triangle_queries": 0, "containment_queries": 0}

    def transform(self, panel, angle):
        import unreal
        from pose_math import from_euler, rotate, sub
        bone = panel["bone"]
        delta = [angle * v for v in panel["axis_deg"]]
        offset = panel.get("pivot_offset_cm", [0, 0, 0])
        translation = sub(offset, rotate(from_euler(delta), offset))
        result = unreal.Transform()
        result.translation = self.base[bone].translation + unreal.Vector(*translation)
        result.rotation = unreal.Rotator(pitch=delta[0], yaw=delta[1], roll=delta[2]).quaternion()
        result.scale3d = self.base[bone].scale3d
        return result

    def apply(self, frame, locals_, globals_):
        import unreal
        colliders = [(name, self.meshes[name], globals_[name], world_box(self.meshes[name].bounds, globals_[name]))
                     for name in self.colliders]
        row = {"frame": frame, "panels": []}
        for panel in self.panels:
            bone = panel["bone"]
            parent = globals_[self.parents[bone]]
            def collisions(angle):
                world = unreal.MathLibrary.compose_transforms(self.transform(panel, angle), parent)
                return [name for name, mesh, transform, box in colliders
                        if mesh_overlap(self.meshes[bone], world, mesh, transform, self.counters, box)]
            closed = collisions(0)
            if closed:
                angle = separation_angle(lambda value: bool(closed) if value == 0 else bool(collisions(value)),
                    panel.get("max_angle_deg", 150), self.settings.get("step_angle_deg", 2),
                    self.settings.get("angle_tolerance_deg", 0.025))
                angle = min(panel.get("max_angle_deg", 150), angle + self.settings.get("separation_epsilon_deg", 0.025))
                if collisions(angle):
                    raise ValueError(f"접촉 분리 실패: {bone}, frame={frame}")
            else:
                angle = 0.0
            local = self.transform(panel, angle)
            locals_[bone] = local
            globals_[bone] = unreal.MathLibrary.compose_transforms(local, parent)
            row["panels"].append({"bone": bone, "closed_contact": bool(closed),
                "closed_contact_bones": closed, "angle_deg": angle, "resolved": True})
        self.rows.append(row)

    def report(self):
        return {"method": "Unreal native triangle intersection and containment; minimum contact separation",
                "dynamics": "quasi_static_hinge_contact_projection", "settings": self.settings,
                "elapsed_seconds": time.perf_counter() - self.started,
                "no_contact_nonzero_angles": sum(not p["closed_contact"] and p["angle_deg"] != 0
                    for row in self.rows for p in row["panels"]), "queries": self.counters, "samples": self.rows}


def self_test():
    import unreal
    def box(size, center):
        mesh = unreal.GeometryScript_Primitives.append_box(unreal.DynamicMesh(),
            unreal.GeometryScriptPrimitiveOptions(), unreal.Transform(location=unreal.Vector(*center)),
            *size, origin=unreal.GeometryScriptPrimitiveOriginMode.CENTER)
        _, positions, _ = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
        return CollisionMesh(mesh, [vector(positions.convert_vector_list_to_array()[0])])
    stats = {"triangle_queries": 0, "containment_queries": 0}
    panel, leg = box([2, 8, 20], [10, 0, -10]), box([4, 8, 10], [8.5, 0, -12])
    rest = unreal.Transform()
    def probe(angle):
        transform = unreal.Transform()
        transform.rotation = unreal.Rotator(pitch=angle).quaternion()
        return mesh_overlap(panel, transform, leg, rest, stats)
    angle = separation_angle(probe, 120)
    assert angle > 0 and not probe(angle) and probe(max(0, angle - 0.05))
    far = unreal.Transform(location=unreal.Vector(-50, 0, 0))
    assert separation_angle(lambda value: mesh_overlap(panel, rest, leg, far, stats), 120) == 0
    cube = box([2, 2, 2], [0, 0, 0])
    diagonal = unreal.Transform(location=unreal.Vector(2.2, 2.2, 0))
    diagonal.rotation = unreal.Rotator(yaw=45).quaternion()
    assert boxes_overlap(world_box(cube.bounds, rest), world_box(cube.bounds, diagonal))
    assert not mesh_overlap(cube, rest, cube, diagonal, stats)
    outer = box([100, 100, 100], [0, 0, 0])
    assert mesh_overlap(panel, rest, outer, rest, stats)
    return {"engine": unreal.SystemLibrary.get_engine_version(), "passed": 4,
            "contact_separation_angle_deg": angle, "queries": stats,
            "checks": ["actual_contact_opens_minimally", "no_contact_stays_zero",
                       "overlapping_bounds_do_not_trigger", "contained_geometry_is_contact"]}


def export_geometry(request):
    """독립 검사용으로 실제 Unreal Static Mesh의 삼각분할을 보존한다."""
    import unreal
    plan_path = (ROOT / request["rig_plan"]).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    selected = set(request["objects"])
    parts = {}
    for part in plan["parts"]:
        if part["name"] not in selected:
            continue
        if part.get("deformation") or part.get("axis_binding"):
            raise ValueError("강체 원본 형상만 검사한다.")
        mesh, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(
            unreal.load_asset(part["asset"]), unreal.DynamicMesh(),
            unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
        if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
            raise ValueError("형상 읽기 실패")
        _, positions, gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
        if gaps:
            raise ValueError("연속된 정점 ID가 필요하다.")
        triangles = []
        for index in range(unreal.GeometryScript_MeshQueries.get_num_triangle_i_ds(mesh)):
            indices, valid = unreal.GeometryScript_MeshQueries.get_triangle_indices(mesh, index)
            if valid:
                triangles.append([indices.x, indices.y, indices.z])
        parts[part["name"]] = {"asset": part["asset"], "bone": part["bone"],
            "vertices": [vector(v) for v in positions.convert_vector_list_to_array()], "triangles": triangles}
    if set(parts) != selected:
        raise ValueError("요청한 부품 형상이 모두 필요하다.")
    output = (ROOT / request["output"]).resolve()
    if not output.is_relative_to(ROOT / "Tools/unreal_pipeline/workspace") or output.exists():
        raise ValueError("새 Unreal 작업본 형상 경로가 필요하다.")
    output.write_text(json.dumps({"version": 1, "coordinate_space": "unreal_bind_cm",
        "rig_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "parts": parts}), encoding="utf-8")
    return {"output": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "parts": len(parts), "triangles": sum(len(p["triangles"]) for p in parts.values())}


def probe_tracking(request):
    """저장된 자세에서 회전 탐색 간격에 따른 접촉 분리각을 비교한다."""
    import unreal
    settings = request["contact_response"]
    plan = json.loads((ROOT / settings["rig_plan"]).read_text(encoding="utf-8"))
    trace = json.loads((ROOT / request["tracking"]).read_text(encoding="utf-8"))
    if trace["space"] != "skeletal_component_cm":
        raise ValueError("Unreal component cm 추적이 필요하다.")
    bind = {"Root": [0, 0, 0], **{b["name"]: b["position_cm"] for b in plan["bones"]}}
    parents = {b["name"]: b["parent"] for b in plan["bones"]}
    base = {name: unreal.Transform(location=unreal.Vector(*[
        point[i] - bind[parents.get(name, "Root")][i] for i in range(3)])) for name, point in bind.items()}
    response = ContactResponse(settings, base, parents, [])
    results = []
    for item in request["probes"]:
        row = min(trace["samples"], key=lambda r: abs(r["source_frame"] - item["frame"]))
        if abs(row["source_frame"] - item["frame"]) > 1e-7:
            raise ValueError("저장된 표본 시각만 검사한다.")
        transforms = {}
        for name, value in {trace["bone"]: row, **row["extra_bones"]}.items():
            transform = unreal.Transform(location=unreal.Vector(*value["position_cm"]))
            transform.rotation = unreal.Quat(*value["rotation_xyzw"])
            transforms[name] = transform
        panel = next(p for p in response.panels if p["bone"] == item["bone"])
        parent = transforms[parents[panel["bone"]]]
        colliders = [(name, response.meshes[name], transforms[name]) for name in response.colliders]
        def collides(angle):
            world = unreal.MathLibrary.compose_transforms(response.transform(panel, angle), parent)
            return any(mesh_overlap(response.meshes[panel["bone"]], world, mesh, transform,
                                    response.counters) for _, mesh, transform in colliders)
        angles = {str(step): separation_angle(collides, panel.get("max_angle_deg", 150), step,
                    min(0.025, step)) for step in request["steps_deg"]}
        results.append({**item, "separation_angles_deg": angles})
    return {"probes": results, "queries": response.counters,
            "limits": "지정된 저장 자세에서의 탐색 간격 비교. 연속 동역학 검사가 아니다."}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import unreal
    request = json.loads(Path(os.environ["FD_UNITS_REQUEST"]).read_text(encoding="utf-8-sig"))
    target = ROOT / request["report"]
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if request["operation"] == "contact_geometry":
            result = export_geometry(request)
        elif request["operation"] == "contact_test":
            result = self_test()
        elif request["operation"] == "contact_probe":
            result = probe_tracking(request)
        else:
            raise ValueError("지원하지 않는 접촉 작업")
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        import traceback
        target.with_suffix(".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    unreal.SystemLibrary.quit_editor()
