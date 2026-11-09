"""Asset Tool의 단일 창 편집을 위한 비표시 Blender 작업자."""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view
from Tools.pose_tool import scene as engine
from Tools.pose_tool.profile import load_profile


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class PoseWorker:
    def __init__(self, config, directory):
        self.directory = directory
        self.work = Path(config["work"]).resolve()
        self.dirty = False
        self.file_dirty = False
        self.exported = None
        if config.get("sample"):
            from samples.pose_tool.make_sample import create_sample
            create_sample()
            source = self.work.parent / "sample_source.blend"
            if source.exists():
                raise FileExistsError(source)
            source.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(source))
        else:
            source = Path(config["source"]).resolve()
            bpy.ops.wm.open_mainfile(filepath=str(source))
        self.opened_source = str(source)
        if engine.STATE not in bpy.context.scene:
            metadata = source.parent / "clips.json"
            engine.prepare(load_profile(config.get("profile")), source,
                           json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else None)
        engine.upgrade_palm_handles()
        if config.get("clip") and any(c["name"] == config["clip"] for c in engine.state()["clips"]):
            engine.activate_clip(config["clip"])
        if self.work.exists() and self.work != source:
            raise FileExistsError(self.work)
        engine.save_work(self.work)
        self.configure_camera()

    def configure_camera(self):
        scene = bpy.context.scene
        rig, _ = engine.rig_objects()
        points = [rig.matrix_world @ b.head for b in rig.pose.bones]
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        self.center = (low+high)*.5
        self.scale = max((high-low).length*1.25, 1)
        camera_data = bpy.data.cameras.new(engine.PREFIX + "PreviewCamera")
        self.camera = bpy.data.objects.new(engine.PREFIX + "PreviewCamera", camera_data)
        scene.collection.objects.link(self.camera)
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = self.scale
        camera_data.clip_end = 10000
        scene.camera = self.camera
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x, scene.render.resolution_y = 640, 560
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.film_transparent = True
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = "BOTH"
        scene.display.render_aa = "8"
        self.view("oblique")

    def view(self, name):
        directions = {"oblique": (6, -8, 3), "front": (8, 0, 0), "side": (0, -8, 0),
                      "back": (-8, 0, 0), "top": (.001, 0, 8)}
        direction = Vector(directions[name]).normalized()
        self.camera.location = self.center + direction*self.scale*3
        self.camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
        engine.update()

    def require_key(self):
        if self.dirty:
            raise ValueError("현재 포즈 키를 저장한 뒤 프레임·동작을 변경한다.")

    def execute(self, request):
        command = request["command"]
        ctrls = engine.controls()
        if command in ("move", "rotate", "bend"):
            obj = ctrls[request["control"]]
            if obj.constraints.get(engine.PREFIX + "Support"):
                raise ValueError("보조손 고정을 해제하거나 주 손을 움직인다.")
            if command in ("move", "bend"):
                location = request["world"]
                if len(location) != 3 or not all(math.isfinite(v) for v in location):
                    raise ValueError("유한한 목표 위치가 필요하다.")
                matrix = obj.matrix_world.copy()
                if command == "bend":
                    limb = engine.state()["profile"]["limbs"][request["control"].removeprefix("pole.")]
                    rig, _ = engine.rig_objects()
                    worlds = engine.world_bones(rig)
                    origin = worlds[limb["upper"]].translation
                    axis = (worlds[limb["end"]].translation-origin).normalized()
                    current = worlds[limb["lower"]].translation-origin
                    desired = Vector(location)-origin
                    current -= axis*current.dot(axis)
                    desired -= axis*desired.dot(axis)
                    if current.length < 1e-5 or desired.length < 1e-5:
                        raise ValueError("관절이 완전히 펴졌다. 골반·손·발 위치로 먼저 굽힘을 만든다.")
                    angle = math.atan2(axis.dot(current.cross(desired)), current.dot(desired))
                    matrix.translation = origin + Matrix.Rotation(angle, 3, axis) @ (matrix.translation-origin)
                else:
                    matrix.translation = Vector(location)
                obj.matrix_world = matrix
            else:
                axis, degrees = request["axis"], float(request["degrees"])
                if axis not in "XYZ" or not math.isfinite(degrees) or abs(degrees) > 180:
                    raise ValueError("회전축/회전각 오류")
                matrix = obj.matrix_world.copy()
                rotation = Matrix.Rotation(math.radians(degrees), 4, axis)
                obj.matrix_world = Matrix.Translation(matrix.translation) @ rotation @ Matrix.Translation(-matrix.translation) @ matrix
            self.dirty = self.file_dirty = True
        elif command == "frame":
            self.require_key()
            scene = bpy.context.scene
            frame = int(request["frame"])
            if not scene.frame_start <= frame <= scene.frame_end:
                raise ValueError("현재 동작 범위 밖의 프레임")
            scene.frame_set(frame)
        elif command == "clip":
            self.require_key()
            engine.activate_clip(request["name"])
            self.exported = None
            self.file_dirty = True
        elif command == "key":
            engine.key_pose()
            self.dirty, self.file_dirty = False, True
        elif command == "save":
            engine.key_pose()
            engine.save_work(self.work)
            self.dirty = self.file_dirty = False
        elif command == "mirror":
            engine.mirror_pose(request["direction"])
            self.dirty = self.file_dirty = True
        elif command == "support":
            engine.support_pin(bool(request["enabled"]))
            self.dirty = self.file_dirty = True
        elif command == "equipment":
            spec = engine.state()["profile"]["equipment"]
            obj = bpy.data.objects.get(spec["object"])
            prop = request["property"]
            if not obj or prop not in spec["properties"] or prop not in obj:
                raise ValueError("무기 속성 없음")
            obj[prop] = float(request["value"])
            obj.update_tag()
            self.dirty = self.file_dirty = True
        elif command == "view":
            self.view(request["name"])
        elif command == "zoom":
            self.camera.data.ortho_scale = max(.2, min(self.scale*5, self.camera.data.ortho_scale*float(request["factor"])))
        elif command == "export":
            engine.key_pose()
            engine.save_work(self.work)
            destination = self.work.parent / ("export_" + str(request["seq"]))
            manifest = engine.export_clip(destination)
            from Tools.blender_pipeline.animation_pipeline import bake
            try:
                bake(manifest, destination / "baked")
            finally:
                bpy.ops.wm.open_mainfile(filepath=str(self.work))
                self.configure_camera()
            self.exported = str(destination / "baked/export_configs" / (engine.state()["active"] + ".json"))
            preset_path = Path(self.exported)
            preset = json.loads(preset_path.read_text(encoding="utf-8"))
            preset["frame_size_pixels"] = [240, 240]
            preset_path.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8")
            self.dirty = self.file_dirty = False
        elif command == "refresh":
            pass
        else:
            raise ValueError(f"지원하지 않는 포즈 명령: {command}")
        engine.update()

    def snapshot(self):
        scene, data = bpy.context.scene, engine.state()
        project = lambda point: list(world_to_camera_view(scene, self.camera, point))
        rig, proxy = engine.rig_objects()
        worlds = engine.world_bones(rig)
        points = {}
        for key, obj in engine.controls().items():
            point = obj.matrix_world.translation
            if key.startswith("pole."):
                limb = data["profile"]["limbs"][key.removeprefix("pole.")]
                joint = worlds[limb["lower"]].translation
                points[key] = {"world": list(joint), "uv": project(joint),
                               "pole_world": list(point), "pole_uv": project(point)}
            else:
                points[key] = {"world": list(point), "uv": project(point)}
        equipment = data["profile"].get("equipment", {})
        eq = bpy.data.objects.get(equipment.get("object", ""))
        errors = {}
        for key, limb in data["profile"]["limbs"].items():
            target = proxy.pose.bones[limb["lower"]].constraints[engine.PREFIX + "IK"].target
            errors[key] = (worlds[limb["end"]].translation-target.matrix_world.translation).length
        camera_up = self.camera.matrix_world.to_3x3().col[1]
        vertical_span = 1 / abs(project(self.center+camera_up)[1]-project(self.center)[1])
        return {"source": self.opened_source, "work": str(self.work), "clips": data["clips"], "active": data["active"],
                "frame": scene.frame_current, "start": scene.frame_start, "end": scene.frame_end,
                "points": points, "right": list(self.camera.matrix_world.to_3x3().col[0]),
                "up": list(camera_up), "scale": vertical_span,
                "dirty": self.dirty, "file_dirty": self.file_dirty, "errors": errors,
                "equipment": {p: eq[p] for p in equipment.get("properties", []) if eq and p in eq},
                "support": any(o.constraints.get(engine.PREFIX+"Support") for o in engine.controls().values()),
                "exported": self.exported}

    def render(self):
        path = self.directory / "preview_next.png"
        scene = bpy.context.scene
        scene.render.filepath = str(path)
        # 렌더가 현재 프레임을 재평가하므로 편집 작업자의 메모리 Action에도
        # 미확정 키를 둔다. 명시적인 키 저장 전에는 프레임 전환을 막고,
        # 파일은 작업본 저장 명령에서만 갱신한다.
        if self.dirty:
            engine.key_pose()
        bpy.ops.render.render(write_still=True)
        for attempt in range(50):
            try:
                os.replace(path, self.directory / "preview.png")
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(.01)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    directory = args.session.resolve().parent
    worker = None
    sequence = 0
    try:
        worker = PoseWorker(json.loads(args.session.read_text(encoding="utf-8")), directory)
        worker.render()
        write_json(directory / "reply_0.json", {"seq": 0, "ok": True, "state": worker.snapshot()})
    except Exception as error:
        write_json(directory / "reply_0.json", {"seq": 0, "ok": False, "error": str(error)})
        raise
    while not (directory / "stop").exists():
        request_path = directory / f"request_{sequence+1}.json"
        if not request_path.exists():
            time.sleep(.025)
            continue
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request["seq"] <= sequence:
            time.sleep(.025)
            continue
        sequence = request["seq"]
        try:
            worker.execute(request)
            worker.render()
            reply = {"seq": sequence, "ok": True, "state": worker.snapshot()}
        except Exception as error:
            reply = {"seq": sequence, "ok": False, "error": str(error), "state": worker.snapshot()}
        write_json(directory / f"reply_{sequence}.json", reply)


if __name__ == "__main__":
    main()
