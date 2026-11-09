"""포즈 파츠·손목 연결·손가락·독립 무기 편집. 원본 메시와 rest 본은 보존한다."""

import math
import bpy
from mathutils import Matrix, Vector
from . import scene as engine


ASSEMBLIES = {"Gun": "총", "Sword": "칼", "Scabbard": "칼집"}
FINGERS = {"Thumb": "엄지", "Index": "검지", "Middle": "중지", "Ring": "약지", "Little": "소지"}
CORE_LABELS = {"pelvis": "골반", "waist": "허리", "chest": "몸통", "head": "머리",
               "shoulder.L": "왼쪽 어깨", "shoulder.R": "오른쪽 어깨",
               "hand.L": "왼손", "hand.R": "오른손", "foot.L": "왼발", "foot.R": "오른발",
               "pole.hand.L": "왼쪽 팔꿈치", "pole.hand.R": "오른쪽 팔꿈치",
               "pole.foot.L": "왼쪽 무릎", "pole.foot.R": "오른쪽 무릎"}


def rows(matrix):
    return [list(row) for row in matrix]


class PartEditing:
    def __init__(self, *, initialize=True):
        self.rig, self.proxy = engine.rig_objects()
        if initialize:
            self.link_wrists()
            self.prepare_assemblies()

    def link_wrists(self):
        controls = engine.controls()
        data = engine.state()
        collection = bpy.data.collections[engine.PREFIX + "Controls"]
        for side in ("L", "R"):
            wrist = self.proxy.pose.bones.get("WristSwivel."+side)
            hand = self.proxy.pose.bones.get("Hand."+side)
            if not wrist or not hand or "hand."+side not in controls:
                continue
            name = engine.PREFIX + "WristFollow."+side
            target = bpy.data.objects.get(name)
            if target is None:
                target = bpy.data.objects.new(name, None)
                collection.objects.link(target)
                target.empty_display_size = 0
                target.hide_select = True
                target.parent = controls["hand."+side]
                offset = engine.palm_offset(self.rig, "hand."+side, data["profile"]["limbs"]["hand."+side])
                relative = hand.bone.matrix_local.inverted() @ wrist.bone.matrix_local
                target.matrix_basis = Matrix.Translation(-offset) @ relative
            constraint = wrist.constraints.get(engine.PREFIX + "HandLinked")
            if constraint is None:
                constraint = wrist.constraints.new("COPY_ROTATION")
                constraint.name = engine.PREFIX + "HandLinked"
            constraint.target = target
            constraint.owner_space = constraint.target_space = "WORLD"
        engine.update()

    def prepare_assemblies(self):
        data = engine.state()
        if "independent_parts" in data:
            return
        objects = [bpy.data.objects[name] for name in ASSEMBLIES if name in bpy.data.objects]
        frame = bpy.context.scene.frame_current
        current = {obj.name: obj.matrix_world.copy() for obj in objects}
        scabbard, stow = bpy.data.objects.get("Scabbard"), bpy.data.objects.get("Sword_StowAnchor")
        # 제작된 칼집 좌표계와 수납 기준점 사이의 관계를 보존한다.
        alignment = scabbard.matrix_world.inverted() @ stow.matrix_world if scabbard and stow else None
        frames = sorted({f for clip in data["clips"] for f in range(clip["start"], clip["end"]+1)})
        samples = {}
        if objects:
            with engine.suspend_meshes():
                engine.source_mode(True)
                try:
                    for sample_frame in frames:
                        bpy.context.scene.frame_set(sample_frame)
                        samples[sample_frame] = {obj.name: obj.matrix_world.copy() for obj in objects}
                finally:
                    engine.source_mode(False)
                    bpy.context.scene.frame_set(frame)
                # 현재 동작에 저장한 컨트롤 편집도 분리 전 위치에 반영한다.
                active = next(c for c in data["clips"] if c["name"] == data["active"])
                for sample_frame in range(active["start"], active["end"]+1):
                    bpy.context.scene.frame_set(sample_frame)
                    samples[sample_frame] = {obj.name: obj.matrix_world.copy() for obj in objects}
                bpy.context.scene.frame_set(frame)
            samples[frame] = current
            for obj in objects:
                for constraint in obj.constraints:
                    constraint.mute = True
                if obj.animation_data:
                    obj.animation_data.action = None
                    for track in obj.animation_data.nla_tracks:
                        track.mute = True
                    for driver in obj.animation_data.drivers:
                        if driver.data_path in ("location", "rotation_euler", "rotation_quaternion", "scale"):
                            driver.mute = True
                obj.parent = None
                obj.rotation_mode = "QUATERNION"
                previous = None
                for sample_frame in frames:
                    obj.matrix_world = samples[sample_frame][obj.name]
                    if previous and previous.dot(obj.rotation_quaternion) < 0:
                        obj.rotation_quaternion.negate()
                    previous = obj.rotation_quaternion.copy()
                    engine.key_transform(obj, sample_frame)
                if obj.animation_data and obj.animation_data.action:
                    obj.animation_data.action.name = engine.PREFIX+"Part_"+obj.name
                    engine.linear_keys(obj.animation_data.action)
        data["independent_parts"] = [obj.name for obj in objects]
        data["sword_alignment"] = rows(alignment) if alignment is not None else None
        engine.store(data)
        bpy.context.scene.frame_set(frame)
        engine.update()

    def entries(self):
        result = {key: {"label": CORE_LABELS.get(key, key), "category": "body", "kind": "control"}
                  for key in engine.controls()}
        owned = set(engine.state()["profile"]["body"].values())
        owned.update(name for limb in engine.state()["profile"]["limbs"].values() for name in limb.values())
        for bone in self.proxy.pose.bones:
            if bone.name in owned or bone.name.startswith("WristSwivel."):
                continue
            finger = next((prefix for prefix in FINGERS if bone.name.startswith(prefix)), None)
            if finger:
                side = "왼손" if bone.name.endswith(".L") else "오른손"
                joint = bone.name.split(".")[0][len(finger):].replace("Base", "뿌리")
                label = f"{side} {FINGERS[finger]} {joint}"
            else:
                label = bone.name
            result["bone:"+bone.name] = {"label": label, "category": "fingers" if finger else "detail", "kind": "bone"}
        for name in engine.state().get("independent_parts", []):
            result["object:"+name] = {"label": ASSEMBLIES.get(name, name), "category": "equipment", "kind": "object"}
        return result

    def target(self, key):
        if key.startswith("bone:"):
            return self.proxy.pose.bones[key[5:]]
        if key.startswith("object:") and key[7:] in engine.state().get("independent_parts", []):
            return bpy.data.objects[key[7:]]
        return engine.controls()[key]

    def world(self, key):
        target = self.target(key)
        return self.proxy.matrix_world @ target.matrix if key.startswith("bone:") else target.matrix_world.copy()

    def set_world(self, key, matrix, *, moving=False):
        target = self.target(key)
        if key.startswith("bone:"):
            if moving and target.bone.use_connect:
                raise ValueError("연결된 손가락 관절은 회전으로 조절한다.")
            target.matrix = self.proxy.matrix_world.inverted() @ matrix
        else:
            if target.constraints.get(engine.PREFIX+"Support"):
                engine.support_pin(False)
            target.matrix_world = matrix
        engine.update()

    def translate(self, key, delta):
        if key.startswith("pole."):
            raise ValueError("팔꿈치·무릎은 화면 손잡이로 굽힘 방향을 조절한다.")
        matrix = self.world(key)
        matrix.translation += Vector(delta)
        self.set_world(key, matrix, moving=True)

    def rotate(self, key, axis, degrees):
        matrix = self.world(key)
        pivot = matrix.translation
        self.set_world(key, Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(degrees), 4, axis) @ Matrix.Translation(-pivot) @ matrix)

    def finger_bones(self, side, finger="all", joint="all"):
        prefix = next((name for name, label in FINGERS.items() if finger in (name, label)), None)
        return [b for b in self.proxy.pose.bones if b.name.endswith("."+side)
                and any(b.name.startswith(name) for name in FINGERS)
                and (finger == "all" or prefix and b.name.startswith(prefix))
                and (joint == "all" or b.name.split(".")[0].endswith(joint))]

    def curl_fingers(self, side, finger, degrees, joint="all"):
        bones = self.finger_bones(side, finger, joint)
        if not bones:
            raise ValueError("선택한 손가락 관절이 없다.")
        # 마디별 rest roll이 달라도 뿌리 관절과 같은 방향으로 굽힌다.
        for bone in bones:
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = bone.rotation_quaternion @ Matrix.Rotation(math.radians(degrees), 3, self.finger_axis(bone)).to_quaternion()
        engine.update()

    def finger_axis(self, bone):
        finger = next(name for name in FINGERS if bone.name.startswith(name))
        root = self.proxy.data.bones[finger+("Base" if finger == "Thumb" else "01")+bone.name[-2:]]
        axis = root.matrix_local.to_3x3().col[2]
        return (bone.bone.matrix_local.to_3x3().inverted() @ axis).normalized()

    def hand_pose(self, side, pose):
        """관절의 로컬 회전을 절대값으로 설정한다. 반복 클릭해도 더 꺾이지 않는다."""
        if side not in ("L", "R") or pose not in ("fist", "open"):
            raise ValueError("손 / 손 모양 오류")
        bones = self.finger_bones(side)
        if not bones:
            raise ValueError("손가락 본이 없다.")
        angles = {"01": 70, "02": 90, "03": 65}
        thumb = {"Base": 25, "01": 55, "02": 65}
        for bone in bones:
            stem = bone.name.split(".")[0]
            table = thumb if stem.startswith("Thumb") else angles
            angle = next((value for suffix, value in table.items() if stem.endswith(suffix)), 0)
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Matrix.Rotation(math.radians(angle if pose == "fist" else 0), 3, self.finger_axis(bone)).to_quaternion()
        engine.update()

    def joint_position(self, key):
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        return engine.world_bones(self.rig)[limb["lower"]].translation

    def bend_joint(self, key, location):
        limb = engine.state()["profile"]["limbs"][key.removeprefix("pole.")]
        worlds = engine.world_bones(self.rig)
        origin = worlds[limb["upper"]].translation
        axis = (worlds[limb["end"]].translation-origin).normalized()
        current = worlds[limb["lower"]].translation-origin
        desired = Vector(location)-origin
        current -= axis*current.dot(axis)
        desired -= axis*desired.dot(axis)
        if current.length < 1e-5 or desired.length < 1e-5:
            raise ValueError("관절이 완전히 펴졌다. 골반·손·발 위치로 먼저 굽힘을 만든다.")
        angle = math.atan2(axis.dot(current.cross(desired)), current.dot(desired))
        matrix = self.world(key)
        matrix.translation = origin + Matrix.Rotation(angle, 3, axis) @ (matrix.translation-origin)
        self.set_world(key, matrix)

    def align_sword(self):
        if not all(name in engine.state().get("independent_parts", []) for name in ("Sword", "Scabbard")):
            raise ValueError("칼과 칼집 파츠가 필요하다.")
        if engine.state().get("sword_alignment") is None:
            raise ValueError("칼집 수납 기준점 Sword_StowAnchor가 필요하다.")
        sword, scabbard = bpy.data.objects["Sword"], bpy.data.objects["Scabbard"]
        sword.matrix_world = scabbard.matrix_world @ Matrix(engine.state()["sword_alignment"])
        engine.update()

    def key_current(self):
        frame = bpy.context.scene.frame_current
        for key, entry in self.entries().items():
            if entry["kind"] != "control":
                engine.key_transform(self.target(key), frame)
        for name in engine.state().get("independent_parts", []):
            obj = bpy.data.objects[name]
            if obj.animation_data and obj.animation_data.action:
                engine.linear_keys(obj.animation_data.action)

    def copy_previous(self, key):
        frame = bpy.context.scene.frame_current
        data = engine.state()
        previous = next((c for c in data["clips"] if c["start"] <= frame-1 <= c["end"]), None)
        if previous is None:
            raise ValueError("복제할 이전 프레임이 없다.")
        engine.key_pose()
        self.key_current()
        active = data["active"]
        local = key.startswith("bone:")
        finger_matrices = {}
        try:
            if previous["name"] != active:
                engine.activate_clip(previous["name"])
            bpy.context.scene.frame_set(frame-1)
            matrix = self.target(key).matrix_basis.copy() if local else self.world(key)
            if key.startswith("hand."):
                finger_matrices = {b.name: b.matrix_basis.copy() for b in self.finger_bones(key[-1])}
        finally:
            if engine.state()["active"] != active:
                engine.activate_clip(active)
            bpy.context.scene.frame_set(frame)
        if local:
            self.target(key).matrix_basis = matrix
        else:
            self.set_world(key, matrix, moving=True)
        for name, basis in finger_matrices.items():
            self.proxy.pose.bones[name].matrix_basis = basis
        engine.update()
