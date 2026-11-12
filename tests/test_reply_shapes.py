"""The shape guard's judge and its two wraps, on replies of the test's own: a word carrying
another shape is refused wherever it sits, and each wrap judges the reply it is handed."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import reply_shapes_guard as shapes


@pytest.mark.parametrize("reply", [
    {"truncated": 3},
    {"rows": [{"name": "a", "truncated": 1}]},
    {"pages": ({"truncated": "yes"},)},
])
def test_a_word_in_another_shape_is_refused_at_any_depth(reply: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="holds `truncated` to bool"):
        shapes._judge(reply, "reply")


def test_the_shape_it_holds_passes_and_a_bool_is_not_an_int() -> None:
    shapes._judge({"truncated": False, "rows": [{"truncated": True}], "n": 3}, "reply")
    assert not isinstance(1, bool), "the direction the table relies on"


@pytest.mark.parametrize(("reply", "where"), [
    ({"pc": None}, r"a null at reply\['pc'\];"),
    ({"rows": [{"name": "a", "linear": None}], "x": None},
     r"at reply\['rows'\]\[0\]\['linear'\], reply\['x'\];"),
    ({"pairs": (None,)}, r"at reply\['pairs'\]\[0\];"),
])
def test_a_null_is_refused_at_any_depth_naming_where(reply: dict[str, Any], where: str) -> None:
    """No reply carries a null: a datum that could not be read, or does not apply, is the
    contract's `unavailable(why)` in its place, and the guard names where the null sits."""
    with pytest.raises(AssertionError, match=where + ".*unavailable"):
        shapes._judge(reply, "reply")


def test_both_wraps_judge_what_they_are_handed() -> None:
    envelope = shapes._wrap_envelope(lambda reply: reply)
    summary = shapes._wrap_summary(lambda name, args, reply: f"{name}: {reply['status']}")
    assert envelope({"status": "ok", "truncated": False}) == {"status": "ok", "truncated": False}
    assert summary("t", {}, {"status": "ok"}) == "t: ok"
    with pytest.raises(AssertionError):
        envelope({"status": "ok", "truncated": 2})
    with pytest.raises(AssertionError):
        summary("t", {}, {"status": "ok", "truncated": 2})


# ---- the plugin, on suites of the test's own ----------------------------------------------------

#: A server as the guard finds one: the decorator's `_summary`, called once per reply.
FAKE_SERVER = '''
def tool(fn):
    return fn


def _summary(name, args, reply):
    return f"{name}: {reply['status']}"
'''


def _suite(pytester: pytest.Pytester, anchors: list[str] | None, test: str) -> None:
    ini = "" if anchors is None else f"reply_shapes_anchors = {anchors!r}\n".replace("'", '"')
    pytester.makepyprojecttoml(f"[tool.pytest.ini_options]\n{ini}")
    pytester.makepyfile(fake_server=FAKE_SERVER, test_it=test)
    pytester.syspathinsert()


def test_a_suite_that_declares_no_anchor_is_refused_before_it_runs(
        pytester: pytest.Pytester) -> None:
    """The empty case: a plugin that wraps nothing would report green having judged nothing."""
    _suite(pytester, None, "def test_x():\n    pass\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*has no `reply_shapes_anchors` to wrap*"])
    assert 'reply_shapes_anchors = ["scry_core.reply_contract", "scry_core.boundary"]' in (
        result.stderr.str())


def test_a_declared_anchor_no_import_can_find_is_refused_before_it_runs(
        pytester: pytest.Pytester) -> None:
    """A misspelt name wraps nothing, and would otherwise read as a run that imported none."""
    _suite(pytester, ["fake_server", "fake_sever"], "def test_x():\n    pass\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*names fake_sever, which no import can find*"])


def test_a_run_that_imports_no_declared_anchor_says_so_and_passes(
        pytester: pytest.Pytester) -> None:
    """A partial run is not the battery: neutral, in one line, never an error."""
    _suite(pytester, ["fake_server"], "def test_x():\n    pass\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(
        ["reply_shapes: none of fake_server was imported, so this run judged no reply's shape"])


def test_an_imported_anchor_is_wrapped_and_judges_every_reply(pytester: pytest.Pytester) -> None:
    _suite(pytester, ["fake_server"], (
        "import fake_server\n\n\n"
        "def test_clean():\n    assert fake_server._summary('t', {}, {'status': 'ok'}) == 't: ok'\n"
        "\n\ndef test_a_count_where_a_boolean_belongs():\n"
        "    fake_server._summary('t', {}, {'status': 'ok', 'truncated': 3})\n"))
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*holds `truncated` to bool*"])
    assert "judged no reply's shape" not in result.stdout.str()


def test_a_declared_anchor_imported_after_the_guard_is_red_naming_it(
        pytester: pytest.Pytester) -> None:
    """The planted unwrapped anchor: imported inside a test body, after the wrap, so every reply
    it builds would go unjudged."""
    _suite(pytester, ["fake_server"], (
        "def test_late():\n    import fake_server\n"
        "    assert fake_server._summary('t', {}, {'status': 'ok', 'truncated': 3})\n"))
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, errors=1)
    # fnmatch reads `[...]` as a character class, so the list is matched as plain text.
    assert "escaped it: ['fake_server._summary']" in result.stdout.str()
    assert "import it in the suite's conftest.py" in result.stdout.str()


def test_a_declared_module_with_no_anchor_is_no_anchor(pytester: pytest.Pytester) -> None:
    _suite(pytester, ["fake_server", "plain"], "import plain\n\n\ndef test_x():\n    pass\n")
    pytester.makepyfile(plain="VALUE = 1\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*names plain, which defines none of check_envelope, _summary*"])


def test_an_install_that_fails_leaves_every_module_with_its_original(
        pytester: pytest.Pytester) -> None:
    """A declared module that is no anchor stops the install; one already wrapped before it gets
    its original back, so nothing outside the guard is left holding a wrap."""
    _suite(pytester, ["fake_server", "plain"],
           "import fake_server\nimport plain\n\n\ndef test_x():\n    pass\n")
    pytester.makepyfile(plain="VALUE = 1\n")
    pytester.makeconftest(
        "import sys\n\n\ndef pytest_sessionfinish(session):\n"
        "    held = sys.modules['fake_server']._summary.__name__\n"
        "    open('held.txt', 'w').write(held)\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert result.ret != pytest.ExitCode.OK
    assert (pytester.path / "held.txt").read_text() == "_summary"


def test_help_needs_no_declaration(pytester: pytest.Pytester) -> None:
    _suite(pytester, None, "def test_x():\n    pass\n")
    result = pytester.runpytest("--help")
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*reply_shapes_anchors*"])


def test_the_teardown_restores_the_module_it_patched_even_when_it_left_sys_modules(
        pytester: pytest.Pytester) -> None:
    _suite(pytester, ["fake_server"], (
        "import sys\n\nimport fake_server\n\nHELD = fake_server\n\n\n"
        "def test_drop():\n    del sys.modules['fake_server']\n"))
    pytester.makeconftest(
        "def pytest_unconfigure(config):\n    import test_it\n"
        "    open('held.txt', 'w').write(test_it.HELD._summary.__name__)\n")
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert (pytester.path / "held.txt").read_text() == "_summary"



def test_a_name_no_import_can_parse_is_not_findable() -> None:
    from scry_core import reply_shapes_guard as guard
    assert guard._findable("") is False and guard._findable("scry_core.boundary") is True
