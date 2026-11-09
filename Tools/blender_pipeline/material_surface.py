"""외부 PBR 맵을 기존 재질의 표면 입력에 적용한다. 발광과 형상은 보존한다."""
import math
from pathlib import Path


def apply_pbr_surface(config):
    import bpy

    material = bpy.data.materials[config['material']]
    if not material.node_tree:
        raise ValueError('노드 기반 재질만 지원한다.')
    shaders = [n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
    if len(shaders) != 1:
        raise ValueError('Principled BSDF 하나인 재질만 지원한다.')
    scale = config.get('scale', 2.0)
    distance = config.get('bump_distance', .002)
    bevel = config.get('bevel_radius', .001)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in (scale, distance, bevel)) or scale == 0:
        raise ValueError('스케일은 양수, 범프·베벨 거리는 0 이상이어야 한다.')
    maps = config['maps']
    loaded = {}
    for role in ('color', 'roughness', 'height'):
        path = Path(maps[role]).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        image = bpy.data.images.load(str(path), check_existing=True)
        if not all(image.size) or max(image.size) > config.get('max_texture_size', 1024):
            raise ValueError(f'텍스처 해상도 범위 초과: {path}')
        image.colorspace_settings.name = 'sRGB' if role == 'color' else 'Non-Color'
        loaded[role] = image
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    prefix = 'SurfacePBR::'
    for node in list(nodes):
        if node.name.startswith(prefix):
            nodes.remove(node)

    def create(kind, name, x, y):
        node = nodes.new(kind)
        node.name = prefix + name
        node.label = name
        node.location = (x, y)
        return node

    shader = shaders[0]
    coord = create('ShaderNodeTexCoord', '부품 로컬 좌표', -1100, 500)
    mapping = create('ShaderNodeVectorMath', '실제 크기 반복', -900, 500)
    mapping.operation = 'SCALE'
    mapping.inputs[3].default_value = scale
    links.new(coord.outputs['Object'], mapping.inputs[0])
    textures = {}
    for index, (role, image) in enumerate(loaded.items()):
        texture = create('ShaderNodeTexImage', role, -680, 600-index*260)
        texture.image = image
        texture.projection = 'BOX'
        texture.projection_blend = .2
        texture.extension = 'REPEAT'
        texture.interpolation = 'Linear'
        links.new(mapping.outputs['Vector'], texture.inputs['Vector'])
        textures[role] = texture

    luminance = create('ShaderNodeRGBToBW', '원본 도장 명도', -430, 650)
    links.new(textures['color'].outputs['Color'], luminance.inputs[0])
    color = create('ShaderNodeValToRGB', '표면 색 범위', -220, 650)
    positions = config.get('color_range', [0, 1])
    if len(positions) != 2 or not 0 <= positions[0] < positions[1] <= 1:
        raise ValueError('색 범위는 증가하는 0~1 값 두 개여야 한다.')
    for element, position, rgb in zip(color.color_ramp.elements, positions, (config['color_low'], config['color_high'])):
        if len(rgb) != 3 or not all(math.isfinite(v) and 0 <= v <= 1 for v in rgb):
            raise ValueError('색은 0~1 RGB 세 값이어야 한다.')
        element.position, element.color = position, (*rgb, 1)
    links.new(luminance.outputs[0], color.inputs[0])

    variation = create('ShaderNodeObjectInfo', '부품별 도장 차이', -430, 920)
    variance = create('ShaderNodeMapRange', '도장 차이 강도', -220, 920)
    variance.inputs['To Min'].default_value = .94
    variance.inputs['To Max'].default_value = 1.04
    links.new(variation.outputs['Random'], variance.inputs['Value'])
    tint = create('ShaderNodeMixRGB', '도장과 표면 결', 30, 700)
    tint.blend_type = 'MULTIPLY'
    tint.inputs[0].default_value = 1
    links.new(color.outputs['Color'], tint.inputs[1])
    links.new(variance.outputs['Result'], tint.inputs[2])

    roughness = create('ShaderNodeMapRange', '거칠기 범위', -200, 260)
    roughness.inputs['To Min'].default_value, roughness.inputs['To Max'].default_value = config.get('roughness_range', [.32, .62])
    links.new(textures['roughness'].outputs['Color'], roughness.inputs['Value'])

    normal = create('ShaderNodeBump', '도장 요철', 30, -30)
    normal.inputs['Strength'].default_value = config.get('bump_strength', .35)
    normal.inputs['Distance'].default_value = distance
    links.new(textures['height'].outputs['Color'], normal.inputs['Height'])
    if bevel > 0:
        edge = create('ShaderNodeBevel', '가공 모서리 음영', -200, -260)
        edge.inputs['Radius'].default_value = bevel
        edge.samples = 4
        links.new(edge.outputs['Normal'], normal.inputs['Normal'])

    base_output = tint.outputs['Color']
    roughness_output = roughness.outputs['Result']
    metallic_output = None
    if (config.get('edge_wear', 0) or config.get('fold_lip', 0)) and bevel > 0:
        geometry = create('ShaderNodeNewGeometry', '가공 전 면 법선', -650, -500)
        angle = create('ShaderNodeVectorMath', '모서리 법선 차이', -430, -500)
        angle.operation = 'DOT_PRODUCT'
        links.new(geometry.outputs['Normal'], angle.inputs[0])
        links.new(edge.outputs['Normal'], angle.inputs[1])
        difference = create('ShaderNodeMath', '모서리 마모 범위', -210, -500)
        difference.operation = 'SUBTRACT'
        difference.inputs[0].default_value = 1
        links.new(angle.outputs['Value'], difference.inputs[1])
        gain = create('ShaderNodeMath', '마모 강도', 0, -500)
        gain.operation = 'MULTIPLY'
        gain.use_clamp = True
        gain.inputs[1].default_value = max(config.get('edge_wear', 0), config.get('fold_lip', 0))
        links.new(difference.outputs[0], gain.inputs[0])
        breakup = create('ShaderNodeTexNoise', '접촉 마모 끊김', -430, -760)
        breakup.inputs['Scale'].default_value = 35
        breakup.inputs['Detail'].default_value = 2
        links.new(coord.outputs['Object'], breakup.inputs['Vector'])
        mask = create('ShaderNodeMath', '노출된 모서리', 210, -500)
        mask.operation = 'MULTIPLY'
        links.new(gain.outputs[0], mask.inputs[0])
        links.new(breakup.outputs['Fac'], mask.inputs[1])
        worn = create('ShaderNodeMixRGB', '모서리 노출 금속', 440, 700)
        links.new(mask.outputs[0], worn.inputs[0])
        links.new(base_output, worn.inputs[1])
        worn.inputs[2].default_value = (*config.get('edge_color', [.32, .36, .40]), 1)
        base_output = worn.outputs[0]
        worn_roughness = create('ShaderNodeMixRGB', '마찰면 거칠기', 440, 350)
        links.new(mask.outputs[0], worn_roughness.inputs[0])
        links.new(roughness_output, worn_roughness.inputs[1])
        worn_roughness.inputs[2].default_value = (.28, .28, .28, 1)
        roughness_output = worn_roughness.outputs[0]
        worn_metal = create('ShaderNodeMapRange', '도막 아래 금속', 440, 70)
        worn_metal.inputs['To Min'].default_value = config.get('metallic', 0)
        worn_metal.inputs['To Max'].default_value = .9
        links.new(mask.outputs[0], worn_metal.inputs['Value'])
        metallic_output = worn_metal.outputs['Result']

    normal_output = normal.outputs['Normal']
    if config.get('fold_lip', 0) and bevel > 0:
        lip = create('ShaderNodeBump', '접힌 모서리의 얕은 돌출', 680, -40)
        lip.inputs['Strength'].default_value = .35
        lip.inputs['Distance'].default_value = config.get('fold_lip_distance', .0015)
        links.new(gain.outputs[0], lip.inputs['Height'])
        links.new(normal_output, lip.inputs['Normal'])
        normal_output = lip.outputs['Normal']
    if config.get('panel_detail'):
        panel = config['panel_detail']
        uv = create('ShaderNodeUVMap', '패널 아틀라스 UV', -660, -1100)
        uv.uv_map = panel.get('uv_layer', '')
        panel_textures = {}
        for index, role in enumerate(('color', 'height')):
            path = Path(panel[role]).resolve()
            im = bpy.data.images.load(str(path), check_existing=True)
            im.colorspace_settings.name = 'Non-Color'
            if list(im.size) != [1024, 1024]:
                raise ValueError('패널 도안은 1K로 생성한다.')
            texture = create('ShaderNodeTexImage', '패널 '+role, -430, -1100-index*250)
            texture.image = im
            texture.extension = 'EXTEND'
            links.new(uv.outputs['UV'], texture.inputs['Vector'])
            panel_textures[role] = texture
        layered = create('ShaderNodeMixRGB', '새 패널 도장과 식별 표기', 680, 700)
        layered.blend_type = 'MULTIPLY'
        layered.inputs[0].default_value = panel.get('strength', .85)
        links.new(base_output, layered.inputs[1])
        links.new(panel_textures['color'].outputs['Color'], layered.inputs[2])
        base_output = layered.outputs[0]
        groove = create('ShaderNodeBump', '새 패널 이음 깊이', 680, -280)
        groove.inputs['Strength'].default_value = .65
        groove.inputs['Distance'].default_value = panel.get('distance', .003)
        links.new(panel_textures['height'].outputs['Color'], groove.inputs['Height'])
        links.new(normal_output, groove.inputs['Normal'])
        normal_output = groove.outputs['Normal']

    for socket in ('Base Color', 'Roughness', 'Metallic', 'Normal'):
        for link in list(shader.inputs[socket].links):
            links.remove(link)
    shader.inputs['Metallic'].default_value = config.get('metallic', 0)
    if not 0 <= shader.inputs['Metallic'].default_value <= 1:
        raise ValueError('금속성은 0~1이어야 한다.')
    links.new(base_output, shader.inputs['Base Color'])
    links.new(roughness_output, shader.inputs['Roughness'])
    if metallic_output is not None:
        links.new(metallic_output, shader.inputs['Metallic'])
    links.new(normal_output, shader.inputs['Normal'])
    material.diffuse_color = (*config['color_high'], 1)
    material['surface_source'] = config.get('source', '')
    material['surface_mapping'] = 'object_local_box'
