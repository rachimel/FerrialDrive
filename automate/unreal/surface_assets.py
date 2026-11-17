"""베이크한 재질과 UV 형상을 새 Unreal 후보로 가져온다."""
import json
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def save_skeletal_material(material):
    import unreal
    library=unreal.MaterialEditingLibrary
    usage=unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH
    library.set_base_material_usage(material,usage,True)
    library.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material)
    if not library.has_material_usage(material,usage):
        raise RuntimeError("스켈레탈 메시 재질 설정 저장 실패")


def repair_usage(request):
    import unreal
    root=request["asset_root"]
    if not root.startswith("/Game/MechLab/Surface") or ".." in root:
        raise ValueError("표면 후보 경로만 수정한다.")
    rows=[]
    for folder in ("Materials","Energy"):
        for path in unreal.EditorAssetLibrary.list_assets(root+"/"+folder,recursive=True):
            material=unreal.load_asset(path)
            if isinstance(material,unreal.Material):
                save_skeletal_material(material)
                rows.append(path)
    (ROOT/request["report"]).write_text(json.dumps({"materials":rows,"skeletal_usage":True},indent=2),encoding="utf-8")


def import_file(filename, destination, options=None):
    import unreal
    task = unreal.AssetImportTask()
    task.filename = str(filename)
    task.destination_path = destination
    task.automated = True
    task.save = True
    task.replace_existing = False
    if options:
        task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return [unreal.load_asset(path) for path in task.imported_object_paths]


def make_material(name, row, folder, source):
    import unreal
    library = unreal.MaterialEditingLibrary
    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    material.set_editor_property("use_material_attributes",True)
    attributes = library.create_material_expression(material,unreal.MaterialExpressionMakeMaterialAttributes)
    pins = {str(n).replace(" ","").replace("_","").lower():str(n) for n in library.get_material_expression_input_names(attributes)}
    def connect(node, output, field):
        if not library.connect_material_expressions(node,output,attributes,pins[field]):
            raise RuntimeError("재질 입력 연결 실패: "+field)
    nodes = {}
    for channel, filename in row["maps"].items():
        textures = import_file(source/filename, folder+"/Textures")
        texture = next(t for t in textures if isinstance(t, unreal.Texture2D))
        texture.set_editor_property("srgb", channel == "base_color")
        compression = (unreal.TextureCompressionSettings.TC_NORMALMAP if channel == "normal" else
                       unreal.TextureCompressionSettings.TC_DEFAULT if channel == "base_color" else unreal.TextureCompressionSettings.TC_MASKS)
        texture.set_editor_property("compression_settings", compression)
        if channel == "normal":
            texture.set_editor_property("flip_green_channel", True)
        unreal.EditorAssetLibrary.save_loaded_asset(texture)
        node = library.create_material_expression(material, unreal.MaterialExpressionTextureSampleParameter2D)
        node.set_editor_property("parameter_name", channel)
        node.set_editor_property("texture", texture)
        node.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if channel == "normal" else
                                 unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if channel == "base_color" else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        nodes[channel] = node
    props = {"base_color":"basecolor", "roughness":"roughness", "metallic":"metallic", "normal":"normal", "coat":"clearcoat"}
    if "coat" in nodes or row.get("coat", 0):
        material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    for channel, prop in props.items():
        if channel in nodes:
            connect(nodes[channel], "RGB" if channel in ("base_color", "normal") else "R", prop)
        elif channel != "normal":
            vector = channel == "base_color"
            node = library.create_material_expression(material, unreal.MaterialExpressionConstant3Vector if vector else unreal.MaterialExpressionConstant)
            if vector:
                node.set_editor_property("constant", unreal.LinearColor(*row.get("base_color", [.1,.1,.1,1])))
            else:
                node.set_editor_property("r", row.get(channel,.6 if channel == "roughness" else 0))
            connect(node,"",prop)
    for value, prop in [(row["specular"], "specular"), (row["coat_roughness"],"clearcoatroughness")]:
        node = library.create_material_expression(material,unreal.MaterialExpressionConstant)
        node.set_editor_property("r",value)
        connect(node,"",prop)
    color = library.create_material_expression(material,unreal.MaterialExpressionVectorParameter)
    color.set_editor_property("parameter_name","EnergyColor")
    color.set_editor_property("default_value",unreal.LinearColor(*row["energy_color"]))
    strength = library.create_material_expression(material,unreal.MaterialExpressionScalarParameter)
    strength.set_editor_property("parameter_name","EnergyStrength")
    strength.set_editor_property("default_value",row["energy_strength"])
    multiply = library.create_material_expression(material,unreal.MaterialExpressionMultiply)
    library.connect_material_expressions(color,"",multiply,"A")
    library.connect_material_expressions(strength,"",multiply,"B")
    if "energy_mask" in nodes:
        masked = library.create_material_expression(material,unreal.MaterialExpressionMultiply)
        library.connect_material_expressions(multiply,"",masked,"A")
        library.connect_material_expressions(nodes["energy_mask"],"R",masked,"B")
        multiply = masked
    connect(multiply,"","emissivecolor")
    if not library.connect_material_property(attributes,"",unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES):
        raise RuntimeError("재질 출력 연결 실패")
    save_skeletal_material(material)
    return material


def make_energy_material(name,row,folder,lit_folder):
    import unreal
    library=unreal.MaterialEditingLibrary
    material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,folder,unreal.Material,unreal.MaterialFactoryNew())
    material.set_editor_property("shading_model",unreal.MaterialShadingModel.MSM_UNLIT)
    if row["maps"].get("energy_mask"):
        texture=unreal.load_asset(lit_folder+"/Textures/"+Path(row["maps"]["energy_mask"]).stem)
        node=library.create_material_expression(material,unreal.MaterialExpressionTextureSampleParameter2D)
        node.set_editor_property("parameter_name","EnergyMask")
        node.set_editor_property("texture",texture)
        node.set_editor_property("sampler_type",unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        output="R"
    else:
        node=library.create_material_expression(material,unreal.MaterialExpressionConstant)
        node.set_editor_property("r",1 if row["energy_strength"]>0 else 0)
        output=""
    library.connect_material_property(node,output,unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    save_skeletal_material(material)
    return material


def create(request):
    import unreal
    from rig_workspace import assemble_rigid_mesh
    from render_units import prepare
    source = (ROOT/request["surface"]).resolve()
    data = json.loads((source/"surface.json").read_text(encoding="utf-8"))
    prefix = request["asset_root"]
    if not prefix.startswith("/Game/MechLab/Surface") or ".." in prefix or unreal.EditorAssetLibrary.list_assets(prefix,recursive=True):
        raise ValueError("새 표면 후보 전용 경로가 필요하다.")
    pipeline = unreal.FbxImportUI()
    pipeline.import_as_skeletal = False
    pipeline.import_mesh = True
    pipeline.import_materials = False
    pipeline.import_textures = False
    pipeline.static_mesh_import_data.combine_meshes = False
    pipeline.static_mesh_import_data.set_editor_property("auto_generate_collision",False)
    pipeline.static_mesh_import_data.normal_import_method=unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    flag = "Interchange.FeatureFlags.Import.FBX"
    previous = unreal.SystemLibrary.get_console_variable_int_value(flag)
    unreal.SystemLibrary.execute_console_command(None,flag+" 0")
    try:
        if request.get("reuse_geometry_root"):
            imported = [unreal.load_asset(p) for p in unreal.EditorAssetLibrary.list_assets(request["reuse_geometry_root"],recursive=True)]
        else:
            imported = import_file(source/data["fbx"],prefix+"/Geometry",pipeline)
    finally:
        unreal.SystemLibrary.execute_console_command(None,flag+" "+str(previous))
    meshes = [asset for asset in imported if isinstance(asset,unreal.StaticMesh)]
    materials = {name:(unreal.load_asset(request["reuse_material_root"]+"/M_"+str(index).zfill(2)) if request.get("reuse_material_root") else
                       make_material("M_"+str(index).zfill(2),row,prefix+"/Materials",source))
                 for index,(name,row) in enumerate(data["materials"].items())}
    masks = {name:make_energy_material("EM_"+str(index).zfill(2),row,prefix+"/Energy",request.get("reuse_material_root",prefix+"/Materials"))
             for index,(name,row) in enumerate(data["materials"].items())}
    raw_images={}
    if request.get("source_images"):
        manifest=(ROOT/request["source_images"]).resolve()
        raw=json.loads(manifest.read_text(encoding="utf-8"))
        for row in raw["source_images"]:
            path=(manifest.parent/row["file"]).resolve()
            if not path.is_relative_to(manifest.parent) or hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:
                raise ValueError("원본 이미지 해시·경로 불일치")
            assets=import_file(path,prefix+"/SourceTextures")
            texture=next(asset for asset in assets if isinstance(asset,unreal.Texture2D))
            texture.set_editor_property("srgb",row["colorspace"]=="sRGB")
            normal="normal" in row["name"].lower()
            texture.set_editor_property("compression_settings",unreal.TextureCompressionSettings.TC_NORMALMAP if normal else
                                       unreal.TextureCompressionSettings.TC_DEFAULT if row["colorspace"]=="sRGB" else unreal.TextureCompressionSettings.TC_MASKS)
            if normal:
                texture.set_editor_property("flip_green_channel",True)
            unreal.EditorAssetLibrary.set_metadata_tag(texture,"FD_SourceSHA256",row["sha256"])
            unreal.EditorAssetLibrary.set_metadata_tag(texture,"FD_SourceImage",row["name"])
            unreal.EditorAssetLibrary.save_loaded_asset(texture)
            raw_images[row["name"]]=texture.get_path_name()
    plan = json.loads((ROOT/request["rig_plan"]).read_text(encoding="utf-8"))
    lookup = {p["id"]:p for p in plan["parts"]}
    mapping = []
    for part in data["parts"]:
        matches = [mesh for mesh in meshes if mesh.get_name().endswith(part["id"])]
        if len(matches)!=1:
            raise RuntimeError("형상 대응 실패: "+part["id"])
        mesh = matches[0]
        old_geometry = unreal.load_asset(lookup[part["id"]]["asset"])
        a,b = mesh.get_bounds(),old_geometry.get_bounds()
        error = max(abs(getattr(v,k)-getattr(w,k)) for v,w in [(a.origin,b.origin),(a.box_extent,b.box_extent)] for k in ("x","y","z"))
        if error>.05:
            raise ValueError("형상 좌표 변경: "+part["id"]+" "+str(error))
        for index,slot in enumerate(mesh.get_editor_property("static_materials")):
            slot_name = str(slot.get_editor_property("imported_material_slot_name"))
            if slot_name not in materials:
                raise ValueError("재질 슬롯 대응 실패: "+slot_name)
            mesh.set_material(index,materials[slot_name])
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        lookup[part["id"]]["asset"] = mesh.get_path_name()
        mapping.append({"id":part["id"],"asset":mesh.get_path_name(),"slots":len(mesh.get_editor_property("static_materials"))})
    if len(meshes)!=len(plan["parts"]):
        raise ValueError("형상 개수 불일치")
    old = unreal.load_asset(request["source_mesh"])
    modifier = unreal.SkeletonModifier()
    modifier.set_skeletal_mesh(old)
    names = [str(n) for n in modifier.get_all_bone_names()]
    full,_ = assemble_rigid_mesh(plan["parts"],old.skeleton,names,prefix+"/SK_Surface")
    plan_path = ROOT/request["output_plan"]
    plan_path.write_text(json.dumps(plan,indent=2),encoding="utf-8")
    scene = {**request["scene"],"source_mesh":full.get_path_name(),"rig_plan":request["output_plan"]}
    scene["energy_materials"]={materials[name].get_path_name():masks[name].get_path_name() for name in materials}
    scene.pop("reuse_mesh_root",None)
    if request.get("source_lighting"):
        from lighting_transfer import normalize_lights
        lights=normalize_lights(data["lights"],request["source_root_matrix"]) if request.get("source_root_matrix") else data["lights"]
        lighting = {"source_lights":lights,"power_scale":request.get("light_power_scale",1.0),
                    "strength_mapping":"source_power_times_scale_lumens", "calibration":"candidate",
                    "area_shape_approximation":any(light["shape"] not in ("RECTANGLE","SQUARE") for light in data["lights"])}
        if data.get("environment"):
            environment = import_file(source/data["environment"],prefix+"/Lighting")
            cube = next(asset for asset in environment if isinstance(asset,unreal.TextureCube))
            lighting["environment"] = cube.get_path_name()
        scene["lighting"] = lighting
    prepare(scene)
    if not data["partial"] and scene.get("animation"):
        animation=unreal.load_asset(scene["animation"])
        animation.set_preview_skeletal_mesh(full)
        unreal.EditorAssetLibrary.save_loaded_asset(animation)
    report={"mesh":full.get_path_name(),"materials":{name:m.get_path_name() for name,m in materials.items()},
            "parts":mapping,"skeleton":old.skeleton.get_path_name(),"source_images":raw_images,
            "scene_report":scene["report"],"partial":data["partial"]}
    (ROOT/request["report"]).write_text(json.dumps(report,indent=2),encoding="utf-8")


if __name__=="__main__":
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import unreal
    request=json.loads(Path(os.environ["FD_UNITS_REQUEST"]).read_text(encoding="utf-8-sig"))
    target=ROOT/request["report"]
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        repair_usage(request) if request["operation"] == "surface_usage" else create(request)
    except Exception:
        import traceback
        target.with_suffix(".error.txt").write_text(traceback.format_exc(),encoding="utf-8")
    unreal.SystemLibrary.quit_editor()
