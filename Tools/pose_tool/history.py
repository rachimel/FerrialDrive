"""편집 파츠와 키를 함께 복구하는 메모리 Undo. 드래그 하나를 한 단계로 묶는다."""

from copy import deepcopy
import bpy
from . import scene as engine


class PoseHistory:
    def __init__(self, parts, limit=48):
        self.parts, self.limit = parts, limit
        self.entries = []
        self.gesture = None

    def objects(self):
        rig, proxy = engine.rig_objects()
        objects = [proxy, *engine.controls().values()]
        objects += [bpy.data.objects[name] for name in engine.state().get("independent_parts", [])]
        equipment = bpy.data.objects.get(engine.state()["profile"].get("equipment", {}).get("object", ""))
        if equipment:
            objects.append(equipment)
        return objects

    def capture(self, worker):
        state = {"data": engine.state(), "frame": bpy.context.scene.frame_current,
                 "range": (bpy.context.scene.frame_start, bpy.context.scene.frame_end),
                 "fps": bpy.context.scene.render.fps, "exported": worker.exported,
                 "dirty": worker.dirty, "file_dirty": worker.file_dirty,
                 "objects": {}, "bones": {b.name: b.matrix_basis.copy() for b in self.parts.proxy.pose.bones},
                 "support": None}
        for obj in self.objects():
            action = obj.animation_data.action if obj.animation_data else None
            copied = action.copy() if action else None
            if copied:
                copied.name = engine.PREFIX+"History"
                copied.use_fake_user = False
            state["objects"][obj.name] = {"action": copied, "basis": obj.matrix_basis.copy(),
                                          "properties": {p: obj[p] for p in ("sword_stowed", "gun_stowed") if p in obj}}
        anchor = bpy.data.objects.get(engine.PREFIX+"SupportAnchor")
        if anchor and any(obj.constraints.get(engine.PREFIX+"Support") for obj in engine.controls().values()):
            state["support"] = anchor.matrix_basis.copy()
        return state

    def discard(self, state):
        for item in state["objects"].values():
            action = item["action"]
            if action and action.users == 0:
                bpy.data.actions.remove(action)

    def push(self, state, gesture=None):
        if gesture and gesture == self.gesture:
            self.discard(state)
            return
        self.gesture = gesture
        self.entries.append(state)
        if len(self.entries) > self.limit:
            self.discard(self.entries.pop(0))

    def restore(self, worker, state):
        engine.support_pin(False)
        engine.store(deepcopy(state["data"]))
        for name, item in state["objects"].items():
            obj = bpy.data.objects[name]
            action = item["action"].copy() if item["action"] else None
            if action:
                action.name = engine.PREFIX+"Restored"
            engine.assign_action(obj, action.name if action else None)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = state["range"]
        scene.render.fps = state["fps"]
        scene.frame_set(state["frame"])
        for name, item in state["objects"].items():
            obj = bpy.data.objects[name]
            obj.matrix_basis = item["basis"]
            for prop, value in item["properties"].items():
                obj[prop] = value
            obj.update_tag()
        for name, matrix in state["bones"].items():
            self.parts.proxy.pose.bones[name].matrix_basis = matrix
        engine.update()
        if state["support"] is not None:
            engine.support_pin(True)
            bpy.data.objects[engine.PREFIX+"SupportAnchor"].matrix_basis = state["support"]
        data = engine.state()
        engine.stash_session(data)
        engine.store(data)
        worker.dirty, worker.file_dirty, worker.exported = state["dirty"], True, None
        engine.update()

    def undo(self, worker):
        if not self.entries:
            raise ValueError("되돌릴 편집이 없다.")
        state = self.entries.pop()
        self.restore(worker, state)
        self.discard(state)
        self.gesture = None
