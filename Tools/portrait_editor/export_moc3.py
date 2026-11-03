"""Minimal Blender keyform -> moc3 4.2 bridge for this experiment.

SPDX-License-Identifier: GPL-3.0-or-later
Layout/serialization adapted from Ayatsuri2D's moc3_export.rs, GPL-3.0,
Copyright Yoru_KenomoVT and Ayatsuri2D contributors.
Upstream source and license are retained in vendor/ayatsuri_2d.
Supports textured meshes, drawable clipping masks, a sampled smile axis and
opacity. This is intentionally not a general Blender rig exporter.
"""
from pathlib import Path
import json
import struct
import argparse
import os

from asset_paths import ROOT, RIG_DIR, EXPORT_DIR
OUT = EXPORT_DIR / 'exported'

def packed(fmt, values):
    return struct.pack('<' + fmt * len(values), *values)

def ids(names):
    return b''.join(n.encode('ascii')[:63].ljust(64,b'\0') for n in names)

def export(source, output_dir=OUT):
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    meshes=source['meshes']; n=len(meshes)
    parameter_keys=source.get('parameter_keys',[0,1])
    if len(parameter_keys)<2 or any(a>=b for a,b in zip(parameter_keys,parameter_keys[1:])):
        raise ValueError('Parameter keys must be strictly increasing')
    sections={}
    I=lambda slot,values: sections.__setitem__(slot,packed('i',values))
    F=lambda slot,values: sections.__setitem__(slot,packed('f',values))
    # One static keyform binding and one binding to the sampled ParamSmile axis.
    coords=[];uv=[];indices=[];starts=[];uvstarts=[];idxstarts=[]
    kfstarts=[];kcounts=[];opacities=[];orders=[];bindings=[]
    mask_starts=[];mask_counts=[];mask_pool=[]
    mesh_indices={mesh['id']:i for i,mesh in enumerate(meshes)}
    for mesh in meshes:
        animated=mesh.get('animated',False)
        keys=mesh.get('forms',[mesh['neutral'],mesh['smile']]) if animated else [mesh['neutral']]
        if animated and len(keys)!=len(parameter_keys):
            raise ValueError(f"{mesh['id']}: keyform count does not match parameter keys")
        alpha=mesh.get('opacities',mesh.get('opacity',[1,1]))
        if any(len(form)!=len(mesh['neutral']) for form in keys):
            raise ValueError(f"{mesh['id']}: keyform vertex count changed")
        bindings.append(1 if animated else 0)
        kfstarts.append(len(opacities)); kcounts.append(len(keys))
        uvstarts.append(len(uv));uv.extend(mesh['uv'])
        idxstarts.append(len(indices));indices.extend(mesh['triangles'])
        masks=[mesh_indices[m] if isinstance(m,str) else int(m) for m in mesh.get('masks',[])]
        if any(m<0 or m>=n or m==mesh_indices[mesh['id']] for m in masks):
            raise ValueError(f"{mesh['id']}: invalid clipping mask")
        mask_starts.append(len(mask_pool));mask_counts.append(len(masks));mask_pool.extend(masks)
        for k,vertices in enumerate(keys):
            starts.append(len(coords));coords.extend(vertices)
            opacities.append(alpha[k])
            orders.append(float(mesh['order']))
    nk=len(opacities)
    counts=[0]*32
    for index,value in {4:n,5:1,9:nk,10:len(coords),11:1,12:2,13:1,14:len(parameter_keys)*2,15:len(uv),16:len(indices),17:len(mask_pool),18:1,19:n,23:nk,24:nk}.items(): counts[index]=value
    I(0,counts)
    w,h=source['canvas']
    sections[1]=packed('f',[100,w/2,h/2,w,h])+bytes(44)
    for slot in range(29,33): sections[slot]=bytes(n*8)
    sections[33]=ids([m['id'] for m in meshes])
    I(34,bindings);I(35,kfstarts);I(36,kcounts);I(37,[1]*n);I(38,[1]*n)
    I(39,[-1]*n);I(40,[-1]*n);I(41,[m['texture'] for m in meshes])
    sections[42]=bytes([4]*n)  # double-sided normal blend
    I(43,[len(m['neutral'])//2 for m in meshes]);I(44,uvstarts)
    I(45,idxstarts);I(46,[len(m['triangles']) for m in meshes]);I(47,mask_starts);I(48,mask_counts)
    sections[49]=bytes(8);sections[50]=ids(['ParamSmile'])
    F(51,[1]);F(52,[0]);F(53,[0]);I(54,[0]);I(55,[2]);I(56,[0]);I(57,[1])
    F(68,opacities);F(69,orders);I(70,starts)
    # moc3 authoring coordinates and UVs use a top-down canvas; Blender uses up.
    F(71,[c/100 if i%2==0 else -c/100 for i,c in enumerate(coords)])
    I(72,[0]);I(73,[0,0]);I(74,[0,1]);I(75,[0]);I(76,[len(parameter_keys)]);F(77,parameter_keys*2)
    F(78,[c if i%2==0 else 1-c for i,c in enumerate(uv)]);sections[79]=packed('h',indices)
    I(80,mask_pool)
    I(81,[0]);I(82,[n]);I(83,[n]);I(84,[int(max(orders))]);I(85,[int(min(orders))])
    I(86,[0]*n);I(87,list(range(n)));I(88,[-1]*n)
    sections[102]=bytes(8);I(103,[len(parameter_keys)]);I(104,[len(parameter_keys)]);I(107,kfstarts)
    for slot in range(108,111): F(slot,[1]*nk)
    for slot in range(111,114): F(slot,[0]*nk)
    I(114,[0]);I(115,[-1]);I(116,[0])
    # Version 4 = Cubism 4.2; 480 section offsets, each aligned to 32 bytes.
    data=bytearray(0x40+480*4)
    data[:6]=b'MOC3\x04\0'
    for slot in range(137):
        while len(data)%32:data.append(0)
        struct.pack_into('<I',data,0x40+slot*4,len(data))
        data.extend(sections.get(slot,b''))
    while len(data)%64:data.append(0)
    (output_dir/'character.moc3').write_bytes(data)
    model={'Version':3,'FileReferences':{'Moc':'character.moc3','Textures':source['textures']},'Groups':[]}
    (output_dir/'character.model3.json').write_text(json.dumps(model,indent=2),encoding='utf-8')
    print(json.dumps({'moc_bytes':len(data),'meshes':n,'keyforms':nk,'parameter':'ParamSmile'}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=RIG_DIR/'blender-keyforms.json')
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args()
    source=json.loads(args.source.read_text(encoding='utf-8'))
    source['textures']=[os.path.relpath(args.source.resolve().parent/p,args.output.resolve()).replace('\\','/') for p in source['textures']]
    export(source,args.output)
