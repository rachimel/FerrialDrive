"""기존 가중치는 보존하고 누락된 정점만 기준 메시에서 보완한다."""


def repair_unweighted(source, target):
    from mathutils.kdtree import KDTree

    if source.type != 'MESH' or target.type != 'MESH':
        raise ValueError('가중치 기준과 대상은 메시여야 한다.')
    missing = [v.index for v in target.data.vertices if sum(g.weight for g in v.groups) <= .001]
    if not missing:
        return 0
    donors = []
    for vertex in source.data.vertices:
        weights = [(source.vertex_groups[g.group].name, g.weight) for g in vertex.groups if g.weight > 0]
        total = sum(weight for _, weight in weights)
        if total > .001:
            donors.append((source.matrix_world @ vertex.co, [(name, weight / total) for name, weight in weights]))
    if not donors:
        raise ValueError('기준 메시에 복사할 가중치가 없다.')
    tree = KDTree(len(donors))
    for index, (point, _) in enumerate(donors):
        tree.insert(point, index)
    tree.balance()
    for index in missing:
        _, donor, _ = tree.find(target.matrix_world @ target.data.vertices[index].co)
        for group in target.vertex_groups:
            group.remove([index])
        for name, weight in donors[donor][1]:
            group = target.vertex_groups.get(name) or target.vertex_groups.new(name=name)
            group.add([index], weight, 'REPLACE')
    return len(missing)
