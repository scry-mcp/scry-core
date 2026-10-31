"""The fields of the tools both servers declare alike, checked field by field: a field is here only
where it means the same on both and carries the same condition. Each server's model adds its own."""

from __future__ import annotations

from typing import Annotated, Any, Required

from typing_extensions import TypedDict

from scry_core.reply_contract import When


class MapWriteFields(TypedDict, total=False):
    """`screen_map_write`'s fields on both servers."""

    anchor: Annotated[str, When("`add`, given one")]
    application: Annotated[str, When("`load`", "`save`")]
    cells: str
    controls: int
    kind: Annotated[str, When("`add`")]
    match: list[Any]
    mode: Annotated[str, When("`load`", "`save`")]
    path: str
    pointer: Annotated[dict[str, Any], When("a map that declares the program's pointer")]
    promoted: Annotated[list[Any], When("`save`")]
    replaced: Annotated[bool, When("`add`")]
    screen: str
    screens: Annotated[int, When("`load`", "`save`")]
    shadows_file: Annotated[bool, When("`add`")]
    size: Annotated[list[Any], When("`add`")]


class LogWaitFields(TypedDict, total=False):
    """`log_wait`'s fields on both servers."""

    already: Annotated[bool, When("`verdict` `TARGET`")]
    arrived_during: Required[int]
    channel: str
    line: Annotated[str, When("`verdict` `TARGET`")]
    lines_before: Annotated[int, When("`verdict` `TARGET`")]
    lines_examined: Required[int]
    lines_total: Annotated[int, When("`verdict` `TARGET`")]
    pattern: str
    verdict: Required[str]
    waited_s: Required[float]


class CommentWriteFields(TypedDict, total=False):
    """`comment_write`'s fields on both servers."""

    added: Annotated[int, When("`load`")]
    comment: Annotated[dict[str, Any], When("`add`")]
    comments_total: Annotated[int, When("`save`", "`load`")]
    declarations: Annotated[dict[str, Any], When("`add`", "`delete`", "`load`")]
    deleted: Annotated[dict[str, Any], When("`delete`")]
    dropped_comments: Annotated[list[Any], When("`save`")]
    dropped_total: Annotated[int, When("`save`")]
    parsed: Annotated[int, When("`load`")]
    path: str
    replaced_comments: Annotated[list[Any], When("`add`", "`load`")]
    replaced_total: Annotated[int, When("`load`")]
    truncated: Annotated[bool, When("`save`", "`load`")]
    unchanged: Annotated[int, When("`load`")]


class WindowRefusedFields(TypedDict, total=False):
    """What a `window_not_visible` refusal says of the window it looked for, on both servers."""

    activation: Annotated[str, When("`window_not_visible` after an activation")]
    asked_display: Annotated[int, When("`window_not_visible`")]
    seen: Annotated[dict[str, Any], When("`window_not_visible` with a window listed")]
