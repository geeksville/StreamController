#!/usr/bin/env python3
"""
StreamController DBus API client.

A command-line tool to interact with the StreamController DBus API.

Usage:
    python api_client.py controllers                              # List controller serial numbers
    python api_client.py pages                                    # List all pages
    python api_client.py add-page NAME [JSON]                     # Add a page
    python api_client.py remove-page NAME                         # Remove a page
    python api_client.py set-active-page SERIAL NAME              # Set active page on a controller
    python api_client.py notify-foreground NAME CLASS             # Notify foreground app
    python api_client.py icon-packs                               # List icon packs
    python api_client.py icons PACK_ID                            # List icons in a pack
    python api_client.py get-property [SERIAL] PROP               # Read a property
    python api_client.py listen                                   # Listen for property changes
"""

import argparse
import re
import sys

from dasbus.connection import SessionMessageBus
from gi.repository import GLib

SERVICE  = "com.core447.StreamController"
OBJECT   = "/com/core447/StreamController"
IFACE    = "com.core447.StreamController"
CTRL_IFACE = "com.core447.StreamController.Controller"
CTRL_BASE  = OBJECT + "/controllers"


def _serial_to_dbus_path(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", serial)


def get_proxy():
    bus = SessionMessageBus()
    return bus.get_proxy(SERVICE, OBJECT)


def get_controller_proxy(serial: str):
    bus = SessionMessageBus()
    path = f"{CTRL_BASE}/{_serial_to_dbus_path(serial)}"
    return bus.get_proxy(SERVICE, path)


# ── Commands ─────────────────────────────────────────────────────────

def cmd_controllers(args):
    proxy = get_proxy()
    controllers = proxy.Controllers
    if not controllers:
        print("No controllers connected.")
        return
    for s in controllers:
        print(s)


def cmd_pages(args):
    proxy = get_proxy()
    pages = proxy.Pages
    if not pages:
        print("No pages found.")
        return
    for p in pages:
        print(p)


def cmd_add_page(args):
    proxy = get_proxy()
    json_contents = args.json if args.json else ""
    proxy.AddPage(args.name, json_contents)
    print(f"Added page: {args.name}")


def cmd_remove_page(args):
    proxy = get_proxy()
    proxy.RemovePage(args.name)
    print(f"Removed page: {args.name}")


def cmd_set_active_page(args):
    proxy = get_controller_proxy(args.serial)
    proxy.SetActivePage(args.name)
    print(f"Set active page: {args.name}")


def cmd_notify_foreground(args):
    proxy = get_proxy()
    proxy.NotifyForegroundApp(args.window_name, args.window_class)
    print(f"Notified foreground app: name={args.window_name!r} class={args.window_class!r}")


def cmd_icon_packs(args):
    proxy = get_proxy()
    packs = proxy.IconPacks
    if not packs:
        print("No icon packs found.")
        return
    for p in packs:
        print(p)


def cmd_icons(args):
    proxy = get_proxy()
    icons = proxy.GetIconNames(args.pack_id)
    if not icons:
        print(f"No icons found in pack: {args.pack_id}")
        return
    for icon in icons:
        print(icon)


def cmd_get_property(args):
    prop = args.property_name
    if args.serial:
        proxy = get_controller_proxy(args.serial)
    else:
        proxy = get_proxy()
    try:
        value = getattr(proxy, prop)
        print(f"{prop} = {value!r}")
    except AttributeError:
        print(f"Unknown property: {prop}", file=sys.stderr)
        sys.exit(1)


def cmd_listen(args):
    """Listen for PropertiesChanged signals on all objects and print them."""
    bus = SessionMessageBus()
    connection = bus.connection

    def on_properties_changed(connection, sender, object_path,
                              interface_name, signal_name, parameters):
        iface, changed, invalidated = parameters.unpack()
        prefix = f"[{object_path}]" if object_path != OBJECT else "[root]"
        for prop, value in changed.items():
            print(f"{prefix} {iface} {prop} = {value!r}")
        for prop in invalidated:
            print(f"{prefix} {iface} {prop} (invalidated)")

    # Listen on the root object
    connection.signal_subscribe(
        SERVICE, "org.freedesktop.DBus.Properties", "PropertiesChanged",
        OBJECT, None, 0, on_properties_changed,
    )
    # Listen on all controller sub-objects (path_namespace match not available,
    # so use None for path and filter in callback)
    connection.signal_subscribe(
        SERVICE, "org.freedesktop.DBus.Properties", "PropertiesChanged",
        None, None, 0, on_properties_changed,
    )

    print(f"Listening for property changes on {SERVICE} …  (Ctrl+C to stop)")
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nStopped.")


# ── Argument parser ──────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description="StreamController DBus API client",
    )
    sub = parser.add_subparsers(dest="command")

    # controllers
    sub.add_parser("controllers", help="List connected controller serial numbers")

    # pages
    sub.add_parser("pages", help="List all pages")

    # add-page
    p = sub.add_parser("add-page", help="Add a new page")
    p.add_argument("name", help="Page name")
    p.add_argument("json", nargs="?", default="", help="JSON contents (optional)")

    # remove-page
    p = sub.add_parser("remove-page", help="Remove a page")
    p.add_argument("name", help="Page name")

    # set-active-page
    p = sub.add_parser("set-active-page", help="Set the active page on a controller")
    p.add_argument("serial", help="Controller serial number")
    p.add_argument("name", help="Page name")

    # notify-foreground
    p = sub.add_parser("notify-foreground", help="Notify foreground application")
    p.add_argument("window_name", help="Window title")
    p.add_argument("window_class", help="Window WM_CLASS")

    # icon-packs
    sub.add_parser("icon-packs", help="List icon packs")

    # icons
    p = sub.add_parser("icons", help="List icons in a pack")
    p.add_argument("pack_id", help="Icon pack ID")

    # get-property
    p = sub.add_parser("get-property", help="Read a DBus property")
    p.add_argument("--serial", "-s", default=None,
                   help="Controller serial (omit for top-level properties)")
    p.add_argument("property_name",
                   help="Property name (Controllers, ForegroundWindowName, ActivePageName, …)")

    # listen
    sub.add_parser("listen", help="Listen for property change notifications")

    return parser


DISPATCH = {
    "controllers":      cmd_controllers,
    "pages":            cmd_pages,
    "add-page":         cmd_add_page,
    "remove-page":      cmd_remove_page,
    "set-active-page":  cmd_set_active_page,
    "notify-foreground": cmd_notify_foreground,
    "icon-packs":       cmd_icon_packs,
    "icons":            cmd_icons,
    "get-property":     cmd_get_property,
    "listen":           cmd_listen,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handler = DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
