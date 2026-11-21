"""`knowledge_find`, held once for both servers: one body, description, judge, summary line and
reply model. A server registers it with `register(wrap, answer, base, live)`: `wrap` is its
registration decorator, `answer` makes the body's fields its reply, `base` its loaded base and
`live` what its machine says about itself. `judge` goes in its pre-gate table."""

from __future__ import annotations

import difflib
import functools
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Protocol, Required

from scry_core import judges, prose
from scry_core import vocabulary as vocab
from scry_core.knowledge import KINDS, Base, Entry, Found, KeyFault, sources
from scry_core.knowledge import keys as keyspelling
from scry_core.knowledge.text import terms
from scry_core.reply_contract import Invalid, When
from scry_core.reply_schema import ReplyEnvelope

TITLE = "What a number is called"
LIMIT_DEFAULT, LIMIT_MAX = 10, 50
KEYS_SHOWN = 12
HOW = "give `id` for the whole entry"
REFERENCE = "Reference: REFERENCE.md, Names for numbers."


class Live(Protocol):
    """What a running machine says about itself, in rows with no `id` and no `sources`: its kinds,
    its scopes (empty with no session; the tool adds the devices'), and the rows for a question
    (None with no session)."""

    kinds: tuple[str, ...]

    def scopes(self) -> tuple[str, ...]: ...

    def rows(self, kind: str, key: str, device: str) -> Sequence[Mapping[str, Any]] | None: ...


class NoLive:
    """A server that reads nothing from its machine."""

    kinds: tuple[str, ...] = ()

    def scopes(self) -> tuple[str, ...]:
        return ()

    def rows(self, kind: str, key: str, device: str) -> None:
        return None


def judge(id: Any = "", kind: Any = "", key: Any = "", text: Any = "", device: Any = "",
          scope: Any = "", limit: Any = LIMIT_DEFAULT) -> None:
    """The refusals that need neither the machine nor the base."""
    for name, value in (("id", id), ("kind", kind), ("key", key), ("text", text),
                        ("device", device), ("scope", scope)):
        if not isinstance(value, str):
            raise Invalid("bad_argument", f"{name}={value!r} is text")
    if not any((id, kind, key, text, device)):
        raise Invalid("bad_argument", "give at least one of `id`, `kind`, `key`, `text` and "
                      "`device`: what to look up")
    if kind and kind not in KINDS:
        raise Invalid("bad_argument", f"kind={kind!r} is one of {', '.join(KINDS)}, or empty "
                      "for every kind")
    if key and kind:
        try:
            keyspelling.query(kind, key)
        except KeyFault as bad:
            raise Invalid("bad_argument", f"key={key!r} is no key of kind {kind}: {bad}") from bad
    if text and not terms(text):
        raise Invalid("bad_argument", f"text={text!r} holds no word: letters and digits, `*` "
                      "after a word for a prefix")
    if not judges.whole(limit, 1, LIMIT_MAX):
        raise Invalid("bad_argument", f"limit={limit!r} is how many entries are listed, "
                      f"1..{LIMIT_MAX}")


def whole(base: Base, e: Entry, pins: Mapping[str, str]) -> dict[str, Any]:
    """An entry whole: its fields, each source with its `url`, and what ties it to hardware."""
    related = base.related(e)
    out: dict[str, Any] = {**e.short()}
    for name, value in (
            ("aliases", list(e.aliases)), ("description", e.description),
            ("behaviour", e.behaviour), ("differs", e.differs),
            ("address", f"0x{e.address:06X}" if e.address is not None else ""),
            ("length", e.length or 0), ("access", e.access),
            ("ports", [{"base": f"0x{b:02X}", "length": n} for b, n in e.ports]),
            ("irq", list(e.irq)), ("dma", list(e.dma)), ("contains", list(e.contains)),
            ("classes", list(e.classes)), ("handlers", dict(e.handlers or {})),
            ("reached", {k: list(v) for k, v in related.reached.items()}),
            ("used_by", [u.id for u in related.used_by]),
            ("checked", e.checked is not None)):
        if value:
            out[name] = value
    out["sources"] = [{"role": s.role, "ref": s.ref, "cites": s.cites,
                       **({"url": u} if (u := sources.url(s.ref, pins)) else {})}
                      for s in e.sources]
    return out


def _nearest_ids(base: Base, wanted: str) -> list[str]:
    ids = [e.id for e in base.entries()]
    return difflib.get_close_matches(wanted, ids, n=5, cutoff=0.0)


def _refuse_scope(base: Base, scope: str) -> None:
    if scope and scope not in base.scopes():
        raise Invalid("bad_argument", f"scope={scope!r} is not one this server holds: "
                      f"{', '.join(base.scopes()) or 'none'}")


def _live_rows(live: Live, kind: str, key: str, device: str) -> list[dict[str, Any]] | None:
    got = live.rows(kind, key, device)
    return None if got is None else [{**r, "live": True} for r in got]


def _tag(base: Base, live: Live, kind: str, key: str, device: str) -> str:
    """The tag of the running machine a question names, with its colon, or empty: `device=":t"`,
    or a device `key` that is `:t` or is no key of the base and the server's machine has devices."""
    if device.startswith(":"):
        return device
    key = key.strip()
    if kind != "device" or device or not key:
        return ""
    if key.startswith(":"):
        return key
    return "" if key in base.device_keys() or "device" not in live.kinds else f":{key}"


def _no_machine(base: Base, tag: str) -> Invalid:
    keys = base.device_keys()
    shown = ", ".join(keys[:KEYS_SHOWN]) + (f" and {len(keys) - KEYS_SHOWN} more"
                                            if len(keys) > KEYS_SHOWN else "")
    return Invalid("no_session", f"the device tag {tag} needs a running machine and no session is "
                   f"live: call `start`. With none, a device is asked by its key: {shown or 'none'}")


def _with_chip(base: Base, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The one row of a tag, with what the base knows of its chip, when the row names one."""
    if len(rows) != 1 or not (chip := base.by_id(str(rows[0].get("chip", "")))):
        return rows
    return [{**rows[0], "chip_entry": whole(base, chip, base.pins)}]


def find(base: Base, live: Live | None = None, id: str = "", kind: str = "", key: str = "",
         text: str = "", device: str = "", scope: str = "",
         limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
    """The body: the fields of the reply."""
    live = live or NoLive()
    judge(id, kind, key, text, device, scope, limit)
    if not len(base):
        raise Invalid("no_channel", "this server's knowledge base holds no entries"
                      + (f": {base.faults()[0]}" if base.faults() else ""))
    _refuse_scope(base, scope)
    if id:
        return _by_id(base, id)
    if kind and kind not in base.kinds() and kind not in live.kinds:
        raise Invalid("no_channel", f"this server holds no entries of kind {kind}; it has "
                      f"{', '.join(base.kinds())}", kinds=base.kinds())
    tag = _tag(base, live, kind, key, device)
    if device and not tag and device not in base.device_keys():
        raise Invalid("unknown_ref", f"device {device!r} is not one the base holds; it has "
                      f"{', '.join(base.device_keys())}", nearest=difflib.get_close_matches(
                          device, base.device_keys(), n=5, cutoff=0.0))
    scopes = (scope,) if scope else live.scopes()
    if scopes and not scope:
        scopes += tuple(k for k in base.device_keys() if k in base.scopes())
    live_rows: list[dict[str, Any]] = []
    if tag or (kind in live.kinds and kind not in base.kinds()):
        got = _live_rows(live, kind, "" if tag else key, tag)
        if got is None:
            raise _no_machine(base, tag) if tag else Invalid(
                "no_session", f"{kind} is read from the running machine and no session is "
                "live: call `start`")
        live_rows = _with_chip(base, got) if tag else got
    try:
        found = base.search(kind, key, text, device, scopes, limit) if not tag else Found()
    except KeyFault as bad:
        raise Invalid("bad_argument", f"key={key!r} is no key: {bad}") from bad
    return _answer(base, found, live_rows, kind, tag if tag and not device else key, text, device,
                   scopes, limit)


def _by_id(base: Base, id: str) -> dict[str, Any]:
    got = base.by_id(id)
    if got is None:
        raise Invalid("unknown_ref", f"id {id!r} names no entry; the nearest are "
                      f"{', '.join(_nearest_ids(base, id))}", nearest=_nearest_ids(base, id))
    return {"query": {"id": id}, "scope": [got.scope], "entries_total": 1,
            "entries": [whole(base, got, base.pins)], "truncated": False, "examined": len(base)}


def _answer(base: Base, found: Found, live_rows: list[dict[str, Any]], kind: str, key: str,
            words: str, device: str, scopes: Sequence[str], limit: int) -> dict[str, Any]:
    query: dict[str, Any] = {}
    for name, value in (("kind", kind), ("key", key), ("text", words), ("device", device)):
        if value:
            query[name] = value
    if kind and key:
        query["key"] = key if kind == "device" else keyspelling.query(kind, key)[0]
    rows: list[dict[str, Any]] = [e.short() for e in found.entries] + live_rows
    total = found.total + len(live_rows)
    out: dict[str, Any] = {"query": query, "scope": list(scopes) or base.scopes(kind),
                           "entries_total": total}
    if total == 1 and found.entries:
        out["entries"] = [whole(base, found.entries[0], base.pins)]
    else:
        out["entries"] = rows[:limit]
    out["truncated"] = total > len(out["entries"])
    out["examined"] = found.examined
    if total > 1:
        out["how"] = HOW
    if not total:
        out["nearest"] = [e.short() for e in found.nearest]
        out["note"] = _stays_a_number(base, found, kind, key, words, scopes)
    return out


def _stays_a_number(base: Base, found: Found, kind: str, key: str, words: str,
                    scopes: Sequence[str]) -> str:
    noun = prose.counted(found.examined, kind) if kind else prose.counted(
        found.examined, "entry", "entries")
    held = f"the base holds {noun}"
    where = f" for {', '.join(scopes)}" if scopes else ""
    if key:
        return f"{held}{where} and none at {key}: it stays a number"
    return f"{held}{where} and none says {words or 'that'}"


class KnowledgeFindReply(ReplyEnvelope, total=False):
    """What `knowledge_find` answers: `how` and `note` are the envelope's."""

    entries: Required[list[dict[str, Any]]]
    entries_total: Required[int]
    examined: Required[int]
    nearest: Annotated[list[dict[str, Any]], When("nothing matched")]
    query: Required[dict[str, Any]]
    scope: Required[list[str]]
    truncated: Required[bool]


def knowledge_find(id: str = "", kind: Annotated[str, vocab.enum(("", *KINDS))] = "",
                   key: str = "", text: str = "", device: str = "", scope: str = "",
                   limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
    """What a number is called on this machine, and what the base knows about it: a port, an
    interrupt vector, a DOS or BIOS call, an IRQ line, a fixed memory address, an input, a device
    and its registers and commands. Rows first (`id`, `kind`, `key`, `name`); one match, or an
    `id`, answers the whole entry: `description`, `behaviour` (what reading, writing or calling it
    does), `aliases`, `device`, and the public `sources` it was checked against, with what the
    emulator does where they differ. Answers with no session, except the kinds read from the
    running machine.

    `id`: an entry's id, as another reply cites it. `kind`: one of `vector`, `call`, `error`,
    `port`, `irq`, `memory`, `input`, `device`, `register`, `command`; empty searches every kind.
    `key`: the number as a reply prints it (`0x3C8`, `0x21`, `0x21/0x4C` for a function of an
    interrupt, `0x10/0x12/BL=0x36` for its variant by a register, `0040:0049`), or a range
    (`0x3C0..0x3CF`). `text`: words looked for in names,
    aliases and descriptions; a word ending in `*` matches by prefix. `device`: everything that
    belongs to that device. Give `id`, `key`, `text`, `device`, or only `kind` to list it.
    `scope`: the system, cpu or device the answer is for; empty, the live session's. `limit` 1..50.

    Refused (INVALID): none of `id`, `kind`, `key`, `text`, `device` (`bad_argument`); a `key`
    that is no number or range of that kind (`bad_argument`); an `id` or a `device` the base does
    not hold (`unknown_ref`, naming the nearest); a kind this server holds nothing of
    (`no_channel`, naming the kinds it has); a kind read from the machine with no session
    (`no_session`); a `scope` it does not support (`bad_argument`, naming them).

    Reply: `query`, `scope`, `entries_total`, `entries`, `truncated`, `examined`; nothing matched
    answers with no entry, `nearest` and a `note`: it stays a number."""
    raise NotImplementedError("a server registers `register`'s bound body, not this signature")


def summary(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """The one line a reader sees first: what was asked and what answered."""
    query = reply["query"]
    asked = " ".join(f"{k} {v}" for k, v in query.items() if k != "id") or f"id {query['id']}"
    total = reply["entries_total"]
    if not total:
        return f"{asked}: no entry; {reply.get('note', 'it stays a number')}"
    entries = reply["entries"]
    if total == 1:
        return f"{asked}: {entries[0]['name']}"
    return (f"{asked}: {prose.counted(total, 'entry', 'entries')}, the first {len(entries)} "
            f"listed" if reply["truncated"] else
            f"{asked}: {prose.counted(total, 'entry', 'entries')}")


def register(wrap: Callable[..., Callable[[Callable[..., Any]], Any]],
             answer: Callable[[dict[str, Any]], dict[str, Any]], base: Base,
             live: Live | None = None) -> Any:
    """Register `knowledge_find` through the server's own decorator: read-only, with the
    description above and the body bound to this server's `base` and `live`."""
    @functools.wraps(knowledge_find)
    def tool(id: str = "", kind: str = "", key: str = "", text: str = "", device: str = "",
             scope: str = "", limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
        return answer(find(base, live, id, kind, key, text, device, scope, limit))
    tool.__doc__ = inspect.cleandoc(knowledge_find.__doc__ or "") + f"\n\n{REFERENCE}\n"
    return wrap(TITLE, summary=summary, read_only=True)(tool)
