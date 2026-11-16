"""Operators and keymap handling."""

import time

import bpy

from . import meshdata, overlay
from .overlay import State
from .props import copy_settings, get_prefs, hold_key

BINDABLE_KEYS = frozenset(
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [f"F{i}" for i in range(1, 13)]
    + ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
       "SPACE", "TAB", "RET", "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL",
       "LEFT_ALT", "RIGHT_ALT", "LEFT_ARROW", "RIGHT_ARROW", "UP_ARROW", "DOWN_ARROW",
       "COMMA", "PERIOD", "SEMI_COLON", "QUOTE", "ACCENT_GRAVE", "MINUS", "EQUAL",
       "LEFT_BRACKET", "RIGHT_BRACKET", "BACK_SLASH", "SLASH"]
)

# The mode keymaps sit above "3D View", so the key has to be bound in each of them
# or Object/Edit Mode shortcuts would swallow it.
KEYMAPS = (("3D View", "VIEW_3D"), ("Object Mode", "EMPTY"), ("Mesh", "EMPTY"))
_keymaps = []

# Hold-key release detection. While a view navigation (MMB orbit/pan/zoom) is running it
# swallows every event, including our key release, so the release is never seen. Events
# going quiet for STALL_SECONDS reveals that; the key must then show up again (auto-repeat)
# within VERIFY_SECONDS or it is treated as released. Modifier keys are checked directly.
POLL_SECONDS = 0.1
STALL_SECONDS = 0.4
VERIFY_SECONDS = 1.2
_MODIFIER_FLAG = {"LEFT_SHIFT": "shift", "RIGHT_SHIFT": "shift", "LEFT_CTRL": "ctrl",
                  "RIGHT_CTRL": "ctrl", "LEFT_ALT": "alt", "RIGHT_ALT": "alt"}


def _hold_is_relevant(props):
    return not (
        props.always_on and props.selected_display != "HOLD"
        and not props.show_object_name)


def clear_keymaps():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()


def apply_keymaps(key):
    clear_keymaps()
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:   # background mode
        return
    for name, space in KEYMAPS:
        km = kc.keymaps.new(name=name, space_type=space)
        _keymaps.append((km, km.keymap_items.new("dimsight.hold", key, "PRESS")))


class DIMSIGHT_OT_session(bpy.types.Operator):
    """Keeps the overlay updated while it is showing"""
    bl_idname = "dimsight.session"
    bl_label = "DimSight Overlay Session"
    bl_options = {"INTERNAL"}

    _timer = None

    def _stop(self, context):
        State.modal_running = False
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

    def invoke(self, context, event):
        if State.modal_running:
            return {"CANCELLED"}
        State.modal_running = True
        wm = context.window_manager
        self._timer = wm.event_timer_add(POLL_SECONDS, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        props = getattr(context.scene, "dimsight", None)
        if props is None or not overlay.overlay_active(props):
            self._stop(context)
            return {"CANCELLED"}
        if event.type == "TIMER":
            overlay.refresh_hover(context)   # the view may have moved under a still pointer
        elif event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            overlay.update_hover(context, event)
        elif event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
            # Selection or active element in Edit Mode may have changed
            overlay.invalidate()
            overlay.tag_redraw_all()
        return {"PASS_THROUGH"}


class DIMSIGHT_OT_hold(bpy.types.Operator):
    """Hold to show DimSight measurements, release to hide"""
    bl_idname = "dimsight.hold"
    bl_label = "DimSight Hold"
    bl_options = {"INTERNAL"}

    _timer = None

    def _finish(self, context):
        State.peek = False
        State.hold_running = False
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        overlay.sync()
        return {"FINISHED"}

    def invoke(self, context, event):
        props = context.scene.dimsight
        if not _hold_is_relevant(props):
            return {"PASS_THROUGH"}   # nothing to peek at, leave the key alone
        if State.hold_running:
            return {"CANCELLED"}
        self._key = event.type
        self._last_event = time.monotonic()
        self._verify_until = None
        State.hold_running = True
        State.peek = True
        overlay.invalidate()
        overlay.sync()
        overlay.update_hover(context, event)
        wm = context.window_manager
        self._timer = wm.event_timer_add(POLL_SECONDS, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        now = time.monotonic()
        if now - self._last_event > STALL_SECONDS and self._verify_until is None:
            # Nothing reached us for a while: a view navigation or similar was eating
            # events and may have eaten the key release too.
            self._verify_until = now + VERIFY_SECONDS
        self._last_event = now

        if event.type == "WINDOW_DEACTIVATE" or not State.enabled:
            return self._finish(context)
        if event.type == self._key:
            if event.value == "RELEASE":
                return self._finish(context)
            self._verify_until = None   # still held (auto-repeat): consume it
            return {"RUNNING_MODAL"}
        flag = _MODIFIER_FLAG.get(self._key)
        if flag and event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"} and not getattr(event, flag):
            return self._finish(context)
        if self._verify_until is not None and now > self._verify_until:
            return self._finish(context)
        return {"PASS_THROUGH"}


class DIMSIGHT_OT_bind_key(bpy.types.Operator):
    bl_idname = "dimsight.bind_key"
    bl_label = "Change Shortcut"
    bl_description = "Choose a shared hold shortcut for Blender's 3D View, Object Mode, and Mesh keymaps"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("DimSight: press a key to bind it  |  Esc: cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.workspace.status_text_set(None)
            return {"CANCELLED"}
        if event.type in BINDABLE_KEYS:
            prefs = get_prefs(context)
            if prefs is not None:
                prefs.hold_key = event.type
            apply_keymaps(event.type)
            context.workspace.status_text_set(None)
            conflicts = []
            user_keyconfig = context.window_manager.keyconfigs.user
            relevant_keymaps = {"3D View", "Object Mode", "Mesh"}
            for keymap in user_keyconfig.keymaps:
                if keymap.name not in relevant_keymaps:
                    continue
                for item in keymap.keymap_items:
                    if (item.idname != "dimsight.hold" and item.type == event.type
                            and item.value == "PRESS" and item.active
                            and (item.any or not (
                                item.shift or item.ctrl or item.alt or item.oskey))):
                        conflicts.append(f"{keymap.name}: {item.name or item.idname}")
            if conflicts:
                more = f" (and {len(conflicts) - 1} more)" if len(conflicts) > 1 else ""
                self.report(
                    {"WARNING"},
                    f"DimSight shortcut {event.type} may conflict with "
                    f"{conflicts[0]}{more}; Blender keymaps were not changed")
            else:
                self.report({"INFO"}, f"DimSight shortcut: {event.type}")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


def _save_defaults(context, prefs, save_preferences=None):
    copy_settings(context.scene.dimsight, prefs)
    context.preferences.is_dirty = True
    result = (save_preferences or bpy.ops.wm.save_userpref)()
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not finish saving user preferences")


class DIMSIGHT_OT_save_defaults(bpy.types.Operator):
    bl_idname = "dimsight.save_defaults"
    bl_label = "Save as Default"
    bl_description = "Save current scene's DimSight settings to Blender preferences as defaults for future scenes"

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            self.report({"ERROR"}, "DimSight preferences are unavailable; defaults were not saved")
            return {"CANCELLED"}
        try:
            _save_defaults(context, prefs)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not save DimSight defaults: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "DimSight defaults saved to Blender preferences")
        return {"FINISHED"}


class DIMSIGHT_OT_restore_defaults(bpy.types.Operator):
    bl_idname = "dimsight.restore_defaults"
    bl_label = "Apply Saved Defaults"
    bl_description = "Copy the saved Blender preference defaults into the current scene"

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is None:
            self.report({"ERROR"}, "DimSight preferences are unavailable; scene settings were not changed")
            return {"CANCELLED"}
        try:
            copy_settings(prefs, context.scene.dimsight)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not apply DimSight defaults: {exc}")
            return {"CANCELLED"}
        overlay.invalidate()
        overlay.tag_redraw_all()
        overlay.refresh_hover(context)
        self.report({"INFO"}, "Saved DimSight defaults applied to the current scene")
        return {"FINISHED"}


class DIMSIGHT_OT_reset(bpy.types.Operator):
    bl_idname = "dimsight.reset"
    bl_label = "Reset Scene Settings"
    bl_description = "Reset DimSight settings in the current scene only; leaves the shortcut and Always On unchanged"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        props = context.scene.dimsight
        for prop in props.bl_rna.properties:
            if prop.identifier not in {"rna_type", "name", "always_on"}:
                props.property_unset(prop.identifier)
        overlay.invalidate()
        overlay.tag_redraw_all()
        overlay.refresh_hover(context)
        self.report({"INFO"}, "Current scene's DimSight settings reset; Always On and the global shortcut were unchanged")
        return {"FINISHED"}


CLASSES = (
    DIMSIGHT_OT_session,
    DIMSIGHT_OT_hold,
    DIMSIGHT_OT_bind_key,
    DIMSIGHT_OT_save_defaults,
    DIMSIGHT_OT_restore_defaults,
    DIMSIGHT_OT_reset,
)


def _apply_saved_key():
    apply_keymaps(hold_key())
    return None


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    try:
        apply_keymaps(hold_key())
    except Exception:
        apply_keymaps("D")
        # Preferences were not readable yet; pick up the saved key a moment later.
        bpy.app.timers.register(_apply_saved_key, first_interval=0.5)


def unregister():
    if bpy.app.timers.is_registered(_apply_saved_key):
        bpy.app.timers.unregister(_apply_saved_key)
    clear_keymaps()
    State.peek = False
    State.hold_running = False
    meshdata.clear_cache()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
