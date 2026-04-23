"""
Simulation: verify that after consolidating per-arg warnings into the
`note` field, the planner's rendered prompt still carries the guidance
that keeps it from emitting bare `description` / `summary` / etc.

Runs without starting any servers or making LLM calls:
  1. Imports the real capability registry.
  2. Runs the real tool_filter.get_filtered_capabilities_v2() for the
     agent/tool pair the planner uses in a scheduling-with-link flow.
  3. Mirrors supervisor_agent.py line 380 exactly:
         json.dumps(filtered_capabilities, indent=2)
  4. Asserts:
     A. Every mutation arg (new_summary ... new_attendees) is still
        declared on the tool.
     B. The per-arg description no longer repeats "use this exact name,
        NOT" boilerplate (the cleanup actually happened).
     C. The `note` field is in the rendered JSON and still names every
        mutation-arg + explicitly warns about the bare names.
     D. The planner's full system-prompt template (Rule 15) still calls
        out the `new_` prefix requirement.

Run from repo root:
    python _sim_update_event_note.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path


# Force UTF-8 stdout so diagnostic prints with arrows / em-dashes don't die
# on Windows cp1252 consoles. The assertions are ASCII-safe but the real
# `note` string we dump below carries em-dashes and arrows.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


REPO_ROOT = Path(__file__).resolve().parent
SUPERVISOR = REPO_ROOT / "supervisor-agent"
if str(SUPERVISOR) not in sys.path:
    sys.path.insert(0, str(SUPERVISOR))


def _header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def test_args_cleanup() -> None:
    _header("TEST 1 — update_event.args is now type-only (no repeated warnings)")
    from agent_capabilities_v3 import agent_capabilities

    update_event = agent_capabilities["calendar_agent"]["tools"]["update_event"]
    args = update_event["args"]

    required_names = {
        "event_id", "event_name",
        "new_summary", "new_start", "new_end",
        "new_description", "new_location", "new_attendees",
        "calendar_name",
    }
    missing = required_names - set(args.keys())
    assert not missing, f"Missing args after cleanup: {sorted(missing)}"
    print(f"  ok  : all {len(required_names)} args still declared")

    banned_phrase = "use this exact name"
    offenders = {k: v for k, v in args.items() if banned_phrase.lower() in str(v).lower()}
    assert not offenders, (
        f"Expected the repeated '{banned_phrase}' phrase to be gone from each arg, "
        f"but it still appears in: {list(offenders.keys())}"
    )
    print(f"  ok  : repeated '{banned_phrase}' phrase removed from every arg description")

    for name in ("new_summary", "new_start", "new_end",
                 "new_description", "new_location", "new_attendees"):
        desc = args[name]
        print(f"        {name:<18} -> {desc}")


def test_note_content() -> None:
    _header("TEST 2 — note field carries the consolidated guidance")
    from agent_capabilities_v3 import agent_capabilities

    update_event = agent_capabilities["calendar_agent"]["tools"]["update_event"]
    note = update_event.get("note", "")
    assert note, "update_event is missing its `note` field"

    for name in ("new_summary", "new_start", "new_end",
                 "new_description", "new_location", "new_attendees"):
        assert name in note, f"note does not mention mutation arg `{name}`"
    print(f"  ok  : note names all 6 mutation args")

    for bare in ("summary", "start_time", "end_time",
                 "description", "location", "attendees"):
        assert bare in note, f"note does not warn against bare name `{bare}`"
    print(f"  ok  : note warns against all 6 create_event bare names")

    for phrase in ("silently ignored", "changes: []", "new_"):
        assert phrase in note, f"note missing failure-mode phrase: {phrase!r}"
    print(f"  ok  : note explains the silent-failure mode")

    print(f"\n  note (full):\n    {note}")


def test_note_reaches_planner_prompt() -> None:
    _header("TEST 3 — planner-facing JSON (real tool_filter path) contains note")
    from tool_filter import get_filtered_capabilities_v2

    scheduling_filter = {"calendar_agent": ["create_event", "update_event"]}
    filtered = get_filtered_capabilities_v2(scheduling_filter)

    assert "calendar_agent" in filtered
    assert "update_event" in filtered["calendar_agent"]["tools"]

    rendered = json.dumps(filtered, indent=2)
    assert '"note"' in rendered, "note key was stripped during filtering"
    assert "new_description" in rendered, "new_description arg missing from rendered prompt"
    assert "silently ignored" in rendered, "consolidated warning not present in rendered prompt"
    assert "changes: []" in rendered, "failure-mode phrase missing from rendered prompt"
    print("  ok  : json.dumps(filtered_capabilities, indent=2) carries the note verbatim")

    banned = "use this exact name"
    assert banned.lower() not in rendered.lower(), (
        "Rendered prompt still has the old repeated phrase — cleanup did not land"
    )
    print(f"  ok  : rendered prompt no longer contains the old '{banned}' noise")

    size_tokens = len(rendered) // 4
    print(f"  info: rendered calendar-agent snippet ≈ {len(rendered):,} chars / ~{size_tokens:,} tokens")

    update_block_start = rendered.find('"update_event":')
    update_block_end = rendered.find('\n      },', update_block_start)
    if update_block_start != -1 and update_block_end != -1:
        preview = rendered[update_block_start:update_block_end + 8]
        print("\n  update_event block as seen by the planner:\n")
        for line in preview.splitlines():
            print("    " + line)


def test_planner_rule_15_still_mentions_prefix() -> None:
    _header("TEST 4 — supervisor_agent.py Rule 15 still names the `new_` prefix")
    sup_path = SUPERVISOR / "supervisor_agent.py"
    text = sup_path.read_text(encoding="utf-8", errors="replace")

    assert "update_event" in text, "supervisor_agent.py no longer references update_event"
    assert "new_description" in text, "Rule 15 lost the explicit new_description warning"
    assert "new_" in text, "Rule 15 lost the `new_` prefix mention"
    print("  ok  : Rule 15 still reinforces the prefix requirement at the prompt-rule layer")


def test_calendar_dispatch_alias_still_in_place() -> None:
    _header("TEST 5 — calendar-agent/api.py still aliases bare names (defense layer)")
    api_path = REPO_ROOT / "calendar-agent" / "api.py"
    if not api_path.exists():
        print(f"  skip: {api_path} not found (repo layout variant)")
        return

    text = api_path.read_text(encoding="utf-8", errors="replace")
    for canonical, aliases in [
        ("new_summary", ["summary"]),
        ("new_description", ["description"]),
        ("new_location", ["location"]),
        ("new_attendees", ["attendees", "emails"]),
        ("new_start", ["start_time", "start"]),
        ("new_end", ["end_time", "end"]),
    ]:
        assert canonical in text, f"{canonical} missing from api.py"
        for alias in aliases:
            assert f'"{alias}"' in text, f"alias `{alias}` missing in _pick call"
    print("  ok  : _pick helper still maps every bare name to its `new_*` canonical")


def main() -> int:
    tests = [
        test_args_cleanup,
        test_note_content,
        test_note_reaches_planner_prompt,
        test_planner_rule_15_still_mentions_prefix,
        test_calendar_dispatch_alias_still_in_place,
    ]
    failures: list[tuple[str, str]] = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"  FAIL: {e}")
        except Exception as e:
            failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"  ERROR: {type(e).__name__}: {e}")

    _header("SUMMARY")
    if failures:
        for name, err in failures:
            print(f"  FAIL {name}: {err}")
        return 1
    print(f"  all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
