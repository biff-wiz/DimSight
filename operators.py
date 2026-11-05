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
        if props.always_on and props.selected_display != "HOLD":
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
    bl_label = "Bind"
    bl_description = "Press a key to use as the DimSight hold key"

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
            self.report({"INFO"}, f"DimSight hold key: {event.type}")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class DIMSIGHT_OT_save_defaults(bpy.types.Operator):
    bl_idname = "dimsight.save_defaults"
    bl_label = "Save as Default"
    bl_description = "Save current DimSight settings as the global default for all future projects"

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is not None:
            copy_settings(context.scene.dimsight, prefs)
            context.preferences.is_dirty = True
            try:
                bpy.ops.wm.save_userpref()
            except Exception:
                pass
            self.report({"INFO"}, "DimSight settings saved as global defaults")
        else:
            self.report({"WARNING"}, "DimSight preferences not found")
        return {"FINISHED"}


class DIMSIGHT_OT_restore_defaults(bpy.types.Operator):
    bl_idname = "dimsight.restore_defaults"
    bl_label = "Restore Defaults"
    bl_description = "Restore settings from your saved global defaults"

    def execute(self, context):
        prefs = get_prefs(context)
        if prefs is not None:
            copy_settings(prefs, context.scene.dimsight)
            overlay.invalidate()
            overlay.tag_redraw_all()
            self.report({"INFO"}, "DimSight settings restored from global defaults")
        else:
            self.report({"WARNING"}, "DimSight preferences not found")
        return {"FINISHED"}


class DIMSIGHT_OT_reset(bpy.types.Operator):
    bl_idname = "dimsight.reset"
    bl_label = "Factory Reset"
    bl_description = "Reset every DimSight setting back to original factory defaults"

    def execute(self, context):
        props = context.scene.dimsight
        for prop in props.bl_rna.properties:
            if prop.identifier not in {"rna_type", "name", "always_on"}:
                props.property_unset(prop.identifier)
        overlay.invalidate()
        overlay.tag_redraw_all()
        self.report({"INFO"}, "DimSight settings reset to factory defaults")
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
