#!/usr/bin/env python3
"""
StreamController DBus API client.

A command-line tool and reusable client for the StreamController DBus API.

Usage:
    python api_client.py controllers                              # List controller serial numbers
    python api_client.py pages                                    # List all pages
    python api_client.py add-page NAME [JSON]                     # Add a page
    python api_client.py remove-page NAME                         # Remove a page
    python api_client.py set-active-page SERIAL NAME              # Set active page on a controller
    python api_client.py notify-foreground NAME CLASS             # Notify foreground app
    python api_client.py icon-packs                               # List icon packs
    python api_client.py icons PACK_ID                            # List icons in a pack
    python api_client.py get-property [--serial SERIAL] PROP      # Read a property
    python api_client.py listen                                   # Listen for property changes
"""

import argparse
import re
import sys

from dasbus.connection import SessionMessageBus
from gi.repository import GLib

SERVICE    = "com.core447.StreamController"
OBJECT     = "/com/core447/StreamController"
IFACE      = "com.core447.StreamController"
CTRL_IFACE = "com.core447.StreamController.Controller"
CTRL_BASE  = OBJECT + "/controllers"


def _serial_to_dbus_path(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", serial)


class StreamControllerClient:
    """Client for the StreamController DBus API."""

    def __init__(self):
        self._bus = SessionMessageBus()

    def _root_proxy(self):
        return self._bus.get_proxy(SERVICE, OBJECT)

    def _controller_proxy(self, serial: str):
        path = f"{CTRL_BASE}/{_serial_to_dbus_path(serial)}"
        return self._bus.get_proxy(SERVICE, path)

    # ── Top-level operations ─────────────────────────────────────────

    def get_controllers(self) -> list[str]:
        """Return serial numbers of all connected controllers."""
        return list(self._root_proxy().Controllers)

    def get_pages(self) -> list[str]:
        """Return a list of page names."""
        return list(self._root_proxy().Pages)

    def add_page(self, name: str, json_contents: str = "") -> None:
        """Add a new page with the given name and optional JSON contents."""
        self._root_proxy().AddPage(name, json_contents)

    def remove_page(self, name: str) -> None:
        """Remove the page with the given name."""
        self._root_proxy().RemovePage(name)

    def notify_foreground(self, window_name: str, window_class: str) -> None:
        """Notify StreamController of the current foreground application."""
        self._root_proxy().NotifyForegroundApp(window_name, window_class)

    def get_icon_packs(self) -> list[str]:
        """Return a list of icon pack IDs."""
        return list(self._root_proxy().IconPacks)

    def get_icon_names(self, pack_id: str) -> list[str]:
        """Return a list of icon names in the given pack."""
        return list(self._root_proxy().GetIconNames(pack_id))

    def get_property(self, name: str) -> object:
        """Read a top-level property by name."""
        return getattr(self._root_proxy(), name)

    # ── Per-controller operations ────────────────────────────────────

    def set_active_page(self, serial: str, name: str) -> None:
        """Set the active page on the given controller."""
        self._controller_proxy(serial).SetActivePage(name)

    def get_controller_property(self, serial: str, name: str) -> object:
        """Read a property from a specific controller."""
        return getattr(self._controller_proxy(serial), name)

    # ── Listener ─────────────────────────────────────────────────────

    def listen(self, callback=None):
        """
        Listen for PropertiesChanged signals. Blocks until interrupted.

        callback(object_path, interface, property_name, value) is called
        for each change.  If callback is None, changes are printed to stdout.
        """
        connection = self._bus.connection

        def _default_callback(object_path, iface, prop, value):
            prefix = "[root]" if object_path == OBJECT else f"[{object_path}]"
            print(f"{prefix} {iface} {prop} = {value!r}")

        cb = callback or _default_callback

        def on_signal(conn, sender, object_path, iface, signal, params):
            sig_iface, changed, invalidated = params.unpack()
            for prop, value in changed.items():
                cb(object_path, sig_iface, prop, value)
            for prop in invalidated:
                cb(object_path, sig_iface, prop, None)

        # Subscribe on root and all sub-objects
        for path in (OBJECT, None):
            connection.signal_subscribe(
                SERVICE, "org.freedesktop.DBus.Properties",
                "PropertiesChanged", path, None, 0, on_signal,
            )

        print(f"Listening for property changes on {SERVICE} …  (Ctrl+C to stop)")
        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            print("\nStopped.")


# ── CLI ──────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(description="StreamController DBus API client")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("controllers", help="List connected controller serial numbers")
    sub.add_parser("pages", help="List all pages")

    p = sub.add_parser("add-page", help="Add a new page")
    p.add_argument("name", help="Page name")
    p.add_argument("json", nargs="?", default="", help="JSON contents (optional)")

    p = sub.add_parser("remove-page", help="Remove a page")
    p.add_argument("name", help="Page name")

    p = sub.add_parser("set-active-page", help="Set the active page on a controller")
    p.add_argument("serial", help="Controller serial number")
    p.add_argument("name", help="Page name")

    p = sub.add_parser("notify-foreground", help="Notify foreground application")
    p.add_argument("window_name", help="Window title")
    p.add_argument("window_class", help="Window WM_CLASS")

    sub.add_parser("icon-packs", help="List icon packs")

    p = sub.add_parser("icons", help="List icons in a pack")
    p.add_argument("pack_id", help="Icon pack ID")

    p = sub.add_parser("get-property", help="Read a DBus property")
    p.add_argument("--serial", "-s", default=None,
                   help="Controller serial (omit for top-level properties)")
    p.add_argument("property_name",
                   help="Property name (Controllers, Pages, ActivePageName, …)")

    sub.add_parser("listen", help="Listen for property change notifications")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    client = StreamControllerClient()

    try:
        if args.command == "controllers":
            for s in client.get_controllers():
                print(s)

        elif args.command == "pages":
            pages = client.get_pages()
            if not pages:
                print("No pages found.")
            else:
                for p in pages:
                    print(p)

        elif args.command == "add-page":
            client.add_page(args.name, args.json or "")
            print(f"Added page: {args.name}")

        elif args.command == "remove-page":
            client.remove_page(args.name)
            print(f"Removed page: {args.name}")

        elif args.command == "set-active-page":
            client.set_active_page(args.serial, args.name)
            print(f"Set active page: {args.name}")

        elif args.command == "notify-foreground":
            client.notify_foreground(args.window_name, args.window_class)
            print(f"Notified foreground app: name={args.window_name!r} class={args.window_class!r}")

        elif args.command == "icon-packs":
            packs = client.get_icon_packs()
            if not packs:
                print("No icon packs found.")
            else:
                for p in packs:
                    print(p)

        elif args.command == "icons":
            icons = client.get_icon_names(args.pack_id)
            if not icons:
                print(f"No icons found in pack: {args.pack_id}")
            else:
                for icon in icons:
                    print(icon)

        elif args.command == "get-property":
            if args.serial:
                value = client.get_controller_property(args.serial, args.property_name)
            else:
                value = client.get_property(args.property_name)
            print(f"{args.property_name} = {value!r}")

        elif args.command == "listen":
            client.listen()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
