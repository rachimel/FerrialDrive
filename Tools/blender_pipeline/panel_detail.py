"""장갑면의 로컬 좌표 도안을 기존 UV에 투영한다. 형상과 UV는 수정하지 않는다."""
from pathlib import Path
import math


def panel_pattern(u, v, profile, index):
    import numpy as np

    shade = np.full(u.shape, .96, dtype=np.float32)
    height = np.full(u.shape, .5, dtype=np.float32)
    boxes = {
        'torso': [(.25, .75, .35, .38), (.75, .75, .35, .38)],
        'split': [(.25, .49, .29, .65), (.75, .49, .29, .65)],
        'limb': [(.5, .53, .65, .70)],
        'head': [(.5, .50, .64, .62)],
        'foot': [(.5, .55, .70, .54)],
    }[profile]
    for cx, cy, width, length in boxes:
        x, y = np.abs(u-cx), np.abs(v-cy)
        cut = min(width, length)*.16
        distance = np.maximum(np.maximum(x-width/2, y-length/2),
                              (x+y-width/2-length/2+cut)/math.sqrt(2))
        inside = distance < -.008
        shade[inside] *= .80
        seam = np.abs(distance) < .006
        shade[seam] = .15
        height[seam] = .30
        # 덮개의 한쪽 체결점 두 개와 반대쪽 잠금 레버다.
        for sign in (-1, 1):
            bx, by = cx+sign*width*.31, cy-length*.30
            radius = .009
            screw = (u-bx)**2+(v-by)**2 < radius**2
            rim = ((u-bx)**2+(v-by)**2 < (radius*1.6)**2) & ~screw
            shade[rim] = .58
            shade[screw] = .23
            height[screw] = .38
            slot = screw & (np.abs(v-by) < .0025)
            shade[slot] = .09
        latch = (np.abs(u-(cx+width*.34)) < .012) & (np.abs(v-cy) < .044)
        shade[latch] = .28
        height[latch] = .42
        # 표면 도안은 정비 식별 번호 두 자리만 사용한다.
        digits = ['111101101101111','010110010010111','111001111100111',
                  '111001111001111','101101111001001','111100111001111',
                  '111100111101111','111001001001001','111101111101111','111101111001111']
        for place, number in enumerate((index//10%10, index%10)):
            gx = (u-(cx-width*.29+place*.042))/.010
            gy = ((cy+length*.27)-v)/.012
            ix, iy = np.floor(gx).astype(int), np.floor(gy).astype(int)
            valid = (ix >= 0) & (ix < 3) & (iy >= 0) & (iy < 5)
            glyph = np.array(list(digits[number]), dtype='U1').reshape(5, 3) == '1'
            mark = valid & glyph[np.clip(iy, 0, 4), np.clip(ix, 0, 2)]
            shade[mark] = .18
        noise = (np.sin(u*721+v*413)*np.sin(u*199-v*821))
        wear = (distance > -.018) & (distance < -.007) & (noise > .72)
        shade[wear] = 1
        height[wear] = .48
    return shade, height


def project_panel_uv(config):
    """장갑 패널 전용 UV를 추가한다. 기존 UV·활성 렌더 UV는 유지한다."""
    import bpy
    import numpy as np

    name = config.get('uv_layer', 'UV_Panel')
    for entry in config['objects']:
        mesh = bpy.data.objects[entry['name']].data
        if mesh.uv_layers.get(name):
            raise ValueError(f'이미 존재하는 UV: {entry["name"]}/{name}')
        active = mesh.uv_layers.active_index
        render = next((x.name for x in mesh.uv_layers if x.active_render), None)
        layer = mesh.uv_layers.new(name=name, do_init=False)
        vertices = np.array([v.co[:] for v in mesh.vertices])
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        extent = np.maximum(high-low, 1e-8)
        for polygon in mesh.polygons:
            axis = int(np.argmax(np.abs(polygon.normal[:])))
            key = ('+' if polygon.normal[axis] >= 0 else '-')+'XYZ'[axis]
            x0, y0, x1, y1 = entry['regions'][key]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError('UV 영역은 0~1 안의 유효한 사각형이어야 한다.')
            axes = [i for i in range(3) if i != axis]
            for loop in polygon.loop_indices:
                p = (vertices[mesh.loops[loop].vertex_index]-low)/extent
                u, v = p[axes[0]], p[axes[1]]
                if polygon.normal[axis] < 0:
                    u = 1-u
                layer.data[loop].uv = (x0+u*(x1-x0), y0+v*(y1-y0))
        mesh.uv_layers.active_index = active
        if render:
            mesh.uv_layers[render].active_render = True


def generate_panel_detail(config):
    import bpy
    import numpy as np

    size = int(config.get('size', 1024))
    if not 32 <= size <= 1024:
        raise ValueError('패널 아틀라스 크기는 32~1024다.')
    resolution = size*2
    color = np.full((resolution, resolution), .96, dtype=np.float32)
    height = np.full_like(color, .5)
    covered = np.zeros_like(color, dtype=bool)
    material = config['material']
    touched = 0
    uv_names = set()
    for entry in config['objects']:
        obj = bpy.data.objects[entry['name']]
        mesh = obj.data
        uv = mesh.uv_layers.get(entry.get('uv_layer', '')) or next((x for x in mesh.uv_layers if x.active_render), mesh.uv_layers.active)
        if uv is None:
            raise ValueError(f'UV 없음: {obj.name}')
        uv_names.add(uv.name)
        mesh.calc_loop_triangles()
        vertices = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        extent = np.maximum(high-low, 1e-8)
        for triangle in mesh.loop_triangles:
            slot = triangle.material_index
            if slot >= len(mesh.materials) or mesh.materials[slot].name != material:
                continue
            tex = np.array([uv.data[i].uv[:] for i in triangle.loops], dtype=np.float64)*resolution
            a, b, c = tex
            determinant = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(determinant) < 1e-7:
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
            mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            pos = (w0[..., None]*vertices[triangle.vertices[0]]+
                   w1[..., None]*vertices[triangle.vertices[1]]+
                   w2[..., None]*vertices[triangle.vertices[2]])
            pos = (pos-low)/extent
            axis = entry.get('normal_axis', 0)
            axes = entry.get('axes', [1, 2])
            facing = abs(triangle.normal[axis])
            if facing >= entry.get('min_facing', .45):
                horizontal = pos[..., axes[0]]
                if triangle.normal[axis] < 0:
                    horizontal = 1-horizontal
                pattern, relief = panel_pattern(horizontal, pos[..., axes[1]],
                                                entry.get('profile', 'limb'), entry.get('id', 1))
            else:
                pattern, relief = np.full(w0.shape, .96), np.full(w0.shape, .5)
            region = np.s_[ymin:ymax+1, xmin:xmax+1]
            color[region][mask] = pattern[mask]
            height[region][mask] = relief[mask]
            covered[region][mask] = True
            touched += 1
    if not touched or not np.any(color < .3):
        raise ValueError(f'유효한 패널 도안이 없다: {material}')
    # 텍셀 경계 여백은 도안을 복제하고, UV 바깥을 검정으로 채우지 않는다.
    for _ in range(12):
        new_covered = covered.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = np.roll(covered, (dy, dx), axis=(0, 1)) & ~new_covered
            if dy == 1: neighbor[0, :] = False
            if dy == -1: neighbor[-1, :] = False
            if dx == 1: neighbor[:, 0] = False
            if dx == -1: neighbor[:, -1] = False
            for data in (color, height):
                data[neighbor] = np.roll(data, (dy, dx), axis=(0, 1))[neighbor]
            new_covered |= neighbor
        covered = new_covered
    paths = []
    for role, data in (('color', color), ('height', height)):
        data = data.reshape(size, 2, size, 2).mean(axis=(1, 3))
        rgba = np.empty((size, size, 4), dtype=np.float32)
        rgba[..., :3] = data[..., None]
        rgba[..., 3] = 1
        path = Path(config['output_'+role]).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        image = bpy.data.images.new(path.stem, width=size, height=size, alpha=False)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
        paths.append(str(path))
    print('PANEL_DETAIL', material, 'triangles', touched, 'uv', sorted(uv_names), flush=True)
    return paths
