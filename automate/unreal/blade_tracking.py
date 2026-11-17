"""저장된 Unreal 동작에서 검 변환·날 양끝·카메라 투영 좌표를 기록한다."""
import json
from pathlib import Path

if __package__:
    from .pose_math import add, cross, dot, mul, sub, unit
else:
    from pose_math import add, cross, dot, mul, sub, unit

ROOT = Path(__file__).resolve().parents[2]


def project_to_screen(point, camera):
    """출력 카메라의 직교 투영을 화면 없는 검토 도구에서도 재사용한다."""
    forward = unit(sub(camera["target"], camera["position"]))
    right = unit(cross([0, 0, 1], forward))
    up = cross(forward, right)
    width, height = camera.get("size", [768, 768])
    scale = width / camera["width_cm"]
    offset = sub(point, camera["target"])
    return [width / 2 + dot(offset, right) * scale, height / 2 - dot(offset, up) * scale]


def vector(value):
    return [value.x, value.y, value.z]


def blade_points(settings, bind_transform):
    import unreal
    if "points_local_cm" in settings:
        return settings["points_local_cm"], {"method": "explicit_bone_local_points"}
    source = unreal.load_asset(settings["blade_mesh"])
    if not isinstance(source, unreal.StaticMesh):
        raise ValueError("검날의 원본 Static Mesh가 필요하다.")
    mesh, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(
        source, unreal.DynamicMesh(), unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
    if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
        raise ValueError("검날 형상을 읽지 못했다.")
    _, positions, _ = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, True)
    vertices = positions.convert_vector_list_to_array()
    vertices = [vector(v) for v in vertices]
    axis = unit(settings["blade_axis_bind"])
    distances = [dot(v, axis) for v in vertices]
    band = settings.get("endpoint_band_cm", 1.0)
    points = {}
    for label, extreme in (("blade_root", min(distances)), ("blade_tip", max(distances))):
        selected = [v for v, distance in zip(vertices, distances) if abs(distance-extreme) <= band]
        center = [sum(v[i] for v in selected)/len(selected) for i in range(3)]
        local = unreal.MathLibrary.inverse_transform_location(bind_transform, unreal.Vector(*center))
        points[label] = vector(local)
    return points, {"method": "native_mesh_axis_extreme_vertex_centroids", "source": source.get_path_name(),
                    "axis_bind": axis, "endpoint_band_cm": band, "vertices_bind_cm": vertices}


def capture(animation, source, modifier, names, parents, count, fps, settings):
    import unreal
    path = (ROOT / settings["output"]).resolve()
    if not path.is_relative_to(ROOT / "Tools/unreal_pipeline/workspace") or path.exists():
        raise ValueError("새 Unreal 작업본의 Trail 출력 경로가 필요하다.")
    hz = settings.get("sample_hz", 120)
    if type(hz) is not int or not fps <= hz <= 240 or hz % fps:
        raise ValueError("원본 FPS 배수인 12~240Hz 기록이 필요하다.")
    bone = settings["bone"]
    if bone not in names:
        raise ValueError("추적할 검 본이 없다.")
    extra_bones = settings.get("extra_bones", [])
    if any(name not in names for name in extra_bones) or len(extra_bones) != len(set(extra_bones)):
        raise ValueError("추가 추적 본은 중복 없는 기존 본이어야 한다.")
    needed = {bone, *extra_bones}
    for tracked in list(needed):
        parent = parents[tracked]
        while parent in names:
            needed.add(parent)
            parent = parents[parent]
    points, provenance = blade_points(settings, modifier.get_bone_transform(bone, global_=True))
    cameras = {}
    for label, camera in settings.get("cameras", {}).items():
        forward = unit(sub(camera["target"], camera["position"]))
        right = unit(cross([0, 0, 1], forward))
        up = cross(forward, right)
        cameras[label] = (camera, right, up)
    rows = []
    for index in range(count*hz//fps + 1):
        seconds = index/hz
        world = {}
        for name in names:
            if name in needed:
                local = unreal.AnimationLibrary.get_bone_pose_for_time(animation, name, seconds, False)
                world[name] = unreal.MathLibrary.compose_transforms(local, world.get(parents[name], unreal.Transform()))
        transform = world[bone]
        row = {"time_seconds": seconds, "source_frame": seconds*fps,
               "position_cm": vector(transform.translation),
               "rotation_xyzw": [transform.rotation.x, transform.rotation.y, transform.rotation.z, transform.rotation.w],
               "points_cm": {name: vector(unreal.MathLibrary.transform_location(transform, unreal.Vector(*value)))
                             for name, value in points.items()}}
        row["screen_top_left_px"] = {}
        if extra_bones:
            row["extra_bones"] = {name: {"position_cm": vector(world[name].translation),
                "rotation_xyzw": [world[name].rotation.x, world[name].rotation.y,
                                  world[name].rotation.z, world[name].rotation.w]}
                for name in extra_bones}
        for label, (camera, right, up) in cameras.items():
            width, height = camera.get("size", [768, 768])
            scale = width/camera["width_cm"]
            row["screen_top_left_px"][label] = {}
            for name, point in {"position": row["position_cm"], **row["points_cm"]}.items():
                offset = sub(point, camera["target"])
                row["screen_top_left_px"][label][name] = [width/2+dot(offset, right)*scale,
                                                        height/2-dot(offset, up)*scale]
        rows.append(row)
    data = {"version": 1, "type": "blade_trajectory", "animation": animation.get_path_name(),
            "source_mesh": source.get_path_name(), "bone": bone, "space": "skeletal_component_cm",
            "axes": {"forward": "+X", "right": "+Y", "up": "+Z"}, "quaternion": "xyzw",
            "source_fps": fps, "sample_hz": hz, "duration_seconds": count/fps, "extra_bones": extra_bones,
            "points_local_cm": points, "point_provenance": provenance,
            "point_definition_source": settings.get("point_definition_source"), "cameras": settings.get("cameras", {}),
            "visual_phase_candidates": settings.get("visual_phase_candidates", {}),
            "combat_hit_windows_approved": False, "samples": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path.relative_to(ROOT)), "sample_hz": hz, "sample_count": len(rows), "points_local_cm": points}
