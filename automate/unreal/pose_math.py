"""Unreal 좌표의 강체 변환·두 관절 목표 계산. 외부 런타임에 의존하지 않는다."""
import math


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def mul(a, value):
    return [x * value for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def length(a):
    return math.sqrt(dot(a, a))


def unit(a):
    size = length(a)
    if size < 1e-9:
        raise ValueError("방향을 정할 수 없는 벡터")
    return mul(a, 1 / size)


def qmul(a, b):
    v = add(add(mul(b[:3], a[3]), mul(a[:3], b[3])), cross(a[:3], b[:3]))
    return v + [a[3]*b[3] - dot(a[:3], b[:3])]


def inverse(q):
    return [-q[0], -q[1], -q[2], q[3]]


def rotate(q, v):
    return qmul(qmul(q, list(v) + [0]), inverse(q))[:3]


def from_euler(value):
    pitch, yaw, roll = [math.radians(v) / 2 for v in value]
    return qmul(qmul([0, 0, math.sin(yaw), math.cos(yaw)],
                     [0, -math.sin(pitch), 0, math.cos(pitch)]),
                [-math.sin(roll), 0, 0, math.cos(roll)])


def to_euler(q):
    q = unit(q)
    x, y, z = [rotate(q, axis) for axis in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
    horizontal = math.hypot(x[0],x[1])
    pitch = math.atan2(x[2],horizontal)
    if horizontal < 1e-8:
        # ±90도에서는 X축의 방위가 정해지지 않는다. Y축으로 합쳐진 방위를 보존한다.
        yaw,roll = math.atan2(-y[0],y[1]),0.0
    else:
        yaw = math.atan2(x[1], x[0])
        roll = -math.atan2(y[2], z[2])
    return [math.degrees(v) for v in (pitch, yaw, roll)]


def slerp(a, b, t):
    cosine = dot(a, b)
    if cosine < 0:
        b, cosine = mul(b, -1), -cosine
    if cosine > 0.9995:
        return unit(add(mul(a, 1-t), mul(b, t)))
    angle = math.acos(max(-1, min(1, cosine)))
    return add(mul(a, math.sin((1-t)*angle)/math.sin(angle)), mul(b, math.sin(t*angle)/math.sin(angle)))


def frame_quaternion(direction, normal):
    x = unit(direction)
    z = unit(sub(normal, mul(x, dot(normal, x))))
    y = cross(z, x)
    matrix = [[x[i], y[i], z[i]] for i in range(3)]
    trace = sum(matrix[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        return [(matrix[2][1]-matrix[1][2])/s, (matrix[0][2]-matrix[2][0])/s,
                (matrix[1][0]-matrix[0][1])/s, s/4]
    i = max(range(3), key=lambda j: matrix[j][j])
    j, k = (i+1) % 3, (i+2) % 3
    s = math.sqrt(1 + matrix[i][i]-matrix[j][j]-matrix[k][k]) * 2
    q = [0.0]*4
    q[i], q[j], q[k], q[3] = s/4, (matrix[i][j]+matrix[j][i])/s, (matrix[i][k]+matrix[k][i])/s, (matrix[k][j]-matrix[j][k])/s
    return q


def align_frame(old_direction, old_normal, direction, normal):
    return qmul(frame_quaternion(direction, normal), inverse(frame_quaternion(old_direction, old_normal)))


def solve_two_bone(start, target, upper_length, lower_length, pole):
    delta = sub(target, start)
    distance = length(delta)
    if not abs(upper_length-lower_length)+1e-5 < distance < upper_length+lower_length-1e-5:
        raise ValueError(f"관절 도달 범위 밖: {distance:.3f} / {upper_length+lower_length:.3f}")
    forward = unit(delta)
    side = unit(sub(sub(pole, start), mul(forward, dot(sub(pole, start), forward))))
    along = (upper_length**2-lower_length**2+distance**2)/(2*distance)
    height = math.sqrt(max(0, upper_length**2-along**2))
    return add(add(start, mul(forward, along)), mul(side, height))


def forward_pose(plan, controls):
    positions = {"Root": [0, 0, 0], **{b["name"]: b["position_cm"] for b in plan["bones"]}}
    parents = {"Root": None, **{b["name"]: b["parent"] for b in plan["bones"]}}
    world = {}
    for name, parent in parents.items():
        row = controls.get(name, {})
        local = add(sub(positions[name], positions.get(parent, [0, 0, 0])), row.get("translation_delta_cm", [0, 0, 0]))
        rotation = from_euler(row.get("rotation_delta_deg", [0, 0, 0]))
        parent_position, parent_rotation = world.get(parent, ([0, 0, 0], [0, 0, 0, 1]))
        world[name] = (add(parent_position, rotate(parent_rotation, local)), qmul(parent_rotation, rotation))
    return world


def chain_controls(plan, controls, reference, chain, target, pole, end_rotation):
    """기준 굽힘 면을 따라 회전만 계산한다. 본 길이와 말단 목표는 유지한다."""
    upper, lower, end = chain
    parents = {b["name"]: b["parent"] for b in plan["bones"]}
    current = forward_pose(plan, controls)
    a0, b0, c0 = [reference[name][0] for name in chain]
    a = current[upper][0]
    b = solve_two_bone(a, target, length(sub(b0, a0)), length(sub(c0, b0)), pole)
    old_normal = cross(sub(b0, a0), sub(c0, b0))
    normal = cross(sub(b, a), sub(target, b))
    upper_q = qmul(align_frame(sub(b0, a0), old_normal, sub(b, a), normal), reference[upper][1])
    lower_q = qmul(align_frame(sub(c0, b0), old_normal, sub(target, b), normal), reference[lower][1])
    for name, parent_q, world_q in ((upper, current[parents[upper]][1], upper_q),
                                    (lower, upper_q, lower_q), (end, lower_q, end_rotation)):
        controls.setdefault(name, {})["rotation_delta_deg"] = to_euler(qmul(inverse(parent_q), world_q))
    return b
