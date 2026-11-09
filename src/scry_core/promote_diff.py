"""What an update changes in a store entry, as a promotion's review shows it."""

from __future__ import annotations

from typing import Any

#: The lists whose items are identified by their `name`, and the changes one diff shows: a map
#: of many screens would otherwise fill a reply. Every other list is compared by index, because
#: a `perform` document's steps are a program and their order is part of it.
NAMED = frozenset({"screens", "controls"})
CHANGES_SHOWN = 20


def difference(old: Any, new: Any) -> dict[str, Any]:
    """What an update changes: the paths it adds, removes and changes, with both values. A map's
    screens and its controls are changed whole by name, and a reordering of them is a change; a
    `perform` document's steps are compared by index, because their order is the program."""
    added: list[str] = []
    removed: list[str] = []
    changed: list[dict[str, Any]] = []
    _walk("", old, new, added, removed, changed)
    shown = {"added": added, "removed": removed, "changed": changed[:CHANGES_SHOWN]}
    if len(changed) > CHANGES_SHOWN:
        shown["changed_total"] = len(changed)
    return shown


def _walk(path: str, old: Any, new: Any, added: list[str], removed: list[str],
          changed: list[dict[str, Any]]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        removed.extend(_join(path, key) for key in sorted(old.keys() - new.keys()))
        added.extend(_join(path, key) for key in sorted(new.keys() - old.keys()))
        for key in sorted(old.keys() & new.keys()):
            _walk(_join(path, key), old[key], new[key], added, removed, changed)
        return
    if isinstance(old, list) and isinstance(new, list):
        if _key(path) in NAMED and _named(old) and _named(new):
            before = {item["name"]: item for item in old}
            after = {item["name"]: item for item in new}
            removed.extend(_join(path, name) for name in sorted(before.keys() - after.keys()))
            added.extend(_join(path, name) for name in sorted(after.keys() - before.keys()))
            for name in sorted(before.keys() & after.keys()):
                if before[name] != after[name]:
                    changed.append({"path": _join(path, name), "was": before[name],
                                    "now": after[name]})
            order_old = [item["name"] for item in old]
            order_new = [item["name"] for item in new]
            if order_old != order_new and sorted(order_old) == sorted(order_new):
                changed.append({"path": f"{path}[order]", "was": order_old, "now": order_new})
            return
        if all(isinstance(item, dict) for item in (*old, *new)):
            for i in range(min(len(old), len(new))):
                _walk(f"{path}[{i}]", old[i], new[i], added, removed, changed)
            added.extend(f"{path}[{i}]" for i in range(len(old), len(new)))
            removed.extend(f"{path}[{i}]" for i in range(len(new), len(old)))
            return
        if old != new:
            changed.append({"path": path, "was": old, "now": new})
        return
    if old != new:
        changed.append({"path": path, "was": old, "now": new})


def _named(items: list[Any]) -> bool:
    """Whether `items` is a list of objects each named: the unit a diff changes whole."""
    names = [item.get("name") for item in items if isinstance(item, dict)]
    if len(names) != len(items) or not all(isinstance(name, str) and name for name in names):
        return False
    return len(set(names)) == len(names)


def _key(path: str) -> str:
    """The document key a diff path ends in, its indices cut."""
    return path.rsplit(".", 1)[-1].split("[", 1)[0]


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key
