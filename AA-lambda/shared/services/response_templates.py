"""
Response Templates -- deterministic formatting for agent tool outputs.

Every tool in agent_capabilities_v3.py has a registry entry that maps its
(agent, tool) pair to a formatting rule.  Two types:

  action  -- single confirmation line (prefer agent ``message`` field, else format string)
  query   -- numbered list with per-item display fields

format_step() is the single entry point consumed by SummarizationService.
"""

from collections import defaultdict
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_format(template: str, data: dict) -> str:
    return template.format_map(defaultdict(str, {k: v for k, v in data.items() if v is not None}))


def _pluralize_header(template_def: dict, count: int) -> str:
    """
    Build a header that honors singular/plural nouns when provided.

    If the template has `noun_singular` + `noun_plural`, format as
    "Found {count} {noun}" (or the template's custom `header_singular`
    / `header_plural`). Otherwise fall back to the legacy `header` field.
    """
    if "noun_singular" in template_def and "noun_plural" in template_def:
        noun = template_def["noun_singular"] if count == 1 else template_def["noun_plural"]
        if count == 0:
            return template_def.get("header_empty", f"No {template_def['noun_plural']} found.")
        verb = template_def.get("verb", "Found")
        return f"{verb} {count} {noun}:"
    return template_def["header"].format_map(
        defaultdict(str, {"count": count})
    )


def _format_date_friendly(raw: str) -> str:
    """
    Reformat a date string into a calmer display form.

    Accepts two common shapes:
      * RFC 2822 (e.g. 'Wed, 21 Feb 2024 04:27:27 +0800') -- Gmail date headers
      * ISO 8601 (e.g. '2024-02-21T04:27:27+08:00')       -- Drive/Calendar times

    Output: 'Wed, 21 Feb 2024, 04:27'. On any parse failure we return the
    original string so no data is ever lost.
    """
    if not raw or not isinstance(raw, str):
        return raw

    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt.strftime("%a, %d %b %Y, %H:%M")
    except (TypeError, ValueError):
        pass

    iso_raw = raw.replace("Z", "+00:00")
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_raw)
        return dt.strftime("%a, %d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return raw


# Google mimeType prefixes we turn into friendly labels instead of raw MIME strings
_MIME_LABELS = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.folder": "Folder",
    "application/vnd.google-apps.form": "Google Form",
    "application/vnd.google-apps.drawing": "Google Drawing",
    "application/pdf": "PDF",
    "application/msword": "Word (.doc)",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
    "application/vnd.ms-excel": "Excel (.xls)",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
    "application/vnd.ms-powerpoint": "PowerPoint (.ppt)",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
    "text/csv": "CSV",
    "text/plain": "Text",
    "image/png": "PNG image",
    "image/jpeg": "JPEG image",
}


def _format_mime_type(mime: str) -> str:
    if not mime or not isinstance(mime, str):
        return mime
    return _MIME_LABELS.get(mime, mime)


def _format_size_bytes(val) -> str:
    """Turn a byte count (int or numeric string) into a readable size."""
    try:
        n = int(val)
    except (TypeError, ValueError):
        return str(val) if val is not None else ""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f}GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


def _attachment_summary(attachments: list) -> str:
    if not attachments:
        return ""
    parts = []
    for att in attachments:
        name = att.get("filename", "unknown")
        size = att.get("size")
        if size and isinstance(size, (int, float)):
            if size > 1_048_576:
                parts.append(f"{name} ({size / 1_048_576:.1f}MB)")
            elif size > 1024:
                parts.append(f"{name} ({size / 1024:.0f}KB)")
            else:
                parts.append(f"{name} ({size}B)")
        else:
            parts.append(name)
    return ", ".join(parts)


def _link_count_summary(links: list) -> str:
    if not links:
        return ""
    return f"{len(links)} link(s)"


def _body_display(body: str, single_item: bool) -> str:
    """Full body for single result, 300-char preview for lists."""
    if not body:
        return ""
    if single_item:
        return body.strip()
    preview = body[:300].replace("\n", " ").strip()
    if len(body) > 300:
        preview += "..."
    return preview


def _summarise_sample_row(item: dict) -> str:
    """One-line rendering of a sample item for per-PDF preview/write
    blocks. Truncates descriptions so the summary stays scannable in
    chat. Missing fields render as `—`."""
    code = str(item.get("item_code") or "—")
    desc = str(item.get("item_description") or "—")
    qty = item.get("qty")
    qty_str = f"{qty}" if qty not in ("", None) else "—"
    uom = str(item.get("uom") or "")
    if len(desc) > 60:
        desc = desc[:57] + "..."
    tail = f"{qty_str} {uom}".strip()
    return f"`{code}` · {desc} · {tail}"


def _render_per_pdf_blocks(
    orders_summary: list,
    files_summary: list,
    include_samples: bool = True,
    max_samples_per_order: int = 3,
) -> str:
    """Render one block per source PDF, listing each page/order beneath
    its file with sample rows. Shared between preview and write
    formatters — both need the same per-PDF breakdown so the user can
    eyeball "page 2 of FoodReq went to the Food tab" before and after
    the write.

    `files_summary` drives the block headers (filename, page count,
    tabs, total items) and `orders_summary` (keyed by file+page) drives
    the nested per-page bullets with refs / requested_by / samples.
    """
    if not files_summary:
        return ""

    orders_by_file: dict = {}
    for o in orders_summary or []:
        orders_by_file.setdefault(o.get("file"), []).append(o)

    parts: list = []
    for fs_idx, fs in enumerate(files_summary):
        fname = fs.get("file") or "(unknown)"
        pages = fs.get("pages") or []
        total_items = fs.get("total_items") or 0
        tabs = fs.get("tabs") or []
        tab_label = " / ".join(t for t in tabs if t) or "—"

        if fs_idx > 0:
            parts.append("")

        parts.append(
            f"**`{fname}`** — {len(pages)} page(s), {total_items} item(s) → {tab_label}"
        )

        for order in orders_by_file.get(fname, []):
            ref = order.get("reference_number") or "(no ref)"
            req = order.get("requested_by") or "(no requester)"
            page = order.get("page")
            page_label = f"Page {page}" if page is not None else "Order"
            item_count = order.get("item_count") or 0
            parts.append(
                f"- {page_label} (ref: `{ref}`, requested by {req}) — {item_count} item(s)"
            )
            if include_samples:
                for sample in (order.get("sample_rows") or [])[:max_samples_per_order]:
                    parts.append(f"    - {_summarise_sample_row(sample)}")

    return "\n".join(parts)


def _render_duplicates_block(
    duplicates: list,
    duplicates_by_file: dict,
    title: str,
    total: Optional[int] = None,
    max_samples: int = 10,
) -> str:
    """Render the duplicate-section tail shared by preview and write
    formatters. Returns "" when there are no duplicates so callers can
    unconditionally append the result.

    `duplicates` may be the full list (preview path) OR a truncated
    sample list of up to 10 entries (write path — `skipped_samples`).
    The caller is expected to pass the TRUE aggregate count via
    `total` when `duplicates` is a sample; otherwise `total` falls
    back to `len(duplicates)` to preserve the single-source-of-truth
    case. Without this split the header would misreport the count
    (e.g. 80 batch-duplicates rendering as "Duplicates skipped (10)").

    Layout:
      **<title> (N):**
      - `file.pdf` — K duplicate row(s)
      (reason breakdown, if derivable from the sample)
      Sample duplicates:
      - Tab "Food" · file.pdf p1 · date · ref · code
    """
    if not duplicates and not (duplicates_by_file and total):
        return ""

    derived_total = total
    if derived_total is None:
        if isinstance(duplicates, list):
            derived_total = len(duplicates)
        elif isinstance(duplicates, int):
            derived_total = duplicates
        else:
            derived_total = 0

    if not derived_total:
        return ""

    out_lines = [f"**{title} ({derived_total}):**"]

    if duplicates_by_file:
        for fname, count in duplicates_by_file.items():
            label = fname or "(unknown)"
            out_lines.append(f"- `{label}` — {count} duplicate row(s)")

    if isinstance(duplicates, list) and duplicates:
        reason_counts: dict = {}
        for d in duplicates:
            if not isinstance(d, dict):
                continue
            r = d.get("reason") or "unknown"
            reason_counts[r] = reason_counts.get(r, 0) + 1
        if reason_counts:
            # When we only have a sample (sample_len < derived_total),
            # report reasons as proportions of the sample, not absolute
            # counts — otherwise a 10-sample of an 80-row batch would
            # claim "10 duplicate within batch" which reads as "only 10
            # of 80 had that reason", misleading the user. For full-
            # list callers (preview), sample_len == derived_total so the
            # proportion becomes the absolute count and reads naturally.
            sample_len = len(duplicates)
            if sample_len == derived_total:
                reason_line = ", ".join(f"{c} {r}" for r, c in reason_counts.items())
                out_lines.append(f"Reasons: {reason_line}.")
            elif sample_len > 0:
                parts = []
                for reason, count in reason_counts.items():
                    pct = round(100 * count / sample_len)
                    parts.append(f"{pct}% {reason}")
                out_lines.append(
                    f"Reasons (sampled from first {sample_len}): {', '.join(parts)}."
                )

        out_lines.append("")
        out_lines.append("Sample duplicate row(s):")
        for d in duplicates[:max_samples]:
            if not isinstance(d, dict):
                continue
            tab = d.get("tab") or "?"
            f = d.get("file") or "?"
            p = d.get("page")
            p_str = f" p{p}" if p is not None else ""
            date = d.get("date") or "—"
            ref = d.get("order_reference") or "—"
            code = d.get("item_code") or "—"
            out_lines.append(
                f"- Tab \"{tab}\" · `{f}`{p_str} · {date} · {ref} · `{code}`"
            )
        shown = min(len(duplicates), max_samples)
        if derived_total > shown:
            out_lines.append(f"_…and {derived_total - shown} more._")

    return "\n".join(out_lines)


def _render_warnings_block(warnings, title: str = "Warnings", max_items: int = 10) -> str:
    """Render a terse warnings tail. Returns "" when empty."""
    if not warnings:
        return ""
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        return ""
    deduped: list = []
    seen = set()
    for w in warnings:
        if not w:
            continue
        if w in seen:
            continue
        seen.add(w)
        deduped.append(w)
    if not deduped:
        return ""
    lines = [f"**{title}:**"]
    for w in deduped[:max_items]:
        lines.append(f"- {w}")
    if len(deduped) > max_items:
        lines.append(f"_…and {len(deduped) - max_items} more._")
    return "\n".join(lines)


def _format_preview_delivery_order_insertion(output: dict) -> str:
    """Render the sheets-agent preview as a per-PDF block with sample
    rows plus an explicit duplicate section.

    Replaces the legacy `use_message: True` behaviour that collapsed the
    preview to a single "N row(s) ready to insert" sentence — the user
    could not see which PDFs routed to which tab, which items previewed,
    or what duplicates were about to be skipped.
    """
    total_new = output.get("total_new_rows")
    has_preview_rows = bool(output.get("preview_rows"))
    if total_new is None:
        total_new = len(output.get("preview_rows") or [])
    target_tabs = output.get("target_tabs") or []
    duplicate_count = output.get("duplicate_count") or 0

    # Backwards-compat fallback: if the caller passed nothing structured
    # (no rows, no tabs, no orders_summary) but DID supply a `message`
    # string, render the message verbatim. Preserves the legacy
    # `use_message: True` template behaviour for synthetic fixtures and
    # callers that haven't been migrated to the rich shape yet — without
    # this, `format_step("...preview...", {"message": "17 row(s) ready"})`
    # would render "Ready to insert 0 row(s) across 0 tab(s)." instead of
    # the supplied message.
    has_structured = (
        bool(total_new) or bool(target_tabs) or bool(output.get("orders_summary"))
        or bool(output.get("files_summary")) or has_preview_rows or bool(duplicate_count)
    )
    msg = output.get("message")
    if not has_structured and isinstance(msg, str) and msg.strip():
        return msg

    headline = f"Ready to insert {total_new} row(s) across {len(target_tabs)} tab(s)"
    if duplicate_count:
        headline += f"; {duplicate_count} duplicate(s) detected"
    headline += "."

    parts = [headline]

    pdf_blocks = _render_per_pdf_blocks(
        output.get("orders_summary") or [],
        output.get("files_summary") or [],
    )
    if pdf_blocks:
        parts.append("")
        parts.append(pdf_blocks)

    dup_block = _render_duplicates_block(
        output.get("duplicates") or [],
        output.get("duplicates_by_file") or {},
        title="Duplicates detected",
        total=output.get("duplicate_count"),
    )
    if dup_block:
        parts.append("")
        parts.append(dup_block)

    warn_block = _render_warnings_block(output.get("warnings"))
    if warn_block:
        parts.append("")
        parts.append(warn_block)

    return "\n".join(parts)


def _format_write_delivery_order_data(output: dict) -> str:
    """Render the sheets-agent write result as a per-PDF block plus an
    explicit duplicate-skipped section.

    Replaces the legacy `use_message: True` one-liner ("Successfully
    wrote N rows to M tab(s)") that silently hid per-PDF routing and
    duplicate-skip counts — users had no way to tell whether
    `write_delivery_order_data` dropped rows vs wrote them all.
    """
    rows_written = output.get("rows_written") or 0
    tabs_used = output.get("tabs_used") or []
    duplicates_skipped = output.get("duplicates_skipped") or 0
    skipped_samples = output.get("skipped_samples") or []

    # Backwards-compat fallback: same rationale as the preview formatter.
    has_structured = (
        bool(rows_written) or bool(tabs_used)
        or bool(duplicates_skipped) or bool(skipped_samples)
        or bool(output.get("orders_summary"))
        or bool(output.get("files_summary"))
    )
    msg = output.get("message")
    if not has_structured and isinstance(msg, str) and msg.strip():
        return msg

    tab_count = len(tabs_used) if isinstance(tabs_used, list) else 0
    headline = f"Wrote {rows_written} row(s) across {tab_count} tab(s)"
    if duplicates_skipped:
        headline += f"; skipped {duplicates_skipped} duplicate row(s)"
    headline += "."

    parts = [headline]

    if isinstance(tabs_used, list) and tabs_used:
        tab_lines = []
        for t in tabs_used:
            if isinstance(t, dict):
                name = t.get("tab") or "?"
                n = t.get("rows_written")
                if n is not None:
                    tab_lines.append(f"- `{name}` — {n} row(s) written")
                else:
                    tab_lines.append(f"- `{name}`")
        if tab_lines:
            parts.append("\n**Tabs updated:**\n" + "\n".join(tab_lines))

    pdf_blocks = _render_per_pdf_blocks(
        output.get("orders_summary") or [],
        output.get("files_summary") or [],
    )
    if pdf_blocks:
        parts.append("")
        parts.append(pdf_blocks)

    dup_block = _render_duplicates_block(
        skipped_samples if isinstance(skipped_samples, list) else [],
        output.get("duplicates_by_file") or {},
        title="Duplicates skipped",
        # `duplicates_skipped` is the TRUE count (an int); `skipped_samples`
        # is truncated to 10 to keep the response compact. We must render
        # the true count in the header or the user will under-estimate the
        # dedup.
        total=int(duplicates_skipped or 0),
    )
    if dup_block:
        parts.append("")
        parts.append(dup_block)

    warn_block = _render_warnings_block(output.get("warnings"))
    if warn_block:
        parts.append("")
        parts.append(warn_block)

    errors = output.get("errors") or []
    err_block = _render_warnings_block(errors, title="Errors")
    if err_block:
        parts.append("")
        parts.append(err_block)

    return "\n".join(parts)


def _format_extract_template_format(output: dict) -> str:
    """Format docs_agent.extract_template_format result.

    Replaces the legacy "Template placeholders found: {placeholders}" line
    that rendered the placeholder list as a Python repr (`['NAME', 'DATE']`)
    with a count + bulleted list. Truncates the bullet list at 8 entries to
    keep chat short and shows a "...and N more" line for the rest.
    """
    placeholders = output.get("placeholders") or output.get("template_placeholders") or []
    if not isinstance(placeholders, list):
        # Some impls return placeholders as a comma-separated string. Handle
        # gracefully so we never expose the raw repr to the user.
        placeholders = [p.strip() for p in str(placeholders).split(",") if p.strip()]

    if not placeholders:
        return "Template analysed — no placeholders found."

    count = len(placeholders)
    text = f"Template analysed — found {count} placeholder(s):"
    rendered = 0
    for p in placeholders:
        text += f"\n- `{p}`"
        rendered += 1
        if rendered >= 8:
            break
    if count > rendered:
        text += f"\n_…and {count - rendered} more._"
    return text


def _format_parse_file(output: dict) -> str:
    """Format mapping_agent.parse_file result.

    Replaces "Parsed {row_count} rows — columns: {columns}" (which dumped
    the column list as a Python repr) with row/column count summary plus
    a friendly comma-separated list of column names. Long column lists are
    truncated with a "…and N more" marker."""
    rows = output.get("row_count")
    if rows is None:
        rows = len(output.get("sample_data") or [])
    columns = output.get("columns") or []
    if not isinstance(columns, list):
        columns = []

    col_count = output.get("column_count")
    if col_count is None:
        col_count = len(columns)

    text = f"Parsed **{rows}** row(s) across **{col_count}** column(s)"
    if columns:
        # Render at most 12 names inline, then a "+N more" indicator —
        # keeps the chat message short for wide datasets.
        if len(columns) <= 12:
            shown = ", ".join(str(c) for c in columns)
            text += f"\nColumns: {shown}"
        else:
            shown = ", ".join(str(c) for c in columns[:12])
            text += f"\nColumns: {shown}, _…and {len(columns) - 12} more_"
    return text


def _format_smart_column_mapping(output: dict) -> str:
    """Format mapping_agent.smart_column_mapping result.

    Replaces the legacy raw-dict dump with a count summary plus a per-mapping
    bullet line. Renders confidence scores when available. Skips the bullet
    list (and just shows the count) when there are more than 12 mappings,
    since a 50-line chat message is worse than no detail at all.
    """
    mappings = output.get("mappings") or {}
    if not isinstance(mappings, dict):
        mappings = {}

    high_conf = output.get("high_confidence_count")
    accuracy = output.get("accuracy_estimate")
    confidence_scores = output.get("confidence_scores") or {}

    total = len(mappings)
    text = f"Created **{total}** column mapping(s)"
    if high_conf is not None:
        text += f" — {high_conf} high-confidence"
    if isinstance(accuracy, (int, float)):
        # accuracy comes through as a 0..1 fraction
        text += f" (accuracy ~{int(round(accuracy * 100))}%)"

    if mappings and total <= 12:
        text += "\n"
        for src, target in list(mappings.items())[:12]:
            score_text = ""
            score = confidence_scores.get(src) if isinstance(confidence_scores, dict) else None
            if isinstance(score, (int, float)):
                score_text = f" _({int(round(score * 100))}%)_"
            text += f"\n- `{src}` → `{target}`{score_text}"

    needs_review = output.get("needs_review") or []
    if isinstance(needs_review, list) and needs_review:
        text += f"\n\n**Needs review:** {len(needs_review)} mapping(s) had low confidence"

    return text


def _format_transform_data(output: dict) -> str:
    """Format mapping_agent.transform_data result.

    Replaces the legacy one-liner "Data transformed successfully" with a
    summary of what was actually transformed — row count, kept/dropped
    column counts when statistics are present.
    """
    rows = output.get("row_count")
    cols = output.get("column_count")
    stats = output.get("statistics") or {}

    parts: list[str] = []
    if rows is not None:
        parts.append(f"**{rows}** row(s)")
    if cols is not None:
        parts.append(f"**{cols}** column(s)")

    if not parts:
        return "Data transformed successfully."

    text = f"Transformed {' and '.join(parts)}"

    src_cols = stats.get("source_columns") if isinstance(stats, dict) else None
    mapped_cols = stats.get("mapped_columns") if isinstance(stats, dict) else None
    if src_cols is not None and mapped_cols is not None:
        text += f"\nKept {mapped_cols} of {src_cols} source column(s) after mapping"

    return text


def _format_update_by_date_match(output: dict) -> str:
    """Format sheets_agent.update_by_date_match result.

    Renders rows updated, rows not matched, and the tab where the update
    landed. Falls back to the legacy compact line when sheet_name is
    missing (older sub-agent deploys before the echo was added)."""
    rows_updated = output.get("rows_updated", 0)
    rows_not_found = output.get("rows_not_found", 0)
    sheet_name = output.get("sheet_name")
    sheet_url = output.get("sheet_url")

    text = f"Updated **{rows_updated}** row(s) by date match"
    if rows_not_found:
        text += f" ({rows_not_found} not matched)"
    if sheet_name:
        text += f" in **{sheet_name}** tab"
    if sheet_url:
        text += f"\nSheet: {sheet_url}"
    return text


def _format_upload_mapped_data(output: dict) -> str:
    """Format sheets_agent.upload_mapped_data result.

    Renders rows added/written, the tab name, and the sheet URL. Handles
    both append-mode (`rows_added`) and overwrite-mode (`rows_written`)
    return shapes."""
    mode = output.get("mode") or "append"
    rows = output.get("rows_added")
    if rows is None:
        rows = output.get("rows_written", 0)
    sheet_name = output.get("sheet_name")
    sheet_url = output.get("sheet_url")

    verb = "Appended" if mode == "append" else "Wrote"
    text = f"{verb} **{rows}** row(s)"
    if sheet_name:
        text += f" to **{sheet_name}** tab"
    if sheet_url:
        text += f"\nSheet: {sheet_url}"
    return text


def _format_add_sheet_tab(output: dict) -> str:
    """Format sheets_agent.add_sheet_tab result.

    Three branches mirror the tool's three success paths:
      * created=True + headers_applied=True -> "Added tab X (headers seeded)"
      * created=True + headers_applied=False -> "Added tab X"
      * created=False (idempotent no-op) -> "Tab X already existed"
    A non-empty `warning` field (e.g. headers write failed after the tab was
    created) is appended on its own line so the user knows the tab was
    created but the row-1 seeding fell through.
    """
    tab_name = output.get("tab_name") or "(unnamed)"
    created = bool(output.get("created"))
    headers_applied = bool(output.get("headers_applied"))
    warning = output.get("warning")

    if not created:
        text = f"Tab **{tab_name}** already existed in the spreadsheet — no change made."
    else:
        text = f"Added tab **{tab_name}** to the spreadsheet."
        if headers_applied:
            text += " Headers seeded in row 1."

    if warning:
        text += f"\nNote: {warning}"

    return text


def _format_mirror_tabs(output: dict) -> str:
    """Format sheets_agent.mirror_tabs result.

    Renders a compact per-tab block plus an aggregate summary. Each tab
    line shows what happened (created / cleared / copied) so the user can
    verify the intended outcome without opening Sheets. Skipped/errored
    tabs are surfaced inline rather than buried in a `warnings` field.

    Header logic mirrors the function-side message logic in
    sheets_agent_api.mirror_tabs so the per-tab block matches the
    aggregate summary the user sees. Specifically: an all-skipped run
    (tabs_succeeded == 0 AND tabs_failed == 0 AND tabs_skipped > 0) is
    reported as "Mirrored 0 of N — all skipped" rather than the
    legacy "Mirrored 0 of N tab(s)" which was indistinguishable from
    "happy path with zero work".
    """
    source_title = output.get("source_title") or "(unknown source)"
    target_title = output.get("target_title") or "(unknown target)"
    tabs_processed = output.get("tabs_processed") or []
    tabs_total = output.get("tabs_total") or 0
    tabs_succeeded = output.get("tabs_succeeded") or 0
    tabs_failed = output.get("tabs_failed") or 0
    tabs_created = output.get("tabs_created") or 0
    tabs_cleared = output.get("tabs_cleared") or 0
    rows_total = output.get("rows_total") or 0
    warnings = output.get("warnings") or []

    # Defensive: derive skip counts from per-tab status when the
    # function-side `tabs_skipped` field is missing (e.g. a stale
    # response from a sub-agent that pre-dates Fix 2).
    tabs_skipped_typo = sum(
        1 for t in tabs_processed
        if isinstance(t, dict) and (t.get("status") or "") == "skipped_source_missing"
    )
    tabs_skipped_missing = sum(
        1 for t in tabs_processed
        if isinstance(t, dict) and (t.get("status") or "") == "skipped_missing"
    )
    tabs_skipped = output.get("tabs_skipped")
    if tabs_skipped is None:
        tabs_skipped = tabs_skipped_typo + tabs_skipped_missing

    if tabs_total == 0:
        return (
            f"Nothing to mirror from **{source_title}** to **{target_title}** — "
            f"no source tabs matched the include/exclude filters."
        )

    if tabs_succeeded == 0 and tabs_failed == 0:
        # Every iteration was a skip — distinguish typo case (user
        # error) from intentional case (create_missing=False). The
        # function returns success=True for the intentional case so
        # the formatter must not paint it as a failure.
        if tabs_skipped_typo > 0 and tabs_skipped_missing == 0:
            header = (
                f"Could not mirror any tabs from **{source_title}** to "
                f"**{target_title}** — all {tabs_skipped_typo} "
                f"tab_mapping entry/entries referenced source tabs that "
                f"do not exist. Check the spelling."
            )
        elif tabs_skipped_typo > 0 and tabs_skipped_missing > 0:
            header = (
                f"Mirrored **0** of **{tabs_total}** tab(s) — "
                f"{tabs_skipped_typo} typo'd source name(s), and "
                f"{tabs_skipped_missing} tab(s) had no matching target "
                f"with create_missing=False."
            )
        else:
            header = (
                f"Mirrored **0** of **{tabs_total}** tab(s) — all "
                f"{tabs_total} source tab(s) were missing from "
                f"**{target_title}** and create_missing=False, so no new "
                f"tabs were created and no data was written."
            )
    elif tabs_failed == 0:
        skip_hint = ""
        if tabs_skipped:
            parts = []
            if tabs_skipped_missing:
                parts.append(f"{tabs_skipped_missing} skipped (no target match)")
            if tabs_skipped_typo:
                parts.append(f"{tabs_skipped_typo} typo'd source name(s)")
            skip_hint = " — " + ", ".join(parts) if parts else ""
        header = (
            f"Mirrored **{tabs_succeeded}** of **{tabs_total}** tab(s) "
            f"from **{source_title}** to **{target_title}**{skip_hint}."
        )
    elif tabs_succeeded == 0:
        skip_hint = f", {tabs_skipped} skipped" if tabs_skipped else ""
        header = (
            f"Failed to mirror any tabs from **{source_title}** to "
            f"**{target_title}** — {tabs_failed} tab(s) errored{skip_hint}."
        )
    else:
        skip_hint = f", {tabs_skipped} skipped" if tabs_skipped else ""
        header = (
            f"Partially mirrored {tabs_succeeded} of {tabs_total} tab(s) "
            f"from **{source_title}** to **{target_title}** — "
            f"{tabs_failed} failed{skip_hint}."
        )

    lines = [header]

    summary_bits = []
    if tabs_created:
        summary_bits.append(f"created **{tabs_created}**")
    if tabs_cleared:
        summary_bits.append(f"cleared **{tabs_cleared}**")
    if rows_total:
        summary_bits.append(f"copied **{rows_total:,}** row(s) total")
    if summary_bits:
        lines.append("Summary: " + ", ".join(summary_bits) + ".")

    lines.append("")
    lines.append("**Per-tab results:**")
    for tab in tabs_processed:
        src_name = tab.get("tab_name") or "(unnamed)"
        tgt_name = tab.get("target_tab_name") or src_name
        # Show "Source → Target" when names differ (tab_mapping case);
        # collapse to a single name when same-name (default behavior)
        # so the line stays concise for the common case.
        if tgt_name and tgt_name.lower() != src_name.lower():
            label = f"**{src_name}** → **{tgt_name}**"
        else:
            label = f"**{src_name}**"
        status = tab.get("status")
        rows = tab.get("rows_copied") or 0
        cols = tab.get("columns_copied") or 0
        if status == "success":
            actions = []
            if tab.get("created"):
                actions.append("created")
            if tab.get("cleared"):
                actions.append("cleared")
            if rows:
                actions.append(f"copied {rows:,} row(s) × {cols} col(s)")
            action_str = ", ".join(actions) if actions else "no changes"
            lines.append(f"- {label} — {action_str}.")
        elif status == "skipped_missing":
            err = tab.get("error") or "skipped"
            lines.append(f"- {label} — skipped: {err}")
        elif status == "skipped_source_missing":
            err = tab.get("error") or "source tab not found"
            lines.append(f"- {label} — skipped: {err}")
        else:
            err = tab.get("error") or "unknown error"
            lines.append(f"- {label} — failed: {err}")

    if warnings:
        lines.append("")
        lines.append("**Warnings:**")
        for w in warnings[:5]:
            lines.append(f"- {w}")
        if len(warnings) > 5:
            lines.append(f"- … and {len(warnings) - 5} more")

    return "\n".join(lines)


def _format_parse_delivery_order_pdfs(output: dict) -> str:
    """Deterministic summary for mapping_agent.parse_delivery_order_pdfs.

    On top of the legacy "Parsed X, Y rejected" headline this now lists the
    rejected filenames with a short reason whenever total_rejected > 0. This
    matters for the partial-success case (e.g. 1 FOOD PDF accepted + 1 Tech
    PDF rejected by the category gate): the write step proceeds on the
    accepted orders, so the user must be told which files were skipped and
    why — otherwise the skip happens silently behind the scenes.
    """
    total_parsed = output.get("total_parsed")
    if total_parsed is None:
        total_parsed = len(output.get("parsed_orders") or [])
    total_rejected = output.get("total_rejected")
    if total_rejected is None:
        total_rejected = len(output.get("rejected_files") or [])

    text = f"Parsed {total_parsed} delivery order(s), {total_rejected} file(s) rejected"

    rejected_files = output.get("rejected_files") or []
    if total_rejected and isinstance(rejected_files, list) and rejected_files:
        text += "\n\n**Skipped files:**"
        rendered = 0
        for rf in rejected_files:
            if not isinstance(rf, dict):
                continue
            fname = rf.get("file") or rf.get("filename") or "(unknown file)"
            reason = rf.get("reason") or "no reason provided"
            short = reason.split(". ")[0] if ". " in reason else reason
            if len(short) > 160:
                short = short[:157] + "..."
            text += f"\n- `{fname}` — {short}"
            rendered += 1
            if rendered >= 5:
                break
        if len(rejected_files) > rendered:
            text += f"\n_…and {len(rejected_files) - rendered} more._"

    return text


# ---------------------------------------------------------------------------
# TOOL_TEMPLATES registry
# ---------------------------------------------------------------------------

TOOL_TEMPLATES: Dict[tuple, dict] = {

    # ========================= GMAIL AGENT =========================

    ("gmail_agent", "search_emails"): {
        "type": "query",
        "list_key": "emails",
        "count_key": "count",
        "item_fields": ["from", "subject", "date"],
        "body_field": "body",
        "show_attachments": True,
        "show_links": True,
        "noun_singular": "email",
        "noun_plural": "emails",
        "date_fields": ["date"],
        "empty_placeholders": {"subject": "_(no subject)_"},
    },
    ("gmail_agent", "get_thread_conversation"): {
        "type": "query",
        "list_key": "messages",
        "count_key": "message_count",
        "item_fields": ["from", "to", "subject", "date"],
        "body_field": "body",
        "noun_singular": "message in this thread",
        "noun_plural": "messages in this thread",
        "verb": "Showing",
        "date_fields": ["date"],
        "empty_placeholders": {"subject": "_(no subject)_"},
    },
    ("gmail_agent", "reply_to_email"): {
        "type": "action",
        "template": "Replied to **{subject}** (to: {to})",
    },
    ("gmail_agent", "forward_email"): {
        "type": "action",
        "template": "Forwarded **{subject}** to **{to}**",
    },
    ("gmail_agent", "create_draft_email"): {
        "type": "action",
        "template": "Draft created for **{to}**, subject: **{subject}**",
    },
    ("gmail_agent", "send_draft_email"): {
        "type": "action",
        "template": "Draft sent — to: **{to}**, subject: **{subject}**",
    },
    ("gmail_agent", "search_drafts"): {
        "type": "query",
        "list_key": "drafts",
        "count_key": "count",
        "nested_message": True,
        "item_fields": ["draft_id"],
        "noun_singular": "draft",
        "noun_plural": "drafts",
        "empty_placeholders": {"subject": "_(no subject)_"},
    },
    ("gmail_agent", "send_email_with_attachment"): {
        "type": "action",
        "template": "Sent email to **{to}**, subject: **{subject}** (attachment: {attachment_name})",
    },
    ("gmail_agent", "download_attachment"): {
        # Callable so we can render bytes via _format_size_bytes (e.g.
        # "1.2MB") instead of the raw byte count, and drop the server-side
        # `save_path` from the user-visible message — it's a path on the
        # backend host that the user has no way to access from the chat UI.
        # The path stays in the agent's return for downstream tools that
        # need it (parse_file, mapping_agent, etc.).
        "type": "action",
        "template": lambda out: (
            f"Downloaded **{out.get('filename') or 'attachment'}**"
            + (
                f" ({_format_size_bytes(out.get('file_size'))})"
                if out.get("file_size") is not None
                else ""
            )
        ),
    },
    ("gmail_agent", "search_emails_with_delivery_order_attachments"): {
        # Callable so we can omit the server-side temp_directory that the
        # legacy template used to expose to the user — that path is meaningful
        # only to the backend agent (e.g. /tmp/gmail_attach_xyz) and offers no
        # value in chat. The download counts and email count are what the user
        # cares about; the temp_dir still flows through the agent return for
        # downstream tools that need to parse the files.
        "type": "action",
        "template": lambda out: (
            f"Found {out.get('total_emails_found', 0)} email(s) with "
            f"{out.get('total_attachments_downloaded', 0)} attachment(s) downloaded"
        ),
    },
    ("gmail_agent", "save_attachment_metadata"): {
        # The legacy template surfaced an internal SQLite `inserted_id` that
        # the user could not act on — it was a row primary key of an opaque
        # metadata table, not the Drive file ID, the Gmail message ID, or
        # anything the chat UI links to. Replaced with a generic confirmation.
        "type": "action",
        "template": "Attachment metadata saved.",
    },

    # ========================= DOCS AGENT =========================

    ("docs_agent", "create_doc"): {
        "type": "action",
        "template": "Created document **{title}**: {document_url}",
    },
    ("docs_agent", "list_my_docs"): {
        "type": "action",
        "use_message": True,
    },
    ("docs_agent", "extract_template_format"): {
        # Legacy template rendered the placeholder list as Python repr
        # ("['NAME', 'DATE']") which is technical and ugly in chat. Render
        # as a friendly bullet list with a count when more than 3.
        "type": "action",
        "template": lambda out: _format_extract_template_format(out),
    },
    ("docs_agent", "create_from_my_template"): {
        # Title was previously dropped — the URL alone makes the user click
        # to verify they got the right document. Title now leads, URL trails.
        "type": "action",
        "template": "Created document **{title}** from template: {url}",
    },
    ("docs_agent", "add_text"): {
        # text_length (a raw character count) is meaningful to a developer
        # but not to a user reviewing what just happened — replaced with a
        # generic "Text added" confirmation. The document_url is the
        # verification mechanism the user actually needs.
        "type": "action",
        "template": "Added text to document: {document_url}",
    },
    ("docs_agent", "create_doc_with_content"): {
        # Same rationale as add_text — drop the technical char count, keep
        # title (as the human-meaningful identifier) and URL (as the
        # verification link).
        "type": "action",
        "template": "Created **{title}** with content: {document_url}",
    },
    ("docs_agent", "add_text_from_file"): {
        "type": "action",
        "template": "Added file content to document: {document_url}",
    },
    ("docs_agent", "read_doc"): {
        "type": "action",
        "template": "Document **{title}**:\n\n{content}",
        "content_field": "content",
        "content_max_length": 4000,
    },
    ("docs_agent", "create_from_template_and_data_ids"): {
        "type": "action",
        "template": "Created **{title}** from template: {document_url}",
        "append_url": "pdf_url",
    },

    # ========================= CALENDAR AGENT =========================

    ("calendar_agent", "list_events"): {
        "type": "query",
        "list_key": "events",
        "count_key": "count",
        "item_fields": ["summary", "start", "end", "location", "attendee_count"],
        "noun_singular": "upcoming event",
        "noun_plural": "upcoming events",
        "date_fields": ["start", "end"],
        "empty_placeholders": {
            "summary": "_(no title)_",
            "location": None,
            "attendee_count": None,
        },
    },
    ("calendar_agent", "create_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "update_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "delete_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "confirm_delete_event"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "list_calendars"): {
        "type": "query",
        "list_key": "calendars",
        "item_fields": ["name"],
        "noun_singular": "calendar",
        "noun_plural": "calendars",
    },
    ("calendar_agent", "create_calendar"): {
        "type": "action",
        "use_message": True,
    },
    ("calendar_agent", "resolve_conflict"): {
        "type": "action",
        "use_message": True,
    },

    # ========================= DRIVE AGENT =========================

    ("drive_agent", "upload_file"): {
        "type": "action",
        "use_message": True,
        "template": "Uploaded **{filename}** to {folder_path}: {file_url}",
    },
    ("drive_agent", "create_folder"): {
        "type": "action",
        "use_message": True,
        "template": "Created folder: {folder_path}",
    },
    ("drive_agent", "list_folders"): {
        "type": "query",
        "list_key": "folders",
        "count_key": "count",
        "item_fields": ["name"],
        "tree_field": "tree",
        "noun_singular": "folder",
        "noun_plural": "folders",
    },
    ("drive_agent", "list_files"): {
        "type": "query",
        "list_key": "files",
        "count_key": "count",
        "item_fields": ["name", "mimeType", "size", "createdTime", "webViewLink"],
        "noun_singular": "file",
        "noun_plural": "files",
        "date_fields": ["createdTime"],
        "mime_fields": ["mimeType"],
        "size_fields": ["size"],
        "link_fields": ["webViewLink"],
        "empty_placeholders": {
            "size": None,
            "createdTime": None,
            "webViewLink": None,
        },
    },
    ("drive_agent", "search_files"): {
        "type": "query",
        "list_key": "results",
        "count_key": "count",
        "verb": "Found",
        "item_fields": ["name", "mimeType", "size", "createdTime", "webViewLink"],
        "noun_singular": "file",
        "noun_plural": "files",
        "date_fields": ["createdTime"],
        "mime_fields": ["mimeType"],
        "size_fields": ["size"],
        "link_fields": ["webViewLink"],
        "empty_placeholders": {
            "size": None,
            "createdTime": None,
            "webViewLink": None,
        },
    },
    ("drive_agent", "get_folder_info"): {
        "type": "action",
        "use_message": True,
        "template": "Folder **{folder_name}**: {file_count} file(s), {subfolder_count} subfolder(s)",
    },
    ("drive_agent", "search_template_and_data"): {
        "type": "action",
        "use_message": True,
        "template": "Found template: **{template_file_name}**, data: **{data_file_name}**",
    },

    # ========================= MAPPING AGENT =========================

    ("mapping_agent", "parse_file"): {
        # Legacy template rendered `columns` as a raw Python list repr
        # (`['Date', 'Amount', 'Customer']`) and ignored row/column counts'
        # context. Now we render a count summary first, then a friendly
        # comma-separated list of column names (truncated when long).
        "type": "action",
        "template": lambda out: _format_parse_file(out),
    },
    ("mapping_agent", "extract_dates_from_all_rows"): {
        "type": "action",
        "template": "Extracted dates from {total_rows} row(s) (date column: **{date_column}**)",
    },
    ("mapping_agent", "smart_column_mapping"): {
        # The legacy template rendered the full mappings dict as Python
        # repr ("{'Date': 'date', 'Amount': 'amount'}") which is unreadable
        # for any non-trivial mapping. Now: count summary + per-mapping
        # bullet list with confidence scores when present.
        "type": "action",
        "template": lambda out: _format_smart_column_mapping(out),
    },
    ("mapping_agent", "transform_data"): {
        # Previously a one-line "Data transformed successfully" — gave the
        # user nothing about what was transformed. Now includes row count,
        # column count, and a comparison against source columns to show
        # what was kept / dropped during mapping.
        "type": "action",
        "template": lambda out: _format_transform_data(out),
    },
    ("mapping_agent", "extract_date_from_data"): {
        "type": "action",
        "template": "Extracted date: {formatted_display}",
    },
    ("mapping_agent", "parse_delivery_order_pdfs"): {
        "type": "action",
        # Callable so the template can list rejected filenames + reasons
        # when total_rejected > 0. Static-string templates still work for
        # every other tool — see _format_action's isinstance(callable) branch.
        "template": _format_parse_delivery_order_pdfs,
    },

    # ========================= SHEETS AGENT =========================

    ("sheets_agent", "update_by_date_match"): {
        # Legacy template hid where the update happened — now shows the
        # specific tab. The sub-agent now echoes sheet_name + sheet_url
        # back in the response so we can render the same level of detail
        # the user got at preview time. Backwards-compat: when sheet_name
        # is missing (older deploys) the template still renders the
        # counts cleanly.
        "type": "action",
        "template": lambda out: _format_update_by_date_match(out),
    },
    ("sheets_agent", "upload_mapped_data"): {
        # Same rationale as update_by_date_match — the user previously
        # had no way to tell which sheet/tab the data landed in unless
        # they opened the Drive link manually. Now renders tab name +
        # the sheet URL inline.
        "type": "action",
        "template": lambda out: _format_upload_mapped_data(out),
    },
    ("sheets_agent", "create_sheet"): {
        # Title was previously omitted — surfacing it makes the success
        # message verifiable without clicking through to the Drive URL.
        "type": "action",
        "template": "Created spreadsheet **{title}**: {sheet_url}",
    },
    ("sheets_agent", "add_sheet_tab"): {
        # Callable so the message branches between created / already-existed
        # / created-with-headers without needing three static templates.
        # Without this entry every successful add_sheet_tab step would fall
        # through to the LLM safety net (gpt-4o-mini), costing an extra LLM
        # call per response.
        "type": "action",
        "template": _format_add_sheet_tab,
    },
    ("sheets_agent", "mirror_tabs"): {
        # Callable because the message has to render a per-tab loop with
        # per-tab status (created/cleared/copied/skipped/error) — not
        # expressible as a simple format string. Keeping this here avoids
        # the LLM safety net for the common multi-tab mirror flow.
        "type": "action",
        "template": _format_mirror_tabs,
    },
    ("sheets_agent", "validate_delivery_sheet"): {
        "type": "action",
        "use_message": True,
    },
    ("sheets_agent", "preview_delivery_order_insertion"): {
        "type": "action",
        # Callable template so the preview surfaces per-PDF blocks with
        # sample rows + an explicit duplicate breakdown. `use_message`
        # collapsed everything into the one-liner "N row(s) ready to
        # insert" which hid the per-file routing the user needs to see
        # before approving the write.
        "template": _format_preview_delivery_order_insertion,
    },
    ("sheets_agent", "write_delivery_order_data"): {
        "type": "action",
        # Same story as preview: callable so the write result shows
        # per-PDF blocks + duplicates-skipped breakdown, not just
        # "Successfully wrote N rows". Silent dedup was the top user
        # complaint from DeliveryTesting.log.
        "template": _format_write_delivery_order_data,
    },

    # ========================= LLM TOOL (built-in) =========================

    ("llm_tool", "transform_text"): {
        "type": "action",
        "template": "{transformed_content}",
    },
}


# ---------------------------------------------------------------------------
# Common 2-step composition patterns  (tool1, tool2) -> connector label
# ---------------------------------------------------------------------------

COMPOSE_PATTERNS: Dict[tuple, str] = {
    ("search_emails", "forward_email"): "Found and forwarded",
    ("search_emails", "reply_to_email"): "Found and replied",
    ("create_draft_email", "send_draft_email"): "Created and sent",
    ("search_drafts", "send_draft_email"): "Found and sent draft",
    ("search_template_and_data", "create_from_template_and_data_ids"): "Found files and created document",
    ("list_my_docs", "read_doc"): "Found and read document",
    ("search_files", "upload_mapped_data"): "Found sheet and uploaded data",
    ("parse_file", "transform_data"): "Parsed and transformed data",
    ("search_emails_with_delivery_order_attachments", "parse_delivery_order_pdfs"): "Found and parsed delivery orders",
    ("validate_delivery_sheet", "preview_delivery_order_insertion"): "Validated sheet and prepared preview",
    ("preview_delivery_order_insertion", "write_delivery_order_data"): "Previewed and wrote delivery order data",
}


# ---------------------------------------------------------------------------
# Core formatting functions
# ---------------------------------------------------------------------------

def format_step(agent: str, tool: str, output: dict) -> Optional[str]:
    """
    Format a single step's output through its registered template.

    Returns formatted text, or None if no template matches.
    """
    template = TOOL_TEMPLATES.get((agent, tool))
    if not template:
        return None

    if template["type"] == "action":
        return _format_action(template, output)

    if template["type"] == "query":
        return _format_query_result(template, output)

    return None


def format_step_compact(agent: str, tool: str, output: dict) -> Optional[str]:
    """One-line summary of a step's output for inclusion in mid-flow
    messages (e.g. the "Completed so far" header on pause prompts).

    Wraps `format_step` and returns only the first non-empty line of the
    rendered text. Returns None when no template applies, when the
    template renders to empty, or when format_step itself raises.

    Why a separate helper instead of inlining `.split('\\n')[0]`:
      * Some callable formatters (e.g. delivery-order preview/write) emit
        20-50 line bodies. Dropping that into a "Completed so far" prefix
        would bury the actual approval/disambiguation prompt below the
        fold. The compact form keeps mid-flow messages scannable.
      * Query-type templates start with a header line (e.g. "Found 5
        emails:") that IS the natural one-line summary.
      * Centralised so callers don't all need their own try/except wrap.
    """
    try:
        full = format_step(agent, tool, output)
    except Exception:
        return None
    if not full:
        return None
    for line in full.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Query templates emit a header like "Found 5 emails:" expecting a
        # following list. When we drop the list and use the header alone
        # in a bullet, the dangling colon reads as a broken sentence —
        # strip it. Bold-wrapped trailing colons (e.g. "**Found 5 emails:**")
        # are also normalized.
        if stripped.endswith("**") and stripped.endswith(":**"):
            stripped = stripped[:-3] + "**"
        elif stripped.endswith(":"):
            stripped = stripped[:-1]
        return stripped
    return None


def _format_action(template_def: dict, output: dict) -> str:
    if template_def.get("use_message") and output.get("message"):
        text = output["message"]
    elif template_def.get("template"):
        template_spec = template_def["template"]
        # Callable templates get the full output dict so they can do
        # multi-field rendering (e.g. list per-file rejections alongside
        # totals). Static-string templates keep the legacy format-string
        # behaviour so nothing else has to change.
        if callable(template_spec):
            text = template_spec(output)
        else:
            out = dict(output)
            content_field = template_def.get("content_field")
            max_len = template_def.get("content_max_length")
            if content_field and max_len and isinstance(out.get(content_field), str):
                if len(out[content_field]) > max_len:
                    out[content_field] = out[content_field][:max_len] + "\n...[truncated]"
            text = _safe_format(template_spec, out)
    else:
        text = "Action completed"

    url_field = template_def.get("append_url")
    if url_field and output.get(url_field):
        text += f"\n{url_field.replace('_', ' ').title()}: {output[url_field]}"

    return text


def _format_query_result(template_def: dict, output: dict) -> str:
    list_key = template_def.get("list_key", "items")
    items = output.get(list_key, [])
    count_key = template_def.get("count_key", "count")
    count = output.get(count_key, len(items))

    header = _pluralize_header(template_def, count)

    tree_field = template_def.get("tree_field")
    if tree_field and output.get(tree_field):
        return f"{header}\n{output[tree_field]}"

    if count == 0 or not items:
        return header

    single_item = (count == 1 and len(items) == 1)
    display_limit = 10
    blocks = [header]

    for i, item in enumerate(items[:display_limit]):
        parts = _format_item(template_def, item, single_item)
        if not parts:
            blocks.append(f"**{i + 1}.** _(empty item)_")
            continue

        first_label, first_value = parts[0]
        heading_line = f"**{i + 1}.** **{first_label}:** {first_value}"
        detail_lines = [f"   - **{label}:** {value}" for label, value in parts[1:]]
        blocks.append("\n".join([heading_line] + detail_lines))

    if count > display_limit:
        blocks.append(f"_… and {count - display_limit} more not shown_")

    # Blank line between header and first item; blank line between items
    return blocks[0] + "\n\n" + "\n\n".join(blocks[1:])


# ---------------------------------------------------------------------------
# Item formatting -- returns list of (label, value) tuples
# ---------------------------------------------------------------------------

_LABEL_OVERRIDES = {
    # Keys -> pretty labels. Applied as a whole word first, then word-by-word.
    "id": "ID",
    "url": "URL",
    "uri": "URI",
    "to": "To",
    "cc": "Cc",
    "bcc": "Bcc",
    "mimetype": "Type",
    "webviewlink": "Open",
    "createdtime": "Created",
    "modifiedtime": "Modified",
    "attendee_count": "Attendees",
    "start_formatted": "Start",
    "event_id": "Event ID",
    "message_id": "Message ID",
    "thread_id": "Thread ID",
    "draft_id": "Draft ID",
}


def _humanize_label(field: str) -> str:
    """Convert 'message_id' -> 'Message ID', 'mimeType' -> 'Type', etc."""
    whole = _LABEL_OVERRIDES.get(field.lower())
    if whole:
        return whole
    words = []
    for part in field.split("_"):
        override = _LABEL_OVERRIDES.get(part.lower())
        words.append(override if override else part.title())
    return " ".join(words)


def _format_field_value(field: str, val: Any, template_def: dict) -> Optional[str]:
    """Format a single field's value, or return None to skip."""
    placeholders = template_def.get("empty_placeholders", {})
    date_fields = set(template_def.get("date_fields", []))
    mime_fields = set(template_def.get("mime_fields", []))
    size_fields = set(template_def.get("size_fields", ["size"]))
    link_fields = set(template_def.get("link_fields", []))

    if val is None or val == "":
        return placeholders.get(field)  # None means skip

    if field in date_fields and isinstance(val, str):
        return _format_date_friendly(val)

    if field in mime_fields and isinstance(val, str):
        return _format_mime_type(val)

    if field in size_fields:
        return _format_size_bytes(val)

    if field in link_fields and isinstance(val, str):
        # Render as a compact markdown link so the UI can render it clickable.
        return f"[link]({val})"

    if isinstance(val, list):
        if not val:
            return None
        # Trim long lists for readability
        shown = val[:5]
        rendered = ", ".join(str(v) for v in shown)
        if len(val) > 5:
            rendered += f", … (+{len(val) - 5} more)"
        return rendered

    return str(val)


def _format_item(template_def: dict, item: dict, single_item: bool) -> list:
    """Build the display parts for a single list item as (label, value) tuples."""

    # Drafts have a nested message object -- flatten it
    if template_def.get("nested_message") and isinstance(item.get("message"), dict):
        msg = item["message"]
        parts = []
        for field in template_def.get("item_fields", []):
            formatted = _format_field_value(field, item.get(field, ""), template_def)
            if formatted is not None:
                parts.append((_humanize_label(field), formatted))
        for key in ("to", "subject", "date"):
            formatted = _format_field_value(key, msg.get(key, ""), template_def)
            if formatted is not None:
                parts.append((_humanize_label(key), formatted))
        body = msg.get("body", "")
        if body:
            label = "Body" if single_item else "Preview"
            parts.append((label, _body_display(body, single_item)))
        return parts

    parts = []
    for field in template_def.get("item_fields", []):
        formatted = _format_field_value(field, item.get(field, ""), template_def)
        if formatted is not None:
            parts.append((_humanize_label(field), formatted))

    body_field = template_def.get("body_field")
    if body_field:
        body = item.get(body_field, "")
        if body:
            label = "Body" if single_item else "Preview"
            parts.append((label, _body_display(body, single_item)))

    if template_def.get("show_attachments"):
        atts = item.get("attachments", [])
        if atts:
            parts.append(("Attachments", _attachment_summary(atts)))

    if template_def.get("show_links"):
        links = item.get("body_links", [])
        if links:
            parts.append(("Links", _link_count_summary(links)))

    return parts
