"""원본 형상과 Unreal 평가 변환으로 지정 부품의 표면 교차를 독립 검사한다."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def check(request):
    import bpy
    from mathutils import Matrix, Quaternion, Vector
    from mathutils.bvhtree import BVHTree

    source = Path(request["source"]).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != request["source_sha256"]:
        raise ValueError("검사 원본 해시 불일치")
    output = Path(request["output"])
    if output.exists():
        raise FileExistsError(output)
    plan = json.loads(Path(request["rig_plan"]).read_text(encoding="utf-8"))
    parts = {part["name"]: part for part in plan["parts"]}
    bind = {bone["name"]: Vector(bone["position_cm"]) for bone in plan["bones"]}
    selected = set(name for pair in request["pairs"] for name in pair)
    geometry = {}
    if request.get("geometry_snapshot"):
        snapshot_path = Path(request["geometry_snapshot"])
        if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != request["geometry_snapshot_sha256"]:
            raise ValueError("Unreal 형상 스냅샷 해시 불일치")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if (snapshot.get("version") != 1 or snapshot.get("coordinate_space") != "unreal_bind_cm"
                or snapshot["rig_plan_sha256"] != hashlib.sha256(Path(request["rig_plan"]).read_bytes()).hexdigest()):
            raise ValueError("실제 리그 계획과 Unreal bind cm 형상이 필요하다.")
        for name in selected:
            item = snapshot["parts"][name]
            if item["bone"] != parts[name]["bone"] or item["asset"] != parts[name]["asset"]:
                raise ValueError("스냅샷의 부품 바인딩이 다르다.")
            geometry[name] = ([Vector(v) for v in item["vertices"]], [tuple(t) for t in item["triangles"]])
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source))
        inverse = bpy.data.objects[request["root"]].matrix_world.inverted()
        graph = bpy.context.evaluated_depsgraph_get()
        for name in selected:
            obj = bpy.data.objects[name].evaluated_get(graph)
            mesh = obj.to_mesh()
            try:
                mesh.calc_loop_triangles()
                vertices = [inverse @ obj.matrix_world @ vertex.co for vertex in mesh.vertices]
                geometry[name] = ([Vector((point.x*100, -point.y*100, point.z*100)) for point in vertices],
                                  [tuple(triangle.vertices) for triangle in mesh.loop_triangles])
            finally:
                obj.to_mesh_clear()
    runs = []
    for entry in request["runs"]:
        trace = json.loads(Path(entry["tracking"]).read_text(encoding="utf-8"))
        if trace.get("space") != "skeletal_component_cm":
            raise ValueError("Unreal component cm 좌표의 추적 결과가 필요하다.")
        intersections = []
        for row in trace["samples"]:
            transforms = {trace["bone"]: row, **row["extra_bones"]}
            trees = {}
            for name in selected:
                bone = parts[name]["bone"]
                transform = transforms[bone]
                x, y, z, w = transform["rotation_xyzw"]
                matrix = (Matrix.Translation(Vector(transform.get("position_cm", (0, 0, 0))))
                          @ Quaternion((w, x, y, z)).to_matrix().to_4x4()
                          @ Matrix.Translation(-bind[bone]))
                vertices, triangles = geometry[name]
                trees[name] = BVHTree.FromPolygons([matrix @ point for point in vertices], triangles,
                                                  all_triangles=True, epsilon=0)
            for a, b in request["pairs"]:
                overlap = trees[a].overlap(trees[b])
                if overlap:
                    intersections.append({"time_seconds": row["time_seconds"], "pair": [a, b],
                                          "triangle_pairs": len(overlap)})
        runs.append({"name": entry["name"], "samples": len(trace["samples"]),
                     "intersections": intersections, "surface_clear": not intersections})
    result = {"runs": runs, "pairs": request["pairs"], "source_unchanged":
              hashlib.sha256(source.read_bytes()).hexdigest() == request["source_sha256"],
              "method": ("Unreal static triangles" if request.get("geometry_snapshot") else "source geometry")
                        + " + Unreal evaluated rigid transforms; independent Blender triangle surface overlap",
              "limits": "지정 부품의 표면 교차만 검사한다. 체적 포함·접촉 여유·전신 간섭·외관 승인은 범위 밖이다."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"runs": [{key: value for key, value in run.items() if key != "intersections"} for run in runs],
            "report": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    print(json.dumps(check(json.loads(args.request.read_text(encoding="utf-8-sig"))), ensure_ascii=True))
