"""실제 메시 경계·급격한 꺾임을 1K 마스크로 만들고 선택한 외장에만 적용한다."""
from pathlib import Path
import math


def generate_boundary_texture(config):
    import bpy
    import numpy as np

    size = int(config.get('size', 1024))
    width = config.get('width', .006)
    angle = config.get('min_angle_degrees', 32)
    if not 32 <= size <= 1024 or not math.isfinite(width) or width <= 0 or not 0 < angle < 180:
        raise ValueError('유효한 크기·양수 선 폭·0~180도 경계각이 필요하다.')
    names = config['objects']
    if not names:
        raise ValueError('경계 마스크 대상이 없다.')
    objects = [bpy.data.objects[name] for name in names]
    if any(obj.type != 'MESH' or obj.data.users != 1 for obj in objects):
        raise ValueError('독립된 메시 데이터만 지원한다.')
    uv_name = config.get('uv_layer', 'UV_Boundary')
    attribute_name = config.get('attribute', 'boundary_detail_enabled')
    for name in config.get('disable_objects',[]):
        if name in names:
            raise ValueError('적용/해제 대상이 겹친다.')
        disabled = bpy.data.objects[name].data.attributes.get(attribute_name)
        if disabled:
            disabled.data.foreach_set('value',np.zeros(len(disabled.data),dtype=np.float32))
    previous = {obj.name: (obj.data.uv_layers.active_index,
                next((uv.name for uv in obj.data.uv_layers if uv.active_render), None)) for obj in objects}
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        if (obj.data.uv_layers.get(uv_name) or obj.data.attributes.get(attribute_name)) and not config.get('overwrite',False):
            raise ValueError('기존 경계 UV/속성을 임의로 덮어쓰지 않는다.')
        layer = obj.data.uv_layers.get(uv_name) or obj.data.uv_layers.new(name=uv_name)
        obj.data.uv_layers.active = layer
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.008,
                             area_weight=.5, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    resolution = size*2
    mask_image = np.zeros((resolution, resolution), dtype=np.float32)
    coverage = np.zeros_like(mask_image, dtype=bool)
    edge_counts = {}
    minimum_uv_faces = 0
    cosine = math.cos(math.radians(angle))
    for obj in objects:
        line_width = config.get('width_overrides',{}).get(obj.name,width)
        if not math.isfinite(line_width) or line_width <= 0:
            raise ValueError('개별 선 폭은 양수여야 한다.')
        mesh = obj.data
        layer = mesh.uv_layers[uv_name]
        vertex = np.array([obj.matrix_world @ v.co for v in mesh.vertices], dtype=np.float64)
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        normals = [(normal_matrix @ p.normal).normalized() for p in mesh.polygons]
        face_filter = config.get('face_filters',{}).get(obj.name,{})
        bounds_low, bounds_high = vertex.min(axis=0), vertex.max(axis=0)
        def accepted(polygon):
            axis = face_filter.get('normal_axis')
            if axis is not None and abs(normals[polygon.index][axis]) < face_filter.get('min_abs_normal',0):
                return False
            position_axis = face_filter.get('position_axis')
            if position_axis is not None:
                extent = max(bounds_high[position_axis]-bounds_low[position_axis],1e-8)
                fraction = (vertex[list(polygon.vertices),position_axis].mean()-bounds_low[position_axis])/extent
                outer = face_filter.get('outer_fraction',.25)
                if outer < fraction < 1-outer:
                    return False
            return True
        edge_faces = {}
        for polygon in mesh.polygons:
            for key in polygon.edge_keys:
                edge_faces.setdefault(tuple(sorted(key)), []).append(polygon.index)
        sharp = {key for key, faces in edge_faces.items()
                 if len(faces) != 2 or normals[faces[0]].dot(normals[faces[1]]) < cosine}
        edge_counts[obj.name] = len(sharp)
        mesh.calc_loop_triangles()
        # 이미 거의 일직선인 미세 면도 새 UV에서는 최소 텍셀 면적을 갖게 한다.
        for triangle in mesh.loop_triangles:
            coords = [layer.data[i].uv.copy() for i in triangle.loops]
            if abs((coords[1]-coords[0]).cross(coords[2]-coords[0])) < 1e-12:
                half = .25/size
                center = np.clip(np.mean(np.array(coords),axis=0),half,1-half)
                for loop,offset in zip(triangle.loops,((-half,-half),(half,-half),(0,half))):
                    layer.data[loop].uv = center+offset
                minimum_uv_faces += 1
        for triangle in mesh.loop_triangles:
            polygon = mesh.polygons[triangle.polygon_index]
            borders = [key for key in polygon.edge_keys if tuple(sorted(key)) in sharp] if accepted(polygon) else []
            tex = np.array([layer.data[i].uv[:] for i in triangle.loops])*resolution
            a, b, c = tex
            determinant = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(determinant) < 1e-8:
                continue
            xmin, ymin = np.maximum(np.floor(tex.min(axis=0)).astype(int), 0)
            xmax, ymax = np.minimum(np.ceil(tex.max(axis=0)).astype(int), resolution-1)
            if xmin > xmax or ymin > ymax:
                continue
            yy, xx = np.mgrid[ymin:ymax+1, xmin:xmax+1]
            xx, yy = xx+.5, yy+.5
            w0 = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/determinant
            w1 = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/determinant
            w2 = 1-w0-w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            region = np.s_[ymin:ymax+1, xmin:xmax+1]
            coverage[region][inside] = True
            if not borders:
                continue
            p = sum(w[..., None]*vertex[v] for w, v in zip((w0, w1, w2), triangle.vertices))
            distance = np.full(w0.shape, np.inf)
            for v0, v1 in borders:
                start, delta = vertex[v0], vertex[v1]-vertex[v0]
                length_squared = float(delta.dot(delta))
                if length_squared <= 1e-16:
                    continue
                parameter = np.clip(np.sum((p-start)*delta, axis=-1)/length_squared, 0, 1)
                distance = np.minimum(distance, np.linalg.norm(p-start-parameter[..., None]*delta, axis=-1))
            line = 1-np.clip((distance-line_width*.60)/(line_width*.40), 0, 1)
            current = mask_image[region]
            current[inside] = np.maximum(current[inside], line[inside])
        attribute = mesh.attributes.get(attribute_name) or mesh.attributes.new(attribute_name, 'FLOAT', 'CORNER')
        if attribute.domain != 'CORNER' or attribute.data_type != 'FLOAT':
            raise ValueError('경계 적용 속성 형식이 다르다.')
        attribute.data.foreach_set('value', np.ones(len(mesh.loops), dtype=np.float32))
        active, render = previous[obj.name]
        mesh.uv_layers.active_index = active
        if render:
            mesh.uv_layers[render].active_render = True
    for _ in range(6):
        expanded = coverage.copy()
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
            neighbor = np.roll(coverage, (dy, dx), axis=(0,1)) & ~expanded
            if dy == 1: neighbor[0,:] = False
            if dy == -1: neighbor[-1,:] = False
            if dx == 1: neighbor[:,0] = False
            if dx == -1: neighbor[:,-1] = False
            mask_image[neighbor] = np.roll(mask_image, (dy,dx), axis=(0,1))[neighbor]
            expanded |= neighbor
        coverage = expanded
    pixels = mask_image.reshape(size,2,size,2).mean(axis=(1,3))
    if not np.any(pixels > .1):
        raise ValueError('유효한 경계선이 생성되지 않았다.')
    rgba = np.ones((size,size,4), dtype=np.float32)
    rgba[...,:3] = pixels[...,None]
    path = Path(config['output']).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    image = next((im for im in bpy.data.images if im.filepath and Path(bpy.path.abspath(im.filepath)).resolve()==path),None)
    if image is None:
        image = bpy.data.images.new(path.stem, width=size, height=size, alpha=False)
    elif list(image.size) != [size,size]:
        image.scale(size,size)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(rgba.ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    if image.packed_file:
        image.pack()
    print('BOUNDARY_MASK', edge_counts, 'minimum_uv_faces', minimum_uv_faces, flush=True)


def apply_boundary_texture(config):
    import bpy

    material = bpy.data.materials[config['material']]
    tree = material.node_tree
    shaders = [node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED']
    if len(shaders) != 1:
        raise ValueError('Principled BSDF 하나인 재질만 지원한다.')
    shader = shaders[0]
    if not shader.inputs['Base Color'].is_linked:
        raise ValueError('색 입력이 연결된 표면 재질에 적용한다.')
    intensity = config.get('strength', .75)
    if not math.isfinite(intensity) or not 0 <= intensity <= 1:
        raise ValueError('선 강도는 0~1이어야 한다.')
    image = bpy.data.images.load(str(Path(config['image']).resolve()), check_existing=True)
    if not all(image.size) or max(image.size) > 1024:
        raise ValueError('유효한 1K 이하 경계 마스크가 필요하다.')
    prefix = 'BoundaryDetail::'
    existing = tree.nodes.get(prefix+'구분선 도장')
    base = (existing.inputs[1].links[0].from_socket if existing else shader.inputs['Base Color'].links[0].from_socket)
    for node in list(tree.nodes):
        if node.name.startswith(prefix):
            tree.nodes.remove(node)
    def node(kind, name, x, y):
        value = tree.nodes.new(kind)
        value.name = prefix+name
        value.label = name
        value.location = (x,y)
        return value
    texture = node('ShaderNodeTexImage','경계 마스크',900,900)
    texture.image = image
    texture.image.colorspace_settings.name = 'Non-Color'
    texture.extension = 'EXTEND'
    uv = node('ShaderNodeUVMap','경계 전용 UV',650,900)
    uv.uv_map = config.get('uv_layer','UV_Boundary')
    tree.links.new(uv.outputs['UV'], texture.inputs['Vector'])
    enabled = node('ShaderNodeAttribute','지정 외장만 적용',650,650)
    enabled.attribute_name = config.get('attribute','boundary_detail_enabled')
    factor = node('ShaderNodeMath','구분선 선택',1130,850)
    factor.operation = 'MULTIPLY'
    tree.links.new(texture.outputs['Color'],factor.inputs[0])
    tree.links.new(enabled.outputs['Fac'],factor.inputs[1])
    strength = node('ShaderNodeMath','구분선 강도',1330,850)
    strength.operation = 'MULTIPLY'
    strength.inputs[1].default_value = intensity
    tree.links.new(factor.outputs[0],strength.inputs[0])
    mix = node('ShaderNodeMixRGB','구분선 도장',1540,850)
    tree.links.new(strength.outputs[0],mix.inputs[0])
    tree.links.new(base,mix.inputs[1])
    mix.inputs[2].default_value = (*config.get('color',[.004,.006,.009]),1)
    tree.links.new(mix.outputs[0],shader.inputs['Base Color'])
