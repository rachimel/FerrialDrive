"""부품의 모서리 길이를 보존하는 축별 구간 변형. 좌표 단위는 cm다."""

from bisect import bisect_right
from math import isfinite


def deform_point(point, settings):
    amount = settings.get("amount", 1)
    shift = settings.get("translation_cm", (0, 0, 0))
    if not isfinite(amount) or not 0 <= amount <= 1 or len(shift) != 3 or not all(map(isfinite, shift)):
        raise ValueError("변형 위상은 0~1, 이동은 유한한 cm 좌표여야 한다.")
    result = list(point)
    used = set()
    for mapping in settings.get("axis_maps", ()):
        axis, points = mapping["axis"], mapping["points"]
        if axis not in (0, 1, 2) or axis in used or len(points) < 2:
            raise ValueError("축별 변형은 중복 없는 축과 두 개 이상의 대응점이 필요하다.")
        used.add(axis)
        if any(len(row) != 2 or not all(map(isfinite, row)) for row in points):
            raise ValueError("축 대응점은 유한한 원본·목표 cm 좌표다.")
        if any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(points, points[1:])):
            raise ValueError("축 대응점은 원본·목표 모두 엄격히 증가해야 한다.")
        value = point[axis]
        index = max(0, min(len(points)-2, bisect_right([row[0] for row in points], value)-1))
        a, b = points[index:index+2]
        target = a[1] + (value-a[0])*(b[1]-a[1])/(b[0]-a[0])
        result[axis] += (target-value)*amount
    return [value+offset*amount for value, offset in zip(result, shift)]


def apply_deformation(mesh, settings):
    import unreal
    _, positions, gaps = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(mesh, False)
    if gaps:
        raise ValueError("부품 변형에는 연속된 정점 ID가 필요하다.")
    for index, position in enumerate(positions.convert_vector_list_to_array()):
        value = deform_point((position.x, position.y, position.z), settings)
        _, valid = unreal.GeometryScript_MeshEdits.set_vertex_position(mesh, index, unreal.Vector(*value), False)
        if not valid:
            raise ValueError("부품 정점 변형 실패: " + str(index))
