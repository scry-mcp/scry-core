"""`knowledge_find`, held once for both servers: one body, description, judge, summary line and
reply model. A server registers it with `register(wrap, answer, base, live)`: `wrap` is its
registration decorator, `answer` makes the body's fields its reply, `base` its loaded base and
`live` what its machine says about itself. `judge` goes in its pre-gate table."""

from __future__ import annotations

import difflib
import functools
import inspect
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Annotated, Any, Protocol, Required

from typing_extensions import TypedDict

from scry_core import judges, prose
from scry_core import vocabulary as vocab
from scry_core.knowledge import KINDS, KeyFault
from scry_core.knowledge import keys as keyspelling
from scry_core.knowledge.index import Found
from scry_core.knowledge.text import terms
from scry_core.reply_contract import Invalid, When
from scry_core.reply_schema import ReplyEnvelope

TITLE = "What a number is called"
LIMIT_DEFAULT, LIMIT_MAX = 10, 50
KEYS_SHOWN = 12
UNCONFIRMED_SHOWN = 10
HOW = "give `id` for the whole entry"
REFERENCE = "Reference: REFERENCE.md, Names for numbers."


class Answers(Protocol):
    """What the tool asks of a base: its lookups (`scry_core.knowledge.index`), an entry whole and
    a row by `<entry id>#<n>`."""

    pins: Mapping[str, str]

    def __len__(self) -> int: ...
    @property
    def held_back(self) -> int: ...
    def faults(self) -> list[str]: ...
    def ids(self) -> list[str]: ...
    def scopes(self, kind: str = "") -> list[str]: ...
    def held_scopes(self) -> list[str]: ...
    def kinds(self, scope: str = "") -> list[str]: ...
    def device_keys(self) -> list[str]: ...
    def unconfirmed(self, id: str = "", kind: str = "", key: str = "", device: str = "",
                    scopes: Iterable[str] = ()) -> list[str]: ...
    def search(self, kind: str = "", key: str = "", words: str = "", device: str = "",
               scopes: Iterable[str] = (), limit: int = 10) -> Found[Any]: ...
    def by_id(self, id: str) -> Any: ...
    def whole(self, e: Any) -> Mapping[str, Any]: ...
    def row(self, id: str) -> Mapping[str, Any] | None: ...


class Counts(TypedDict):
    """How many entries a base serves and how many it holds back as not confirmed: the block a
    server's `status` carries and the two fields every `knowledge_find` reply ends with."""

    served: int
    held_back: int


def counts(base: Answers) -> Counts:
    return {"served": len(base), "held_back": base.held_back}


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


def _nearest_ids(base: Answers, wanted: str) -> list[str]:
    ids = base.ids()
    return difflib.get_close_matches(wanted, ids, n=5, cutoff=0.0)


def _read_scope(base: Answers, scope: str) -> tuple[str, str]:
    """`scope` as the base holds it and, when a near miss was read as one (`6809` for `m6809`,
    `M-6809`: the same letters and digits, or a few letters before them), what was read."""
    held = sorted({*base.scopes(), *base.held_scopes()})
    if not scope or scope in held:
        return scope, ""
    plain = re.sub(r"[^a-z0-9]", "", scope.lower())
    near = [h for h in held if plain and re.fullmatch(
        rf"([a-z]{{1,4}})?{re.escape(plain)}", re.sub(r"[^a-z0-9]", "", h.lower()))]
    if len(near) != 1:
        raise Invalid("bad_argument", f"scope={scope!r} is not one this server holds: "
                      f"{', '.join(held) or 'none'}")
    return near[0], f"scope {scope!r} was read as {near[0]}"


def _live_rows(live: Live, kind: str, key: str, device: str) -> list[dict[str, Any]] | None:
    got = live.rows(kind, key, device)
    return None if got is None else [{**r, "live": True} for r in got]


def _tag(base: Answers, live: Live, kind: str, key: str, device: str) -> str:
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


def _no_machine(base: Answers, tag: str) -> Invalid:
    keys = base.device_keys()
    shown = ", ".join(keys[:KEYS_SHOWN]) + (f" and {len(keys) - KEYS_SHOWN} more"
                                            if len(keys) > KEYS_SHOWN else "")
    return Invalid("no_session", f"the device tag {tag} needs a running machine and no session "
                   f"is live: call `start`. With none, a device is asked by its key: "
                   f"{shown or 'none'}")


def _with_chip(base: Answers, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The one row of a tag, with what the base knows of its chip, when the row names one."""
    if len(rows) != 1 or not (chip := base.by_id(str(rows[0].get("chip", "")))):
        return rows
    return [{**rows[0], "chip_entry": dict(base.whole(chip))}]


def find(base: Answers, live: Live | None = None, id: str = "", kind: str = "", key: str = "",
         text: str = "", device: str = "", scope: str = "",
         limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
    """The body: the fields of the reply, and the base's two counts."""
    return {**_find(base, live or NoLive(), id, kind, key, text, device, scope, limit),
            **counts(base)}


def _find(base: Answers, live: Live, id: str, kind: str, key: str, text: str, device: str,
          scope: str, limit: int) -> dict[str, Any]:
    judge(id, kind, key, text, device, scope, limit)
    if not len(base) and not base.held_back:
        raise Invalid("no_channel", "this server's knowledge base holds no entries"
                      + (f": {base.faults()[0]}" if base.faults() else ""))
    scope, read = _read_scope(base, scope)
    if id:
        return _by_id(base, id)
    if kind and kind not in base.kinds() and kind not in live.kinds and not base.unconfirmed(
            kind=kind):
        raise Invalid("no_channel", f"this server holds no entries of kind {kind}; it has "
                      f"{', '.join(base.kinds())}", kinds=base.kinds())
    tag = _tag(base, live, kind, key, device)
    if device and not tag and device not in base.device_keys() and not base.unconfirmed(
            device=device):
        raise Invalid("unknown_ref", f"device {device!r} is not one the base holds; it has "
                      f"{', '.join(base.device_keys())}", nearest=difflib.get_close_matches(
                          device, base.device_keys(), n=5, cutoff=0.0))
    scopes = (scope,) if scope else live.scopes()
    if scopes and not scope:
        held = base.scopes()
        shared = (*(k for k in base.device_keys() if k in held), *base.scopes("device"))
        scopes += tuple(dict.fromkeys(s for s in shared if s not in scopes))
    live_rows: list[dict[str, Any]] = []
    if tag or (kind in live.kinds and kind not in base.kinds()):
        got = _live_rows(live, kind, "" if tag else key, tag)
        if got is None:
            raise _no_machine(base, tag) if tag else Invalid(
                "no_session", f"{kind} is read from the running machine and no session is "
                "live: call `start`")
        live_rows = _with_chip(base, got) if tag else got
    try:
        found = base.search(kind, key, text, device, scopes, limit) if not tag else Found[Any]()
    except KeyFault as bad:
        raise Invalid("bad_argument", f"key={key!r} is no key: {bad}") from bad
    return _answer(base, found, live_rows, kind, tag if tag and not device else key, text, device,
                   scopes, limit, read, bool(tag))


def _by_id(base: Answers, id: str) -> dict[str, Any]:
    if "#" in id and (one := base.row(id)) is not None:
        return {"query": {"id": id}, "scope": [one["scope"]], "entries_total": 1,
                "entries": [dict(one)], "truncated": False, "examined": len(base)}
    got = base.by_id(id)
    if got is None and (hidden := base.unconfirmed(id=id)):
        return {"query": {"id": id}, "scope": [], "entries_total": 0, "entries": [],
                "truncated": False, "examined": len(base),
                "note": _unconfirmed_note(hidden, 0), "unconfirmed": hidden}
    if got is None:
        raise Invalid("unknown_ref", f"id {id!r} names no entry; the nearest are "
                      f"{', '.join(_nearest_ids(base, id))}", nearest=_nearest_ids(base, id))
    return {"query": {"id": id}, "scope": [got.scope], "entries_total": 1,
            "entries": [dict(base.whole(got))], "truncated": False, "examined": len(base)}


def _answer(base: Answers, found: Found[Any], live_rows: list[dict[str, Any]], kind: str, key: str,
            words: str, device: str, scopes: Sequence[str], limit: int,
            read: str = "", tagged: bool = False) -> dict[str, Any]:
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
        out["entries"] = [dict(base.whole(found.entries[0]))]
    else:
        out["entries"] = rows[:limit]
    out["truncated"] = total > len(out["entries"])
    out["examined"] = found.examined
    if total > 1:
        out["how"] = HOW
    hidden = [] if tagged or words or not (key or device or (kind and not total)
                                           ) else base.unconfirmed(
        kind=kind, key=key, device=device, scopes=scopes)
    if not total:
        out["nearest"] = [e.short() for e in found.nearest]
        out["note"] = (_unconfirmed_note(hidden, 0) if hidden else
                       f"the running machine has no device at {key or device}: it stays a number"
                       if tagged else _stays_a_number(base, found, kind, key, words, scopes))
    elif hidden:
        out["note"] = _unconfirmed_note(hidden, total)
    if hidden:
        out["unconfirmed"] = hidden[:UNCONFIRMED_SHOWN]
    if read:
        out["note"] = f"{read}; {out['note']}" if "note" in out else read
    return out


def _unconfirmed_note(hidden: Sequence[str], total: int) -> str:
    """What the reply says of the entries a question matches and the base holds back."""
    n = len(hidden)
    if total:
        return (f"{n} more {'entry exists' if n == 1 else 'entries exist'} and "
                f"{'is' if n == 1 else 'are'} not confirmed, so not served")
    return ("an entry exists and is not confirmed, so it is not served: it stays a number"
            if n == 1 else f"{n} entries exist and none is confirmed, so none is served: "
            "they stay numbers")


def _stays_a_number(base: Answers, found: Found[Any], kind: str, key: str, words: str,
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
    held_back: Required[int]
    nearest: Annotated[list[dict[str, Any]], When("nothing matched")]
    query: Required[dict[str, Any]]
    scope: Required[list[str]]
    served: Required[int]
    truncated: Required[bool]
    unconfirmed: Annotated[list[str], When("held back")]


def knowledge_find(id: str = "", kind: Annotated[str, vocab.enum(("", *KINDS))] = "",
                   key: str = "", text: str = "", device: str = "", scope: str = "",
                   limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
    """What a number is called on the machine and what the base knows of it: a port, vector,
    DOS or BIOS call, IRQ, memory address, input, device, register or command. One match, or an
    `id`, answers the entry: its `rows`, the document's first with each emulator's `verdicts`,
    then the emulators' notes (`vs`); `id=<id>#<n>`: a row, with URLs. More: a list. No session
    is needed except for a device by tag, inputs and memory.

    `id`: an entry's id. `kind`: `vector`, `call`, `error`, `port`, `irq`, `memory`, `input`,
    `device`, `register` or `command`; empty searches all. `key`: the number as a reply prints it,
    or a range. `text`: words in names, aliases, rows; `*` ends a prefix. `device`: all of
    that device. `scope`: the system, cpu or device; empty, the live session's. `limit` 1..50.

    Examples: `key=0x3C8`; `kind=vector key=0xFFF8 scope=<scope>`; `kind=call key=0x21/0x4C`,
    a variant `kind=call key=0x10/0x12/BL=0x36`;
    a live device by tag `kind=device key=:maincpu`; its registers
    `kind=register device=<device>`; `text=palette*`.

    Refused (INVALID): nothing to look up, a bad `key`, or a `scope` it lacks
    (`bad_argument`; `6809` is read as `m6809`); an `id` or `device` it
    lacks (`unknown_ref`); a kind it holds none of (`no_channel`); a tag or live kind with no
    session (`no_session`).

    Reply: `query`, `scope`, `entries_total`, `entries`, `truncated`, `examined`, `served`,
    `held_back`; nothing matched: no entry, `nearest` and a `note`: it stays a number.
    `unconfirmed` lists ids held back."""
    raise NotImplementedError("a server registers `register`'s bound body, not this signature")


def scopes_line(scopes: Sequence[str]) -> str:
    """The scopes a server holds, as its description lists them: the server's own, never typed
    twice."""
    return f"Scopes: {', '.join(scopes) or 'none'}."


def summary(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """The one line a reader sees first: what was asked and what answered."""
    query = reply["query"]
    asked = " ".join(f"{k} {v}" for k, v in query.items() if k != "id") or f"id {query['id']}"
    total = reply["entries_total"]
    if not total:
        return (f"{asked}: no entry served; {reply['note']}" if reply.get("unconfirmed")
                else f"{asked}: no entry; {reply.get('note', 'it stays a number')}")
    entries = reply["entries"]
    if total == 1:
        return f"{asked}: {entries[0]['name']}"
    return (f"{asked}: {prose.counted(total, 'entry', 'entries')}, the first {len(entries)} "
            f"listed" if reply["truncated"] else
            f"{asked}: {prose.counted(total, 'entry', 'entries')}")


def register(wrap: Callable[..., Callable[[Callable[..., Any]], Any]],
             answer: Callable[[dict[str, Any]], dict[str, Any]], base: Answers,
             live: Live | None = None) -> Any:
    """Register `knowledge_find` through the server's own decorator: read-only, with the
    description above and the body bound to this server's `base` and `live`."""
    @functools.wraps(knowledge_find)
    def tool(id: str = "", kind: str = "", key: str = "", text: str = "", device: str = "",
             scope: str = "", limit: int = LIMIT_DEFAULT) -> dict[str, Any]:
        return answer(find(base, live, id, kind, key, text, device, scope, limit))
    tool.__doc__ = (inspect.cleandoc(knowledge_find.__doc__ or "") + "\n\n"
                    + scopes_line(base.scopes()) + f"\n\n{REFERENCE}\n")
    return wrap(TITLE, summary=summary, read_only=True)(tool)
