"""공통 단면 기반 메시 생성. 에셋별 좌표는 JSON으로 전달한다."""
import math


def profile_faces(profile_count, point_count, capped=True, cyclic_profiles=False):
    """단면 연결 면을 만든다. 순환 연결은 속이 빈 외피의 앞뒤 경계를 닫는다."""
    if profile_count < 2 or point_count < 3:
        raise ValueError('두 개 이상의 단면과 세 개 이상의 단면 정점이 필요하다.')
    if cyclic_profiles and (capped or profile_count < 3):
        raise ValueError('순환 단면은 캡 없이 세 개 이상의 단면을 사용한다.')
    count = point_count
    faces = [(row*count+i, row*count+(i+1) % count,
              ((row+1) % profile_count)*count+(i+1) % count,
              ((row+1) % profile_count)*count+i)
             for row in range(profile_count if cyclic_profiles else profile_count-1)
             for i in range(count)]
    if capped:
        faces.extend([tuple(reversed(range(count))),
                      tuple(range((profile_count-1)*count, profile_count*count))])
    return faces


def profile_mesh(name, profiles, capped=True, cyclic_profiles=False):
    import bpy
    import bmesh
    if len(profiles) < 2 or len(profiles[0]) < 3:
        raise ValueError('동일 정점 수의 닫힌 단면이 두 개 이상 필요하다.')
    count = len(profiles[0])
    if any(len(row) != count for row in profiles):
        raise ValueError('모든 단면의 정점 수/순서를 맞춘다.')
    points = [point for row in profiles for point in row]
    if any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in points):
        raise ValueError('단면 좌표는 유한한 3차원 값이어야 한다.')
    faces = profile_faces(len(profiles), count, capped, cyclic_profiles)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
