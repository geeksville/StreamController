"""
StreamController DBus API

Provides a DBus interface at com.core447.StreamController for external
tools to query and control StreamController.

Top-level object: /com/core447/StreamController
  - Controllers property (list of serial numbers)
  - Pages property, AddPage, RemovePage
  - NotifyForegroundApp, IconPacks property, GetIconNames

Per-controller objects: /com/core447/StreamController/controllers/<serial>
  - SetActivePage
  - ActivePageName property

Uses dbus-python (dbus.service) to expose the API.
"""

import json
import os
import re
from src.Signals import Signals
from loguru import logger as log

import globals as gl

if not gl.IS_MAC:
    import dbus
    import dbus.service

DBUS_BUS_NAME = "com.core447.StreamController"
DBUS_OBJECT_PATH = "/com/core447/StreamController"
CONTROLLER_BASE_PATH = DBUS_OBJECT_PATH + "/controllers"

TOPLEVEL_IFACE = "com.core447.StreamController"
CONTROLLER_IFACE = "com.core447.StreamController.Controller"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECTABLE_IFACE = "org.freedesktop.DBus.Introspectable"

# ── Introspection XML ────────────────────────────────────────────────

TOPLEVEL_INTROSPECTION_XML = f"""\
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node name="{DBUS_OBJECT_PATH}">
  <interface name="{TOPLEVEL_IFACE}">
    <method name="AddPage">
      <arg direction="in" type="s" name="name"/>
      <arg direction="in" type="s" name="json_contents"/>
    </method>
    <method name="RemovePage">
      <arg direction="in" type="s" name="name"/>
    </method>
    <method name="NotifyForegroundApp">
      <arg direction="in" type="s" name="window_name"/>
      <arg direction="in" type="s" name="window_class"/>
    </method>
    <method name="GetIconNames">
      <arg direction="in" type="s" name="icon_pack_id"/>
      <arg direction="out" type="as" name="icon_names"/>
    </method>
    <property name="Controllers" type="as" access="read"/>
    <property name="Pages" type="as" access="read"/>
    <property name="IconPacks" type="as" access="read"/>
    <property name="ForegroundWindowName" type="s" access="readwrite"/>
    <property name="ForegroundWindowClass" type="s" access="readwrite"/>
  </interface>
  <interface name="{PROPERTIES_IFACE}">
    <method name="Get">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="in" type="s" name="property_name"/>
      <arg direction="out" type="v" name="value"/>
    </method>
    <method name="Set">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="in" type="s" name="property_name"/>
      <arg direction="in" type="v" name="value"/>
    </method>
    <method name="GetAll">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="out" type="a{{sv}}" name="properties"/>
    </method>
  </interface>
  <interface name="{INTROSPECTABLE_IFACE}">
    <method name="Introspect">
      <arg direction="out" type="s" name="xml_data"/>
    </method>
  </interface>
</node>
"""

CONTROLLER_INTROSPECTION_XML = """\
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="{iface}">
    <method name="SetActivePage">
      <arg direction="in" type="s" name="name"/>
    </method>
    <property name="ActivePageName" type="s" access="readwrite"/>
  </interface>
  <interface name="{props_iface}">
    <method name="Get">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="in" type="s" name="property_name"/>
      <arg direction="out" type="v" name="value"/>
    </method>
    <method name="Set">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="in" type="s" name="property_name"/>
      <arg direction="in" type="v" name="value"/>
    </method>
    <method name="GetAll">
      <arg direction="in" type="s" name="interface_name"/>
      <arg direction="out" type="a{{sv}}" name="properties"/>
    </method>
  </interface>
  <interface name="{intro_iface}">
    <method name="Introspect">
      <arg direction="out" type="s" name="xml_data"/>
    </method>
  </interface>
</node>
""".format(iface=CONTROLLER_IFACE, props_iface=PROPERTIES_IFACE,
           intro_iface=INTROSPECTABLE_IFACE)


def _serial_to_dbus_path(serial: str) -> str:
    """Convert a serial number to a valid DBus object path component."""
    # DBus paths only allow [A-Za-z0-9_], so replace anything else with _
    return re.sub(r"[^A-Za-z0-9_]", "_", serial)


# ─────────────────────────────────────────────────────────────────────
# Per-controller API (published at .../controllers/<serial>)
# ─────────────────────────────────────────────────────────────────────

class ControllerInstanceAPI(dbus.service.Object):
    """DBus interface for a single StreamDeck controller."""

    def __init__(self, controller, bus_name, obj_path):
        self._controller = controller
        self._active_page_name: str = ""
        super().__init__(bus_name, obj_path)

    # ── Introspection ────────────────────────────────────────────────

    @dbus.service.method(INTROSPECTABLE_IFACE,
                         in_signature='', out_signature='s')
    def Introspect(self):
        return CONTROLLER_INTROSPECTION_XML

    # ── Methods ──────────────────────────────────────────────────────

    @dbus.service.method(CONTROLLER_IFACE,
                         in_signature='s', out_signature='')
    def SetActivePage(self, name):
        """Set the active page on this controller."""
        serial = self._controller.serial_number()
        log.info(f"DBus API [{serial}]: SetActivePage called – name={name!r}")
        try:
            if gl.page_manager is not None:
                page_path = gl.page_manager.find_matching_page_path(name)
                if page_path is None:
                    log.warning(f"DBus API [{serial}]: SetActivePage – page not found: {name}")
                    return
                page = gl.page_manager.get_page(page_path, self._controller)
                self._controller.load_page(page)
                self._active_page_name = name
        except Exception as e:
            log.error(f"DBus API [{serial}]: SetActivePage error: {e}")

    # ── Properties via org.freedesktop.DBus.Properties ───────────────

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        if interface_name == CONTROLLER_IFACE:
            if property_name == "ActivePageName":
                return self._active_page_name
        raise dbus.exceptions.DBusException(
            f"Unknown property: {interface_name}.{property_name}",
            name="org.freedesktop.DBus.Error.UnknownProperty")

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='ssv', out_signature='')
    def Set(self, interface_name, property_name, value):
        if interface_name == CONTROLLER_IFACE:
            if property_name == "ActivePageName":
                self._active_page_name = str(value)
                log.debug(
                    f"DBus API [{self._controller.serial_number()}]: "
                    f"ActivePageName changed to {self._active_page_name!r}")
                return
        raise dbus.exceptions.DBusException(
            f"Unknown property: {interface_name}.{property_name}",
            name="org.freedesktop.DBus.Error.UnknownProperty")

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name == CONTROLLER_IFACE:
            return {"ActivePageName": self._active_page_name}
        return {}


# ─────────────────────────────────────────────────────────────────────
# Top-level API (published at /com/core447/StreamController)
# ─────────────────────────────────────────────────────────────────────

class StreamControllerAPI(dbus.service.Object):
    """DBus interface for StreamController (top-level)."""

    def __init__(self, bus_name, obj_path):
        self._foreground_window_name: str = ""
        self._foreground_window_class: str = ""
        super().__init__(bus_name, obj_path)

    # ── Introspection ────────────────────────────────────────────────

    @dbus.service.method(INTROSPECTABLE_IFACE,
                         in_signature='', out_signature='s')
    def Introspect(self):
        return TOPLEVEL_INTROSPECTION_XML

    # ── Methods ──────────────────────────────────────────────────────

    @dbus.service.method(TOPLEVEL_IFACE,
                         in_signature='ss', out_signature='')
    def AddPage(self, name, json_contents):
        """Add a new page with the given name and JSON contents."""
        log.info(f"DBus API: AddPage called – name={name!r}")
        try:
            page_dict = json.loads(json_contents) if json_contents else {}
            if gl.page_manager is not None:
                path = gl.page_manager.add_page(name, page_dict)
                gl.page_manager.update_dict_of_pages_with_path(path)
                gl.page_manager.reload_pages_with_path(path)
                gl.signal_manager.trigger_signal(Signals.PageAdd, path)
        except json.JSONDecodeError as e:
            log.error(f"DBus API: AddPage – invalid JSON: {e}")
        except Exception as e:
            log.error(f"DBus API: AddPage error: {e}")

    @dbus.service.method(TOPLEVEL_IFACE,
                         in_signature='s', out_signature='')
    def RemovePage(self, name):
        """Remove the page with the given name."""
        log.info(f"DBus API: RemovePage called – name={name!r}")
        try:
            if gl.page_manager is not None:
                page_path = os.path.join(gl.page_manager.PAGE_PATH, f"{name}.json")
                if os.path.exists(page_path):
                    gl.page_manager.remove_page(page_path)
                    gl.signal_manager.trigger_signal(Signals.PageDelete, page_path)
                else:
                    log.warning(f"DBus API: RemovePage – page not found: {name}")
        except Exception as e:
            log.error(f"DBus API: RemovePage error: {e}")

    @dbus.service.method(TOPLEVEL_IFACE,
                         in_signature='ss', out_signature='')
    def NotifyForegroundApp(self, window_name, window_class):
        """
        Notify StreamController of the current foreground application.
        Useful for testing/development without kdotool.
        """
        log.info(
            f"DBus API: NotifyForegroundApp called – "
            f"window_name={window_name!r}, window_class={window_class!r}"
        )
        try:
            self._foreground_window_name = window_name
            self._foreground_window_class = window_class

            if gl.window_grabber is not None:
                from src.backend.WindowGrabber.Window import Window
                window = Window(wm_class=window_class, title=window_name)
                gl.window_grabber.on_active_window_changed(window)
        except Exception as e:
            log.error(f"DBus API: NotifyForegroundApp error: {e}")

    @dbus.service.method(TOPLEVEL_IFACE,
                         in_signature='s', out_signature='as')
    def GetIconNames(self, icon_pack_id):
        """Return a list of all icon names in the given icon pack."""
        log.info(f"DBus API: GetIconNames called – icon_pack_id={icon_pack_id!r}")
        try:
            if gl.icon_pack_manager is not None:
                packs = gl.icon_pack_manager.get_icon_packs()
                pack = packs.get(icon_pack_id)
                if pack is None:
                    log.warning(f"DBus API: GetIconNames – pack not found: {icon_pack_id}")
                    return dbus.Array([], signature='s')
                icons = pack.get_icons()
                return dbus.Array([icon.name for icon in icons], signature='s')
        except Exception as e:
            log.error(f"DBus API: GetIconNames error: {e}")
        return dbus.Array([], signature='s')

    # ── Properties via org.freedesktop.DBus.Properties ───────────────

    def _get_property(self, property_name):
        """Internal helper to read a property value."""
        if property_name == "Controllers":
            try:
                if gl.deck_manager is not None:
                    return dbus.Array(
                        [c.serial_number() for c in gl.deck_manager.deck_controller],
                        signature='s')
            except Exception as e:
                log.error(f"DBus API: Controllers error: {e}")
            return dbus.Array([], signature='s')

        if property_name == "Pages":
            log.info("DBus API: Pages read")
            try:
                if gl.page_manager is not None:
                    return dbus.Array(gl.page_manager.get_page_names(), signature='s')
            except Exception as e:
                log.error(f"DBus API: Pages error: {e}")
            return dbus.Array([], signature='s')

        if property_name == "IconPacks":
            log.info("DBus API: IconPacks read")
            try:
                if gl.icon_pack_manager is not None:
                    packs = gl.icon_pack_manager.get_icon_packs()
                    return dbus.Array(list(packs.keys()), signature='s')
            except Exception as e:
                log.error(f"DBus API: IconPacks error: {e}")
            return dbus.Array([], signature='s')

        if property_name == "ForegroundWindowName":
            return self._foreground_window_name

        if property_name == "ForegroundWindowClass":
            return self._foreground_window_class

        return None

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        if interface_name == TOPLEVEL_IFACE:
            val = self._get_property(property_name)
            if val is not None:
                return val
        raise dbus.exceptions.DBusException(
            f"Unknown property: {interface_name}.{property_name}",
            name="org.freedesktop.DBus.Error.UnknownProperty")

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='ssv', out_signature='')
    def Set(self, interface_name, property_name, value):
        if interface_name == TOPLEVEL_IFACE:
            if property_name == "ForegroundWindowName":
                self._foreground_window_name = str(value)
                log.debug(f"DBus API: ForegroundWindowName changed to {value!r}")
                return
            if property_name == "ForegroundWindowClass":
                self._foreground_window_class = str(value)
                log.debug(f"DBus API: ForegroundWindowClass changed to {value!r}")
                return
        raise dbus.exceptions.DBusException(
            f"Unknown or read-only property: {interface_name}.{property_name}",
            name="org.freedesktop.DBus.Error.UnknownProperty")

    @dbus.service.method(PROPERTIES_IFACE,
                         in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name == TOPLEVEL_IFACE:
            return {
                "Controllers": self._get_property("Controllers"),
                "Pages": self._get_property("Pages"),
                "IconPacks": self._get_property("IconPacks"),
                "ForegroundWindowName": self._foreground_window_name,
                "ForegroundWindowClass": self._foreground_window_class,
            }
        return dbus.Dictionary({}, signature='sv')


# ── Helper to start / stop the service ──────────────────────────────

_bus_name = None
_api_instance = None
_controller_instances: dict[str, ControllerInstanceAPI] = {}


def start_dbus_service():
    """Publish the StreamController API on the session bus."""
    global _bus_name, _api_instance
    try:
        bus = dbus.SessionBus()
        _bus_name = dbus.service.BusName(DBUS_BUS_NAME, bus=bus)
        _api_instance = StreamControllerAPI(_bus_name, DBUS_OBJECT_PATH)

        # Publish a sub-object for each connected controller
        if gl.deck_manager is not None:
            for controller in gl.deck_manager.deck_controller:
                _publish_controller(controller)

        log.success(f"DBus API published at {DBUS_OBJECT_PATH}")
    except Exception as e:
        log.error(f"Failed to start DBus API service: {e}")


def _publish_controller(controller):
    """Publish a ControllerInstanceAPI for a single deck controller."""
    global _bus_name
    serial = controller.serial_number()
    if serial in _controller_instances:
        return  # already published
    path_component = _serial_to_dbus_path(serial)
    obj_path = f"{CONTROLLER_BASE_PATH}/{path_component}"
    instance = ControllerInstanceAPI(controller, _bus_name, obj_path)
    _controller_instances[serial] = instance
    log.info(f"DBus API: published controller {serial} at {obj_path}")


def stop_dbus_service():
    """Remove objects from the session bus."""
    global _bus_name, _api_instance
    try:
        if _api_instance is not None:
            _api_instance.remove_from_connection()
            _api_instance = None
        for inst in _controller_instances.values():
            try:
                inst.remove_from_connection()
            except Exception:
                pass
        _controller_instances.clear()
        _bus_name = None
        log.info("DBus API service stopped")
    except Exception as e:
        log.error(f"Failed to stop DBus API service: {e}")


def get_api_instance() -> "StreamControllerAPI | None":
    """Return the active top-level API instance, or None if not started."""
    return _api_instance


def get_controller_instance(serial: str) -> "ControllerInstanceAPI | None":
    """Return the API instance for a specific controller, or None."""
    return _controller_instances.get(serial)