import json
import boto3
import os
import re
import base64
import struct
import zipfile
import io
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

lambda_client = boto3.client('lambda', region_name='ap-southeast-1')

MAPPING_LAMBDA = 'safexpressops-mapping-agent'
SHEETS_LAMBDA  = 'safexpressops-sheets-agent'

XLSX_MAGIC = b'PK\x03\x04'
EOCD_SIG   = b'PK\x05\x06'


def _try_truncate_zip(data):
    """
    If trailing garbage was appended to a valid ZIP, locate the real
    end-of-central-directory record and return a clean copy.
    """
    pos = 0
    while True:
        pos = data.find(EOCD_SIG, pos)
        if pos == -1:
            break
        if pos + 22 <= len(data):
            comment_len = struct.unpack_from('<H', data, pos + 20)[0]
            end = pos + 22 + comment_len
            candidate = data[:end]
            try:
                zipfile.ZipFile(io.BytesIO(candidate)).close()
                return candidate
            except Exception:
                pass
        pos += 1
    return None


def sanitize_file_content(file_content, file_type='xlsx'):
    """
    Ensure file_content is a single-layer base64 string whose decoded bytes
    are a valid file.  Handles:
      - data-URI prefix  (data:...;base64,XXXX)
      - double base64 encoding
      - trailing garbage from multipart parsing
    """
    if not isinstance(file_content, str):
        return file_content

    if file_content.startswith('data:'):
        idx = file_content.find(';base64,')
        if idx != -1:
            file_content = file_content[idx + 8:]
            print("   Stripped data-URI prefix from file_content")

    try:
        decoded = base64.b64decode(file_content)
    except Exception:
        return file_content

    if file_type in ('xlsx', 'xls', 'excel'):
        if decoded[:4] == XLSX_MAGIC:
            # Starts like a ZIP — check if it's actually valid
            try:
                zipfile.ZipFile(io.BytesIO(decoded)).close()
                print(f"   File content OK ({len(decoded)} bytes, valid ZIP)")
                return file_content
            except Exception:
                # ZIP header present but structure broken — try truncating trailing garbage
                print(f"   ZIP header valid but file corrupt ({len(decoded)} bytes), attempting repair...")
                fixed = _try_truncate_zip(decoded)
                if fixed is not None:
                    result = base64.b64encode(fixed).decode('utf-8')
                    print(f"   Fixed trailing garbage: {len(decoded)} -> {len(fixed)} bytes")
                    return result
                print(f"   Could not repair ZIP file")

        # Try decoding a second time (double-encoded case)
        try:
            second = base64.b64decode(decoded)
            if second[:4] == XLSX_MAGIC:
                fixed = base64.b64encode(second).decode('utf-8')
                print(f"   Fixed double-base64: {len(file_content)} -> {len(fixed)} chars")
                return fixed
        except Exception:
            pass

        # Decoded bytes might be a base64 string stored as raw bytes
        try:
            text = decoded.decode('ascii')
            inner = base64.b64decode(text)
            if inner[:4] == XLSX_MAGIC:
                fixed = base64.b64encode(inner).decode('utf-8')
                print(f"   Fixed ASCII-wrapped base64: {len(file_content)} -> {len(fixed)} chars")
                return fixed
        except Exception:
            pass

        print(f"   Warning: could not produce valid xlsx (first 4 bytes: {decoded[:4]})")

    return file_content


def invoke(fn_name, payload):
    def default_serializer(obj):
        if isinstance(obj, set):
            return list(obj)
        raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')

    response = lambda_client.invoke(
        FunctionName=fn_name,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload, default=default_serializer)
    )
    raw = json.loads(response['Payload'].read().decode('utf-8'))

    if isinstance(raw.get('body'), str):
        raw = json.loads(raw['body'])

    if isinstance(raw.get('result'), dict):
        return raw['result']

    return raw


def lambda_handler(event, context):
    try:
        print(f"Dynamic Mapping Agent: {list(event.keys())}")

        body = event
        if 'body' in event and 'tool' not in event:
            body = event['body']
            if isinstance(body, str):
                body = json.loads(body)

        tool   = body.get('tool', 'run_dynamic_mapping')
        inputs = body.get('inputs', body)

        if tool == 'run_dynamic_mapping':
            return run_dynamic_mapping(inputs)
        elif tool == 'preview_dynamic_mapping':
            return preview_dynamic_mapping(inputs)
        elif tool == 'fetch_tabs':
            return fetch_tabs(inputs)
        else:
            return {'success': False, 'error': f'Unknown tool: {tool}'}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def run_dynamic_mapping(inputs):
    file_content      = inputs['file_content']
    file_type         = inputs.get('file_type', 'xlsx')
    sheet_name        = inputs.get('sheet_name', 0)
    target_sheet_url  = inputs['target_sheet_url']
    target_sheet_name = inputs.get('target_sheet_name', 'Sheet1')
    credentials       = inputs['credentials']
    section_index     = inputs.get('section_index')

    # Check for cached preview results (avoids repeating the AI call)
    cached_strategy = inputs.get('write_strategy')
    cached_anchor   = inputs.get('anchor_column')
    cached_mappings = inputs.get('column_mappings')
    cached_formulas = inputs.get('formula_cols')
    use_cache = cached_strategy and cached_anchor is not None and cached_mappings

    # Unpack per-strategy state envelope (new preferred field). Fall back
    # to legacy top-level fields so older frontend bundles still work.
    strategy_metadata = inputs.get('strategy_metadata') or {}
    if isinstance(strategy_metadata, str):
        try:
            strategy_metadata = json.loads(strategy_metadata)
        except Exception:
            strategy_metadata = {}
    for _legacy_field in ('pivot_source_col', 'value_source_col',
                          'period_columns', 'label_column',
                          'section_index', 'anchor_columns'):
        if _legacy_field not in strategy_metadata and _legacy_field in inputs:
            strategy_metadata[_legacy_field] = inputs.get(_legacy_field)
    # Mirror envelope fields back into inputs so the rest of run_dynamic_mapping
    # (which already reads inputs.get('pivot_source_col'), etc.) just works.
    for _k, _v in strategy_metadata.items():
        if _v is not None and inputs.get(_k) is None:
            inputs[_k] = _v

    print(f"Sanitizing file content (len={len(file_content) if isinstance(file_content, str) else '?'})...")
    file_content = sanitize_file_content(file_content, file_type)

    sheet_id = extract_sheet_id(target_sheet_url)

    # Step 0 fast-path: when the FE confirms a previously-previewed
    # mapping (cached_strategy is set) OR the user explicitly confirmed
    # the target tab via the multi-tab picker (target_tab_chosen is
    # set), the same target_sheet_name already resolved successfully
    # during preview and downstream read_sheet calls will surface a
    # clear error if anything changed in between. Skipping the
    # get_sheet_metadata round-trip saves ~5-7s on the confirm path —
    # critical for staying under API Gateway's 30s timeout. Non-cached
    # paths (preview, fresh runs) keep the resolve so dropdown typos
    # / gid-only URLs still self-heal.
    target_tab_chosen = inputs.get('target_tab_chosen')
    skip_resolve = bool(use_cache) or bool(
        strategy_metadata.get('column_merge')
        or strategy_metadata.get('aggregate')
        or strategy_metadata.get('auto_route')
        or strategy_metadata.get('cross_tab_section_aggregate')
    ) or bool(target_tab_chosen)
    if skip_resolve:
        print(
            f"Step 0: Skipping target tab resolve "
            f"(use_cache={bool(use_cache)}, "
            f"target_tab_chosen={target_tab_chosen!r}); "
            f"trusting target_sheet_name={target_sheet_name!r}"
        )
    else:
        print(f"Step 0: Resolving target sheet tab name...")
        target_sheet_name = resolve_sheet_name(sheet_id, target_sheet_name, target_sheet_url, credentials)

    # Cross-tab × per-source-section aggregate confirm. Most precise of the
    # multi-sheet strategies — runs first because its strategy_metadata key
    # (cross_tab_section_aggregate) is unique. The route_groups blob carries
    # the per-bucket {target_section_index, sources: [(sheet, section)]}
    # pairing the preview produced. See _run_cross_tab_section_aggregate
    # for the per-bucket write loop.
    if (
        cached_strategy == 'cross_tab_section_aggregate'
        or strategy_metadata.get('cross_tab_section_aggregate')
    ):
        route_groups = strategy_metadata.get('route_groups') or []
        if not route_groups:
            return {
                'success': False,
                'error': 'cross_tab_section_aggregate confirm is missing '
                         'strategy_metadata.route_groups. Try previewing again.',
                'error_type': 'missing_cross_tab_section_plan',
            }
        return _run_cross_tab_section_aggregate(
            inputs=inputs,
            route_groups=route_groups,
            conflict_resolutions=strategy_metadata.get('conflict_resolutions') or {},
            sheet_id=sheet_id,
            target_sheet_name=target_sheet_name,
            credentials=credentials,
        )

    # Multi-sheet auto-route confirm: preview stashed a per-sheet route plan
    # in strategy_metadata.routes. Dispatch to the per-route writer before
    # any of the single-sheet setup runs — parsing only the first sheet
    # would drop the other sections' data.
    if (
        cached_strategy == 'multi_sheet_section'
        or strategy_metadata.get('auto_route')
    ):
        routes = strategy_metadata.get('routes') or []
        if not routes:
            return {
                'success': False,
                'error': 'multi_sheet_section confirm is missing strategy_metadata.routes. '
                         'Try previewing again.',
                'error_type': 'missing_route_plan',
            }
        return _run_multi_sheet_auto_route(
            inputs=inputs,
            routes=routes,
            sheet_id=sheet_id,
            target_sheet_name=target_sheet_name,
            credentials=credentials,
        )

    # Multi-sheet aggregate confirm: preview stashed the aggregated sheet
    # names + the user's conflict resolution choices. Dispatch to the
    # aggregate writer before any single-sheet setup runs — same rationale
    # as the auto-route branch above. Also handles the intra-tab section
    # variant (cached_strategy == 'multi_section_aggregate'), which
    # carries strategy_metadata.aggregated_sections instead of
    # aggregated_sheet_names. The shared writer
    # (_run_multi_sheet_aggregate) detects which path to take from the
    # presence of the aggregated_sections kwarg.
    if (
        cached_strategy in ('multi_sheet_aggregate', 'multi_section_aggregate')
        or strategy_metadata.get('aggregate')
    ):
        aggregated_sheet_names = strategy_metadata.get('aggregated_sheet_names') or []
        aggregated_sections    = strategy_metadata.get('aggregated_sections') or []
        if not aggregated_sheet_names and not aggregated_sections:
            return {
                'success': False,
                'error': 'Aggregate confirm is missing '
                         'strategy_metadata.aggregated_sheet_names or '
                         'strategy_metadata.aggregated_sections. Try previewing again.',
                'error_type': 'missing_aggregate_plan',
            }
        return _run_multi_sheet_aggregate(
            inputs=inputs,
            aggregated_sheet_names=aggregated_sheet_names,
            aggregated_sections=aggregated_sections or None,
            conflict_resolutions=strategy_metadata.get('conflict_resolutions') or {},
            target_section_index=strategy_metadata.get('target_section_index'),
            sheet_id=sheet_id,
            target_sheet_name=target_sheet_name,
            credentials=credentials,
        )

    # Multi-sheet column-merge confirm: preview stashed the sheet names in
    # strategy_metadata.sheet_names + the user's conflict_resolutions for
    # any cell-level cross-sheet conflicts. Dispatch to the column-merge
    # writer before single-sheet setup runs — same reason as the aggregate
    # branch above (single-sheet parsing would drop the other sheet's
    # column contributions).
    if (
        cached_strategy == 'multi_sheet_column_merge'
        or strategy_metadata.get('column_merge')
    ):
        sheet_names_cm = strategy_metadata.get('sheet_names') or []
        if not sheet_names_cm:
            return {
                'success': False,
                'error': 'Column-merge confirm is missing '
                         'strategy_metadata.sheet_names. Try previewing again.',
                'error_type': 'missing_column_merge_plan',
            }
        return _run_multi_sheet_column_merge(
            inputs=inputs,
            sheet_names=sheet_names_cm,
            conflict_resolutions=strategy_metadata.get('conflict_resolutions') or {},
            sheet_id=sheet_id,
            target_sheet_name=target_sheet_name,
            credentials=credentials,
            # Per-sheet identification cache from preview — replaces the
            # confirm-time find_identifier LLM call. Older FE bundles
            # that pre-date this field send None and the writer falls
            # back to the LLM path unchanged.
            cached_per_sheet=strategy_metadata.get('per_sheet_cache'),
        )

    # Step 0a (defensive mirror of preview's Step 0a): if the caller did not
    # forward an explicit source sheet_name, re-run the same detect+auto-pick
    # logic the preview used. This is what makes the confirm path self-heal
    # when an older frontend bundle forgets to echo sheet_name — without this
    # we would silently default to sheet 0 (e.g. an IgnoreMe tab) and end up
    # with "0 rows transformed". Only dominant picks are honored here so a
    # guess never overrides a preview-time user choice; genuine ambiguity
    # falls through and will be caught by the empty_write guard downstream.
    caller_picked_sheet = isinstance(sheet_name, str) and sheet_name.strip() != ""
    if (
        file_type and file_type.lower() in ('xlsx', 'xls', 'excel')
        and not caller_picked_sheet
    ):
        print("Step 0a: Detecting source sheets (confirm path)...")
        sheets_result = invoke(MAPPING_LAMBDA, {
            'tool': 'detect_source_sheets',
            'inputs': {
                'file_content': file_content,
                'file_type': file_type,
                # Target headers aren't read yet on the cached path, so let
                # detect_source_sheets score against whatever the caller knows
                # (mapping values double as a proxy for target headers).
                'target_headers': list(set((cached_mappings or {}).values())) if cached_mappings else [],
            }
        })
        sheets_list = sheets_result.get('sheets', []) if sheets_result.get('success') else []
        if len(sheets_list) >= 2:
            picked = _auto_pick_source_sheet(sheets_list)
            if picked is not None:
                sheet_name = picked
                print(f"   Auto-picked source sheet '{picked}' "
                      f"(scores: {[(s.get('name'), s.get('score')) for s in sheets_list]})")
            else:
                # Ambiguous — don't guess. Log so CloudWatch shows why we
                # might end up with 0 writes instead of silently defaulting.
                print(f"   Multi-sheet detected ({len(sheets_list)}) with no dominant pick; "
                      f"frontend did not echo sheet_name — falling back to default.")
        elif len(sheets_list) == 1:
            only = sheets_list[0].get('name')
            if only:
                sheet_name = only
                print(f"   Single-sheet file, using '{only}'")

    # Resolve which section (if any) the user picked in the preview step so the
    # write operates on the same sliced rows. Same shape as preview's Step 0b.
    # If the frontend forgot to echo section_index on confirm but preview had
    # stashed cached mappings (so we know which target headers the user
    # actually chose), try the same dominant-overlap auto-pick we use for
    # sheets. Only honored when a single source section clearly dominates —
    # a guess here writes INBOUND data into OUTBOUND's column, which is worse
    # than failing loudly.
    if (
        section_index is None
        and use_cache
        and file_type and file_type.lower() in ('xlsx', 'xls', 'excel')
    ):
        print("Step 0b (auto-recover): section_index missing on confirm — "
              "probing for a dominant source section...")
        probe = invoke(MAPPING_LAMBDA, {
            'tool': 'detect_source_sections',
            'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
        })
        probe_sections = probe.get('sections', []) if probe.get('success') else []
        if len(probe_sections) >= 2:
            cached_target_headers = list(set((cached_mappings or {}).values()))
            recovered_idx = _auto_pick_source_section(probe_sections, cached_target_headers)
            if recovered_idx is not None:
                section_index = recovered_idx
                print(f"   Auto-recovered section_index={recovered_idx} "
                      f"('{probe_sections[recovered_idx].get('title')}')")
            else:
                print(f"   Multi-section detected ({len(probe_sections)}) with no dominant pick; "
                      f"frontend did not echo section_index — falling back to full-file parse.")

    selected_section = None
    if section_index is not None and file_type and file_type.lower() in ('xlsx', 'xls', 'excel'):
        print(f"Step 0b: Resolving source section #{section_index}...")
        sec_result = invoke(MAPPING_LAMBDA, {
            'tool': 'detect_source_sections',
            'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
        })
        sections = sec_result.get('sections', []) if sec_result.get('success') else []
        try:
            idx = int(section_index)
            if 0 <= idx < len(sections):
                selected_section = sections[idx]
                print(f"   Using section '{selected_section.get('title')}' ({selected_section.get('row_count')} rows)")
            else:
                return {'success': False, 'error': f'Invalid section_index {idx}; file has {len(sections)} sections'}
        except (TypeError, ValueError):
            return {'success': False, 'error': f'section_index must be an integer (got {section_index!r})'}

    # Parse the source file (always needed)
    print("Step 1: Parsing source file...")
    parse_inputs = {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
    if selected_section is not None:
        parse_inputs['section'] = selected_section
    parse_result = invoke(MAPPING_LAMBDA, {
        'tool': 'parse_file',
        'inputs': parse_inputs
    })
    if not parse_result.get('success'):
        return {'success': False, 'error': f"File parse failed: {parse_result.get('error')}"}
    print(f"   {parse_result.get('row_count')} rows parsed from source")

    # Apply intra-section choices BEFORE either branch consumes the rows.
    # The FE re-sends intra_section_choices on every confirm after the
    # user resolved duplicates in the conflict modal — applying here in
    # the cached AND non-cached branches keeps both paths in lock-step
    # with the preview's view of the data. If the user did NOT resolve
    # duplicates the choices dict is empty and this is a no-op. Filtering
    # this early means structure_source_data, transform_data, and the
    # per-row writers all see the deduped row set.
    intra_section_choices = _normalize_intra_section_choices(
        inputs.get('intra_section_choices')
        or strategy_metadata.get('intra_section_choices')
    )
    if intra_section_choices:
        # Anchor names: prefer cached/explicit source_anchor, else fall back
        # to the column anchor (it's the same field for non-list anchors).
        _src_anchor_for_filter = (
            inputs.get('source_anchor')
            or cached_anchor
            or []
        )
        _src_anchor_names = (
            _src_anchor_for_filter
            if isinstance(_src_anchor_for_filter, list)
            else [_src_anchor_for_filter]
        )
        # Date-anchor flag: same heuristic the preview uses (cached
        # strategy is sufficient on this path because the FE only echoes
        # back row_per_date / row_per_entity strategies on confirm).
        _is_date_anchor_filter = (
            cached_strategy == 'row_per_date'
            or (
                isinstance(cached_anchor, str)
                and 'date' in (cached_anchor or '').lower()
            )
        )
        full_data_in = parse_result.get('full_data') or []
        if isinstance(full_data_in, str):
            try:
                full_data_in = json.loads(full_data_in)
            except Exception:
                full_data_in = []
        full_data_filtered = _apply_intra_section_choices(
            full_data_in,
            intra_section_choices,
            _src_anchor_names,
            _is_date_anchor_filter,
        )
        if len(full_data_filtered) != len(full_data_in):
            print(
                f"   Applied intra_section_choices on confirm: "
                f"{len(full_data_in)} -> {len(full_data_filtered)} rows"
            )
            parse_result['full_data'] = full_data_filtered
            # Patch row_count too so downstream logging reflects the filter.
            parse_result['row_count'] = len(full_data_filtered)

    if use_cache:
        print("Using cached preview results (skipping AI call)")
        write_strategy  = cached_strategy
        anchor_column   = cached_anchor
        column_mappings = cached_mappings
        source_anchor   = inputs.get('source_anchor', cached_anchor)
        formula_col_set = set(cached_formulas or [])
        # Pre-resolved TARGET section index — set by find_identifier when
        # its multi-section pre-resolver picked a non-first section. Echoed
        # back from the frontend via strategy_metadata.target_section_index
        # so the writer pins to the same section the preview mapped against
        # (instead of relying on _pick_best_section's auto-pick which can
        # tie-break onto a different section). Different from the SOURCE
        # section_index above (which slices the source file). Accept both
        # the top-level shape (older FE bundles) and the strategy_metadata
        # nested shape (current FE bundles via the wrapper passthrough).
        _strategy_meta_in = inputs.get('strategy_metadata') or {}
        target_section_idx = (
            inputs.get('target_section_index')
            if inputs.get('target_section_index') is not None
            else _strategy_meta_in.get('target_section_index')
        )

        # Rebuild the identification + minimal schemas so the shared
        # _prepare_strategy_state helper can apply strategy-specific prep
        # (e.g. cross_tab pivot). When pivot metadata is missing from the
        # frontend (stale bundle, dropped field), auto-recover it from the
        # parsed source rows so confirm still works.
        if write_strategy == 'cross_tab':
            pivot_src_in = inputs.get('pivot_source_col')
            value_src_in = inputs.get('value_source_col')
            if not (pivot_src_in and value_src_in):
                pivot_src_in, value_src_in = _recover_cross_tab_metadata(
                    parse_result, column_mappings, anchor_column
                )
                if pivot_src_in and value_src_in:
                    print(
                        f"   Recovered cross_tab metadata from parse_result: "
                        f"pivot='{pivot_src_in}', value='{value_src_in}'"
                    )
        else:
            pivot_src_in = value_src_in = None

        cached_identification = {
            'write_strategy':   write_strategy,
            'anchor_column':    anchor_column,
            'source_anchor':    source_anchor,
            'column_mappings':  column_mappings,
            'pivot_source_col': pivot_src_in,
            'value_source_col': value_src_in,
            'period_columns':   inputs.get('period_columns'),
            'label_column':     inputs.get('label_column'),
            'section_index':    inputs.get('section_index'),
        }
        # Always run structure_source_data on the cached confirm path
        # too so any grouped-header rewrite of ``full_data`` is applied
        # back into ``parse_result``. Without this the cached path would
        # write 0 rows for sources with composite headers (e.g.
        # "Inbound Metrics > Date"): the LLM mapping (echoed back from
        # the frontend in ``column_mappings``) uses composite names but
        # ``parse_result['full_data']`` would still be keyed by the raw
        # pandas columns ("Unnamed: 1", "Inbound Metrics", …) so every
        # ``row.get(composite_name)`` returns None.
        cached_source_schema = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_source_data',
            'inputs': {'parse_result': parse_result}
        })
        if not cached_source_schema.get('success'):
            # Fall back to the minimal hand-rolled shape so the cached
            # confirm path doesn't regress when structure_source_data
            # itself fails for an unrelated reason (e.g. mapping-agent
            # cold-start error). _prepare_strategy_state only reads
            # ``headers`` / ``total_rows`` for cross_tab and writes them
            # back, so the minimal shape is sufficient as a safety net.
            cached_source_schema = {
                'headers': list((parse_result.get('columns') or [])),
                'total_rows': parse_result.get('row_count', 0),
                'col_samples': {},
            }
        else:
            _corrected_full_data = cached_source_schema.get('full_data')
            if _corrected_full_data is not None:
                parse_result['full_data'] = _corrected_full_data
        cached_target_schema = {
            'headers': list(set(column_mappings.values())),
        }
        if _prepare_strategy_state(
            cached_identification, parse_result,
            cached_source_schema, cached_target_schema,
        ):
            # Pick up any mapping refinement the prep step performed
            # (e.g. cross_tab pivot trims mappings to matched cols only).
            column_mappings = cached_identification.get('column_mappings', column_mappings)
    else:
        print("Step 2: Reading target sheet...")
        range_name = f"'{target_sheet_name}'" if ' ' in target_sheet_name else target_sheet_name
        sheet_read = invoke(SHEETS_LAMBDA, {
            'tool': 'read_sheet',
            'inputs': {'sheet_id': sheet_id, 'range_name': range_name},
            'credentials_dict': credentials
        })
        if not sheet_read.get('success'):
            return {'success': False, 'error': f"Cannot read target sheet: {sheet_read.get('error')}"}
        raw_values = sheet_read.get('data', sheet_read.get('values', []))

        print("Detecting formula columns...")
        formula_cols = detect_formula_columns(sheet_id, range_name, credentials)

        print("Structuring target data...")
        target_schema = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_target_data',
            'inputs': {'raw_values': raw_values, 'sheet_name': target_sheet_name}
        })
        if not target_schema.get('success'):
            return {'success': False, 'error': f"Cannot structure target: {target_schema.get('error')}"}
        existing_formula_cols = set(target_schema.get('formula_cols', []))
        existing_formula_cols.update(formula_cols)
        target_schema['formula_cols'] = list(existing_formula_cols)

        print("Structuring source data...")
        source_schema = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_source_data',
            'inputs': {'parse_result': parse_result}
        })
        if not source_schema.get('success'):
            return {'success': False, 'error': f"Cannot structure source: {source_schema.get('error')}"}
        # Patch parse_result with the grouped-header-aware ``full_data``
        # so every downstream consumer (transform_data, anchor pairing,
        # _aggregate_build_anchor_map) sees rows keyed by the composite
        # header names that find_identifier and column_mappings use.
        # No-op for flat-header sources because structure_source_data
        # round-trips the original full_data unchanged in that case.
        _corrected_full_data = source_schema.get('full_data')
        if _corrected_full_data is not None:
            parse_result['full_data'] = _corrected_full_data

        # Empty-target short-circuit: mirror the preview path. When the target
        # sheet is empty we skip AI entirely and force a clean append with
        # identity column mappings so the source columns become row 1 headers.
        is_empty_target_run = bool(target_schema.get('is_empty_target'))
        if is_empty_target_run:
            print("Target sheet is empty — forcing append strategy with identity mappings")
            src_headers_for_append = source_schema.get('headers', [])
            identification = {
                'success': True,
                'write_strategy': 'append',
                'anchor_column': None,
                'source_anchor': None,
                'anchor_type': '',
                'column_mappings': {h: h for h in src_headers_for_append},
                'reasoning': 'Target sheet is empty; treating source columns as new headers.',
            }
            target_schema['headers'] = list(src_headers_for_append)
            target_schema['header_index'] = {h: i for i, h in enumerate(src_headers_for_append)}
        else:
            print("AI finding identifier and mapping columns...")
            # Pass the SOURCE section title (Fix N) so the multi-section
            # pre-resolver can title-tie-break — same rationale as the
            # preview path above. ``selected_section`` is set when the
            # user picked a source section via section_index.
            identification = invoke(MAPPING_LAMBDA, {
                'tool': 'find_identifier',
                'inputs': {
                    'target_schema': target_schema,
                    'source_schema': source_schema,
                    'source_section_title': (selected_section.get('title') if selected_section else None),
                }
            })
            if not identification.get('success'):
                return {'success': False, 'error': f"Identifier detection failed: {identification.get('error')}"}

        # Apply strategy-specific prep (cross_tab pivot, etc.) so the data
        # is in the shape the downstream transform + write expect.
        _prepare_strategy_state(identification, parse_result, source_schema, target_schema)

        write_strategy  = identification['write_strategy']
        anchor_column   = identification.get('anchor_column')
        column_mappings = identification.get('column_mappings', {})
        source_anchor   = identification.get('source_anchor', anchor_column)
        formula_col_set = set(target_schema.get('formula_cols', []))
        # Pre-resolved TARGET section index from find_identifier's
        # multi-section pre-resolver. Mirrors the cached-path lookup
        # above so the writer pins to the right section regardless of
        # which path produced the identification.
        target_section_idx = identification.get('target_section_index')

    # Guard: if no columns could be mapped, fail early.
    # cross_tab, key_value and append are allowed to have zero direct mappings.
    strategy_bypasses_mapping_guard = write_strategy in ('cross_tab', 'key_value', 'append')
    mappable = [k for k, v in column_mappings.items() if v is not None]
    if not mappable and not strategy_bypasses_mapping_guard:
        return {
            'success': False,
            'error': 'No columns in your file could be matched to the target sheet.'
        }

    # Exclude anchor column(s) and formula columns from writes
    anchor_col_set = set(anchor_column) if isinstance(anchor_column, list) else {anchor_column} if anchor_column else set()
    write_mappings = {k: v for k, v in column_mappings.items()
                      if v and v not in anchor_col_set and v not in formula_col_set}
    # cross_tab pivots source values into the matrix at write time, and
    # key_value writes into the value column derived from the anchor — both
    # legitimately produce empty write_mappings.
    if not write_mappings and not strategy_bypasses_mapping_guard:
        return {
            'success': False,
            'error': 'All mapped columns are either the anchor or formula columns. No data columns to write.'
        }
    print(f"   Strategy: {write_strategy}, Anchor: {anchor_column}")
    print(f"   Write mappings: {list(write_mappings.keys())}")

    print("Transforming data...")
    transform_result = invoke(MAPPING_LAMBDA, {
        'tool': 'transform_data',
        'inputs': {'source_data': parse_result.get('full_data'), 'mappings': write_mappings}
    })
    if not transform_result.get('success'):
        return {'success': False, 'error': f"Transform failed: {transform_result.get('error')}"}

    transformed = transform_result.get('transformed_data', [])
    if isinstance(transformed, str):
        transformed = json.loads(transformed)

    # Strip empty cells from every transformed row BEFORE any strategy
    # writer sees them. transform_data coerces NaN/None to "" (see
    # mapping_agent_api.transform_data:1083-1086); if those empty
    # strings flow through to update_rows_by_date / update_rows_by_anchor
    # / _write_cross_tab etc. they blank out existing target values,
    # which is the TC-D10 "empty source cell overwrites target 99 with
    # empty" bug. Partial-update semantics say: empty source = leave
    # target alone, no exceptions. The anchor value itself is added
    # later (at row['_anchor_value']) so it's safe to filter here.
    stripped_empty = 0
    for row in transformed:
        for k in [k for k, v in row.items() if v is None or (isinstance(v, str) and v.strip() == '')]:
            row.pop(k, None)
            stripped_empty += 1
    if stripped_empty:
        print(f"   Stripped {stripped_empty} empty source cell(s) — "
              f"they will NOT overwrite existing target values")

    print(f"   {len(transformed)} rows transformed")

    # Pair anchor values back with transformed rows (supports composite keys)
    try:
        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
        source_anchors = [source_anchor] if not isinstance(source_anchor, list) else source_anchor
        for i, row in enumerate(transformed):
            if i < len(full_data):
                parts = []
                for sa in source_anchors:
                    val = full_data[i].get(sa)
                    if val is not None:
                        normed = _normalize_date_value(val)
                        parts.append(normed or str(val))
                if parts:
                    row['_anchor_value'] = '|'.join(parts) if len(parts) > 1 else parts[0]
    except Exception as e:
        print(f"   Warning: could not pair anchor values: {e}")

    # Per-row write filter (writeOnly). The preview UI lets the user
    # uncheck individual rows in the diff / appended-rows tables before
    # confirming. The frontend passes the user's selection as
    # `write_only.allowed_diff_cells` (rows that match an existing target
    # row, identified by anchor + column) and
    # `write_only.allowed_append_anchors` (brand-new rows, identified by
    # anchor only).
    #
    # We only filter when the strategy is row-based (each transformed row
    # corresponds to one target row). Non-row strategies — cross_tab,
    # key_value, horizontal, multi_section — have different write
    # semantics where individual transformed entries don't map cleanly
    # onto user-visible rows; the frontend disables the per-row UI for
    # them, but we ignore the filter as a backstop in case an old bundle
    # still sends it.
    write_only_raw = inputs.get('write_only')
    if isinstance(write_only_raw, str) and write_only_raw.strip():
        try:
            write_only_raw = json.loads(write_only_raw)
        except Exception as _err:
            print(f"   write_only payload was not valid JSON ({_err}); ignoring filter")
            write_only_raw = None
    write_only = write_only_raw if isinstance(write_only_raw, dict) else None

    if (
        write_only
        and write_strategy in ('row_per_date', 'row_per_entity', 'composite_key', 'append')
    ):
        diff_cells = write_only.get('allowed_diff_cells') or []
        append_anchors = write_only.get('allowed_append_anchors') or []

        allowed_anchors = set()
        for c in diff_cells:
            if isinstance(c, dict) and c.get('anchor') is not None:
                allowed_anchors.add(str(c['anchor']))
        for a in append_anchors:
            if a is not None:
                allowed_anchors.add(str(a))

        if allowed_anchors:
            before = len(transformed)
            kept = []
            for row in transformed:
                anchor_val = row.get('_anchor_value')
                if anchor_val is None:
                    # Append strategy or rows that didn't carry an explicit
                    # anchor — keep them only if the user opted into 'append'
                    # for an unknown anchor (rare; preserve legacy behavior
                    # by keeping when the diff list is empty AND there was
                    # exactly one append entry).
                    if not append_anchors and not diff_cells:
                        kept.append(row)
                    continue
                if str(anchor_val) in allowed_anchors:
                    kept.append(row)
            dropped = before - len(kept)
            transformed = kept
            print(
                f"   write_only filter: kept {len(transformed)}/{before} row(s); "
                f"dropped {dropped} deselected row(s) "
                f"(allowed anchors: {len(allowed_anchors)})"
            )

            if not transformed:
                return {
                    'success': False,
                    'error': (
                        "All rows were deselected before write. Pick at least one "
                        "row in the preview's checkbox list and confirm again."
                    ),
                    'error_type': 'empty_write_selection',
                }
        else:
            print("   write_only payload had no allowed anchors; ignoring filter")

    # Get header info for grouped headers
    hrc = 1
    ctci = {}
    if use_cache:
        hrc = int(inputs.get('header_row_count', 1))
        ctci_raw = inputs.get('composite_to_col_index', {})
        ctci = ctci_raw if isinstance(ctci_raw, dict) else {}
    else:
        hrc = target_schema.get('header_row_count', 1)
        ctci = target_schema.get('composite_to_col_index', {})

    # If the target sheet was empty we need to seed row 1 with the source
    # headers before calling append_rows (otherwise the first appended row
    # lands in A1 and there's no header row at all).
    if not use_cache and bool(target_schema.get('is_empty_target')):
        seed_headers = list(column_mappings.values())
        if seed_headers:
            safe_seed_name = (
                f"'{target_sheet_name}'"
                if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
                else target_sheet_name
            )
            print(f"Seeding empty target with headers: {seed_headers}")
            seed_result = invoke(SHEETS_LAMBDA, {
                'tool': 'update_sheet',
                'inputs': {
                    'sheet_id': sheet_id,
                    'range_name': f"{safe_seed_name}!A1",
                    'data': [seed_headers],
                },
                'credentials_dict': credentials
            })
            if not seed_result.get('success'):
                return {
                    'success': False,
                    'error': f"Could not seed headers into empty target sheet: "
                             f"{seed_result.get('error')}"
                }

    # --- Resolve target section row-range BEFORE route_write so the
    # writer (Fix O) can pin update_rows_by_date / update_rows_by_anchor
    # to the section's row span (Fix L). Without this pin a date that
    # appears in TWO sections of the same target tab (e.g. Inbound + Outbound
    # both having "2025-05-01") gets silently overwritten in the wrong
    # section because update_rows_by_date's date_to_row_map is a plain
    # dict and the later occurrence wins.
    #
    # Two paths:
    #   - non-cached: target_schema is built fresh + has 'sections' loaded
    #   - cached: target_schema does not exist as a local at all (the cached
    #     branch builds `cached_target_schema` instead) → MUST NOT touch
    #     `target_schema` here or Python raises UnboundLocalError. Use the
    #     re-read fallback in that case (one extra read, only when
    #     target_section_idx is set, so single-section users pay nothing).
    section_data_start_row = None
    section_data_end_row = None
    if target_section_idx is not None:
        # Defensive: only read target_schema on the non-cached path. The
        # `use_cache` flag is the same gate used for hrc/ctci above
        # (see lines ~696) so we are 1:1 with the existing branch
        # structure — no risk of touching an unbound name.
        sections_for_write = []
        if not use_cache:
            sections_for_write = (
                (target_schema.get('sections') if isinstance(target_schema, dict) else None)
                or []
            )
        if not sections_for_write:
            try:
                rng = (
                    f"'{target_sheet_name}'"
                    if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
                    else target_sheet_name
                )
                section_read = invoke(SHEETS_LAMBDA, {
                    'tool': 'read_sheet',
                    'inputs': {'sheet_id': sheet_id, 'range_name': rng},
                    'credentials_dict': credentials,
                })
                if section_read.get('success'):
                    sections_for_write = _detect_sections_local(
                        section_read.get('data', []) or []
                    )
                    print(
                        f"   Cached-path section re-detect: found "
                        f"{len(sections_for_write)} section(s) in target tab"
                    )
            except Exception as _sec_err:
                print(f"   Warning: could not re-detect target sections "
                      f"on cached path: {_sec_err}")
        if sections_for_write and 0 <= target_section_idx < len(sections_for_write):
            sec_for_write = sections_for_write[target_section_idx]
            ds = sec_for_write.get('data_start')
            de = sec_for_write.get('data_end')
            if isinstance(ds, int) and isinstance(de, int) and de > ds:
                # Convert 0-indexed [data_start..data_end) → 1-indexed
                # [data_start+1..data_end] both inclusive (sheet row numbers).
                # Empty-template sections (de == ds) intentionally leave
                # both bounds None so the lookup map is empty and every
                # source row falls through to the append fallback.
                section_data_start_row = ds + 1
                section_data_end_row = de
                print(
                    f"   Section row-range resolved: "
                    f"target section #{target_section_idx} "
                    f"'{sec_for_write.get('title')}' → "
                    f"sheet rows {section_data_start_row}..{section_data_end_row}"
                )

    print(f"Writing via '{write_strategy}'...")
    write_result = route_write(
        write_strategy=write_strategy,
        anchor_column=anchor_column,
        transformed=transformed,
        target_headers=list(column_mappings.values()),
        sheet_id=sheet_id,
        sheet_name=target_sheet_name,
        credentials=credentials,
        header_row_count=hrc,
        composite_to_col_index=ctci,
        target_section_index=target_section_idx,
        section_data_start_row=section_data_start_row,
        section_data_end_row=section_data_end_row,
    )

    # Loud-fail guard: a write that touched nothing almost always means
    # strategy state was dropped between preview and confirm (classic
    # symptom: cached_mappings don't line up with the flat parse_result
    # because a pre-pivot / section-slice step was skipped). Surface a
    # concrete, actionable error instead of the generic "Dynamic mapping
    # failed" string the frontend used to show.
    rows_updated  = write_result.get('rows_updated',  0) or 0
    rows_appended = write_result.get('rows_appended', 0) or 0
    cells_updated = write_result.get('cells_updated', 0) or 0

    append_mode     = write_result.get('append_mode')
    overflow_reason = write_result.get('overflow_reason')

    # Always emit a one-line summary of the write outcome — without this,
    # successful row_per_date / row_per_entity confirms log nothing
    # between "Rows prepared for write: N" and END, which makes
    # CloudWatch debugging much harder than it needs to be.
    summary = (
        f"Write result: success={write_result.get('success')} "
        f"rows_updated={rows_updated} rows_appended={rows_appended} "
        f"cells_updated={cells_updated} "
        f"strategy={write_strategy} anchor={anchor_column}"
    )
    if append_mode:
        summary += f" append_mode={append_mode}"
    if overflow_reason:
        summary += f" overflow_reason={overflow_reason!r}"
    print(summary)

    if (write_result.get('success')
            and rows_updated == 0
            and rows_appended == 0
            and cells_updated == 0):
        return {
            'success': False,
            'error': (
                f"Strategy '{write_strategy}' produced no writes. "
                f"This usually means strategy metadata was stripped "
                f"between preview and confirm. Try previewing again."
            ),
            'error_type': 'empty_write',
            'write_strategy': write_strategy,
            'anchor_column':  anchor_column,
            'rows_processed': len(transformed),
            'column_mappings': column_mappings,
            'write_result':    write_result,
        }

    response = {
        'success':         write_result.get('success', False),
        'write_strategy':  write_strategy,
        'anchor_column':   anchor_column,
        'rows_processed':  len(transformed),
        'column_mappings': column_mappings,
        'write_result':    write_result
    }
    # Surface append-mode signals at the top level so the frontend does not
    # need to dig into write_result to render the fallback warning.
    if append_mode:
        response['append_mode'] = append_mode
    if overflow_reason:
        response['overflow_reason'] = overflow_reason
    # Surface route_write's hard-fail diagnostics (Fix K) at the top level so
    # the FE renders the actionable Google API error (e.g. PERMISSION_DENIED)
    # instead of the generic "Dynamic mapping failed" string. The FE checks
    # `error_type` to switch its message and `error` for the human-readable
    # explanation. Both fields originate inside route_write's hard-fail
    # short-circuits — promote them up the call chain.
    if not response['success'] and write_result.get('error'):
        response['error'] = write_result.get('error')
        if write_result.get('error_type'):
            response['error_type'] = write_result.get('error_type')
        if write_result.get('underlying_error'):
            response['underlying_error'] = write_result.get('underlying_error')
    return response


def preview_dynamic_mapping(inputs):
    file_content      = inputs['file_content']
    file_type         = inputs.get('file_type', 'xlsx')
    sheet_name        = inputs.get('sheet_name', 0)
    target_sheet_url  = inputs['target_sheet_url']
    target_sheet_name = inputs.get('target_sheet_name', 'Sheet1')
    credentials       = inputs['credentials']
    section_index     = inputs.get('section_index')

    print(f"Sanitizing file content (len={len(file_content) if isinstance(file_content, str) else '?'})...")
    file_content = sanitize_file_content(file_content, file_type)

    sheet_id = extract_sheet_id(target_sheet_url)

    print(f"Step 0: Resolving target sheet tab name...")
    target_sheet_name = resolve_sheet_name(sheet_id, target_sheet_name, target_sheet_url, credentials)

    # Read + structure the target FIRST so that Step 0a (sheet detection) can
    # score source sheets by header overlap with the real target. Doing this up
    # here also means we read the target exactly once regardless of whether
    # sheet/section pickers short-circuit later.
    print(f"Step 1: Reading target sheet '{target_sheet_name}'...")
    range_name = f"'{target_sheet_name}'" if ' ' in target_sheet_name else target_sheet_name
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': range_name},
        'credentials_dict': credentials
    })
    print(f"   sheet_read keys: {list(sheet_read.keys())}")
    print(f"   sheet_read success: {sheet_read.get('success')}")
    print(f"   sheet_read error: {sheet_read.get('error')}")
    if not sheet_read.get('success'):
        return {'success': False, 'error': f"Cannot read target sheet: {sheet_read.get('error')}"}
    raw_values = sheet_read.get('data', sheet_read.get('values', []))
    print(f"   {len(raw_values)} rows read from target sheet")

    print("Step 1b: Detecting formula columns...")
    formula_cols = detect_formula_columns(sheet_id, range_name, credentials)
    print(f"   Formula columns detected: {len(formula_cols)}")

    print("Step 2: Structuring target data...")
    target_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_target_data',
        'inputs': {'raw_values': raw_values, 'sheet_name': target_sheet_name}
    })
    print(f"   target_schema success: {target_schema.get('success')}")
    print(f"   target_schema error: {target_schema.get('error')}")
    if not target_schema.get('success'):
        return {'success': False, 'error': f"Cannot structure target: {target_schema.get('error')}"}
    existing_formula_cols = set(target_schema.get('formula_cols', []))
    existing_formula_cols.update(formula_cols)
    target_schema['formula_cols'] = list(existing_formula_cols)
    print(f"   Headers count: {len(target_schema.get('headers', []))}")
    print(f"   Total formula columns: {len(target_schema['formula_cols'])}")

    target_headers_for_scoring = list(target_schema.get('headers', []) or [])

    # Step 0a: multi-sheet source detection. For xlsx files with 2+ non-trivial
    # sheets we either auto-pick the best-scoring sheet (when one dominates by
    # target-header overlap) or surface a picker to the UI. ``sheet_name`` only
    # counts as "explicit" when it's a non-default string — the service layer
    # sends 0 by default when the user has not picked a sheet. This must run
    # BEFORE Step 0b so section detection operates on the correct sheet.
    #
    # Auto-route special case: if the source has N sheets AND the target has
    # N stacked sections AND each sheet's headers clearly match exactly one
    # section (dominance + 1:1 claim), route each sheet into its matching
    # section without any picker. See _plan_multi_sheet_auto_route for the
    # exact dominance rules (TC-L03 fixture is the canonical case).
    caller_picked_sheet = isinstance(sheet_name, str) and sheet_name.strip() != ""
    auto_selected_sheet = None
    sheets_list = []
    if (
        file_type and file_type.lower() in ('xlsx', 'xls', 'excel')
        and not caller_picked_sheet
    ):
        print("Step 0a: Detecting source sheets...")
        sheets_result = invoke(MAPPING_LAMBDA, {
            'tool': 'detect_source_sheets',
            'inputs': {
                'file_content': file_content,
                'file_type': file_type,
                'target_headers': target_headers_for_scoring,
            }
        })
        sheets_list = sheets_result.get('sheets', []) if sheets_result.get('success') else []

        # Cross-tab × per-source-section aggregate. The MOST PRECISE planner —
        # runs first because it sees per-tab section structure, not just
        # flat per-tab columns. Fires when:
        #   - 2+ source tabs (after sidecar filter)
        #   - 2+ target sections
        #   - every source tab has detectable sections
        #   - every (sheet, section) maps cleanly to a target section
        # User scenario: source TC-L06 has March_Data + April_Data tabs each
        # with stacked Inbound + Outbound sections; target has Inbound +
        # Outbound. Routes: {target Inbound: March.Inbound + April.Inbound,
        # target Outbound: March.Outbound}. Conflicts only when same anchor
        # value exists in 2+ source rows that route to the same target
        # section (intra-section dups + cross-tab dups unified into one ask).
        if len(sheets_list) >= 2 and section_index is None:
            target_sections_for_ct_section = _detect_sections_local(raw_values or [])
            if len(target_sections_for_ct_section) >= 2:
                # Filter sidecar tabs (score==0) the same way
                # _plan_multi_sheet_aggregate does, so a "Notes" tab can't
                # poison the per-tab section detection step.
                ct_section_candidate_sheets = [
                    s for s in sheets_list
                    if (s.get('data_rows') or 0) > 0
                    and (s.get('meaningful_headers') or 0) > 0
                    and (s.get('score') or 0) > 0
                ]
                if len(ct_section_candidate_sheets) >= 2:
                    print(
                        f"Step 0a-cross-tab-section: probing per-tab sections "
                        f"({len(ct_section_candidate_sheets)} candidate tab(s))..."
                    )
                    per_tab_sections = []
                    for sheet in ct_section_candidate_sheets:
                        sname = sheet.get('name')
                        sec_probe = invoke(MAPPING_LAMBDA, {
                            'tool': 'detect_source_sections',
                            'inputs': {
                                'file_content':   file_content,
                                'file_type':      file_type,
                                'sheet_name':     sname,
                                'include_single': True,
                            },
                        })
                        per_tab_sections.append({
                            'sheet_name': sname,
                            'sections': (
                                sec_probe.get('sections', [])
                                if sec_probe.get('success') else []
                            ),
                        })
                    ct_section_plan = _plan_cross_tab_section_aggregate(
                        per_tab_sections, target_sections_for_ct_section,
                    )
                    if ct_section_plan:
                        return _preview_cross_tab_section_aggregate(
                            file_content=file_content,
                            file_type=file_type,
                            target_sheet_name=target_sheet_name,
                            raw_values=raw_values,
                            target_schema=target_schema,
                            formula_cols=target_schema.get('formula_cols', []) or [],
                            route_groups=ct_section_plan['route_groups'],
                            conflict_choices=inputs.get('conflict_choices'),
                        )

        if len(sheets_list) >= 2 and section_index is None:
            target_sections_for_route = _detect_sections_local(raw_values or [])
            if len(target_sections_for_route) >= 2:
                route_plan = _plan_multi_sheet_auto_route(sheets_list, target_sections_for_route)
                if route_plan:
                    print(
                        f"Step 0a-auto-route: 1:1 plan detected — "
                        + ", ".join(
                            f"{r['sheet_name']!r}→#{r['section_index']} {r['section_title']!r}"
                            for r in route_plan
                        )
                    )
                    return _preview_multi_sheet_auto_route(
                        file_content=file_content,
                        file_type=file_type,
                        target_sheet_name=target_sheet_name,
                        raw_values=raw_values,
                        target_sections=target_sections_for_route,
                        routes=route_plan,
                        formula_cols=target_schema.get('formula_cols', []) or [],
                    )

        # Aggregate path: try when 1:1 auto-route did not fit AND every
        # source sheet is plausibly stacking into the SAME target tab.
        # The frontend sends conflict_choices on the second pass once the
        # user has resolved cross-sheet conflicts. See
        # _plan_multi_sheet_aggregate / _preview_multi_sheet_aggregate.
        if len(sheets_list) >= 2 and section_index is None:
            target_sections_for_aggregate = _detect_sections_local(raw_values or [])
            aggregate_plan = _plan_multi_sheet_aggregate(
                sheets_list,
                target_sections_for_aggregate,
                target_headers_for_scoring,
            )
            if aggregate_plan:
                print(
                    f"Step 0a-aggregate: {len(aggregate_plan['aggregated_sheet_names'])} sheets "
                    f"→ single target tab/section "
                    f"(target_section_index={aggregate_plan['target_section_index']})"
                )
                return _preview_multi_sheet_aggregate(
                    inputs=inputs,
                    file_content=file_content,
                    file_type=file_type,
                    target_sheet_name=target_sheet_name,
                    raw_values=raw_values,
                    target_schema=target_schema,
                    formula_cols=target_schema.get('formula_cols', []) or [],
                    aggregated_sheet_names=aggregate_plan['aggregated_sheet_names'],
                    target_section_index=aggregate_plan['target_section_index'],
                    conflict_choices=inputs.get('conflict_choices'),
                )

            # Column-merge path: tried AFTER the aggregate path bails (so a
            # workbook with same-shape monthly tabs still goes to aggregate
            # — Jaccard >= 0.70 — and only files whose sheets DON'T form
            # a clean row-stack reach this planner). Column overlap between
            # source sheets is allowed; the preview path resolves it
            # cell-by-cell (silent merge when owners agree, conflict modal
            # when they disagree). When the target has multiple sections
            # we skip column-merge and let the picker handle it;
            # column-merge is a flat-target strategy by design.
            if not target_sections_for_aggregate or len(target_sections_for_aggregate) <= 1:
                column_merge_plan = _plan_multi_sheet_column_merge(
                    sheets_list,
                    target_headers_for_scoring,
                )
                if column_merge_plan:
                    print(
                        f"Step 0a-column-merge: {len(column_merge_plan['sheet_names'])} sheets "
                        f"→ {target_sheet_name!r} (shared anchor candidates: "
                        f"{column_merge_plan['shared_anchor_candidates']})"
                    )
                    return _preview_multi_sheet_column_merge(
                        inputs=inputs,
                        file_content=file_content,
                        file_type=file_type,
                        target_sheet_name=target_sheet_name,
                        raw_values=raw_values,
                        target_schema=target_schema,
                        formula_cols=target_schema.get('formula_cols', []) or [],
                        sheet_names=column_merge_plan['sheet_names'],
                        conflict_choices=inputs.get('conflict_choices'),
                    )

        if len(sheets_list) >= 2:
            # Pre-picker rejection guard. By the time we get here EVERY
            # multi-sheet planner has bailed. If ALSO no source sheet has
            # any target overlap beyond a date-like anchor column, the
            # picker is misleading — picking ANY sheet still produces zero
            # mapped cells. Surface a clear "wrong target tab" rejection
            # instead so the user can re-pick rather than chase an empty
            # preview. (See `_plan_multi_sheet_column_merge` docstring for
            # why anchor-only sheets are excluded silently — this guard is
            # the orchestrator-level mirror for the case where ALL sheets
            # would be excluded.)
            target_norm_for_check = {
                _norm_header(h) for h in (target_headers_for_scoring or []) if h
            }
            if target_norm_for_check:
                per_sheet_useful = []
                total_useful = 0
                for s in sheets_list:
                    sheet_hdrs = {
                        _norm_header(h) for h in (s.get('headers') or []) if h
                    }
                    on_target = sheet_hdrs & target_norm_for_check
                    non_date = {h for h in on_target if 'date' not in h}
                    per_sheet_useful.append({
                        'name':         s.get('name'),
                        'on_target':    sorted(on_target),
                        'useful_cols':  sorted(non_date),
                    })
                    total_useful += len(non_date)
                if total_useful == 0:
                    print(
                        f"   no-useful-overlap: every sheet's target overlap "
                        f"is empty or anchor-only (date-like). "
                        f"target_tab={target_sheet_name!r} "
                        f"target_cols={len(target_norm_for_check)} "
                        f"per_sheet={per_sheet_useful}"
                    )
                    return {
                        'success':        False,
                        'error_type':     'no_useful_overlap',
                        'error':          (
                            f"None of the {len(sheets_list)} source sheet(s) "
                            f"have columns matching the target tab "
                            f"'{target_sheet_name}' beyond a date column. "
                            f"Pick a target tab whose headers match your "
                            f"source data, or upload a different source file."
                        ),
                        'target_tab':     target_sheet_name,
                        'sheets_diag':    per_sheet_useful,
                    }
            picked = _auto_pick_source_sheet(sheets_list)
            if picked is not None:
                sheet_name = picked
                auto_selected_sheet = picked
                print(f"   Auto-picked source sheet '{picked}' "
                      f"(scores: {[(s.get('name'), s.get('score')) for s in sheets_list]})")
            else:
                # Last-resort picker. By the time we get here BOTH the 1:1
                # auto-route and the aggregate path returned None — log the
                # per-sheet diagnostics so future debugging can tell at a
                # glance WHY they bailed (per-sheet overlap, sheet sizes,
                # cross-sheet similarity all printed by the inner functions).
                sheet_diag = [
                    {
                        'name':   s.get('name'),
                        'score':  s.get('score'),
                        'rows':   s.get('data_rows'),
                        'mhdrs':  s.get('meaningful_headers'),
                    }
                    for s in sheets_list
                ]
                print(
                    f"   Multi-sheet detected ({len(sheets_list)}). "
                    f"Returning picker response. sheets={sheet_diag}"
                )
                return {
                    'success': True,
                    'requires_sheet_selection': True,
                    'sheets': sheets_list,
                    'message': (
                        f'Your file contains {len(sheets_list)} sheets and no single one '
                        f'dominates by header overlap. Please pick which sheet to map.'
                    ),
                }
        elif len(sheets_list) == 1:
            # Single sheet — record the name so downstream confirm calls can be
            # explicit rather than relying on the default-0 fallback.
            only = sheets_list[0].get('name')
            if only:
                sheet_name = only
                auto_selected_sheet = only
                print(f"   Single-sheet file, using '{only}'")

    # Step 0b: detect stacked sections in the source file. If 2+ are found and
    # the caller did not specify which section to write, short-circuit and ask
    # the frontend to show the section picker. When section_index is provided
    # we pass the matching section through to parse_file so the DataFrame only
    # contains that section's rows.
    selected_section = None
    if file_type and file_type.lower() in ('xlsx', 'xls', 'excel'):
        print(f"Step 0b: Detecting source sections...")
        sec_result = invoke(MAPPING_LAMBDA, {
            'tool': 'detect_source_sections',
            'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
        })
        sections = sec_result.get('sections', []) if sec_result.get('success') else []
        if len(sections) >= 2:
            if section_index is None:
                # Before bailing to the section picker, try the intra-tab
                # planners (auto-route then aggregate). Either one fires
                # silently when the layout is unambiguous AND there are no
                # cross-section anchor conflicts. The picker only appears
                # when both planners return None — which means the source
                # section structure is genuinely ambiguous and we need
                # the user to clarify.
                target_sections_for_intratab = _detect_sections_local(raw_values or [])
                # Path 1 — auto-route (1:1 source-section → target-section).
                # Fires when each source section has a dominant + unique
                # target section AND target has 2+ sections to route to.
                section_route_plan = _plan_multi_section_auto_route(
                    sections, target_sections_for_intratab,
                )
                if section_route_plan:
                    print(
                        f"Step 0b-section-auto-route: "
                        f"{len(section_route_plan)} source section(s) → "
                        f"target sections " + ", ".join(
                            f"{r['source_section_title']!r}→#{r['target_section_index']}"
                            f"({r['target_section_title']!r})"
                            for r in section_route_plan
                        )
                    )
                    # Convert the section route plan to the routes shape
                    # _preview_multi_sheet_auto_route expects (additive
                    # source_section + source_section_title fields tell
                    # the per-route block to slice the source by section).
                    routes_for_preview = []
                    for r in section_route_plan:
                        routes_for_preview.append({
                            'sheet_name':           sheet_name,
                            'source_section':       sections[r['source_section_index']],
                            'source_section_title': r['source_section_title'],
                            'section_index':        r['target_section_index'],
                            'section_title':        r['target_section_title'],
                            'overlap_score':        r['overlap_score'],
                        })
                    return _preview_multi_sheet_auto_route(
                        file_content=file_content,
                        file_type=file_type,
                        target_sheet_name=target_sheet_name,
                        raw_values=raw_values,
                        target_sections=target_sections_for_intratab,
                        routes=routes_for_preview,
                        formula_cols=target_schema.get('formula_cols', []) or [],
                    )
                # Path 2 — aggregate (N source sections → 1 target section).
                # Fires when source sections share roughly the same shape
                # and either target is single-section OR all source
                # sections funnel into the same target section. Surfaces
                # the cross-section conflict modal when an anchor value
                # appears in 2+ source sections.
                section_agg_plan = _plan_multi_section_aggregate(
                    sections, target_sections_for_intratab,
                    target_headers_for_scoring,
                )
                if section_agg_plan:
                    print(
                        f"Step 0b-section-aggregate: "
                        f"{len(section_agg_plan['aggregated_section_indices'])} sections "
                        f"→ single target section "
                        f"(target_section_index={section_agg_plan['target_section_index']})"
                    )
                    aggregated_sections_for_preview = [
                        {
                            'sheet_name':           sheet_name,
                            'section':              sections[idx],
                            'source_section_index': idx,
                            'source_section_title': sections[idx].get('title'),
                        }
                        for idx in section_agg_plan['aggregated_section_indices']
                    ]
                    return _preview_multi_sheet_aggregate(
                        inputs=inputs,
                        file_content=file_content,
                        file_type=file_type,
                        target_sheet_name=target_sheet_name,
                        raw_values=raw_values,
                        target_schema=target_schema,
                        formula_cols=target_schema.get('formula_cols', []) or [],
                        aggregated_sheet_names=[],  # unused on intra-tab path
                        target_section_index=section_agg_plan['target_section_index'],
                        conflict_choices=inputs.get('conflict_choices'),
                        aggregated_sections=aggregated_sections_for_preview,
                    )
                # Both planners declined — fall through to the section picker.
                print(f"   Multi-section detected ({len(sections)}). Returning picker response.")
                resp = {
                    'success': True,
                    'requires_section_selection': True,
                    'sections': sections,
                    'message': f'Your file contains {len(sections)} sections. Please pick one to map.',
                }
                if auto_selected_sheet:
                    resp['auto_selected_sheet'] = auto_selected_sheet
                    resp['sheet_name'] = auto_selected_sheet
                return resp
            try:
                idx = int(section_index)
                if 0 <= idx < len(sections):
                    selected_section = sections[idx]
                    print(f"   Using section #{idx}: '{selected_section.get('title')}' ({selected_section.get('row_count')} rows)")
                else:
                    return {'success': False, 'error': f'Invalid section_index {idx}; file has {len(sections)} sections'}
            except (TypeError, ValueError):
                return {'success': False, 'error': f'section_index must be an integer (got {section_index!r})'}

    print("Step 3: Parsing source file...")
    parse_inputs = {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
    if selected_section is not None:
        parse_inputs['section'] = selected_section
    parse_result = invoke(MAPPING_LAMBDA, {
        'tool': 'parse_file',
        'inputs': parse_inputs
    })
    print(f"   parse_result success: {parse_result.get('success')}")
    print(f"   parse_result error: {parse_result.get('error')}")
    if not parse_result.get('success'):
        return {'success': False, 'error': f"File parse failed: {parse_result.get('error')}"}
    print(f"   {parse_result.get('row_count')} rows parsed")

    print("Step 4: Structuring source data...")
    source_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_source_data',
        'inputs': {'parse_result': parse_result}
    })
    print(f"   source_schema success: {source_schema.get('success')}")
    print(f"   source_schema error: {source_schema.get('error')}")
    if not source_schema.get('success'):
        return {'success': False, 'error': f"Cannot structure source: {source_schema.get('error')}"}
    # Patch parse_result with the grouped-header-aware ``full_data``
    # so the anchor extraction loop below (and any downstream consumer)
    # sees rows keyed by composite header names rather than the raw
    # pandas columns. See confirm_apply for the longer explanation.
    _corrected_full_data = source_schema.get('full_data')
    if _corrected_full_data is not None:
        parse_result['full_data'] = _corrected_full_data
    print(f"   Source headers: {source_schema.get('headers', [])}")

    # Empty-target short-circuit: if the target sheet has zero headers there is
    # nothing to align against, so skip the AI call entirely and force a clean
    # append with an identity column mapping. The UI will show the source
    # columns as the ones that will be created in row 1 of the target.
    is_empty_target = bool(target_schema.get('is_empty_target'))
    if is_empty_target:
        print("Target sheet is empty — forcing append strategy with identity column mappings")
        src_headers_for_append = source_schema.get('headers', [])
        identification = {
            'success': True,
            'write_strategy': 'append',
            'anchor_column': None,
            'source_anchor': None,
            'anchor_type': '',
            'column_mappings': {h: h for h in src_headers_for_append},
            'reasoning': (
                'Target sheet is empty. Source columns will be written as headers in row 1 '
                'and all source rows appended as new data.'
            ),
        }
        # Populate target_schema so downstream diff generation treats the
        # source headers as the target layout (identity mapping).
        target_schema['headers'] = list(src_headers_for_append)
        target_schema['header_index'] = {h: i for i, h in enumerate(src_headers_for_append)}
    else:
        print("Step 5: AI finding identifier...")
        # Pass the SOURCE section title (Fix N) so find_identifier's
        # multi-section pre-resolver can tie-break on title similarity
        # when the target also has multiple sections sharing a column
        # shape — e.g. picking source "Outbound Metrics" routes to
        # target "Outbound Metrics" instead of defaulting to the first
        # section. Harmless when the source has no section selected
        # (selected_section is None → arg defaults to None → legacy
        # column-overlap-only behavior).
        identification = invoke(MAPPING_LAMBDA, {
            'tool': 'find_identifier',
            'inputs': {
                'target_schema': target_schema,
                'source_schema': source_schema,
                'source_section_title': (selected_section.get('title') if selected_section else None),
            }
        })
        print(f"   identification success: {identification.get('success')}")
        print(f"   identification error: {identification.get('error')}")
        print(f"   write_strategy: {identification.get('write_strategy')}")
        print(f"   anchor_column: {identification.get('anchor_column')}")
        # Surface the AI's column mapping decisions so future debugging can
        # spot weak/wrong matches at a glance (e.g. Cases→Expected Receiving
        # Qty was a hallucination caught only after a user complaint —
        # printing the mappings here would have made it obvious in CW).
        _id_mappings = identification.get('column_mappings') or {}
        if _id_mappings:
            print(f"   column_mappings: {_id_mappings}")
        _id_reasoning = identification.get('reasoning')
        if _id_reasoning:
            print(f"   identification.reasoning: {_id_reasoning}")
        if not identification.get('success'):
            return {'success': False, 'error': f"Identifier detection failed: {identification.get('error')}"}

    # Apply strategy-specific prep (cross_tab pivot, etc.) so the diff
    # generation + rows_to_update/append split below can treat the data as
    # a flat upsert. Mutates identification + parse_result + schemas.
    _prepare_strategy_state(identification, parse_result, source_schema, target_schema)

    write_strategy  = identification.get('write_strategy')
    anchor_column   = identification.get('anchor_column')
    column_mappings = identification.get('column_mappings', {})
    # Capture the pre-resolved TARGET section index so the diff loop's
    # data_rows slice (Fix M) and the writer's row-range pin (Fix L via
    # Fix O) operate on the same section the prompt was scoped to.
    # Empty-target short-circuit above bypasses find_identifier entirely
    # so target_section_idx legitimately defaults to None there.
    target_section_idx = identification.get('target_section_index')

    # Guard: if no columns could be mapped, return a clear error.
    # Skip for strategies that legitimately don't need direct source->target
    # column mappings:
    #   - cross_tab: source values become target column positions
    #     (e.g. source Store col with values "Store A"/"Store B"/"Store C"
    #     never maps to target matrix headers of the same names).
    #   - key_value: writes into a 2-column label/value layout; the anchor
    #     carries the meaning and the value column is inferred at write time.
    #   - append: the guard is irrelevant — an anchor-less append just
    #     tacks all source rows onto the end of the sheet.
    strategy_bypasses_mapping_guard = write_strategy in ('cross_tab', 'key_value', 'append')
    mappable = [k for k, v in column_mappings.items() if v is not None]
    if not mappable and not strategy_bypasses_mapping_guard:
        return {
            'success': False,
            'error': 'No columns in your file could be matched to the target sheet. '
                     'The source columns do not correspond to any columns in the target.',
            'error_type': 'unmappable_columns',
            'source_columns': source_schema.get('headers', []),
            'target_headers': target_schema.get('headers', [])
        }

    # Build set of source anchor values so we only preview matching rows
    source_anchor_name = identification.get('source_anchor', anchor_column)
    source_anchor_names = source_anchor_name if isinstance(source_anchor_name, list) else [source_anchor_name] if source_anchor_name else []
    anchor_type = identification.get('anchor_type', '')
    is_date_anchor = (
        write_strategy == 'row_per_date'
        or 'date' in (anchor_type or '').lower()
        or (isinstance(anchor_column, str) and 'date' in (anchor_column or '').lower())
    )

    # --- Intra-section duplicate-anchor handling (Bug "silent overwrite").
    # Two paths interleave:
    #   (1) If the FE has already echoed back a per-anchor row pick from a
    #       previous turn's conflict modal (intra_section_choices), apply
    #       it FIRST so the duplicate-detection pass that follows runs on
    #       the post-resolution row set. This means a fully-resolved set
    #       falls through cleanly with no second prompt.
    #   (2) Detect remaining duplicates. If any anchor still has 2+ rows
    #       that disagree on at least one mapped column, return the
    #       requires_conflict_resolution shape — same envelope the cross-
    #       sheet aggregate path uses, so the existing FE ConflictModal
    #       just works (the FE only needs to round-trip choices under a
    #       new key name; cand.sheet_name is set to the row label as a
    #       back-compat shim for older bundles).
    # Strategies that bypass the column-mapping guard (cross_tab,
    # key_value, append) also bypass this — duplicates are meaningful
    # only for the row-per-anchor strategies (row_per_date, row_per_entity,
    # row_per_id, multi_section, etc.).
    #
    # Read strategy_metadata locally (preview entry point doesn't unpack
    # it the way run_dynamic_mapping does at line ~176, so referencing
    # the bare `strategy_metadata` name here would be a NameError on the
    # first user-facing preview where inputs.get('intra_section_choices')
    # is None and the `or` falls through to the right operand).
    _preview_strategy_meta = inputs.get('strategy_metadata') or {}
    if isinstance(_preview_strategy_meta, str):
        try:
            _preview_strategy_meta = json.loads(_preview_strategy_meta)
        except Exception:
            _preview_strategy_meta = {}
    intra_section_choices = _normalize_intra_section_choices(
        inputs.get('intra_section_choices')
        or (_preview_strategy_meta.get('intra_section_choices')
            if isinstance(_preview_strategy_meta, dict) else None)
    )
    if intra_section_choices and not strategy_bypasses_mapping_guard:
        full_data_in = parse_result.get('full_data') or []
        if isinstance(full_data_in, str):
            try:
                full_data_in = json.loads(full_data_in)
            except Exception:
                full_data_in = []
        full_data_filtered = _apply_intra_section_choices(
            full_data_in,
            intra_section_choices,
            source_anchor_names,
            is_date_anchor,
        )
        if len(full_data_filtered) != len(full_data_in):
            print(
                f"   Applied intra_section_choices: "
                f"{len(full_data_in)} -> {len(full_data_filtered)} rows"
            )
            parse_result['full_data'] = full_data_filtered
    if not strategy_bypasses_mapping_guard:
        rows_for_dup_check = parse_result.get('full_data') or []
        if isinstance(rows_for_dup_check, str):
            try:
                rows_for_dup_check = json.loads(rows_for_dup_check)
            except Exception:
                rows_for_dup_check = []
        intra_conflicts = _detect_intra_section_anchor_conflicts(
            rows_for_dup_check,
            source_anchor_names,
            column_mappings,
            is_date_anchor,
        )
        if intra_conflicts:
            print(
                f"   Intra-section duplicate conflicts detected: "
                f"{len(intra_conflicts)} anchor(s)"
            )
            return {
                'success': True,
                'preview': True,
                'requires_conflict_resolution': True,
                'conflict_kind': 'intra_section',
                'conflicts_to_resolve': intra_conflicts,
                # aggregated_sheets is a legacy field the FE renders in
                # the modal header. Re-purposed here to display the
                # source section title so the user understands WHERE the
                # duplicates live without us renaming the field.
                'aggregated_sheets': [
                    (selected_section.get('title')
                     if selected_section
                     else (sheet_name if isinstance(sheet_name, str) else 'this section'))
                ],
                'message': (
                    f'Found {len(intra_conflicts)} identifier(s) appearing in '
                    f'multiple rows of the same section with different column '
                    f'values. Pick which row wins for each one.'
                ),
                'write_strategy':  write_strategy,
                'anchor_column':   anchor_column,
                'column_mappings': column_mappings,
            }

    source_anchor_values = set()
    # Index source rows by their anchor key so the preview can emit a
    # current -> new diff for every cell that will change.
    # Keyed by the same normalization used below in the target-walk comparison
    # (lowercased for non-date anchors) so lookups align.
    source_row_by_anchor = {}
    full_data = []
    try:
        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
        for src_row in full_data:
            parts = []
            for sa in source_anchor_names:
                val = src_row.get(sa)
                if val is not None:
                    normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                    if normed:
                        parts.append(normed)
            if parts:
                anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
                source_anchor_values.add(anchor_val)
                lookup_key = anchor_val if is_date_anchor else anchor_val.lower()
                source_row_by_anchor[lookup_key] = src_row
    except Exception as e:
        print(f"   Warning: could not extract source anchors: {e}")

    print(f"   Source anchor values ({len(source_anchor_values)}): {source_anchor_values}")
    print(f"   is_date_anchor: {is_date_anchor}")

    # Step 0c: target-tab anchor-overlap picker (Option D).
    # Scan every tab in the target spreadsheet for matching anchor values
    # so the user can be informed when their data could plausibly belong to
    # 2+ tabs. Strictly behind ENABLE_TARGET_TAB_PICKER because:
    #   - it costs one read_sheet per tab (expensive on big workbooks)
    #   - the simple case (single matching tab OR user already picked) is
    #     handled identically with or without the feature
    # Skipped entirely when:
    #   - the user already echoed back a target_tab_chosen (avoids loops)
    #   - the strategy is non-row-based (matrix / label-value layouts don't
    #     line up cleanly with a per-tab anchor concept)
    #   - no anchor or no source anchor values were derived
    target_tab_chosen = inputs.get('target_tab_chosen')
    enable_tab_picker = (
        os.environ.get('ENABLE_TARGET_TAB_PICKER', '').lower() in ('1', 'true', 'yes')
    )
    if (
        enable_tab_picker
        and not target_tab_chosen
        and write_strategy in ('row_per_date', 'row_per_entity', 'composite_key')
        and isinstance(anchor_column, str) and anchor_column
        and source_anchor_values
    ):
        try:
            print("Step 0c: Detecting target-tab anchor overlap...")
            meta = invoke(SHEETS_LAMBDA, {
                'tool': 'get_sheet_metadata',
                'inputs': {'sheet_id': sheet_id},
                'credentials_dict': credentials,
            })
            tab_metas = meta.get('sheets', []) if meta.get('success') else []
            # Cap at 12 tabs; reading more is expensive and the picker UI
            # would be unwieldy beyond that anyway.
            tab_metas = tab_metas[:12]

            tabs_for_overlap = []
            for tm in tab_metas:
                tab_title = tm.get('title') or ''
                if not tab_title:
                    continue
                rname = f"'{tab_title}'" if ' ' in tab_title else tab_title
                tab_read = invoke(SHEETS_LAMBDA, {
                    'tool': 'read_sheet',
                    'inputs': {'sheet_id': sheet_id, 'range_name': rname},
                    'credentials_dict': credentials,
                })
                if not tab_read.get('success'):
                    continue
                rv = tab_read.get('data', tab_read.get('values', [])) or []
                if not rv:
                    continue
                tabs_for_overlap.append({
                    'name': tab_title,
                    'raw_values': rv,
                    'header_row_count': 1,
                })

            if len(tabs_for_overlap) >= 2:
                overlap_result = invoke(MAPPING_LAMBDA, {
                    'tool': 'detect_target_tab_overlap',
                    'inputs': {
                        'tabs': tabs_for_overlap,
                        'anchor_target_col': anchor_column,
                        'source_anchor_values': sorted(source_anchor_values),
                        'sample_limit': 5,
                    }
                })
                if overlap_result.get('success'):
                    overlap_tabs = overlap_result.get('tabs', []) or []
                    positive = [t for t in overlap_tabs if (t.get('overlap_count') or 0) > 0]
                    print(
                        f"   Tab overlap (anchor='{anchor_column}'): "
                        + ', '.join(f"{t['name']}={t['overlap_count']}" for t in overlap_tabs)
                    )
                    if len(positive) >= 2:
                        picked_tab = _auto_pick_target_tab(overlap_tabs, target_sheet_name)
                        if picked_tab is None:
                            return {
                                'success': True,
                                'requires_target_tab_selection': True,
                                'target_tabs': [
                                    {
                                        'name': t.get('name'),
                                        'overlap_count': t.get('overlap_count') or 0,
                                        'sample_overlap_values': t.get('sample_overlap_values') or [],
                                        'anchor_column_resolved': t.get('anchor_column_resolved'),
                                        'is_current_choice': t.get('name') == target_sheet_name,
                                    }
                                    for t in positive
                                ],
                                'anchor_column': anchor_column,
                                'message': (
                                    f"Found {len(positive)} target tabs with rows that match "
                                    f"your source's '{anchor_column}' values. "
                                    f"Pick which tab to write to."
                                ),
                            }
        except Exception as _tab_err:
            # Picker is informational. Any failure here should NOT block
            # the preview — fall through to the normal write path.
            print(f"   Step 0c skipped: {_tab_err}")

    # Remove anchor column(s) and formula columns from mappings
    formula_cols = target_schema.get('formula_cols', [])
    formula_col_set = set(formula_cols)
    anchor_col_set = set(anchor_column) if isinstance(anchor_column, list) else {anchor_column} if anchor_column else set()
    write_mappings = {k: v for k, v in column_mappings.items()
                      if v and v not in anchor_col_set and v not in formula_col_set}

    conflicts    = []
    empty_cells  = []
    # Reverse map target column -> source column so we can pull the new value
    # for each (anchor, target column) pair when enriching the diff.
    target_to_source = {tgt: src for src, tgt in write_mappings.items()}
    target_cols_to_write = list(write_mappings.values())
    header_index = target_schema.get('header_index', {})
    raw_rows     = target_schema.get('raw_rows', [])

    # Section row-range pin (Fix M companion to Fix L's writer-side pin):
    # When find_identifier's multi-section pre-resolver picked a non-first
    # target section (target_section_idx is not None), restrict the diff
    # loop's data_rows to just that section's row range. Without this the
    # diff loop scans the WHOLE tab and emits a duplicate OVERWRITE entry
    # for every section that happens to share the anchor value (the bug:
    # Inbound row 7 + Outbound row 13 both had date 2025-05-01 → 2 entries
    # in the preview, then the writer silently picked the LATER one and
    # corrupted Outbound's columns by treating Dispatched/Cases as Trucks/
    # Pallets positionally). Section_data slice uses the section's
    # 0-indexed [data_start, data_end) range so the loop sees exactly the
    # rows the writer is going to touch, keeping preview and write in sync.
    diff_data_rows = raw_rows[1:] if raw_rows else []
    target_sections_for_diff = target_schema.get('sections', []) or []
    if (
        target_section_idx is not None
        and target_sections_for_diff
        and 0 <= target_section_idx < len(target_sections_for_diff)
    ):
        sec_for_diff = target_sections_for_diff[target_section_idx]
        diff_start = sec_for_diff.get('data_start')
        diff_end = sec_for_diff.get('data_end')
        if (
            isinstance(diff_start, int) and isinstance(diff_end, int)
            and 0 <= diff_start <= diff_end <= len(raw_rows)
        ):
            diff_data_rows = raw_rows[diff_start:diff_end]
            print(
                f"   Diff section pin: target section #{target_section_idx} "
                f"'{sec_for_diff.get('title')}' → "
                f"raw_rows[{diff_start}:{diff_end}] "
                f"({len(diff_data_rows)} row(s))"
            )
    data_rows = diff_data_rows

    # Diff payload cap: count every cell that would appear in the diff, but stop
    # emitting once we hit MAX_DIFF_CELLS so the response stays small.
    diff_total_cells = 0
    diff_truncated = False

    if write_strategy in ('row_per_date', 'row_per_entity', 'composite_key',
                          'multi_section', 'cross_tab', 'horizontal',
                          'key_value') and anchor_column:
        anchor_cols = anchor_column if isinstance(anchor_column, list) else [anchor_column]
        anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

        # Pre-compute the normalized source anchor set once so the per-row loop
        # doesn't rebuild it on every iteration. When the source has no rows at
        # all we bail out entirely instead of flagging every target cell as an
        # "overwrite with (empty)" (the Append.xlsx bug).
        src_check = {(v if is_date_anchor else v.lower()) for v in source_anchor_values}
        if not src_check:
            print("   Source has zero anchor values — skipping conflict/empty-cell diff generation")
            data_rows = []

        for row in data_rows:
            parts = []
            for ai in anchor_idxs:
                val = row[ai] if ai is not None and ai < len(row) else None
                if val:
                    normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                    parts.append(normed)
            anchor_val = '|'.join(parts) if len(parts) > 1 else (parts[0] if parts else None)
            if not anchor_val:
                continue
            check = anchor_val if is_date_anchor else anchor_val.lower()
            if check not in src_check:
                continue
            # Look up the matching source row for this anchor (case-insensitive
            # for non-date anchors, raw for date anchors — mirrors the set
            # comparison a few lines above).
            lookup_key = anchor_val if is_date_anchor else anchor_val.lower()
            src_row = source_row_by_anchor.get(lookup_key, {})

            for col_name in target_cols_to_write:
                col_idx = header_index.get(col_name)
                if col_idx is None:
                    continue
                existing = row[col_idx] if col_idx < len(row) else None
                existing_str = str(existing).strip() if existing is not None else ''
                # Skip formula cells entirely (they compute their own value)
                if existing_str.startswith('='):
                    continue

                source_col = target_to_source.get(col_name)
                new_raw = src_row.get(source_col) if source_col else None
                new_value = _format_cell_value(new_raw)

                # Skip empty source cells entirely. A blank source cell must
                # never overwrite an existing target value (OVERWRITE with
                # "(empty)") and never emit a noisy FILL-with-empty entry
                # either. This mirrors the write-side filter below and
                # matches the universal "partial update" convention — the
                # TC-D10 bug where target 99 got blanked out by a missing
                # source cell was caused by this branch firing
                # unconditionally.
                if new_value == '' or new_raw is None:
                    continue

                diff_total_cells += 1
                if diff_total_cells > MAX_DIFF_CELLS:
                    diff_truncated = True
                    continue

                if existing_str:
                    conflicts.append({
                        'anchor_value': str(anchor_val),
                        'column': col_name,
                        'existing_value': existing_str,
                        'new_value': new_value,
                    })
                else:
                    empty_cells.append({
                        'anchor_value': str(anchor_val),
                        'column': col_name,
                        'new_value': new_value,
                    })

    print(f"   Conflicts found: {len(conflicts)}")
    print(f"   Empty cells found: {len(empty_cells)}")

    # Upsert split: determine which source rows will update vs append
    target_anchor_set = set()
    if write_strategy in ('row_per_date', 'row_per_entity', 'composite_key',
                          'multi_section', 'cross_tab', 'horizontal',
                          'key_value') and anchor_column:
        anchor_cols = anchor_column if isinstance(anchor_column, list) else [anchor_column]
        for row in data_rows:
            parts = []
            for ac in anchor_cols:
                ai = header_index.get(ac)
                val = row[ai] if ai is not None and ai < len(row) else None
                if val:
                    parts.append(_normalize_date_value(val) if is_date_anchor else str(val).strip().lower())
            if parts:
                target_anchor_set.add('|'.join(parts) if len(parts) > 1 else parts[0])

    rows_to_update = []
    rows_to_append = []
    source_total_rows = source_schema.get('total_rows', 0)

    if write_strategy == 'append' or not anchor_column:
        # 'append' has no meaningful anchor comparison — every source row will be
        # appended. Report a truthful count instead of the misleading 0/0 that
        # the anchor-based split produces (source_anchor_values is empty here).
        # Use row-index placeholders so any UI that iterates rows_to_append as a
        # list still gets the right length.
        rows_to_append = [f"row_{i + 1}" for i in range(source_total_rows)]
        print(
            f"   Append strategy: {source_total_rows} source row(s) will be appended "
            f"(upsert split not applicable — no anchor)"
        )
    else:
        for v in sorted(source_anchor_values):
            check = v if is_date_anchor else v.lower()
            if check in target_anchor_set:
                rows_to_update.append(v)
            else:
                rows_to_append.append(v)
        print(f"   Upsert split: {len(rows_to_update)} to update, {len(rows_to_append)} to append")

    rows_to_update_count = len(rows_to_update)
    rows_to_append_count = len(rows_to_append)

    # Build a preview of whole new rows that will be appended. For anchor-based
    # strategies we key by the source anchor value; for pure append (null
    # anchor) we fall back to positional row_N placeholders that match the keys
    # already emitted in rows_to_append above. Respects the same MAX_DIFF_CELLS
    # cap as conflicts/empty_cells — diff_total_cells keeps counting past the
    # cap so the UI can show "N more not shown".
    #
    # The anchor column (e.g. Date) is intentionally stripped from
    # ``write_mappings`` above because it drives row identity rather than
    # being a "cell update". BUT for the preview we still want the user to
    # SEE the Date value on every new row — otherwise the panel looks like
    # the date is being dropped entirely (TC-L08 bug: preview showed
    # Trucks/Pallets with no Date label anywhere visible). So we prepend a
    # synthetic anchor cell whose column name is the anchor column(s) and
    # whose value is the row's anchor_value. See ``_preview_anchor_cells``.
    appended_rows_preview = []
    if write_strategy == 'append' or not anchor_column:
        for i, src_row in enumerate(full_data or []):
            cells = list(_preview_anchor_cells(
                anchor_col_set, source_anchor_names, src_row,
                f"row_{i + 1}", is_date_anchor,
            ))
            for tgt_col in target_cols_to_write:
                src_col = target_to_source.get(tgt_col)
                if not src_col:
                    continue
                new_value = _format_cell_value(src_row.get(src_col))
                diff_total_cells += 1
                if diff_total_cells > MAX_DIFF_CELLS:
                    diff_truncated = True
                    continue
                cells.append({'column': tgt_col, 'new_value': new_value})
            if cells:
                appended_rows_preview.append({
                    'anchor_value': f"row_{i + 1}",
                    'cells': cells,
                })
    else:
        for anchor_val in rows_to_append:
            lookup_key = anchor_val if is_date_anchor else anchor_val.lower()
            src_row = source_row_by_anchor.get(lookup_key)
            if not src_row:
                continue
            cells = list(_preview_anchor_cells(
                anchor_col_set, source_anchor_names, src_row,
                str(anchor_val), is_date_anchor,
            ))
            for tgt_col in target_cols_to_write:
                src_col = target_to_source.get(tgt_col)
                if not src_col:
                    continue
                new_value = _format_cell_value(src_row.get(src_col))
                diff_total_cells += 1
                if diff_total_cells > MAX_DIFF_CELLS:
                    diff_truncated = True
                    continue
                cells.append({'column': tgt_col, 'new_value': new_value})
            if cells:
                appended_rows_preview.append({
                    'anchor_value': str(anchor_val),
                    'cells': cells,
                })

    print(
        f"   Diff preview: {len(conflicts)} overwrites + {len(empty_cells)} fills + "
        f"{len(appended_rows_preview)} new rows "
        f"(total cells: {diff_total_cells}, truncated: {diff_truncated})"
    )

    return {
        'success':          True,
        'preview':          True,
        'write_strategy':   write_strategy,
        'anchor_column':    anchor_column,
        'source_anchor':    identification.get('source_anchor'),
        'anchor_type':      identification.get('anchor_type'),
        'reasoning':        identification.get('reasoning'),
        'source_columns':   source_schema.get('headers', []),
        'target_headers':   target_schema.get('headers', []),
        'column_mappings':  write_mappings,
        'unmapped_source':  [k for k, v in column_mappings.items() if not v],
        'rows_in_source':   source_schema.get('total_rows', 0),
        'rows_in_target':   target_schema.get('total_rows', 0),
        'source_col_types': source_schema.get('col_types', {}),
        'target_col_types': target_schema.get('col_types', {}),
        'formula_cols':     formula_cols,
        'conflicts':        conflicts,
        'empty_cells':      empty_cells,
        'appended_rows_preview': appended_rows_preview,
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   rows_to_update,
        'rows_to_append':   rows_to_append,
        'rows_to_update_count': rows_to_update_count,
        'rows_to_append_count': rows_to_append_count,
        'is_empty_target':  is_empty_target,
        'header_row_count': target_schema.get('header_row_count', 1),
        'composite_to_col_index': target_schema.get('composite_to_col_index', {}),
        # Source-sheet selection state — echoed back on confirm so run_dynamic_mapping
        # reads from the same sheet that preview mapped against. auto_selected_sheet
        # is only set when the backend picked a sheet without user input (TC-E02
        # style "IgnoreMe" vs "RealData").
        'sheet_name':           sheet_name if isinstance(sheet_name, str) else None,
        'auto_selected_sheet':  auto_selected_sheet,
        # Per-strategy state envelope — the frontend should echo this back
        # verbatim on the confirm call so run_dynamic_mapping can reapply
        # any strategy-specific prep (pivot, section slice, etc.) without
        # re-running find_identifier. Single dict replaces the former
        # scattered per-field keys.
        'strategy_metadata': {
            'pivot_source_col': identification.get('pivot_source_col'),
            'value_source_col': identification.get('value_source_col'),
            'period_columns':   identification.get('period_columns'),
            'label_column':     identification.get('label_column'),
            'section_index':    identification.get('section_index'),
            # Pre-resolved TARGET section index from find_identifier's
            # multi-section pre-resolver (Fix E). The frontend echoes this
            # back verbatim on confirm so route_write can pin _write_multi_section
            # to the same section the preview mapped against.
            'target_section_index': identification.get('target_section_index'),
            'target_section_title': identification.get('target_section_title'),
            'anchor_columns':   anchor_column if isinstance(anchor_column, list) else None,
        },
        # Legacy top-level fields kept for one release so older frontend
        # bundles don't break. New code should read strategy_metadata.
        'pivot_source_col': identification.get('pivot_source_col'),
        'value_source_col': identification.get('value_source_col'),
    }


def fetch_tabs(inputs):
    """Return the list of sheet tabs for a given spreadsheet URL."""
    target_sheet_url = inputs['target_sheet_url']
    credentials      = inputs['credentials']

    sheet_id = extract_sheet_id(target_sheet_url)

    meta = invoke(SHEETS_LAMBDA, {
        'tool': 'get_sheet_metadata',
        'inputs': {'sheet_id': sheet_id},
        'credentials_dict': credentials
    })

    if not meta.get('success'):
        return {'success': False, 'error': f"Cannot access spreadsheet: {meta.get('error')}"}

    tabs = meta.get('sheets', [])
    spreadsheet_title = meta.get('title', '')

    gid = extract_gid(target_sheet_url)
    auto_selected = None

    if gid is not None:
        for tab in tabs:
            if tab.get('sheetId') == gid:
                auto_selected = tab['title']
                break

    if auto_selected is None and tabs:
        auto_selected = tabs[0]['title']

    return {
        'success': True,
        'spreadsheet_title': spreadsheet_title,
        'tabs': [{'title': t['title'], 'sheetId': t.get('sheetId')} for t in tabs],
        'auto_selected': auto_selected,
        'gid': gid
    }


def _classify_sheets_api_error(err_str):
    """Map a sheets-agent error string to a coarse error_type tag.

    Used by route_write to give the FE enough context to render an
    actionable message instead of the generic "Dynamic mapping failed".
    Tags mirror the common Google Sheets API failure modes.
    """
    if not err_str:
        return 'unknown'
    s = str(err_str).lower()
    if '403' in s and ('permission_denied' in s or 'caller does not have permission' in s
                       or 'permission' in s):
        return 'permission_denied'
    if '401' in s or 'unauthorized' in s or 'invalid_grant' in s or 'token' in s:
        return 'auth_expired'
    if '404' in s and ('not found' in s or 'sheet' in s):
        return 'not_found'
    if '429' in s or 'quota' in s or 'rate limit' in s or 'rate_limit' in s:
        return 'quota_exceeded'
    if '500' in s or '503' in s or 'unavailable' in s or 'timeout' in s:
        return 'service_unavailable'
    return 'api_error'


def _friendly_sheets_api_error(error_type, raw_err):
    """Translate a classified sheets-agent error into a user-actionable
    message. Falls back to the raw error string for unclassified failures.
    """
    msg_map = {
        'permission_denied': (
            "Google denied write access to this spreadsheet. "
            "Make sure (a) you are signed in with the account that owns or has "
            "edit access to the file, and (b) the destination tab is not "
            "protected (Data → Protect sheets and ranges in Google Sheets). "
            "Open the spreadsheet in your browser, try editing a cell directly — "
            "if that also fails, the share permission is the issue."
        ),
        'auth_expired': (
            "Your Google sign-in token expired or was revoked. Refresh the page "
            "(F5) and sign in again, then re-try the mapping."
        ),
        'not_found': (
            "The target spreadsheet or tab could not be found. Verify the URL "
            "is current and the tab still exists."
        ),
        'quota_exceeded': (
            "Google Sheets API quota was exceeded for this account. Wait a "
            "minute and retry, or split the upload into smaller batches."
        ),
        'service_unavailable': (
            "Google Sheets is temporarily unavailable. Retry in a moment."
        ),
    }
    return msg_map.get(error_type) or str(raw_err or 'Unknown error')


def route_write(write_strategy, anchor_column, transformed,
                target_headers, sheet_id, sheet_name, credentials,
                header_row_count=1, composite_to_col_index=None,
                target_section_index=None,
                section_data_start_row=None,
                section_data_end_row=None):
    """
    section_data_start_row / section_data_end_row (Fix O for cross-section
        anchor collision): 1-indexed sheet-row bounds of the chosen target
        section's DATA rows (inclusive). When provided, forwarded to the
        sheets-agent's update_rows_by_date / update_rows_by_anchor as
        ``data_start_row`` / ``data_end_row`` so the writer's lookup map
        only sees rows within that section. ``None`` on either bound
        preserves the legacy whole-tab behavior — single-section targets
        and pre-Fix-N callers are unaffected. The caller (run path)
        resolves these from ``target_schema['sections'][target_section_index]``
        with a fallback re-read on the cached confirm path.
    """

    safe_name = f"'{sheet_name}'" if ' ' in sheet_name and not sheet_name.startswith("'") else sheet_name
    header_row = max(header_row_count - 1, 0)

    # For grouped headers, remap composite "Group > Sub" keys to just "Sub"
    # so the values written to the sheet line up with the FLAT header row that
    # the sheets-agent reads (the sheets-agent only ever sees one header row,
    # not the grouped 2-row structure). The same prefix stripping must also be
    # applied to anchor_column when we hand it off to the sheets-agent — see
    # `anchor_column_for_write` below — otherwise the agent searches for
    # "Group > Anchor" against flat headers ["Anchor", ...] and fails with
    # either "Date column not found" or a silent 0-matched/0-unmatched result
    # that triggers the append-all fallback (which then writes empty rows).
    is_grouped_target = bool(header_row_count > 1 and composite_to_col_index)

    def _strip_group_prefix(name):
        """For grouped targets only, strip 'Group > ' so the flat sheet matches.
        No-op when no ' > ' is present or when the target is not grouped."""
        if not is_grouped_target or not isinstance(name, str):
            return name
        return name.split(' > ', 1)[1] if ' > ' in name else name

    if is_grouped_target:
        for row in transformed:
            remapped = {}
            for k, v in list(row.items()):
                if k == '_anchor_value':
                    remapped[k] = v
                elif ' > ' in k:
                    remapped[k.split(' > ', 1)[1]] = v
                else:
                    remapped[k] = v
            row.clear()
            row.update(remapped)

    # Flat-name version of anchor_column for sheets-agent calls (string OR
    # list-of-strings). The original `anchor_column` is preserved in the
    # response payload for diagnostics / FE display.
    if isinstance(anchor_column, list):
        anchor_column_for_write = [_strip_group_prefix(a) for a in anchor_column]
    else:
        anchor_column_for_write = _strip_group_prefix(anchor_column)

    if write_strategy in ('row_per_date', 'row_per_entity', 'composite_key'):
        rows_for_update = []
        anchor_to_row_data = {}
        is_composite = isinstance(anchor_column, list)
        # `anchor_cols` carries the FLAT names for sheets-agent dispatch; the
        # original composite names live on `anchor_column` for the response.
        anchor_cols = anchor_column_for_write if is_composite else [anchor_column_for_write]

        for row in transformed:
            anchor_val = row.pop('_anchor_value', None)

            if write_strategy == 'row_per_date' and not is_composite:
                entry = {
                    'date': anchor_val,
                    'date_formatted': anchor_val,
                    'row_data': row
                }
            else:
                entry = dict(row)
                if is_composite and isinstance(anchor_val, str) and '|' in anchor_val:
                    parts = anchor_val.split('|')
                    for col, part in zip(anchor_cols, parts):
                        entry[col] = part.strip()
                else:
                    entry[anchor_cols[0]] = anchor_val

            rows_for_update.append(entry)
            if anchor_val:
                anchor_to_row_data[str(anchor_val)] = row

        # The sheets agent returns unmatched date/anchor keys normalized
        # (update_rows_by_date normalizes via parse_date_flexible → YYYY-MM-DD;
        # update_rows_by_anchor preserves display case but compares lowercased).
        # `anchor_to_row_data` is keyed by the pre-normalization `_anchor_value`
        # which may differ by case or date format. Build a lookup index keyed by
        # the same normalized form used by the sheets agent so that the
        # append-side row_data lookup actually resolves and we don't append
        # rows that contain only the anchor value (TC-10 / TC-12 regression).
        normalized_anchor_to_row_data = {}
        for k, v in anchor_to_row_data.items():
            if write_strategy == 'row_per_date' and not is_composite:
                nk = _normalize_date_value(k) or k
            else:
                nk = k
            normalized_anchor_to_row_data[str(nk)] = v
            normalized_anchor_to_row_data[str(k).strip().lower()] = v

        print(f"   Rows prepared for write: {len(rows_for_update)}")

        # Section row-range pin (Fix O): forward the chosen target
        # section's [start..end] sheet-row bounds so update_rows_by_date /
        # update_rows_by_anchor only consider rows within that section.
        # Both keys default to None (omitted from inputs) when no section
        # was chosen, preserving the legacy whole-tab behavior.
        section_inputs = {}
        if section_data_start_row is not None:
            section_inputs['data_start_row'] = section_data_start_row
        if section_data_end_row is not None:
            section_inputs['data_end_row'] = section_data_end_row

        if write_strategy == 'row_per_date' and not is_composite:
            update_result = invoke(SHEETS_LAMBDA, {
                'tool': 'update_rows_by_date',
                'inputs': {
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_name,
                    'date_column_name': anchor_column_for_write,
                    'rows_with_dates': rows_for_update,
                    'header_row': header_row,
                    **section_inputs,
                },
                'credentials_dict': credentials
            })
            unmatched = update_result.get('unmatched_dates', [])
        else:
            update_result = invoke(SHEETS_LAMBDA, {
                'tool': 'update_rows_by_anchor',
                'inputs': {
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_name,
                    'anchor_column': anchor_column_for_write,
                    'rows': rows_for_update,
                    'header_row': header_row,
                    **section_inputs,
                },
                'credentials_dict': credentials
            })
            unmatched = update_result.get('unmatched_anchors', [])

        # Hard-fail short-circuit: if the sheets-agent returned an explicit
        # error (e.g. Google API 403 PERMISSION_DENIED, 401 invalid token,
        # 404 sheet not found, quota exhaustion, network timeout), DO NOT
        # silently fall through to the append fallback — that fallback was
        # designed for the "target has rows but none matched our anchors"
        # case, NOT for "the API call itself blew up". Falling through here
        # used to mask the real error behind a generic "Dynamic mapping
        # failed" because the append call would also fail with the same
        # underlying error, returning 0 rows_appended with no signal of why.
        # Surface the underlying error so the user can act on it (refresh
        # token / fix sheet permissions / retry).
        update_failed = (
            update_result.get('success') is False
            and bool(update_result.get('error'))
        )
        if update_failed:
            err = update_result.get('error')
            err_type = _classify_sheets_api_error(err)
            friendly = _friendly_sheets_api_error(err_type, err)
            print(f"   Update tool hard-failed ({err_type}): {err}")
            return {
                'success': False,
                'error': friendly,
                'error_type': err_type,
                'rows_updated': 0,
                'rows_appended': 0,
                'cells_updated': 0,
                'underlying_error': str(err),
            }

        # Fallback for the header-only / empty-data-rows case: if the sheets
        # agent reported zero updates AND zero unmatched but we actually
        # have source rows to write, none of those source rows had any
        # corresponding target row to update. Treat every source anchor as
        # unmatched so the append branch below still seeds new rows instead
        # of silently no-op'ing (was a hidden "Dynamic mapping failed").
        if (
            rows_for_update
            and not unmatched
            and update_result.get('rows_updated', 0) == 0
        ):
            print(
                "   Update tool returned 0 matched + 0 unmatched — target has "
                "no data rows to match against. Falling back to append-all."
            )
            synthesized = []
            seen = set()
            for entry in rows_for_update:
                if write_strategy == 'row_per_date' and not is_composite:
                    raw_key = entry.get('date') or entry.get('date_formatted')
                else:
                    if is_composite:
                        raw_key = '|'.join(
                            str(entry.get(col, '')).strip() for col in anchor_cols
                        )
                    else:
                        raw_key = entry.get(anchor_cols[0])
                if raw_key is None or raw_key == '':
                    continue
                key_str = str(raw_key)
                if key_str in seen:
                    continue
                seen.add(key_str)
                synthesized.append(key_str)
            unmatched = synthesized
            print(f"   Synthesized {len(unmatched)} unmatched keys for append fallback")

        rows_appended = 0
        if unmatched:
            print(f"   Upsert: {len(unmatched)} unmatched rows to append")
            # For grouped (2+ row) targets the actual flat header row lives at
            # row `header_row_count` (1-indexed), NOT row 1 — row 1 is the
            # banner. Without this offset the append fallback reads
            # ['Inbound Metrics'] (a single banner cell) as headers, fails to
            # locate the anchor + value columns, and silently appends rows of
            # blanks (Sheets API then reports `updatedRows: 0`).
            header_range_row = max(header_row_count, 1)
            header_read = invoke(SHEETS_LAMBDA, {
                'tool': 'read_sheet',
                'inputs': {
                    'sheet_id': sheet_id,
                    'range_name': f"{safe_name}!{header_range_row}:{header_range_row}",
                },
                'credentials_dict': credentials
            })
            sheet_headers = header_read.get('data', [[]])[0] if header_read.get('success') else []

            if sheet_headers:
                header_lower = {}
                for i, h in enumerate(sheet_headers):
                    header_lower[' '.join(h.strip().replace('\n', ' ').split()).lower()] = i

                append_rows_data = []
                for ukey in unmatched:
                    # Resolve the matching source row_data by trying several
                    # forms the orchestrator / sheets-agent may have used:
                    #  1. exact ukey  (identity)
                    #  2. date-normalized ukey  (for row_per_date)
                    #  3. lowercased ukey  (for row_per_entity / composite_key)
                    raw_key = str(ukey)
                    norm_date = _normalize_date_value(raw_key) or raw_key
                    row_data = (
                        anchor_to_row_data.get(raw_key)
                        or normalized_anchor_to_row_data.get(raw_key)
                        or normalized_anchor_to_row_data.get(norm_date)
                        or normalized_anchor_to_row_data.get(raw_key.strip().lower())
                        or {}
                    )
                    full_row = [''] * len(sheet_headers)
                    if is_composite and isinstance(ukey, str) and '|' in ukey:
                        parts = ukey.split('|')
                        for col, part in zip(anchor_cols, parts):
                            idx = header_lower.get(' '.join(col.strip().split()).lower())
                            if idx is not None:
                                full_row[idx] = part.strip()
                    else:
                        anchor_idx = header_lower.get(' '.join(anchor_cols[0].strip().split()).lower())
                        if anchor_idx is not None:
                            full_row[anchor_idx] = ukey
                    for col_name, value in row_data.items():
                        cn = ' '.join(col_name.strip().split()).lower()
                        idx = header_lower.get(cn)
                        if idx is not None:
                            full_row[idx] = value if value is not None else ''
                    append_rows_data.append(full_row)

                if append_rows_data:
                    append_result = invoke(SHEETS_LAMBDA, {
                        'tool': 'append_rows',
                        'inputs': {
                            'sheet_id': sheet_id,
                            'sheet_name': sheet_name,
                            'rows': append_rows_data
                        },
                        'credentials_dict': credentials
                    })
                    rows_appended = append_result.get('rows_appended', 0)
                    print(f"   Appended {rows_appended} new rows")
                    # Same hard-fail propagation for append: if the underlying
                    # call exploded (typically the same 403 / 401 / quota issue
                    # that hit the update path), surface that error instead of
                    # returning a misleading "success=False, rows_appended=0".
                    if append_result.get('success') is False and append_result.get('error'):
                        append_err = append_result.get('error')
                        append_err_type = _classify_sheets_api_error(append_err)
                        append_friendly = _friendly_sheets_api_error(append_err_type, append_err)
                        print(f"   Append tool hard-failed ({append_err_type}): {append_err}")
                        return {
                            'success': False,
                            'error': append_friendly,
                            'error_type': append_err_type,
                            'rows_updated': update_result.get('rows_updated', 0),
                            'rows_appended': 0,
                            'cells_updated': update_result.get('cells_updated', 0),
                            'underlying_error': str(append_err),
                        }

        return {
            'success': update_result.get('success', False) or rows_appended > 0,
            'rows_updated': update_result.get('rows_updated', 0),
            'cells_updated': update_result.get('cells_updated', 0),
            'rows_appended': rows_appended,
        }

    elif write_strategy == 'horizontal':
        # Read target sheet to get row entity positions for matching
        sheet_read = invoke(SHEETS_LAMBDA, {
            'tool': 'read_sheet',
            'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
            'credentials_dict': credentials
        })
        if not sheet_read.get('success'):
            return sheet_read

        raw_values = sheet_read.get('data', [])
        hr = header_row if header_row < len(raw_values) else 0
        if len(raw_values) < hr + 2:
            return {'success': False, 'error': 'Sheet has no data rows for horizontal write'}

        sheet_headers = raw_values[hr]
        data_rows = raw_values[hr + 1:]

        header_lower = {}
        for i, h in enumerate(sheet_headers):
            header_lower[' '.join(h.strip().replace('\n', ' ').split()).lower()] = i

        # Detect entity column: first non-numeric column in headers (usually col 0)
        entity_col_idx = 0
        entity_col_name = sheet_headers[0] if sheet_headers else ''
        # Use the FLAT-name version of anchor for header lookup — for grouped
        # targets, the composite "Group > Sub" name will not match the
        # single-row sheet headers.
        if anchor_column_for_write:
            ac = (
                anchor_column_for_write
                if isinstance(anchor_column_for_write, str)
                else anchor_column_for_write[0]
            )
            idx = header_lower.get(' '.join(ac.strip().split()).lower())
            if idx is not None:
                entity_col_idx = idx
                entity_col_name = ac

        # Build entity → sheet row map
        entity_to_row = {}
        for row_idx, row in enumerate(data_rows):
            if entity_col_idx < len(row) and row[entity_col_idx]:
                entity_to_row[str(row[entity_col_idx]).strip().lower()] = row_idx + hr + 2

        updates = []
        matched = []
        append_entities = {}

        for row in transformed:
            # Keep the anchor value before popping — if transform_data
            # stripped the anchor column (it isn't in column_mappings when
            # every non-anchor col maps 1:1 to target period cols), this
            # is the only place the row entity ("Revenue", "Profit", …)
            # still survives.
            anchor_val = row.pop('_anchor_value', None)

            # Find entity value for this row
            entity_val = None
            entity_key = None
            for k, v in row.items():
                ki = header_lower.get(' '.join(k.strip().split()).lower())
                if ki == entity_col_idx:
                    entity_val = v
                    entity_key = k
                    break
            if not entity_val and anchor_val:
                entity_val = anchor_val
            if not entity_val:
                continue

            sheet_row = entity_to_row.get(str(entity_val).strip().lower())
            if sheet_row is not None:
                matched.append(str(entity_val))
                for col_name, value in row.items():
                    if col_name == entity_key:
                        continue
                    cn = ' '.join(col_name.strip().split()).lower()
                    col_idx = header_lower.get(cn)
                    if col_idx is not None and value is not None:
                        cl = _col_index_to_letter(col_idx)
                        updates.append({
                            'range': f"{safe_name}!{cl}{sheet_row}",
                            'values': [[value]]
                        })
            else:
                full_row = [''] * len(sheet_headers)
                full_row[entity_col_idx] = entity_val
                for col_name, value in row.items():
                    if col_name == entity_key:
                        continue
                    cn = ' '.join(col_name.strip().split()).lower()
                    ci = header_lower.get(cn)
                    if ci is not None:
                        full_row[ci] = value if value is not None else ''
                append_entities[str(entity_val)] = full_row

        cells_updated = 0
        write_error = None
        if updates:
            print(f"   Horizontal: batching {len(updates)} cell updates for {len(matched)} rows")
            batch_result = invoke(SHEETS_LAMBDA, {
                'tool': 'batch_update_cells',
                'inputs': {
                    'sheet_id': sheet_id,
                    'updates': updates,
                },
                'credentials_dict': credentials
            })
            if batch_result.get('success'):
                cells_updated = batch_result.get('cells_updated', 0)
            else:
                write_error = batch_result.get('error') or 'batch_update_cells failed'
                print(f"   Horizontal batch update failed: {write_error}")

        rows_appended = 0
        if append_entities:
            ar = invoke(SHEETS_LAMBDA, {
                'tool': 'append_rows',
                'inputs': {
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_name,
                    'rows': list(append_entities.values())
                },
                'credentials_dict': credentials
            })
            if ar.get('success'):
                rows_appended = ar.get('rows_appended', 0)
            else:
                write_error = write_error or ar.get('error') or 'append_rows failed'

        success = len(matched) > 0 or rows_appended > 0 or (cells_updated > 0 and not write_error)
        result = {
            'success': success,
            'rows_updated': len(matched),
            'cells_updated': cells_updated,
            'rows_appended': rows_appended,
        }
        if not success and write_error:
            result['error'] = write_error
        return result

    elif write_strategy == 'multi_section':
        return _write_multi_section(anchor_column, transformed, sheet_id,
                                    sheet_name, safe_name, credentials,
                                    header_row_count, composite_to_col_index,
                                    target_section_index=target_section_index)

    elif write_strategy == 'key_value':
        return _write_key_value(anchor_column, transformed, sheet_id, sheet_name,
                                safe_name, credentials)

    elif write_strategy == 'cross_tab':
        return _write_cross_tab(anchor_column, transformed, target_headers,
                                sheet_id, sheet_name, safe_name, credentials)

    else:  # append
        return _write_append(transformed, target_headers, sheet_id, sheet_name,
                             safe_name, credentials)


def _write_append(transformed, target_headers, sheet_id, sheet_name,
                  safe_name, credentials):
    """Append rows to the target sheet.

    When the target has >=2 stacked sections, attempt to insert the rows inside
    the section whose headers best overlap the source data. If inserting would
    cross the next section's title row, fall back to appending at the sheet
    bottom (observable via `append_mode='sheet-bottom'` and `overflow_reason`
    in the return value).

    Single-section (or no detected sections) targets keep the original behavior
    of appending at the sheet end.
    """
    rows_as_lists = [
        [row.get(h, '') for h in target_headers]
        for row in transformed
    ]

    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials
    })

    sections = []
    if sheet_read.get('success'):
        sections = _detect_sections_local(sheet_read.get('data', []) or [])

    if len(sections) >= 2:
        source_cols = {_norm_header(k)
                       for row in transformed
                       for k in row.keys()
                       if k != '_anchor_value'}
        best_section, best_score = _pick_best_section(sections, source_cols)

        if best_section and best_score > 0:
            insert_row, overflow_reason = _section_insert_row(
                sections, best_section, len(rows_as_lists)
            )

            if insert_row is not None:
                print(
                    f"   Section-aware append: inserting {len(rows_as_lists)} row(s) "
                    f"into section '{best_section['title']}' "
                    f"starting at row {insert_row}"
                )
                range_updates = []
                for i, r in enumerate(rows_as_lists):
                    row_num = insert_row + i
                    end_col_letter = _col_index_to_letter(max(len(r) - 1, 0))
                    range_updates.append({
                        'range': f"{safe_name}!A{row_num}:{end_col_letter}{row_num}",
                        'values': [r],
                    })
                batch = invoke(SHEETS_LAMBDA, {
                    'tool': 'batch_update_cells',
                    'inputs': {
                        'sheet_id': sheet_id,
                        'updates': range_updates,
                    },
                    'credentials_dict': credentials
                })
                if batch.get('success'):
                    return {
                        'success': True,
                        'rows_updated': 0,
                        'rows_appended': len(rows_as_lists),
                        'cells_updated': batch.get('cells_updated', 0),
                        'append_mode': 'in-section',
                        'section': best_section['title'],
                    }
                # Fall through to sheet-bottom append on batch failure.
                print(
                    f"   Section-aware append batch failed: "
                    f"{batch.get('error') or 'unknown error'}; "
                    f"falling back to sheet-bottom append"
                )
                overflow_reason = overflow_reason or (
                    batch.get('error') or 'section batch write failed'
                )
            else:
                print(
                    f"   Section-aware append overflow: {overflow_reason}; "
                    f"appending at sheet end instead"
                )

            fallback = invoke(SHEETS_LAMBDA, {
                'tool': 'append_rows',
                'inputs': {
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_name,
                    'rows': rows_as_lists,
                },
                'credentials_dict': credentials
            })
            fallback['append_mode'] = 'sheet-bottom'
            if overflow_reason:
                fallback['overflow_reason'] = overflow_reason
            return fallback

    result = invoke(SHEETS_LAMBDA, {
        'tool': 'append_rows',
        'inputs': {
            'sheet_id': sheet_id,
            'sheet_name': sheet_name,
            'rows': rows_as_lists
        },
        'credentials_dict': credentials
    })
    if isinstance(result, dict):
        result.setdefault('append_mode', 'sheet-bottom')
    return result


def _write_key_value(anchor_column, transformed, sheet_id, sheet_name,
                     safe_name, credentials):
    """Write key-value (2-column label+value) data into the target sheet."""
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials
    })
    if not sheet_read.get('success'):
        return sheet_read

    raw_values = sheet_read.get('data', [])
    if len(raw_values) < 2:
        return {'success': False, 'error': 'Sheet has no data rows'}

    headers = raw_values[0]
    data_rows = raw_values[1:]

    label_idx = 0
    value_idx = 1
    if anchor_column:
        ac = anchor_column if isinstance(anchor_column, str) else anchor_column[0]
        for i, h in enumerate(headers):
            if ' '.join(h.strip().replace('\n', ' ').split()).lower() == ac.strip().lower():
                label_idx = i
                value_idx = i + 1 if i + 1 < len(headers) else 1
                break

    label_to_row = {}
    for row_idx, row in enumerate(data_rows):
        if label_idx < len(row) and row[label_idx]:
            label_to_row[str(row[label_idx]).strip().lower()] = row_idx + 2

    # Pre-extract anchor values and data so we can iterate cleanly
    row_entries = []
    for row in transformed:
        anchor_val = row.pop('_anchor_value', None)
        label = anchor_val
        if not label:
            label = next(iter(row.values()), None)
        value = next((v for k, v in row.items()), '')
        if label:
            row_entries.append((str(label), value))

    updates = []
    matched = []
    unmatched_entries = []

    for label, value in row_entries:
        sheet_row = label_to_row.get(label.strip().lower())
        if sheet_row is not None:
            col_letter = _col_index_to_letter(value_idx)
            updates.append({
                'range': f"{safe_name}!{col_letter}{sheet_row}",
                'values': [[value if value is not None else '']]
            })
            matched.append(label)
        else:
            unmatched_entries.append((label, value))

    if updates:
        print(f"   Key-value: updating {len(updates)} cells")
        for upd in updates:
            invoke(SHEETS_LAMBDA, {
                'tool': 'update_sheet',
                'inputs': {
                    'sheet_id': sheet_id,
                    'range_name': upd['range'],
                    'data': upd['values']
                },
                'credentials_dict': credentials
            })

    rows_appended = 0
    if unmatched_entries:
        append_data = []
        for label, value in unmatched_entries:
            new_row = [''] * len(headers)
            new_row[label_idx] = label
            new_row[value_idx] = value if value is not None else ''
            append_data.append(new_row)
        if append_data:
            ar = invoke(SHEETS_LAMBDA, {
                'tool': 'append_rows',
                'inputs': {'sheet_id': sheet_id, 'sheet_name': sheet_name, 'rows': append_data},
                'credentials_dict': credentials
            })
            rows_appended = ar.get('rows_appended', 0)
            print(f"   Key-value: appended {rows_appended} new rows")

    return {
        'success': len(matched) > 0 or rows_appended > 0,
        'rows_updated': len(matched),
        'cells_updated': len(updates),
        'rows_appended': rows_appended,
    }


def _write_cross_tab(anchor_column, transformed, target_headers,
                     sheet_id, sheet_name, safe_name, credentials):
    """Write cross-tab (matrix) data: row-header x col-header → value.
    Source may be in flat form (row_entity, col_entity, value) which needs pivoting,
    or already in wide form matching target columns."""
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials
    })
    if not sheet_read.get('success'):
        return sheet_read

    raw_values = sheet_read.get('data', [])
    if len(raw_values) < 2:
        return {'success': False, 'error': 'Sheet has no data rows'}

    headers = raw_values[0]
    data_rows = raw_values[1:]

    row_header_col = 0
    ac_name = ''
    if anchor_column:
        ac_name = anchor_column if isinstance(anchor_column, str) else anchor_column[0]
        for i, h in enumerate(headers):
            if ' '.join(h.strip().replace('\n', ' ').split()).lower() == ac_name.strip().lower():
                row_header_col = i
                break

    col_header_map = {}
    for i, h in enumerate(headers):
        if i != row_header_col:
            col_header_map[' '.join(h.strip().replace('\n', ' ').split()).lower()] = i

    # Detect whether the row axis looks date-like by sniffing target values,
    # so we can match "2025-03-01" (source normalized) against "3/1/2025"
    # (target). Do this BEFORE the entity map is built so both sides use
    # the same key.
    def _looks_like_date_str(s):
        if not s:
            return False
        s = str(s).strip()
        normed = _normalize_date_value(s)
        return bool(normed and normed != s.lower())

    is_date_row_axis = False
    if data_rows:
        sample_vals = [row[row_header_col] for row in data_rows[:5]
                       if row_header_col < len(row) and row[row_header_col]]
        if sample_vals:
            is_date_row_axis = sum(1 for v in sample_vals if _looks_like_date_str(v)) >= max(1, len(sample_vals) // 2)

    def _entity_key(v):
        if v is None:
            return ''
        s = str(v).strip()
        if is_date_row_axis:
            n = _normalize_date_value(s)
            if n:
                return n
        return s.lower()

    row_entity_map = {}
    for row_idx, row in enumerate(data_rows):
        if row_header_col < len(row) and row[row_header_col]:
            row_entity_map[_entity_key(row[row_header_col])] = row_idx + 2

    # Detect if source is flat (3 cols: row entity, col entity, value) and pivot it
    if transformed and len(transformed) > 0:
        first_keys = [k for k in transformed[0].keys() if k != '_anchor_value']
        # Flat form: typically 2-3 keys; check if values map to target column headers
        is_flat = False
        if len(first_keys) <= 3:
            # Check how many keys match target column headers
            matching_col_headers = sum(
                1 for k in first_keys
                if ' '.join(k.strip().split()).lower() in col_header_map
            )
            if matching_col_headers == 0 and len(first_keys) >= 2:
                is_flat = True

        if is_flat:
            print(f"   Cross-tab: detected flat source, pivoting to matrix form")
            pivoted = {}
            ac_lower = ac_name.strip().lower() if ac_name else ''
            for row in transformed:
                row.pop('_anchor_value', None)
                vals = list(row.values())
                if len(vals) < 2:
                    continue
                row_entity = vals[0]
                col_entity = vals[1] if len(vals) >= 3 else None
                value = vals[2] if len(vals) >= 3 else vals[1]

                re_key = str(row_entity).strip().lower()
                if re_key not in pivoted:
                    pivoted[re_key] = {'_entity': row_entity}
                if col_entity is not None:
                    pivoted[re_key][str(col_entity).strip()] = value
                else:
                    pivoted[re_key]['_value'] = value

            transformed = list(pivoted.values())

    updates = []
    matched = []
    append_entities = {}

    for row in transformed:
        anchor_val = row.pop('_anchor_value', None)
        row_entity = row.pop('_entity', None)
        if not row_entity:
            ac_lower = ac_name.strip().lower() if ac_name else ''
            for k, v in list(row.items()):
                kl = ' '.join(k.strip().split()).lower()
                if kl == ac_lower:
                    row_entity = v
                    break
        # Fallback: if the anchor column was stripped from transformed rows
        # (because it's the write anchor and therefore excluded from
        # write_mappings), recover it from the _anchor_value that route_write
        # attaches per-row.
        if not row_entity and anchor_val:
            row_entity = anchor_val
        if not row_entity:
            continue

        sheet_row = row_entity_map.get(_entity_key(row_entity))
        if sheet_row is not None:
            for col_name, value in row.items():
                cn = ' '.join(col_name.strip().split()).lower()
                col_idx = col_header_map.get(cn)
                if col_idx is not None and value is not None:
                    cl = _col_index_to_letter(col_idx)
                    updates.append({
                        'range': f"{safe_name}!{cl}{sheet_row}",
                        'values': [[value]]
                    })
            matched.append(str(row_entity))
        else:
            full_row = [''] * len(headers)
            full_row[row_header_col] = row_entity
            for col_name, value in row.items():
                cn = ' '.join(col_name.strip().split()).lower()
                col_idx = col_header_map.get(cn)
                if col_idx is not None:
                    full_row[col_idx] = value if value is not None else ''
            append_entities[str(row_entity)] = full_row

    if updates:
        print(f"   Cross-tab: updating {len(updates)} cells for {len(matched)} entities")
        for upd in updates:
            invoke(SHEETS_LAMBDA, {
                'tool': 'update_sheet',
                'inputs': {
                    'sheet_id': sheet_id,
                    'range_name': upd['range'],
                    'data': upd['values']
                },
                'credentials_dict': credentials
            })

    rows_appended = 0
    if append_entities:
        ar = invoke(SHEETS_LAMBDA, {
            'tool': 'append_rows',
            'inputs': {
                'sheet_id': sheet_id,
                'sheet_name': sheet_name,
                'rows': list(append_entities.values())
            },
            'credentials_dict': credentials
        })
        rows_appended = ar.get('rows_appended', 0)

    return {
        'success': len(matched) > 0 or rows_appended > 0,
        'rows_updated': len(matched),
        'cells_updated': len(updates),
        'rows_appended': rows_appended,
    }


def _looks_like_header_value(s):
    """Return True when ``s`` plausibly looks like a column-header label.

    Heuristic: a genuine header (e.g., "Date", "Trucks", "Pallets", "Q1 Sales")
    contains at least one alphabetic character. Pure numeric or date-formatted
    values (e.g., "2025-03-02", "424", "01/05/2025") return False. Used by
    :func:`_detect_sections_local` to reject sparse data rows that would
    otherwise be mis-classified as a new section's header row, producing
    phantom sections with garbage titles (e.g., a date as the section title)
    and date-as-header chips. See the previous-bugs notes for TC-L06 / TC-L03
    where leaky data rows like ``2025-03-01 | (blank) | (blank)`` followed
    by ``2025-03-02 | 424`` were detected as a phantom second section.
    """
    if s is None:
        return False
    s = str(s).strip()
    if not s:
        return False
    return any(c.isalpha() for c in s)


def _detect_sections_local(raw_values, min_section_rows=0):
    """Detect multiple data sections separated by blank rows or title rows.

    Mirrors mapping_agent_api._detect_sections — ``min_section_rows``
    defaults to 0 so empty template sections (title + header row + no
    data yet) still count, which matters for the "seed an empty
    multi-section OPS_DASHBOARD" workflow.

    FOLLOW-UP / DEBT:
        This function is a duplicate of mapping_agent_api._detect_sections.
        Both copies must stay in lock-step (we've already been bitten once by
        the min_section_rows=2 → 0 drift). Planned follow-up: extract into a
        shared ``common/`` module uploaded as a Lambda layer. Until then, any
        behavior change here MUST be applied to mapping_agent_api as well.
    """
    sections = []
    i = 0
    while i < len(raw_values):
        row = raw_values[i]
        non_empty = [c for c in row if c and str(c).strip()]

        if len(non_empty) == 0:
            i += 1
            continue

        if len(non_empty) == 1:
            title = str(non_empty[0]).strip()
            if i + 1 < len(raw_values):
                header_row = raw_values[i + 1]
                header_vals = [str(c).strip() for c in header_row if c and str(c).strip()]
                # Require >=2 non-empty header cells AND at least one cell
                # that looks like a real column-name label (contains
                # alphabetic chars). This rejects sparse data rows like
                # "2025-03-02, 424" that would otherwise be mis-classified
                # as a new section's header row, producing phantom sections
                # with date-shaped titles and date-as-header chips.
                if len(header_vals) >= 2 and any(_looks_like_header_value(v) for v in header_vals):
                    # Convert None cells to '' instead of the literal
                    # string "None" so the FE's filter(Boolean) chip
                    # rendering correctly hides empties and downstream
                    # header_index keys aren't polluted.
                    sec_headers = [str(c).strip() if c is not None else '' for c in header_row]
                    sec_header_index = {h: idx for idx, h in enumerate(sec_headers) if h}
                    data_start = i + 2
                    data_end = data_start
                    while data_end < len(raw_values):
                        r = raw_values[data_end]
                        ne = [c for c in r if c and str(c).strip()]
                        if len(ne) == 0:
                            break
                        if len(ne) == 1 and data_end > data_start:
                            # A single-non-empty row mid-data is only a
                            # real section break if the NEXT row contains
                            # plausible header strings (alphabetic). When
                            # the next row is also sparse / numeric-only,
                            # this is leaky data, not a section title —
                            # keep extending the current section's range.
                            next_idx = data_end + 1
                            if next_idx < len(raw_values):
                                next_row = raw_values[next_idx]
                                next_ne = [str(c).strip() for c in next_row if c and str(c).strip()]
                                if (
                                    len(next_ne) >= 2
                                    and any(_looks_like_header_value(v) for v in next_ne)
                                ):
                                    break
                            data_end += 1
                            continue
                        data_end += 1
                    if data_end - data_start >= min_section_rows:
                        sections.append({
                            'title': title,
                            'title_row': i,
                            'header_row': i + 1,
                            'data_start': data_start,
                            'data_end': data_end,
                            'headers': sec_headers,
                            'header_index': sec_header_index,
                        })
                    # Always advance past the header row so an empty
                    # section doesn't leave us stuck on it.
                    i = max(data_end, i + 2)
                    continue
        i += 1

    return sections if len(sections) >= 2 else []


def _norm_header(h):
    """Whitespace-and-case normalization used for every header-name compare in this file."""
    return ' '.join(str(h).strip().split()).lower() if h is not None else ''


def _pick_best_section(sections, source_cols_lower):
    """Pick the section whose headers overlap the source columns the most.

    source_cols_lower: an iterable of already-normalized (via _norm_header) header names.
    Returns (best_section, best_score) or (None, 0) if no overlap was found.
    """
    source_set = set(source_cols_lower)
    best_section = None
    best_score = 0
    for sec in sections:
        sec_headers_lower = {_norm_header(h) for h in sec['headers'] if h}
        overlap = len(source_set & sec_headers_lower)
        if overlap > best_score:
            best_score = overlap
            best_section = sec
    return best_section, best_score


def _section_insert_row(sections, best_section, append_len):
    """Pick a target row to insert `append_len` new rows for `best_section`.

    Returns (insert_row, overflow_reason).
      - insert_row:      1-indexed sheet row to start writing at, or None if the
                         write would cross the next section's title row.
      - overflow_reason: human-readable explanation when insert_row is None,
                         otherwise None.

    Encodes the invariant: section-aware append must NEVER write on top of the
    next section's title row or its data. On overflow the caller should fall
    back to appending at the sheet end.
    """
    insert_row = best_section['data_end'] + 1
    next_section_start = None
    for other in sections:
        if other is best_section:
            continue
        if other['title_row'] >= best_section['data_end']:
            ts = other['title_row']
            if next_section_start is None or ts < next_section_start:
                next_section_start = ts

    if next_section_start is None:
        return max(insert_row, 1), None

    insert_row = max(insert_row, 1)
    if insert_row + append_len > next_section_start:
        reason = (
            f"would collide with next section at row {next_section_start + 1} "
            f"({insert_row}+{append_len} > {next_section_start})"
        )
        return None, reason
    return insert_row, None


def _sort_key_for_anchor(value, is_date_anchor):
    """Return a sortable key for a row's anchor value.

    Date anchors are normalized to YYYY-MM-DD so string compare gives
    chronological order (2025-05-01 < 2025-06-01). Non-date anchors are
    lower-cased stripped strings so "Alpha" and "alpha" merge correctly.
    ``None`` / empty values sort AFTER everything so junk rows land at the
    bottom instead of leaking above real data.
    """
    if value is None:
        return (1, '')
    s = str(value).strip()
    if not s:
        return (1, '')
    if is_date_anchor:
        normed = _normalize_date_value(s)
        if normed:
            return (0, normed)
        return (1, s.lower())
    try:
        f = float(s.replace(',', ''))
        return (0, f"{f:020.4f}")
    except (ValueError, TypeError):
        pass
    return (0, s.lower())


def _next_section_start_row(sections, current_section):
    """Return the 0-indexed title_row of the next section below ``current_section``,
    or ``None`` if ``current_section`` is the last one.
    """
    cur_end = current_section.get('data_end', 0)
    best = None
    for other in sections:
        if other is current_section:
            continue
        other_title = other.get('title_row')
        if other_title is None:
            continue
        if other_title >= cur_end and (best is None or other_title < best):
            best = other_title
    return best


def _sort_merge_section_rows(
    section, sections, transformed_rows, raw_values, anchor_column, is_date_anchor,
    sheet_id, sheet_name, safe_name, credentials,
):
    """Merge ``transformed_rows`` into the given target section, sorted by
    ``anchor_column``. If the merged row count exceeds the section's current
    capacity, insert rows (via ``insert_rows``) to shift sections below down
    rather than falling back to sheet-bottom.

    Returns the same shape as ``_write_multi_section`` writes
    ({success, rows_updated, rows_appended, cells_updated, append_mode, …}).

    Algorithm:
      1. Read the section's existing data rows from ``raw_values``.
      2. Convert each existing row to a header→value dict, and pair with its
         anchor sort-key.
      3. For each source row, merge into an existing row (when anchors match
         — source non-empty values overwrite target) or add as a new row.
      4. Sort the merged list by anchor sort-key.
      5. If merged_count > existing_count AND the next section would be
         clobbered, call ``insert_rows`` to create the gap.
      6. Batch-write the merged rows into the section via batch_update_cells.
      7. Report rows_updated / rows_appended / cells_updated.
    """
    data_start = int(section.get('data_start', 0))
    data_end = int(section.get('data_end', data_start))
    sec_headers = list(section.get('headers') or [])
    sec_header_index = dict(section.get('header_index') or {})

    # Expand the "existing rows" window past the detector's data_end to
    # include any orphan rows that live between data_end and the next
    # section's title row. This matters when the user pre-seeds the
    # template with partially-empty placeholder dates (e.g. "2025-06-02"
    # with blank Trucks/Pallets) — _detect_sections_local stops at the
    # first such row because a single-non-empty row looks like a title
    # candidate, so a naive raw_values[data_start:data_end] read would
    # miss them and the sort-merge writer would happily clobber them.
    next_title_row = _next_section_start_row(sections, section)
    if next_title_row is not None:
        extended_end = min(next_title_row, len(raw_values))
    else:
        extended_end = len(raw_values)
    # Trim trailing fully-empty rows so we don't pad the merge with
    # junk space that would otherwise artificially block inserts.
    while extended_end > data_end:
        probe = raw_values[extended_end - 1]
        if any(c is not None and str(c).strip() != '' for c in probe):
            break
        extended_end -= 1
    extended_end = max(extended_end, data_end)

    existing_rows = [list(r) for r in (raw_values[data_start:extended_end] or [])]
    anchor_col_norm = _norm_header(anchor_column) if anchor_column else ''

    anchor_idx = None
    anchor_display_name = None
    for h, idx in sec_header_index.items():
        if _norm_header(h) == anchor_col_norm:
            anchor_idx = idx
            anchor_display_name = h
            break
    if anchor_idx is None and sec_header_index:
        anchor_display_name = next(iter(sec_header_index.keys()))
        anchor_idx = sec_header_index[anchor_display_name]

    def _existing_to_dict(row):
        d = {}
        for h, idx in sec_header_index.items():
            if idx < len(row) and row[idx] is not None:
                val = row[idx]
                if not (isinstance(val, str) and val.strip() == ''):
                    d[h] = val
        return d

    def _display_anchor(raw_val):
        """Value we actually write into the anchor cell. For date anchors
        we always canonicalize to YYYY-MM-DD so the cell shows a clean
        date instead of "2025-03-01 00:00:00" leaking back from a pandas
        Timestamp round-trip."""
        if raw_val is None:
            return ''
        if is_date_anchor:
            normed = _normalize_date_value(raw_val)
            if normed:
                return normed
        return raw_val

    merged_by_key = {}
    ordered_keys = []

    for row in existing_rows:
        row_dict = _existing_to_dict(row)
        anchor_val = row[anchor_idx] if (anchor_idx is not None and anchor_idx < len(row)) else None
        key = _sort_key_for_anchor(anchor_val, is_date_anchor)
        # Canonicalize the anchor cell so repeated writes don't oscillate
        # between "2025-03-01" and "2025-03-01 00:00:00" formats.
        if anchor_display_name and anchor_val not in (None, ''):
            row_dict[anchor_display_name] = _display_anchor(anchor_val)
        merged_by_key[key] = {
            'row':    row_dict,
            'origin': 'existing',
            'anchor': anchor_val,
        }
        ordered_keys.append(key)

    rows_updated_keys = set()
    rows_appended_keys = set()

    for src in transformed_rows:
        src_clean = {k: v for k, v in src.items() if k != '_anchor_value'}
        anchor_val = src.get('_anchor_value')
        if anchor_val is None and anchor_display_name:
            anchor_val = src_clean.get(anchor_display_name)
        key = _sort_key_for_anchor(anchor_val, is_date_anchor)

        entry = merged_by_key.get(key)
        if entry is None:
            entry = {
                'row':    {},
                'origin': 'new',
                'anchor': anchor_val,
            }
            merged_by_key[key] = entry
            ordered_keys.append(key)
            rows_appended_keys.add(key)
        else:
            rows_updated_keys.add(key)

        if anchor_display_name:
            entry['row'][anchor_display_name] = _display_anchor(anchor_val)
        for k, v in src_clean.items():
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == '':
                continue
            # For the anchor column specifically, canonicalize — a source
            # cell of "2025-03-01 00:00:00" should land as "2025-03-01".
            if anchor_display_name and _norm_header(k) == _norm_header(anchor_display_name):
                entry['row'][k] = _display_anchor(v)
            else:
                entry['row'][k] = v

    sorted_keys = sorted(merged_by_key.keys())
    merged_rows = [merged_by_key[k]['row'] for k in sorted_keys]

    existing_count = len(existing_rows)
    merged_count   = len(merged_rows)
    extra_needed   = max(merged_count - existing_count, 0)

    overflow_reason = None
    rows_inserted_for_shift = 0
    if extra_needed > 0 and next_title_row is not None:
        available_gap = next_title_row - extended_end
        shortfall = extra_needed - max(available_gap, 0)
        if shortfall > 0:
            insert_result = invoke(SHEETS_LAMBDA, {
                'tool': 'insert_rows',
                'inputs': {
                    'sheet_id':        sheet_id,
                    'sheet_name':      sheet_name,
                    # Insert *at* the next section's title row so all
                    # existing section content (including orphan rows)
                    # stays put and only the section BELOW gets pushed
                    # down. start_row_index is 0-indexed and the new
                    # empty rows land BEFORE this index.
                    'start_row_index': next_title_row,
                    'num_rows':        shortfall,
                },
                'credentials_dict': credentials
            })
            if not insert_result.get('success'):
                overflow_reason = (
                    f"insert_rows failed while making room in section "
                    f"{section.get('title')!r}: {insert_result.get('error')}"
                )
            else:
                rows_inserted_for_shift = shortfall
                print(
                    f"   Sort-merge: inserted {shortfall} row(s) at index {next_title_row} "
                    f"to expand section {section.get('title')!r}"
                )

    range_updates = []
    start_col_idx = min((idx for idx in sec_header_index.values()), default=0)
    end_col_idx   = max((idx for idx in sec_header_index.values()), default=start_col_idx)
    start_col_letter = _col_index_to_letter(start_col_idx)
    end_col_letter   = _col_index_to_letter(end_col_idx)
    width = end_col_idx - start_col_idx + 1

    for i, row_dict in enumerate(merged_rows):
        row_values = [''] * width
        for h, idx in sec_header_index.items():
            if idx < start_col_idx or idx > end_col_idx:
                continue
            v = row_dict.get(h)
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == '':
                continue
            row_values[idx - start_col_idx] = v

        # Preserve unrelated existing cells (e.g. a formula column the source
        # didn't touch) so sort-merge doesn't blank them out when we rewrite
        # the full section range.
        existing_row = existing_rows[i] if i < len(existing_rows) else None
        if existing_row is not None:
            for j in range(start_col_idx, end_col_idx + 1):
                if j >= len(existing_row):
                    break
                ev = existing_row[j]
                rel = j - start_col_idx
                if row_values[rel] == '' and ev is not None and str(ev).strip() != '':
                    if not (isinstance(ev, str) and str(ev).strip().startswith('=')):
                        row_values[rel] = ev

        row_num = data_start + i + 1
        range_updates.append({
            'range':  f"{safe_name}!{start_col_letter}{row_num}:{end_col_letter}{row_num}",
            'values': [row_values],
        })

    cells_updated = 0
    write_error = None
    if range_updates:
        batch = invoke(SHEETS_LAMBDA, {
            'tool':   'batch_update_cells',
            'inputs': {'sheet_id': sheet_id, 'updates': range_updates},
            'credentials_dict': credentials,
        })
        if batch.get('success'):
            cells_updated = int(batch.get('cells_updated', 0) or 0)
        else:
            write_error = batch.get('error') or 'batch_update_cells failed'

    append_mode = 'in-section-sort-merge' if not overflow_reason else 'sheet-bottom-overflow'
    success = cells_updated > 0 and not write_error

    result = {
        'success':        success,
        'rows_updated':   len(rows_updated_keys),
        'rows_appended':  len(rows_appended_keys),
        'cells_updated':  cells_updated,
        'section':        section.get('title'),
        'append_mode':    append_mode,
        'rows_inserted_for_shift': rows_inserted_for_shift,
    }
    if overflow_reason:
        result['overflow_reason'] = overflow_reason
    if write_error and not success:
        result['error'] = write_error
    return result


def _plan_multi_sheet_auto_route(sheets_list, target_sections):
    """Plan a 1:1 source-sheet → target-section routing when unambiguous.

    Returns a list of route dicts ordered by section_index, or None when
    routing is ambiguous (caller falls back to sheet/section pickers).

    A route is included only when ALL of the following hold:
      - ≥2 source sheets AND ≥2 target sections.
      - Every source sheet has a best-matching section with overlap ≥ 2
        headers (so we never route on a single shared column like "Date").
      - The best-matching section is dominant: 2× the runner-up score or
        the runner-up is 0.
      - No two sheets claim the same section.
      - Every source sheet gets a claim (no orphan data sheet).
      - Every target section gets a claim (no unfilled output section).

    ``sheets_list``: output of detect_source_sheets (each with name,
    headers, data_rows, meaningful_headers).
    ``target_sections``: output of _detect_sections_local (each with
    title, headers, data_start, data_end).
    """
    if len(sheets_list) < 2 or len(target_sections) < 2:
        return None

    usable_sheets = [
        s for s in sheets_list
        if (s.get('data_rows') or 0) > 0 and (s.get('meaningful_headers') or 0) > 0
    ]
    if len(usable_sheets) < 2:
        return None
    if len(usable_sheets) != len(target_sections):
        return None

    assignments = {}
    for sheet in usable_sheets:
        sheet_headers = {_norm_header(h) for h in (sheet.get('headers') or []) if h}
        if not sheet_headers:
            return None

        scored = []
        for si, sec in enumerate(target_sections):
            sec_headers = {_norm_header(h) for h in (sec.get('headers') or []) if h}
            scored.append((len(sheet_headers & sec_headers), si))
        scored.sort(key=lambda t: t[0], reverse=True)

        best_overlap, best_idx = scored[0]
        if best_overlap < 2:
            return None
        if len(scored) > 1:
            runner_up = scored[1][0]
            if runner_up > 0 and best_overlap < 2 * runner_up:
                return None
        if best_idx in assignments:
            return None
        assignments[best_idx] = (sheet, best_overlap)

    if len(assignments) != len(target_sections):
        return None

    plan = []
    for si in sorted(assignments.keys()):
        sheet, overlap = assignments[si]
        plan.append({
            'sheet_name':      sheet.get('name'),
            'sheet_headers':   list(sheet.get('headers') or []),
            'section_index':   si,
            'section_title':   target_sections[si].get('title'),
            'section_headers': list(target_sections[si].get('headers') or []),
            'overlap_score':   overlap,
        })
    return plan


# Minimum header overlap (with target) every sheet needs to qualify for the
# aggregate path. Two columns is the same floor used by 1:1 auto-route — anything
# less risks aggregating sheets that just happen to share a single common column
# like "Date" with the target.
MIN_HEADERS_FOR_AGGREGATE = 2

# Relaxed per-sheet overlap requirement that kicks in when source sheets are
# essentially identical to each other (worst-pair Jaccard >= MIN_HOMOGENEOUS_SIMILARITY
# below). The "user uploaded a stack of identically-shaped sheets" signal is
# strong enough on its own that we trust the smart_mapping_engine to bridge
# any source<->target column-name fuzz downstream — we only need ONE shared
# anchor column (typically Date / ID) for the upsert keying to work.
#
# Without this relaxation TC-L06 fails: source has [Date, Trucks, Pallets, Cases],
# target has 114 KPI columns where only "Date" matches verbatim — overlap = 1,
# strict gate rejects, user is forced into the single-sheet picker even though
# the user clearly intended to aggregate all 3 month-tabs into the single
# Date-keyed target.
MIN_HEADERS_FOR_AGGREGATE_HOMOGENEOUS = 1

# Minimum cross-sheet header similarity (Jaccard on normalized header sets)
# required for the aggregate path to fire AT ALL. 0.7 is strict enough to reject
# accidentally-grouped tabs (e.g. a "Notes" sheet alongside two data sheets)
# but permissive enough to allow real-world drift like one sheet having an
# extra optional column.
MIN_AGGREGATE_HEADER_SIMILARITY = 0.7

# Threshold for the "homogeneous-sheets" relaxation above. 0.95 means the
# sheets share AT LEAST 95% of their headers pairwise — practically
# identical schemas with at most one optional column drift (e.g. one tab
# carries an extra "Notes" column). This is a deliberately tight gate so
# the relaxation only triggers on the canonical "monthly tab fan-out"
# pattern (TC-L06 March/April/May with identical Date/Trucks/Pallets/Cases),
# NOT on grab-bags of loosely-related tabs.
MIN_HOMOGENEOUS_SIMILARITY = 0.95


# ============================================================================
# Intra-section duplicate-anchor conflict detection (Bug "silent overwrite")
# ============================================================================
# When the user uploads a source whose single section has 2+ rows that share
# the same anchor value but disagree on at least one mapped column, today the
# writer silently overwrites — last source row wins for shared columns. This
# is the same data-loss class as the cross-tab anchor collision case that
# _preview_multi_sheet_aggregate already surfaces via requires_conflict_resolution.
#
# These helpers add intra-section detection and per-anchor row-pick filtering.
# They reuse the same FE modal payload shape (anchor_value + candidates[]) so
# the frontend's ConflictModal renders intra-section duplicates identically
# to cross-tab duplicates — only the candidate label changes (Row N vs sheet
# name). The choice_id format is "row_{0-indexed-position}" so the run-time
# filter can deterministically pick the winner without re-parsing in a
# different order. ============================================================================

def _normalize_intra_section_choices(choices) -> dict:
    """Best-effort coerce intra_section_choices to a {anchor: choice_str} dict.

    Accepts a JSON string (FE wrapper round-trip), a dict, or None.
    Anything else collapses to {} so callers can treat it as no-op.
    """
    if choices is None:
        return {}
    if isinstance(choices, str):
        try:
            choices = json.loads(choices)
        except Exception:
            return {}
    if not isinstance(choices, dict):
        return {}
    return choices


def _anchor_key_from_row(src_row, source_anchor_names, is_date_anchor):
    """Compute (raw_anchor, lookup_key) for a single source row.

    Returns (None, None) when the row has no usable anchor (all anchor
    columns are empty / None). Mirrors the exact same key derivation used
    by source_row_by_anchor in the preview path so detection lookups
    align with the downstream consumers.
    """
    parts = []
    for sa in source_anchor_names or []:
        val = src_row.get(sa)
        if val is None:
            continue
        normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
        if normed:
            parts.append(normed)
    if not parts:
        return None, None
    raw_anchor = '|'.join(parts) if len(parts) > 1 else parts[0]
    lookup_key = raw_anchor if is_date_anchor else raw_anchor.lower()
    return raw_anchor, lookup_key


def _detect_intra_section_anchor_conflicts(
    source_rows,
    source_anchor_names,
    column_mappings,
    is_date_anchor,
    write_only_anchors=None,
):
    """Find anchors that appear in 2+ source rows with ANY mapped-column
    value disagreement.

    Returns ``[{anchor_value, candidates: [{choice_id, label, sheet_name,
    row_data, row_index}], conflict_kind: 'intra_section'}]`` (empty list
    if every duplicate group is fully identical or there are no
    duplicates at all).

    Rules:
      - Two rows share the same lookup_key (date-normalized for date
        anchors, lowercased for non-date) → candidate group.
      - Within the group, compare every mapped non-anchor column. If
        ALL rows agree on every column → silent dedupe (no conflict).
      - If at least one column differs → emit a conflict so the user
        picks which row wins.
      - source rows whose anchor is in write_only_anchors are ALWAYS
        considered (the user explicitly checked them); rows outside the
        set when write_only_anchors is provided are SKIPPED entirely
        (the user already deselected them — no point asking which dup
        they meant).
      - sheet_name is set to the row label too so the existing FE
        ConflictModal that reads cand.sheet_name keeps rendering
        correctly without code changes (back-compat shim — new code
        should read cand.choice_id + cand.label).
    """
    if not source_rows or not source_anchor_names:
        return []
    non_anchor_mappings = {
        src_col: tgt_col
        for src_col, tgt_col in (column_mappings or {}).items()
        if tgt_col and src_col not in set(source_anchor_names)
    }
    if not non_anchor_mappings:
        return []
    write_only_set = None
    if write_only_anchors:
        write_only_set = {
            (str(a) if is_date_anchor else str(a).lower())
            for a in write_only_anchors
        }
    anchor_to_rows = {}
    for idx, src_row in enumerate(source_rows or []):
        if not isinstance(src_row, dict):
            continue
        raw_anchor, lookup_key = _anchor_key_from_row(
            src_row, source_anchor_names, is_date_anchor,
        )
        if not raw_anchor:
            continue
        if write_only_set is not None and lookup_key not in write_only_set:
            continue
        anchor_to_rows.setdefault(lookup_key, []).append((idx, raw_anchor, src_row))
    conflicts = []
    for lookup_key, occurrences in anchor_to_rows.items():
        if len(occurrences) < 2:
            continue
        value_tuples = []
        for _, _, row in occurrences:
            value_tuples.append(tuple(
                str(row.get(src_col, '') or '').strip()
                for src_col in non_anchor_mappings.keys()
            ))
        if len(set(value_tuples)) <= 1:
            continue
        candidates = []
        raw_anchor_display = occurrences[0][1]
        for idx, _, row in occurrences:
            row_data = {}
            for src_col, tgt_col in non_anchor_mappings.items():
                row_data[tgt_col] = _format_cell_value(row.get(src_col))
            row_label = f"Row {idx + 1}"
            candidates.append({
                'choice_id': f'row_{idx}',
                'label': row_label,
                'sheet_name': row_label,
                'row_index': idx,
                'row_data': row_data,
            })
        conflicts.append({
            'anchor_value': str(raw_anchor_display),
            'candidates': candidates,
            'conflict_kind': 'intra_section',
        })
    return conflicts


def _apply_intra_section_choices(
    source_rows,
    intra_section_choices,
    source_anchor_names,
    is_date_anchor,
):
    """Filter source_rows to honor the user's per-anchor row pick.

    intra_section_choices keys are anchor display values (date strings
    or lower-cased identifiers). Values are either ``"row_<N>"`` (keep
    only the row whose 0-indexed position equals N for that anchor) or
    ``"skip"`` (drop ALL rows with that anchor).

    Anchors NOT in choices pass through untouched (the typical case for
    rows that had no duplicate to begin with). Bad/unknown choice
    values fall through and the duplicate is preserved unchanged so
    the next preview re-detects and re-prompts (no silent data loss).
    """
    if not intra_section_choices or not source_rows:
        return source_rows
    norm_choices = {}
    for k, v in (intra_section_choices or {}).items():
        if k is None:
            continue
        norm_k = str(k) if is_date_anchor else str(k).lower()
        norm_choices[norm_k] = v
    if not norm_choices:
        return source_rows
    filtered = []
    for idx, src_row in enumerate(source_rows or []):
        if not isinstance(src_row, dict):
            filtered.append(src_row)
            continue
        _, lookup_key = _anchor_key_from_row(
            src_row, source_anchor_names, is_date_anchor,
        )
        if not lookup_key or lookup_key not in norm_choices:
            filtered.append(src_row)
            continue
        choice = norm_choices[lookup_key]
        if choice == 'skip':
            continue
        chosen_idx = None
        if isinstance(choice, str) and choice.startswith('row_'):
            try:
                chosen_idx = int(choice.split('_', 1)[1])
            except (ValueError, IndexError):
                chosen_idx = None
        if chosen_idx is None:
            filtered.append(src_row)
            continue
        if idx == chosen_idx:
            filtered.append(src_row)
    return filtered


def _plan_multi_sheet_aggregate(sheets_list, target_sections, target_headers):
    """Plan an N source-sheet -> 1 target section aggregate.

    Aggregate mode is the third multi-sheet orchestration path (1:1
    auto-route and the single-sheet picker being the other two). It fires
    when 2+ source tabs share roughly the same header layout AND all of
    them logically write into the SAME target section (typical TC-L06
    shape: march_data + april_data + may_data, each keyed by Date,
    stacking into a single Date-keyed target tab).

    Returns ``{'aggregated_sheet_names': [...], 'target_section_index': int|None}``
    when the gate passes, or ``None`` so the caller falls back to the
    existing requires_sheet_selection picker.

    Gate (all required):
      - >= 2 source sheets with data + meaningful headers.
      - Cross-sheet header similarity (pairwise Jaccard) is symmetric AND
        >= MIN_AGGREGATE_HEADER_SIMILARITY for the WORST pair (so we
        don't aggregate sheets that diverge significantly).
      - Each sheet has header overlap with the target >= a per-sheet floor
        that depends on cross-sheet similarity:
            worst_sim >= MIN_HOMOGENEOUS_SIMILARITY (0.95) → floor = 1
            otherwise                                     → floor = 2
        Rationale: when all source sheets share essentially the same
        schema, a single shared anchor column with the target (Date,
        ID, etc.) is enough — smart_mapping_engine bridges the rest of
        the source<->target column-name fuzz downstream. For loosely
        related sheets we keep the strict 2-column floor.
      - Target has either no detected sections (single flat layout, the
        common case) OR exactly one applicable section. If 2+ sections
        exist, _plan_multi_sheet_auto_route already had a chance and
        returned None — aggregating into one section would silently drop
        the others, so we bail.

    NOTE: Caller must invoke this AFTER _plan_multi_sheet_auto_route and
    only when that returned None. Otherwise we'd take the slow path for
    workbooks that perfectly route 1:1.

    Bail decisions are logged to stdout (visible in CloudWatch as
    ``aggregate-bail: <reason> ...``) so the caller can diagnose without
    re-running with a debugger attached.
    """
    if not sheets_list or len(sheets_list) < 2:
        print(f"   aggregate-bail: too-few-sheets (got {len(sheets_list or [])})")
        return None

    target_set = {_norm_header(h) for h in (target_headers or []) if h}
    if not target_set:
        print("   aggregate-bail: empty-target-headers")
        return None

    # A "usable" sheet for aggregation must have:
    #   - actual data rows (>0)
    #   - meaningful headers (>0)
    #   - at least 1 header overlapping the target (score >0)
    # The score>0 filter is what excludes sidecar sheets like a "Notes"
    # tab from polluting the cross-sheet similarity calc. Without it,
    # a single 1-column Notes tab can drag the worst-pair Jaccard to
    # ~0 and force the entire workbook into the picker even when 2 of
    # 3 sheets are perfectly compatible (TC-L06 fixture: March_Data +
    # April_Data + Notes — score=[1,1,0] would yield Jaccard 0.00 for
    # any pair touching Notes). We deliberately drop zero-target-
    # overlap sheets BEFORE the Jaccard pass instead of after, because
    # the Jaccard pass is already strict (>=0.7) and would just bail.
    usable_sheets = [
        s for s in sheets_list
        if (s.get('data_rows') or 0) > 0
        and (s.get('meaningful_headers') or 0) > 0
        and (s.get('score') or 0) > 0
    ]
    if len(usable_sheets) < 2:
        skipped = [
            (s.get('name'), s.get('score'), s.get('data_rows'), s.get('meaningful_headers'))
            for s in sheets_list if s not in usable_sheets
        ]
        print(
            f"   aggregate-bail: too-few-usable-sheets after sidecar-filter "
            f"(got {len(usable_sheets)} usable / {len(sheets_list)} total; "
            f"skipped sidecars={skipped})"
        )
        return None
    if len(usable_sheets) < len(sheets_list):
        skipped_names = [s.get('name') for s in sheets_list if s not in usable_sheets]
        print(f"   aggregate-info: filtered out {len(skipped_names)} sidecar(s) {skipped_names}")

    # Build per-sheet header sets BEFORE applying the per-sheet target
    # overlap gate — we need the cross-sheet Jaccard first to know which
    # tier of strictness to apply.
    per_sheet_headers = []
    for sheet in usable_sheets:
        sh_set = {_norm_header(h) for h in (sheet.get('headers') or []) if h}
        if not sh_set:
            print(f"   aggregate-bail: sheet {sheet.get('name')!r} has no usable headers")
            return None
        per_sheet_headers.append((sheet.get('name'), sh_set))

    # Pairwise Jaccard — bail on the WORST pair, not the average, so one
    # outlier sheet can't sneak in by being averaged with two well-aligned
    # sheets.
    worst_sim = 1.0
    worst_pair = None
    for i in range(len(per_sheet_headers)):
        for j in range(i + 1, len(per_sheet_headers)):
            a = per_sheet_headers[i][1]
            b = per_sheet_headers[j][1]
            union = a | b
            if not union:
                print(
                    f"   aggregate-bail: empty-union for pair "
                    f"({per_sheet_headers[i][0]!r}, {per_sheet_headers[j][0]!r})"
                )
                return None
            sim = len(a & b) / len(union)
            if sim < worst_sim:
                worst_sim = sim
                worst_pair = (per_sheet_headers[i][0], per_sheet_headers[j][0])
    if worst_sim < MIN_AGGREGATE_HEADER_SIMILARITY:
        print(
            f"   aggregate-bail: worst-Jaccard-too-low "
            f"({worst_sim:.2f} < {MIN_AGGREGATE_HEADER_SIMILARITY:.2f}) "
            f"for pair {worst_pair}"
        )
        return None

    # Two-tier per-sheet target overlap: relaxed when sheets are
    # essentially identical (homogeneous-monthly-tabs pattern), strict
    # otherwise.
    if worst_sim >= MIN_HOMOGENEOUS_SIMILARITY:
        per_sheet_min_overlap = MIN_HEADERS_FOR_AGGREGATE_HOMOGENEOUS
        tier = "homogeneous"
    else:
        per_sheet_min_overlap = MIN_HEADERS_FOR_AGGREGATE
        tier = "strict"

    per_sheet_overlaps = [
        (name, len(sh_set & target_set)) for name, sh_set in per_sheet_headers
    ]
    weakest = min(per_sheet_overlaps, key=lambda t: t[1])
    if weakest[1] < per_sheet_min_overlap:
        print(
            f"   aggregate-bail: per-sheet target overlap too low "
            f"(tier={tier}, floor={per_sheet_min_overlap}, "
            f"weakest={weakest[0]!r}={weakest[1]}, all={per_sheet_overlaps})"
        )
        return None

    # Resolve target section: 0 sections means flat single-section layout
    # (the common case). 1 section is the "stacked but only one block has
    # data" edge case. 2+ sections means caller should have hit the 1:1
    # auto-route already; if it didn't, the aggregate path is the wrong
    # tool and we bail.
    target_section_index = None
    if target_sections:
        if len(target_sections) == 1:
            target_section_index = 0
        else:
            print(
                f"   aggregate-bail: target has {len(target_sections)} sections, "
                f"would need 0 or 1 for aggregate"
            )
            return None

    print(
        f"   aggregate-pass: tier={tier}, worst_sim={worst_sim:.2f}, "
        f"per_sheet_overlaps={per_sheet_overlaps}, "
        f"target_section_index={target_section_index}"
    )
    return {
        'aggregated_sheet_names': [name for name, _ in per_sheet_headers],
        'target_section_index': target_section_index,
    }


# ============================================================================
# Multi-sheet COLUMN-MERGE planner / preview / run
# ============================================================================
# When a workbook has 2+ source sheets that:
#   - share at least one anchor-candidate header with the target (typically
#     `Date` or another row-identifier column), AND
#   - cover MOSTLY DISJOINT sets of non-anchor target columns (each sheet
#     contributes different columns to the same target rows)
# the user wants both sheets to populate DIFFERENT columns of the same
# target rows in ONE pass — NOT to row-stack (existing aggregate path) and
# NOT to be forced to pick one sheet (current sheet picker).
#
# Concrete shape this fixes (PROPER FUCKING TABLE + Operational Cost case):
#   Sheet A: Date / Total Stock On-Hand / Good Pallet Inventory / ...
#   Sheet B: Date / LPG Expenses / Diesel Expenses / Office Supplies / ...
#   Target : Date / Total Stock On-Hand / ... / LPG Expenses / ...
# For each Date in target: fill inventory cols from Sheet A, fill expense
# cols from Sheet B, leave non-contributed cells alone.
#
# Conservatism: this path runs AFTER _plan_multi_sheet_aggregate and AFTER
# the auto-route planner. The Jaccard >= 0.70 row-stack aggregate would
# already have absorbed any "same-shape monthly tabs" workbook before we
# get here, so a workbook with disjoint columns + shared anchor is the
# only realistic shape that lands in this planner. We still bail (return
# None) on any ambiguity so the picker stays as the safety net.
# ============================================================================


def _plan_multi_sheet_column_merge(sheets_list, target_headers):
    """Plan a column-merge across 2+ source sheets that share an anchor and
    contribute DIFFERENT or PARTIALLY OVERLAPPING target columns.

    Returns a plan dict like::

        {
          'sheet_names': ['Sheet A', 'Sheet B', ...],
          'shared_anchor_candidates': ['date'],          # normalized
          'per_sheet_target_cols': {                     # normalized header names
            'Sheet A': ['date', 'total stock on-hand', 'good pallet inventory', ...],
            'Sheet B': ['date', 'lpg expenses', 'diesel expenses', ...],
          },
          'overlap_warn_cols': [],                       # cols claimed by 2+ sheets
                                                         # (informational only — does
                                                         # not gate the plan)
        }

    Or ``None`` to fall through to the picker.

    Caller MUST invoke this AFTER ``_plan_multi_sheet_aggregate`` returned
    None — otherwise we'd poach files that genuinely belong on the
    row-stack aggregate path.

    Overlap policy: when 2+ sheets BOTH map to the same target column,
    we DO NOT bail. The preview path (`_preview_multi_sheet_column_merge`)
    computes per-cell ownership: if all owners agree on the value the
    cell is silently merged, if they disagree the user picks via the
    cross-sheet conflict modal. The historical 25% overlap cap was
    removed because it predated cell-level conflict detection — back
    then "too much overlap" meant "silent overwrite risk", which no
    longer applies.

    Sheet exclusion (silent — never plan-killing as long as 2+ remain):
      * ``no_target_overlap`` — sheet has zero columns the target wants.
      * ``no_shared_anchor``  — sheet has target overlap but doesn't share
        the chosen anchor column with the others.
      * ``anchor_only``       — sheet shares the anchor but contributes
        nothing else (e.g. a SKU sheet whose only target-mapped col is
        DATE). Same semantics as ``no_target_overlap`` from the merge's
        POV — the sheet has nothing to contribute.

    All three are reported back to the caller via the returned plan's
    ``excluded_sheets`` dict so the orchestrator can show users which
    tabs were skipped and why. The plan still bails (returns None) only
    when fewer than 2 sheets remain after exclusion.

    Bail decisions are logged to stdout (``column-merge-bail: <reason>``)
    so the caller can diagnose without re-running with a debugger.
    """
    if not sheets_list or len(sheets_list) < 2:
        print(f"   column-merge-bail: too-few-sheets (got {len(sheets_list or [])})")
        return None

    target_set = {_norm_header(h) for h in (target_headers or []) if h}
    if not target_set:
        print("   column-merge-bail: empty-target-headers")
        return None

    # Same usability filter as the aggregate path: drop sidecars (score 0,
    # no data, or no meaningful headers). Without this a Notes tab can
    # poison the shared-anchor intersection (no shared headers => bail).
    usable_sheets = [
        s for s in sheets_list
        if (s.get('data_rows') or 0) > 0
        and (s.get('meaningful_headers') or 0) > 0
        and (s.get('score') or 0) > 0
    ]
    if len(usable_sheets) < 2:
        skipped = [
            (s.get('name'), s.get('score'), s.get('data_rows'), s.get('meaningful_headers'))
            for s in sheets_list if s not in usable_sheets
        ]
        print(
            f"   column-merge-bail: too-few-usable-sheets after sidecar-filter "
            f"(got {len(usable_sheets)} usable / {len(sheets_list)} total; "
            f"skipped sidecars={skipped})"
        )
        return None

    # Per-sheet header sets, restricted to headers that ALSO appear in
    # the target. A sheet with zero target-overlap is silently excluded
    # from this plan (it has nothing to contribute), but we no longer
    # bail the whole planner — the remaining sheets may still column-merge
    # cleanly. This is what makes a workbook like
    # ``[PROPER FUCKING TABLE, Operational Cost, Doesn't matter]`` where
    # the third sheet shares no anchor with the other two still route to
    # column-merge instead of falling back to the picker.
    per_sheet = []
    excluded_no_overlap = []
    for sheet in usable_sheets:
        all_hdrs = {_norm_header(h) for h in (sheet.get('headers') or []) if h}
        on_target = all_hdrs & target_set
        if not on_target:
            excluded_no_overlap.append(sheet.get('name'))
            continue
        per_sheet.append({
            'name':        sheet.get('name'),
            'headers_set': all_hdrs,
            'on_target':   on_target,
        })

    if len(per_sheet) < 2:
        print(
            f"   column-merge-bail: only {len(per_sheet)} sheet(s) have "
            f"target-overlapping headers (excluded: {excluded_no_overlap})"
        )
        return None

    # Anchor candidate selection: instead of requiring an anchor present on
    # EVERY usable sheet (intersection across all), we look for the LARGEST
    # SUBSET of sheets that share at least one anchor candidate. The
    # canonical case this unblocks: a workbook with 3 sheets where 2 share
    # `Date` and the 3rd shares nothing — the original strict intersection
    # returned ∅ and we fell back to the picker. Now we column-merge the 2
    # that share `Date` and silently drop the 3rd (logged so the user can
    # see it in CloudWatch / response payload).
    #
    # Header → set-of-sheet-names that have it on_target. We only care
    # about headers that appear on >=2 sheets because anything narrower
    # can't be a multi-sheet anchor.
    header_to_sheets = {}
    for p in per_sheet:
        for h in p['on_target']:
            header_to_sheets.setdefault(h, set()).add(p['name'])
    multi_sheet_headers = {
        h: sheets for h, sheets in header_to_sheets.items() if len(sheets) >= 2
    }
    if not multi_sheet_headers:
        print(
            f"   column-merge-bail: no header appears on 2+ sheets "
            f"(per-sheet target overlap: "
            f"{[(p['name'], len(p['on_target'])) for p in per_sheet]})"
        )
        return None

    # Score each candidate header by:
    #   1) coverage (how many sheets share it) — larger is better
    #   2) date-anchor preference — `date` substring beats arbitrary cols
    #      because it's the canonical row identifier in this domain
    #   3) shorter normalized name — proxy for "more atomic" (e.g. `date`
    #      beats `start date of period`)
    # Tuple sorts lexicographically; we want max so we negate the third
    # field (shorter = bigger when negated).
    def _candidate_rank(h_sheets):
        h, sheets = h_sheets
        date_pref = 1 if 'date' in h else 0
        return (len(sheets), date_pref, -len(h))

    best_header, best_sheet_names = max(
        multi_sheet_headers.items(), key=_candidate_rank,
    )

    # Tie-detection: if multiple candidates achieve the SAME top rank but
    # cover DIFFERENT sheet subsets, we have ambiguity (which subset does
    # the user actually want?). Bail so the picker can surface and the
    # user clarifies. Same rank + same subset is fine — they all point
    # at the same plan.
    top_rank = _candidate_rank((best_header, best_sheet_names))
    same_rank_candidates = [
        (h, sheets)
        for h, sheets in multi_sheet_headers.items()
        if _candidate_rank((h, sheets)) == top_rank
    ]
    distinct_subsets = {frozenset(sheets) for _, sheets in same_rank_candidates}
    if len(distinct_subsets) > 1:
        print(
            f"   column-merge-bail: ambiguous anchor — multiple candidates "
            f"({[h for h, _ in same_rank_candidates]}) cover DIFFERENT sheet "
            f"subsets ({[sorted(s) for s in distinct_subsets]}). User must "
            f"clarify via picker."
        )
        return None

    chosen_anchor = best_header
    chosen_per_sheet = [p for p in per_sheet if p['name'] in best_sheet_names]
    excluded_no_anchor = sorted(
        p['name'] for p in per_sheet if p['name'] not in best_sheet_names
    )

    # Each chosen sheet's UNIQUE contribution = on_target - {chosen_anchor}.
    # A sheet that contributes ONLY the anchor (no other target-mapped
    # cols) has nothing to merge — silently exclude it (mirrors the
    # `excluded_no_anchor` handling above; both flavors of "this sheet
    # has nothing useful to add" are now soft-skips, not plan-killers).
    # Caller sees the exclusion in `excluded_sheets.anchor_only` and in
    # the `column-merge-pass` log line.
    per_sheet_unique = []
    excluded_anchor_only = []
    for p in chosen_per_sheet:
        unique = p['on_target'] - {chosen_anchor}
        if not unique:
            excluded_anchor_only.append(p['name'])
            continue
        per_sheet_unique.append({**p, 'unique_target': unique})

    if len(per_sheet_unique) < 2:
        print(
            f"   column-merge-bail: only {len(per_sheet_unique)} sheet(s) "
            f"contribute non-anchor target cols after exclusions "
            f"(anchor-only excluded: {excluded_anchor_only}, "
            f"no-shared-anchor excluded: {excluded_no_anchor})"
        )
        return None

    # Cross-sheet overlap on UNIQUE target cols. We compute it for the
    # response payload's `overlap_warn_cols` (purely informational — the
    # FE may surface it in the preview as a "these cols are claimed by
    # multiple tabs" hint) but DO NOT gate the plan on it. The preview
    # path's per-cell ownership map handles overlap correctly:
    #   - 2+ owners with same value  → silent merge
    #   - 2+ owners with diff values → cross-sheet conflict modal asks
    #                                   user to pick the winner per anchor
    # See `_preview_multi_sheet_column_merge` lines 6826-6845 for the
    # cell-level resolution logic this planner now defers to.
    overlap_cols = set()
    for i in range(len(per_sheet_unique)):
        for j in range(i + 1, len(per_sheet_unique)):
            inter = (
                per_sheet_unique[i]['unique_target']
                & per_sheet_unique[j]['unique_target']
            )
            if inter:
                overlap_cols |= inter

    excluded_summary = []
    if excluded_no_overlap:
        excluded_summary.append(f"no-target-overlap={excluded_no_overlap}")
    if excluded_no_anchor:
        excluded_summary.append(f"no-shared-anchor={excluded_no_anchor}")
    if excluded_anchor_only:
        excluded_summary.append(f"anchor-only={excluded_anchor_only}")
    print(
        f"   column-merge-pass: anchor={chosen_anchor!r} on "
        f"{len(per_sheet_unique)} sheet(s); per-sheet unique target cols: "
        + "; ".join(
            f"{p['name']!r}={len(p['unique_target'])}"
            for p in per_sheet_unique
        )
        + (f"; overlap_cols={sorted(overlap_cols)}" if overlap_cols else "")
        + (f"; excluded={'; '.join(excluded_summary)}" if excluded_summary else "")
    )
    return {
        'sheet_names':              [p['name'] for p in per_sheet_unique],
        'shared_anchor_candidates': [chosen_anchor],
        'per_sheet_target_cols':    {
            p['name']: sorted(p['on_target']) for p in per_sheet_unique
        },
        'overlap_warn_cols':        sorted(overlap_cols),
        'excluded_sheets':          {
            'no_target_overlap': excluded_no_overlap,
            'no_shared_anchor':  excluded_no_anchor,
            'anchor_only':       excluded_anchor_only,
        },
    }


# ============================================================================
# Intra-tab section auto-route + aggregate (mirrors of the cross-tab planners)
# ============================================================================
# When the user uploads ONE source tab containing 2+ stacked sections (e.g.
# Inbound + Outbound metrics in one sheet) AND the target tab also has matching
# sections, today's code unconditionally bails to the section picker (forcing a
# manual choice + dropping the unchosen section's data silently). The planners
# below mirror the cross-tab ones but operate on the source-section list:
#   - _plan_multi_section_auto_route: 1:1 source-section → target-section
#     when each source section has a dominant + unique target section. Allows
#     fewer source sections than target sections (the unmatched target
#     sections remain untouched, which is correct for "I only have this
#     month's data, leave the others alone" workflows).
#   - _plan_multi_section_aggregate: every source section funnels into the
#     SAME target section (or the lone target section). Triggers the cross-
#     section conflict modal when an anchor value appears in 2+ source
#     sections and the rows disagree on a mapped column.
#
# Title-similarity tie-breaker (from Fix N's _section_title_similarity, lifted
# inline so the dynamic-mapping-agent doesn't need a cross-Lambda hop just for
# string scoring) keeps the routing semantically correct: source "Outbound
# Metrics" routes to target "Outbound Metrics" even when their column shapes
# are identical to "Inbound Metrics".
# ============================================================================

# Suffix tokens stripped from section titles before similarity scoring.
# Without these "Outbound Metrics" vs "Outbound" would jaccard at 0.5 and
# the suffix would dominate any *_metrics vs *_metrics pair. Mirrors the
# mapping_agent helper to keep scoring identical end-to-end.
_SECTION_TITLE_SUFFIXES = ('metrics', 'metric', 'data', 'table', 'section', 'summary')


def _local_section_title_similarity(src_title, tgt_title):
    """Local copy of mapping_agent._section_title_similarity for in-process
    scoring. 0..100. Returns 0 when either title is missing/empty so the
    caller's fallback scoring (column overlap) takes over cleanly.

    Reasoning for the cap at 99 for suffix-trimmed exact matches: keeps a
    discrimination gradient between literal exact matches (100) and
    "stripped 'metrics'" exact matches (99) so two candidate sections with
    titles "Outbound" and "Outbound Metrics" both scoring against source
    "Outbound" can still rank distinctly.
    """
    if not src_title or not tgt_title:
        return 0
    s = ' '.join(str(src_title).lower().split())
    t = ' '.join(str(tgt_title).lower().split())
    if s == t:
        return 100
    s_tokens = {tok for tok in s.split() if tok not in _SECTION_TITLE_SUFFIXES}
    t_tokens = {tok for tok in t.split() if tok not in _SECTION_TITLE_SUFFIXES}
    if not s_tokens or not t_tokens:
        return 0
    overlap = len(s_tokens & t_tokens)
    union = len(s_tokens | t_tokens)
    if not union:
        return 0
    sim = int(100 * overlap / union)
    return min(sim, 99)


# Title similarity score above which the section auto-router treats two
# titles as "semantically the same" and ALLOWS the dominance gate even
# when column overlap is identical. Without this an Inbound + Outbound
# pair with identical column shapes always bails (column-overlap tie-
# breaker can't distinguish them) — even though the titles clearly do.
SECTION_TITLE_STRONG_MATCH = 75


def _plan_multi_section_auto_route(source_sections, target_sections):
    """Plan a 1:1 source-section → target-section routing inside ONE tab.

    Returns a list of route dicts ordered by source_section_index, or None
    when routing is ambiguous (caller falls back to the section picker).

    Asymmetric counts: ``len(source) <= len(target)`` is allowed (the
    extra target sections stay untouched, which is the correct behavior
    for "user uploaded only the Inbound metrics, leave Outbound alone").
    Cross-tab equivalent _plan_multi_sheet_auto_route is STRICTER and
    requires equal counts because it's the higher-confidence "I'm
    fanning out monthly tabs into a flat target" pattern; sections in
    one tab carry less semantic weight per match so the asymmetric
    relaxation is safer.

    A route is included only when ALL of the following hold:
      - ≥2 usable source sections AND ≥2 target sections.
      - len(source) <= len(target).
      - Every source section has a best-matching target section that
        EITHER (a) has column overlap ≥ 2 AND dominates the runner-up
        (2× score or runner-up == 0), OR (b) has title similarity ≥
        SECTION_TITLE_STRONG_MATCH (semantic match wins over a tied
        column overlap).
      - No two source sections claim the same target section.

    ``source_sections``: output of detect_source_sections (each with
    title, headers, data_start, data_end, row_count).
    ``target_sections``: output of _detect_sections_local (same shape).
    """
    if len(source_sections or []) < 2 or len(target_sections or []) < 2:
        return None
    usable_src = [
        (i, s) for i, s in enumerate(source_sections)
        if (s.get('row_count') or 0) > 0
        and any(h and str(h).strip() for h in (s.get('headers') or []))
    ]
    if len(usable_src) < 2:
        return None
    if len(usable_src) > len(target_sections):
        print(
            f"   section-auto-route-bail: too-many-source-sections "
            f"(usable={len(usable_src)} > target={len(target_sections)})"
        )
        return None
    assignments = {}
    for src_idx, src_sec in usable_src:
        src_headers = {_norm_header(h) for h in (src_sec.get('headers') or []) if h}
        if not src_headers:
            print(f"   section-auto-route-bail: source #{src_idx} has empty header set")
            return None
        scored = []
        for ti, tgt_sec in enumerate(target_sections):
            tgt_headers = {_norm_header(h) for h in (tgt_sec.get('headers') or []) if h}
            col_overlap = len(src_headers & tgt_headers)
            title_sim = _local_section_title_similarity(
                src_sec.get('title'), tgt_sec.get('title'),
            )
            scored.append((col_overlap, title_sim, ti))
        # Sort by (title_sim DESC, col_overlap DESC, ti ASC) so a strong
        # title match always trumps a marginally-better column overlap.
        # Without this, two target sections with identical column shapes
        # but different titles tie on overlap and fall through to bail.
        scored.sort(key=lambda t: (-t[1], -t[0], t[2]))
        best_overlap, best_title_sim, best_idx = scored[0]
        # Acceptance: strong title match OR (overlap >= 2 AND dominant)
        accept_via_title = best_title_sim >= SECTION_TITLE_STRONG_MATCH
        accept_via_overlap = False
        if best_overlap >= 2:
            if len(scored) > 1:
                runner_overlap = scored[1][0]
                if runner_overlap == 0 or best_overlap >= 2 * runner_overlap:
                    accept_via_overlap = True
            else:
                accept_via_overlap = True
        if not (accept_via_title or accept_via_overlap):
            print(
                f"   section-auto-route-bail: source #{src_idx} '{src_sec.get('title')}' "
                f"has no dominant target — best={best_overlap} cols / {best_title_sim}% title"
            )
            return None
        if best_idx in assignments:
            # Two source sections claim the same target — ambiguous,
            # let the picker step in so the user disambiguates.
            print(
                f"   section-auto-route-bail: target #{best_idx} claimed twice "
                f"(by source #{assignments[best_idx][0]} and source #{src_idx})"
            )
            return None
        assignments[best_idx] = (src_idx, src_sec, best_overlap, best_title_sim)
    plan = []
    for src_idx, src_sec in usable_src:
        # Find which target index claims this source section
        match = next(
            ((tgt_idx, payload) for tgt_idx, payload in assignments.items()
             if payload[0] == src_idx),
            None,
        )
        if not match:
            return None
        tgt_idx, (_, _, overlap, title_sim) = match
        plan.append({
            'source_section_index':   src_idx,
            'source_section_title':   src_sec.get('title'),
            'source_section_headers': list(src_sec.get('headers') or []),
            'target_section_index':   tgt_idx,
            'target_section_title':   target_sections[tgt_idx].get('title'),
            'target_section_headers': list(target_sections[tgt_idx].get('headers') or []),
            'overlap_score':          overlap,
            'title_similarity':       title_sim,
        })
    return plan


def _plan_multi_section_aggregate(source_sections, target_sections, target_headers):
    """Plan an N source-section -> 1 target-section aggregate inside ONE tab.

    Returns ``{'aggregated_section_indices': [...], 'aggregated_section_titles':
    [...], 'target_section_index': int|None}`` when the gate passes, else None.

    Gate (mirrors _plan_multi_sheet_aggregate but for sections):
      - ≥2 usable source sections.
      - Cross-section header similarity (worst-pair Jaccard) >=
        MIN_AGGREGATE_HEADER_SIMILARITY.
      - Each source section overlaps the target by ≥ floor (1 in
        homogeneous tier, 2 otherwise).
      - Target has either no detected sections (single flat layout) OR
        exactly one applicable target section. If 2+ target sections
        exist AND the auto-route plan above did NOT pick a single
        winner across all source sections, we'd be silently dropping
        sections — bail and let auto-route or picker handle it.
    """
    if len(source_sections or []) < 2:
        print(f"   section-aggregate-bail: too-few-source-sections (got {len(source_sections or [])})")
        return None
    target_set = {_norm_header(h) for h in (target_headers or []) if h}
    if not target_set:
        print("   section-aggregate-bail: empty-target-headers")
        return None
    usable = [
        (i, s) for i, s in enumerate(source_sections)
        if (s.get('row_count') or 0) > 0
        and any(h and str(h).strip() for h in (s.get('headers') or []))
    ]
    if len(usable) < 2:
        print(
            f"   section-aggregate-bail: too-few-usable-sections "
            f"({len(usable)}/{len(source_sections)})"
        )
        return None
    per_section_headers = []
    for idx, sec in usable:
        sh_set = {_norm_header(h) for h in (sec.get('headers') or []) if h}
        if not sh_set:
            print(f"   section-aggregate-bail: section #{idx} has no usable headers")
            return None
        per_section_headers.append((idx, sec.get('title'), sh_set))
    # Pairwise Jaccard
    worst_sim = 1.0
    for i in range(len(per_section_headers)):
        for j in range(i + 1, len(per_section_headers)):
            a = per_section_headers[i][2]
            b = per_section_headers[j][2]
            union = a | b
            if not union:
                return None
            sim = len(a & b) / len(union)
            if sim < worst_sim:
                worst_sim = sim
    if worst_sim < MIN_AGGREGATE_HEADER_SIMILARITY:
        print(
            f"   section-aggregate-bail: worst-pair Jaccard {worst_sim:.2f} < "
            f"{MIN_AGGREGATE_HEADER_SIMILARITY}"
        )
        return None
    floor = (
        MIN_HEADERS_FOR_AGGREGATE_HOMOGENEOUS
        if worst_sim >= MIN_HOMOGENEOUS_SIMILARITY
        else MIN_HEADERS_FOR_AGGREGATE
    )
    per_section_overlaps = []
    for idx, title, sh_set in per_section_headers:
        ov = len(sh_set & target_set)
        if ov < floor:
            print(
                f"   section-aggregate-bail: section #{idx} '{title}' has only "
                f"{ov} target overlap (floor={floor})"
            )
            return None
        per_section_overlaps.append((idx, title, ov))
    # Target section: pick the single applicable section. If 2+ exist,
    # let the (separate) auto-route step handle it OR fall through to picker.
    target_section_index = None
    if target_sections:
        if len(target_sections) == 1:
            target_section_index = 0
        else:
            # Multiple target sections: pick the one whose title matches
            # the COMBINED source section (by name overlap with the union
            # of source titles) OR has the best column overlap. If no
            # clear winner, bail — auto-route is the right path then.
            scored = []
            for ti, tgt in enumerate(target_sections):
                t_headers = {_norm_header(h) for h in (tgt.get('headers') or []) if h}
                avg_overlap = sum(
                    len(sh & t_headers) for _, _, sh in per_section_headers
                ) / len(per_section_headers)
                avg_title = sum(
                    _local_section_title_similarity(title, tgt.get('title'))
                    for _, title, _ in per_section_headers
                ) / len(per_section_headers)
                scored.append((avg_overlap, avg_title, ti))
            scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
            best_avg_overlap, best_avg_title, best_ti = scored[0]
            if len(scored) > 1:
                runner = scored[1]
                if runner[0] > 0 and best_avg_overlap < 2 * runner[0]:
                    print(
                        f"   section-aggregate-bail: no dominant target section "
                        f"(best avg overlap {best_avg_overlap:.1f} vs runner {runner[0]:.1f})"
                    )
                    return None
            target_section_index = best_ti
    print(
        f"   section-aggregate-pass: worst_sim={worst_sim:.2f}, "
        f"per_section_overlaps={per_section_overlaps}, "
        f"target_section_index={target_section_index}"
    )
    return {
        'aggregated_section_indices': [idx for idx, _, _ in per_section_headers],
        'aggregated_section_titles':  [title for _, title, _ in per_section_headers],
        'target_section_index':       target_section_index,
    }


# ============================================================================
# Cross-tab × per-source-section routing planner
# ============================================================================
# This is the planner the user described in the "anchor-routes-by-source-section"
# model: when each source TAB itself contains 2+ stacked sections (Inbound,
# Outbound, ...) AND the target has matching sections, the system should:
#   - identify section structure on BOTH sides
#   - route each (sheet, section) -> target section by title similarity
#   - aggregate cross-tab per target section (e.g. Inbound bucket = March.Inbound
#     rows + April.Inbound rows; Outbound bucket = March.Outbound rows)
#   - flag conflicts ONLY when the same anchor value appears in 2+ source rows
#     that route to the same target section (intra-tab AND cross-tab dups
#     unified into one ask-the-user moment)
#
# This runs BEFORE _plan_multi_sheet_auto_route and _plan_multi_sheet_aggregate
# because it is the most precise of the three (it sees per-tab section
# structure, not just flat per-tab columns). The earlier planners only fire
# when this one bails.
# ============================================================================
def _plan_cross_tab_section_aggregate(per_tab_sections, target_sections):
    """Plan per-(source-tab, source-section) -> target-section routing.

    Inputs:
      per_tab_sections: list of {'sheet_name': str, 'sections': [section dicts]}
                        from detect_source_sections per tab. Tabs with 0 usable
                        sections are excluded by the caller (they fall through
                        to the existing flat-tab planners).
      target_sections:  list of section dicts from _detect_sections_local on the
                        target sheet's raw_values.

    Returns:
      {'route_groups': [
          {
            'target_section_index': int,
            'target_section_title': str,
            'sources': [
              {'sheet_name': str, 'section': dict, 'source_section_index': int,
               'source_section_title': str},
              ...
            ],
          },
          ...
        ]}
      OR None when routing is ambiguous (any (sheet, section) doesn't map
      cleanly to a target section). Caller falls back to existing planners.

    Acceptance per (sheet, section):
      - target_section_title strong title match >= SECTION_TITLE_STRONG_MATCH, OR
      - column overlap >= 2 AND dominant (2x runner-up or runner-up == 0)
    Both gates mirror _plan_multi_section_auto_route so behavior is consistent.

    Bail conditions (any => None):
      - <2 source tabs with sections
      - any source tab with 0 detected sections (truly flat)
      - any (sheet, section) has no acceptable target section match
      - target has <2 sections (then existing _plan_multi_sheet_aggregate
        handles the simpler 1-section target case correctly)
    """
    if not target_sections or len(target_sections) < 2:
        print(
            f"   cross-tab-section-aggregate-bail: target has "
            f"{len(target_sections or [])} section(s); needs 2+"
        )
        return None
    usable_tabs = [
        t for t in (per_tab_sections or [])
        if t.get('sections') and len(t['sections']) > 0
    ]
    if len(usable_tabs) < 2:
        print(
            f"   cross-tab-section-aggregate-bail: <2 tabs with sections "
            f"(usable={len(usable_tabs)} of {len(per_tab_sections or [])})"
        )
        return None
    # Any tab that has ZERO sections is flat — this planner can't handle that
    # mix cleanly (we'd be guessing where the flat rows belong). The existing
    # _plan_multi_sheet_aggregate path covers all-flat-tabs. Defer.
    flat_tabs = [
        t.get('sheet_name') for t in (per_tab_sections or [])
        if not t.get('sections')
    ]
    if flat_tabs:
        print(
            f"   cross-tab-section-aggregate-bail: mixed flat/sectioned tabs "
            f"(flat tabs: {flat_tabs}). Defer to flat-tab planners."
        )
        return None

    # Per (sheet, section) -> target section assignment
    target_buckets = {}  # target_section_index -> list of source descriptors
    for tab in usable_tabs:
        sheet_name = tab.get('sheet_name')
        for s_idx, src_sec in enumerate(tab['sections']):
            src_title = src_sec.get('title') or ''
            src_headers = {
                _norm_header(h) for h in (src_sec.get('headers') or []) if h
            }
            if not src_headers:
                print(
                    f"   cross-tab-section-aggregate-bail: source section "
                    f"{sheet_name!r} > #{s_idx} {src_title!r} has no usable headers"
                )
                return None
            scored = []
            for ti, tgt_sec in enumerate(target_sections):
                tgt_headers = {
                    _norm_header(h) for h in (tgt_sec.get('headers') or []) if h
                }
                col_overlap = len(src_headers & tgt_headers)
                title_sim = _local_section_title_similarity(
                    src_title, tgt_sec.get('title'),
                )
                scored.append((col_overlap, title_sim, ti))
            # Sort by (title_sim DESC, overlap DESC, idx ASC) so a strong
            # title match dominates a marginally-better column overlap.
            scored.sort(key=lambda t: (-t[1], -t[0], t[2]))
            best_overlap, best_title_sim, best_idx = scored[0]

            # Acceptance is a 3-tier OR — any of these signals is enough,
            # but ALL of them must rule the candidate IN, not in. We
            # deliberately allow weaker title sim than the intra-tab
            # planner because real-world source files have typos
            # ("Inbound Metrix" vs "Inbound Metrics"), and a perfect
            # column-overlap match with a 50% title hint is still a clearer
            # signal than guessing.
            #
            # Tier 1: very strong title match (>=75%) — accept even if
            #         overlap doesn't dominate. Acts as a definitive vote.
            # Tier 2: column overlap is dominant in the runner-up sense
            #         (best is 2x runner-up OR runner-up is 0) AND >=2
            #         cols. Pure-structure signal.
            # Tier 3: column overlap is high (>= half of source headers)
            #         AND title sim is the UNIQUE max across all targets.
            #         Catches the "tied-columns" case where titles break
            #         the tie even at moderate similarity (the typo case).
            accept_via_title = best_title_sim >= SECTION_TITLE_STRONG_MATCH
            accept_via_overlap = False
            if best_overlap >= 2:
                if len(scored) > 1:
                    runner_overlap = scored[1][0]
                    if runner_overlap == 0 or best_overlap >= 2 * runner_overlap:
                        accept_via_overlap = True
                else:
                    accept_via_overlap = True
            accept_via_title_tiebreak = False
            if best_overlap * 2 >= len(src_headers) and best_title_sim > 0:
                # Title sim must be UNIQUE max (no other target section
                # has the same title sim). Otherwise the tie-break is
                # ambiguous and we'd be guessing.
                title_sims = [t[1] for t in scored]
                max_title_sim = max(title_sims)
                if title_sims.count(max_title_sim) == 1 and best_title_sim == max_title_sim:
                    accept_via_title_tiebreak = True

            if not (accept_via_title or accept_via_overlap or accept_via_title_tiebreak):
                print(
                    f"   cross-tab-section-aggregate-bail: no acceptable "
                    f"target match for {sheet_name!r} > #{s_idx} {src_title!r} "
                    f"(best={best_overlap} cols / {best_title_sim}% title; "
                    f"all_scored={scored})"
                )
                return None
            target_buckets.setdefault(best_idx, []).append({
                'sheet_name':           sheet_name,
                'section':              src_sec,
                'source_section_index': s_idx,
                'source_section_title': src_title,
                'overlap_score':        best_overlap,
                'title_similarity':     best_title_sim,
            })

    route_groups = []
    for tgt_idx in sorted(target_buckets.keys()):
        route_groups.append({
            'target_section_index': tgt_idx,
            'target_section_title': target_sections[tgt_idx].get('title'),
            'sources':              target_buckets[tgt_idx],
        })
    print(
        f"   cross-tab-section-aggregate-pass: "
        + "; ".join(
            f"target #{g['target_section_index']} "
            f"({g['target_section_title']!r}) <- "
            + ", ".join(
                f"{s['sheet_name']!r}.{s['source_section_title']!r}"
                for s in g['sources']
            )
            for g in route_groups
        )
    )
    return {'route_groups': route_groups}


def _aggregate_parse_one_section(file_content, file_type, sheet_name,
                                 source_section, target_schema):
    """Parse + structure + identify-anchor for ONE source SECTION inside the
    intra-tab aggregate / auto-route flow.

    Mirrors _aggregate_parse_one_sheet exactly except:
      - parse_file is called with section=source_section (mapping_agent
        slices the rows to that section's data range).
      - find_identifier is called with source_section_title=
        source_section.get('title') so Fix N's title-similarity tie-
        breaker resolves the target section correctly when the target
        has multiple similarly-shaped sections.

    Returns ``(per_section_state, error_str)`` with the same shape as the
    per_sheet_state dict from the cross-tab path so downstream merge code
    is shared verbatim. The 'sheet_name' field is reused as the source
    label (the section title) to avoid renaming downstream consumers.
    """
    # Headerless sections (Path 2 detection in mapping_agent_api) have a
    # None title — fall back to the sheet name so:
    #   1. find_identifier's source_section_title hint is meaningful
    #      (sheet_name often IS the de-facto section name when the user
    #      didn't bother to add a title row, e.g. "Outbound Metrics" tab
    #      whose first stack is unlabeled headers).
    #   2. The conflict modal label reads "Sheet > Sheet > Row N" — a
    #      bit redundant but unambiguous and recognizable, vs the
    #      previous "Sheet > section > Row N" generic placeholder.
    src_title = source_section.get('title') or sheet_name or 'section'
    parse_result = invoke(MAPPING_LAMBDA, {
        'tool': 'parse_file',
        'inputs': {
            'file_content': file_content,
            'file_type':    file_type,
            'sheet_name':   sheet_name,
            'section':      source_section,
        },
    })
    if not parse_result.get('success'):
        return (None, f"Section {src_title!r}: parse failed — {parse_result.get('error')}")
    source_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_source_data',
        'inputs': {'parse_result': parse_result},
    })
    if not source_schema.get('success'):
        return (None, f"Section {src_title!r}: structure failed — {source_schema.get('error')}")
    _corrected_full_data = source_schema.get('full_data')
    if _corrected_full_data is not None:
        parse_result['full_data'] = _corrected_full_data
    identification = invoke(MAPPING_LAMBDA, {
        'tool': 'find_identifier',
        'inputs': {
            'target_schema':        target_schema,
            'source_schema':        source_schema,
            'source_section_title': src_title,
        },
    })
    if not identification.get('success'):
        return (None, f"Section {src_title!r}: identifier failed — {identification.get('error')}")
    _id_mappings = identification.get('column_mappings') or {}
    if _id_mappings:
        print(f"   section {src_title!r} column_mappings: {_id_mappings}")
    _id_reasoning = identification.get('reasoning')
    if _id_reasoning:
        print(f"   section {src_title!r} identification.reasoning: {_id_reasoning}")
    _prepare_strategy_state(identification, parse_result, source_schema, target_schema)
    write_strategy = identification.get('write_strategy')
    anchor_column  = identification.get('anchor_column')
    source_anchor  = identification.get('source_anchor', anchor_column)
    anchor_type    = (identification.get('anchor_type') or '').lower()
    column_mappings = identification.get('column_mappings') or {}
    source_anchor_names = (
        source_anchor if isinstance(source_anchor, list)
        else ([source_anchor] if source_anchor else [])
    )
    is_date_anchor = (
        write_strategy == 'row_per_date'
        or 'date' in anchor_type
        or (isinstance(anchor_column, str) and 'date' in anchor_column.lower())
    )
    try:
        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
    except Exception:
        full_data = []
    return ({
        # Reuse 'sheet_name' as the source label so the existing
        # _aggregate_build_anchor_map and conflict-emit code work as-is.
        # The label is the section title; downstream consumers display
        # this in the conflict modal as the source identifier.
        'sheet_name':           src_title,
        'source_section_index': source_section.get('__source_section_index'),
        'source_section_title': src_title,
        'parse_result':         parse_result,
        'source_schema':        source_schema,
        'identification':       identification,
        'full_data':            full_data or [],
        'source_anchor_names':  source_anchor_names,
        'is_date_anchor':       is_date_anchor,
        'write_strategy':       write_strategy,
        'anchor_column':        anchor_column,
        'column_mappings':      column_mappings,
    }, None)


def _build_section_target_schema(section, raw_values, target_sheet_name, target_formula_cols):
    """Construct a target_schema dict scoped to a single detected section.

    The returned dict has the same shape as structure_target_data's output
    so find_identifier and the shared diff logic treat the section as if
    it were the whole sheet. Data rows keep their original column positions
    (we don't strip leading empty columns) so header_index lookups into
    raw_rows stay correct — matching what _detect_sections_local produced.
    """
    sec_headers_full = list(section.get('headers') or [])
    header_index = {
        h: i for i, h in enumerate(sec_headers_full) if h and str(h).strip()
    }
    data_start = int(section.get('data_start', 0))
    data_end   = int(section.get('data_end', data_start))
    data_rows  = list(raw_values[data_start:data_end])

    meaningful_headers = [h for h in sec_headers_full if h and str(h).strip()]

    col_samples = {}
    col_types   = {}
    for col_name, col_idx in header_index.items():
        samples = []
        for row in data_rows[:5]:
            val = row[col_idx] if col_idx < len(row) else None
            if val is not None and str(val).strip():
                samples.append(str(val).strip())
        col_samples[col_name] = samples
        col_types[col_name]   = 'unknown'

    section_formula_cols = [h for h in (target_formula_cols or []) if h in header_index]

    return {
        'success':        True,
        'sheet_name':     target_sheet_name,
        'total_rows':     len(data_rows),
        'total_cols':     len(meaningful_headers),
        'headers':        meaningful_headers,
        'header_index':   {h: header_index[h] for h in meaningful_headers},
        'header_row_count': 1,
        'composite_to_col_index': {},
        'sections':       [],
        'col_samples':    col_samples,
        'col_types':      col_types,
        'formula_cols':   section_formula_cols,
        'raw_rows':       [sec_headers_full] + data_rows,
        'is_empty_target': len(data_rows) == 0,
    }


def _auto_pick_source_sheet(sheets):
    """Pick a source sheet when we're confident; otherwise return None for picker.

    Rules (evaluated in order):
      1. Zero sheets        -> None (caller falls back to first sheet).
      2. One sheet          -> auto-pick it.
      3. Exactly one sheet  -> that one (only it has target overlap).
         has score > 0
      4. Best score  >= 2x  -> auto-pick (dominant winner, no tie).
         second-best score
      5. Otherwise          -> None -> surface picker to user.

    ``sheets`` is the list returned by mapping_agent.detect_source_sheets, each
    entry with keys: name, headers, data_rows, score, meaningful_headers.
    """
    if not sheets:
        return None
    if len(sheets) == 1:
        return sheets[0].get('name')

    # Prefer sheets with any data and any meaningful headers so a blank/junk
    # sheet never silently wins. If ALL sheets fail this, fall back to raw list
    # so we don't deadlock.
    usable = [s for s in sheets if (s.get('data_rows') or 0) > 0 and (s.get('meaningful_headers') or 0) > 0]
    if not usable:
        usable = list(sheets)

    ranked = sorted(usable, key=lambda s: (s.get('score', 0), s.get('data_rows', 0)), reverse=True)
    best = ranked[0]
    best_score = best.get('score', 0) or 0

    top_scorers = [s for s in usable if (s.get('score', 0) or 0) > 0]
    if len(top_scorers) == 1 and best_score > 0:
        return top_scorers[0].get('name')

    if len(ranked) >= 2:
        runner_up_score = ranked[1].get('score', 0) or 0
        if best_score >= 2 and best_score >= 2 * max(runner_up_score, 1):
            return best.get('name')

    return None


def _auto_pick_source_section(sections, target_headers):
    """Pick a source section when one clearly dominates by target overlap.

    Mirrors _auto_pick_source_sheet's conservatism. Returns a section index
    (int) when we're confident, otherwise None so the caller surfaces the
    picker to the user. A guess here is strictly worse than a picker because
    we'd write someone else's data into the wrong target slice.

    Rules (evaluated in order):
      1. No sections / no target_headers -> None.
      2. After filtering to sections with > 0 data rows:
         - Zero usable sections -> None.
         - One usable section with overlap > 0 -> auto-pick.
         - Exactly one section has any target overlap -> auto-pick that one.
         - Best score >= 2 and best >= 2 * runner-up -> auto-pick.
         - Otherwise -> None (picker).

    ``sections`` comes from detect_source_sections; each dict exposes
    ``headers`` (list[str]) and usually ``row_count`` / ``data_rows``.
    """
    if not sections or not target_headers:
        return None

    target_set = {_norm_header(h) for h in target_headers if h}
    if not target_set:
        return None

    scored = []
    for i, sec in enumerate(sections):
        data_rows = sec.get('row_count')
        if data_rows is None:
            data_rows = sec.get('data_rows', 0)
        if (data_rows or 0) <= 0:
            continue
        sec_headers = {_norm_header(h) for h in (sec.get('headers') or []) if h}
        overlap = len(target_set & sec_headers)
        scored.append((overlap, i, data_rows or 0))

    if not scored:
        return None

    scored.sort(key=lambda t: (t[0], t[2]), reverse=True)
    best_score, best_idx, _ = scored[0]

    if best_score <= 0:
        return None

    if len(scored) == 1:
        return best_idx

    positive = [t for t in scored if t[0] > 0]
    if len(positive) == 1:
        return positive[0][1]

    runner_up_score = scored[1][0]
    if best_score >= 2 and best_score >= 2 * max(runner_up_score, 1):
        return best_idx

    return None


def _auto_pick_target_tab(tabs_overlap, user_chosen_tab=None):
    """Pick a target tab when one clearly dominates by anchor overlap.

    Used by Step 0c (multi-tab anchor-overlap picker). Mirrors the
    conservatism of _auto_pick_source_section / _auto_pick_source_sheet:
    only return a name when one tab dominates, otherwise return None so
    the caller surfaces a picker to the user.

    Rules:
      1. No tabs                      -> None.
      2. Zero tabs with overlap > 0   -> None (picker would be useless;
                                          caller skips and writes to user's
                                          original tab).
      3. Exactly one tab w/ overlap>0 -> auto-pick that one (might be the
                                          user's choice or another tab).
      4. user_chosen_tab is itself in the overlapping set AND its overlap
         is >= half the best non-user tab -> respect user choice.
      5. Best overlap >= 2 and >= 2x runner-up -> auto-pick best.
      6. Otherwise                    -> None (genuine ambiguity, picker).

    ``tabs_overlap`` is the list under ``detect_target_tab_overlap['tabs']``;
    each entry exposes ``name`` and ``overlap_count``.
    """
    if not tabs_overlap:
        return None

    positive = [t for t in tabs_overlap if (t.get('overlap_count') or 0) > 0]
    if not positive:
        return None
    if len(positive) == 1:
        return positive[0].get('name')

    ranked = sorted(positive, key=lambda t: t.get('overlap_count') or 0, reverse=True)
    best = ranked[0]
    best_score = best.get('overlap_count') or 0
    runner_up_score = ranked[1].get('overlap_count') or 0

    # Respect a user's existing choice when it sits inside the positive set
    # and isn't dramatically beaten by another tab. Saves an unnecessary
    # picker prompt for the common case "user picked the right tab and a
    # second tab happens to share a few values".
    if user_chosen_tab:
        for t in positive:
            if t.get('name') == user_chosen_tab:
                if (t.get('overlap_count') or 0) >= max(1, best_score // 2):
                    return user_chosen_tab
                break

    if best_score >= 2 and best_score >= 2 * max(runner_up_score, 1):
        return best.get('name')

    return None


def _preview_multi_sheet_auto_route(
    file_content, file_type, target_sheet_name, raw_values, target_sections,
    routes, formula_cols
):
    """Run preview per (source_sheet → target_section) route and aggregate.

    Each route runs a mini preview pipeline (parse, structure, find_identifier,
    diff). Returns a single preview response with:
      - ``write_strategy = 'multi_sheet_section'``
      - aggregated conflicts / empty_cells / appended_rows_preview / rows_*
      - a ``strategy_metadata.routes`` list carrying per-route write plans
        (write_strategy, anchor_column, column_mappings, section_index, …)
        so run_dynamic_mapping can confirm without re-running find_identifier.

    Columns from different routes live in different target sections so they
    don't collide. Column_mappings in the top-level response is the UNION
    across routes (identity-preserving) so the existing UI that renders
    {source → target} badges still works end-to-end.
    """
    agg_conflicts          = []
    agg_empty_cells        = []
    agg_appended_rows      = []
    agg_rows_to_update     = []
    agg_rows_to_append     = []
    agg_column_mappings    = {}
    agg_source_columns_set = []
    agg_target_headers_set = []
    route_results          = []
    rows_in_source_total   = 0
    rows_in_target_total   = 0
    diff_total_cells       = 0
    diff_truncated         = False

    for route in routes:
        sheet_name     = route['sheet_name']
        # Source-section slice: present when the planner is the intra-tab
        # _plan_multi_section_auto_route variant. None for the original
        # cross-tab path. Carrying the section dict in the route lets the
        # single per-route block below stay symmetrical for both shapes —
        # we just thread it through parse_file + find_identifier on the
        # intra-tab path.
        source_section       = route.get('source_section')
        source_section_title = route.get('source_section_title') or (
            source_section.get('title') if isinstance(source_section, dict) else None
        )
        section_index  = route['section_index']
        section        = target_sections[section_index]
        section_title  = section.get('title')

        scope_label = (
            f"sheet {sheet_name!r} / section {source_section_title!r}"
            if source_section
            else f"sheet {sheet_name!r}"
        )
        print(f"   Auto-route: previewing {scope_label} → target section #{section_index} '{section_title}'")

        parse_inputs = {
            'file_content': file_content,
            'file_type':    file_type,
            'sheet_name':   sheet_name,
        }
        if source_section:
            parse_inputs['section'] = source_section
        parse_result = invoke(MAPPING_LAMBDA, {
            'tool': 'parse_file',
            'inputs': parse_inputs,
        })
        if not parse_result.get('success'):
            return {
                'success': False,
                'error': f"Route parse failed for {scope_label}: {parse_result.get('error')}"
            }

        source_schema = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_source_data',
            'inputs': {'parse_result': parse_result}
        })
        if not source_schema.get('success'):
            return {
                'success': False,
                'error': f"Route structure failed for {scope_label}: {source_schema.get('error')}"
            }
        # Patch parse_result with the grouped-header-aware ``full_data``
        # so downstream anchor extraction and transform_data invocations
        # for this auto-routed section see composite-keyed rows.
        _corrected_full_data = source_schema.get('full_data')
        if _corrected_full_data is not None:
            parse_result['full_data'] = _corrected_full_data

        section_target = _build_section_target_schema(
            section, raw_values, target_sheet_name, formula_cols
        )

        if section_target.get('is_empty_target'):
            src_hdrs = source_schema.get('headers', [])
            identification = {
                'success':         True,
                'write_strategy':  'append',
                'anchor_column':   None,
                'source_anchor':   None,
                'anchor_type':     '',
                'column_mappings': {h: h for h in src_hdrs if h in section_target['header_index']
                                    or _norm_header(h) in {_norm_header(th) for th in section_target['headers']}},
                'reasoning': f"Target section {section_title!r} is empty; appending all source rows.",
            }
            if not identification['column_mappings']:
                identification['column_mappings'] = {h: h for h in src_hdrs}
            section_target['headers']      = list(identification['column_mappings'].values())
            section_target['header_index'] = {h: i for i, h in enumerate(section_target['headers'])}
        else:
            id_inputs = {
                'target_schema': section_target,
                'source_schema': source_schema,
            }
            # Pass the SOURCE section title on the intra-tab path so Fix N's
            # title-similarity tie-breaker can disambiguate when the route's
            # target_schema (built via _build_section_target_schema) has a
            # title shape similar to other target sections we excluded.
            if source_section_title:
                id_inputs['source_section_title'] = source_section_title
            identification = invoke(MAPPING_LAMBDA, {
                'tool': 'find_identifier',
                'inputs': id_inputs,
            })
            if not identification.get('success'):
                return {
                    'success': False,
                    'error': f"Route identifier failed for {scope_label}: {identification.get('error')}"
                }

        _prepare_strategy_state(identification, parse_result, source_schema, section_target)

        route_strategy  = identification.get('write_strategy') or 'append'
        route_anchor    = identification.get('anchor_column')
        route_mappings  = identification.get('column_mappings') or {}
        route_source_anchor = identification.get('source_anchor', route_anchor)
        route_anchor_type   = (identification.get('anchor_type') or '').lower()

        # Strip anchor + formula cols from writable mappings for diffing.
        anchor_col_set = set(route_anchor) if isinstance(route_anchor, list) else ({route_anchor} if route_anchor else set())
        formula_col_set = set(section_target.get('formula_cols', []) or [])
        write_mappings = {
            k: v for k, v in route_mappings.items()
            if v and v not in anchor_col_set and v not in formula_col_set
        }

        target_to_source = {tgt: src for src, tgt in write_mappings.items()}

        source_anchor_names = (
            route_source_anchor if isinstance(route_source_anchor, list)
            else ([route_source_anchor] if route_source_anchor else [])
        )
        is_date_anchor = (
            route_strategy == 'row_per_date'
            or 'date' in route_anchor_type
            or (isinstance(route_anchor, str) and 'date' in route_anchor.lower())
        )

        try:
            full_data = parse_result.get('full_data', '[]')
            if isinstance(full_data, str):
                full_data = json.loads(full_data)
        except Exception:
            full_data = []

        src_anchor_values = set()
        src_row_by_anchor = {}
        for src_row in full_data or []:
            parts = []
            for sa in source_anchor_names:
                val = src_row.get(sa)
                if val is not None:
                    normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                    if normed:
                        parts.append(normed)
            if parts:
                anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
                src_anchor_values.add(anchor_val)
                key = anchor_val if is_date_anchor else anchor_val.lower()
                src_row_by_anchor[key] = src_row

        header_index = section_target.get('header_index', {})
        raw_rows     = section_target.get('raw_rows', [])
        section_data_rows = raw_rows[1:] if raw_rows else []
        target_cols_to_write = list(write_mappings.values())

        route_conflicts      = []
        route_empty_cells    = []
        route_appended_rows  = []
        rows_to_update_route = []
        rows_to_append_route = []

        if route_strategy in ('row_per_date', 'row_per_entity', 'composite_key',
                              'multi_section', 'cross_tab', 'horizontal',
                              'key_value') and route_anchor:
            anchor_cols = route_anchor if isinstance(route_anchor, list) else [route_anchor]
            anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

            src_check = {(v if is_date_anchor else v.lower()) for v in src_anchor_values}
            walk_rows = section_data_rows if src_check else []

            for row in walk_rows:
                parts = []
                for ai in anchor_idxs:
                    val = row[ai] if ai is not None and ai < len(row) else None
                    if val:
                        normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                        parts.append(normed)
                anchor_val = '|'.join(parts) if len(parts) > 1 else (parts[0] if parts else None)
                if not anchor_val:
                    continue
                check = anchor_val if is_date_anchor else anchor_val.lower()
                if check not in src_check:
                    continue

                src_row = src_row_by_anchor.get(check, {})
                for col_name in target_cols_to_write:
                    col_idx = header_index.get(col_name)
                    if col_idx is None:
                        continue
                    existing = row[col_idx] if col_idx < len(row) else None
                    existing_str = str(existing).strip() if existing is not None else ''
                    if existing_str.startswith('='):
                        continue
                    source_col = target_to_source.get(col_name)
                    new_raw    = src_row.get(source_col) if source_col else None
                    new_value  = _format_cell_value(new_raw)
                    if new_value == '' or new_raw is None:
                        continue

                    diff_total_cells += 1
                    if diff_total_cells > MAX_DIFF_CELLS:
                        diff_truncated = True
                        continue

                    entry_prefix = f"[{section_title}] " if section_title else ""
                    if existing_str:
                        route_conflicts.append({
                            'anchor_value':   f"{entry_prefix}{anchor_val}",
                            'column':         col_name,
                            'existing_value': existing_str,
                            'new_value':      new_value,
                            'section':        section_title,
                        })
                    else:
                        route_empty_cells.append({
                            'anchor_value': f"{entry_prefix}{anchor_val}",
                            'column':       col_name,
                            'new_value':    new_value,
                            'section':      section_title,
                        })

            target_anchor_set = set()
            for row in section_data_rows:
                parts = []
                for ac in anchor_cols:
                    ai = header_index.get(ac)
                    val = row[ai] if ai is not None and ai < len(row) else None
                    if val:
                        parts.append(
                            _normalize_date_value(val) if is_date_anchor else str(val).strip().lower()
                        )
                if parts:
                    target_anchor_set.add('|'.join(parts) if len(parts) > 1 else parts[0])

            for v in sorted(src_anchor_values):
                check = v if is_date_anchor else v.lower()
                if check in target_anchor_set:
                    rows_to_update_route.append(v)
                else:
                    rows_to_append_route.append(v)

            for anchor_val in rows_to_append_route:
                key = anchor_val if is_date_anchor else anchor_val.lower()
                src_row = src_row_by_anchor.get(key)
                if not src_row:
                    continue
                cells = list(_preview_anchor_cells(
                    anchor_col_set, source_anchor_names, src_row,
                    str(anchor_val), is_date_anchor,
                ))
                for tgt_col in target_cols_to_write:
                    src_col = target_to_source.get(tgt_col)
                    if not src_col:
                        continue
                    new_value = _format_cell_value(src_row.get(src_col))
                    diff_total_cells += 1
                    if diff_total_cells > MAX_DIFF_CELLS:
                        diff_truncated = True
                        continue
                    cells.append({'column': tgt_col, 'new_value': new_value})
                if cells:
                    route_appended_rows.append({
                        'anchor_value': str(anchor_val),
                        'section':      section_title,
                        'cells':        cells,
                    })
        else:
            rows_to_append_route = [f"row_{i + 1}" for i in range(len(full_data or []))]
            for i, src_row in enumerate(full_data or []):
                cells = list(_preview_anchor_cells(
                    anchor_col_set, source_anchor_names, src_row,
                    f"row_{i + 1}", is_date_anchor,
                ))
                for tgt_col in target_cols_to_write:
                    src_col = target_to_source.get(tgt_col)
                    if not src_col:
                        continue
                    new_value = _format_cell_value(src_row.get(src_col))
                    diff_total_cells += 1
                    if diff_total_cells > MAX_DIFF_CELLS:
                        diff_truncated = True
                        continue
                    cells.append({'column': tgt_col, 'new_value': new_value})
                if cells:
                    route_appended_rows.append({
                        'anchor_value': f"row_{i + 1}",
                        'section':      section_title,
                        'cells':        cells,
                    })

        agg_conflicts.extend(route_conflicts)
        agg_empty_cells.extend(route_empty_cells)
        agg_appended_rows.extend(route_appended_rows)
        agg_rows_to_update.extend(f"{section_title}::{v}" for v in rows_to_update_route)
        agg_rows_to_append.extend(f"{section_title}::{v}" for v in rows_to_append_route)

        for src, tgt in write_mappings.items():
            if tgt and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt

        for h in source_schema.get('headers', []) or []:
            if h not in agg_source_columns_set:
                agg_source_columns_set.append(h)
        for h in section_target.get('headers', []) or []:
            if h not in agg_target_headers_set:
                agg_target_headers_set.append(h)

        rows_in_source_total += source_schema.get('total_rows', 0) or 0
        rows_in_target_total += section_target.get('total_rows', 0) or 0

        route_results.append({
            'sheet_name':           sheet_name,
            # Echo source_section + source_section_title back into the
            # route plan so the confirm path's _run_multi_sheet_auto_route
            # can re-parse with the exact same slice (intra-tab path).
            # Plain dict / str values, JSON-serializable for the
            # strategy_metadata round-trip through the FE.
            'source_section':       source_section,
            'source_section_title': source_section_title,
            'section_index':        section_index,
            'section_title':        section_title,
            'write_strategy':       route_strategy,
            'anchor_column':        route_anchor,
            'source_anchor':        route_source_anchor,
            'anchor_type':          identification.get('anchor_type'),
            'column_mappings':      route_mappings,
            'rows_to_update':       len(rows_to_update_route),
            'rows_to_append':       len(rows_to_append_route),
        })

    print(
        f"   Auto-route preview: {len(routes)} routes, "
        f"{len(agg_conflicts)} overwrites + {len(agg_empty_cells)} fills + "
        f"{len(agg_appended_rows)} new rows "
        f"(total cells: {diff_total_cells}, truncated: {diff_truncated})"
    )

    return {
        'success':          True,
        'preview':          True,
        'write_strategy':   'multi_sheet_section',
        'anchor_column':    None,
        'source_anchor':    None,
        'anchor_type':      '',
        'reasoning': (
            f"Auto-routing {len(routes)} source sheets to {len(routes)} target "
            f"sections: "
            + ", ".join(f"{r['sheet_name']!r}→{r['section_title']!r}" for r in routes)
        ),
        'source_columns':   agg_source_columns_set,
        'target_headers':   agg_target_headers_set,
        'column_mappings':  agg_column_mappings,
        'unmapped_source':  [],
        'rows_in_source':   rows_in_source_total,
        'rows_in_target':   rows_in_target_total,
        'source_col_types': {},
        'target_col_types': {},
        'formula_cols':     list(formula_cols or []),
        'conflicts':        agg_conflicts,
        'empty_cells':      agg_empty_cells,
        'appended_rows_preview': agg_appended_rows,
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   agg_rows_to_update,
        'rows_to_append':   agg_rows_to_append,
        'rows_to_update_count': len(agg_rows_to_update),
        'rows_to_append_count': len(agg_rows_to_append),
        'is_empty_target':  False,
        'header_row_count': 1,
        'composite_to_col_index': {},
        'sheet_name':           None,
        'auto_selected_sheet':  None,
        'strategy_metadata': {
            'auto_route': True,
            'routes':     route_results,
        },
        'pivot_source_col': None,
        'value_source_col': None,
    }


def _aggregate_parse_one_sheet(
    file_content, file_type, sheet_name, target_schema,
    cached_identification=None,
):
    """Parse + structure + identify-anchor for ONE source sheet inside the
    aggregate flow.

    Returns ``(per_sheet_state, error_str)``. ``per_sheet_state`` is a dict
    with everything the aggregate preview/run paths need to merge results
    across sheets without re-parsing:
      ``parse_result``, ``source_schema``, ``identification``, ``full_data``,
      ``source_anchor_names``, ``is_date_anchor``, ``write_strategy``,
      ``anchor_column``, ``column_mappings``.
    On parse / structure / find_identifier failure, returns
    ``(None, "Sheet 'X': <reason>")`` so the caller can either skip or abort.

    When ``cached_identification`` is provided (confirm path replay), we
    skip the ``find_identifier`` LLM call entirely and use the cached
    ``column_mappings`` / ``write_strategy`` / ``anchor_column`` /
    ``source_anchor`` / ``anchor_type`` that the preview already computed.
    The XLSX parse + structure_source_data calls still run because the
    raw rows aren't cached (would balloon the response payload past
    Lambda's 6 MB synchronous-invoke limit). This is the per-sheet
    counterpart of ``run_dynamic_mapping``'s ``use_cache`` branch and
    cuts column-merge confirm time from ~17s of LLM work to ~0s.
    """
    parse_result = invoke(MAPPING_LAMBDA, {
        'tool': 'parse_file',
        'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
    })
    if not parse_result.get('success'):
        return (None, f"Sheet {sheet_name!r}: parse failed — {parse_result.get('error')}")

    source_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_source_data',
        'inputs': {'parse_result': parse_result}
    })
    if not source_schema.get('success'):
        return (None, f"Sheet {sheet_name!r}: structure failed — {source_schema.get('error')}")
    # Patch parse_result with the grouped-header-aware ``full_data`` so
    # the per-sheet aggregate state below carries composite-keyed rows
    # for cross-sheet anchor matching and conflict detection.
    _corrected_full_data = source_schema.get('full_data')
    if _corrected_full_data is not None:
        parse_result['full_data'] = _corrected_full_data

    if cached_identification:
        # Replay the preview's identification decision verbatim. We mark
        # success=True so the downstream check passes and re-emit the
        # cached column_mappings/anchor/strategy fields find_identifier
        # would have produced. The reasoning string is overridden with a
        # cache-hit marker so CloudWatch makes it obvious which sheets
        # skipped the LLM (vs which ones fell through and called it).
        identification = {
            'success':          True,
            'write_strategy':   cached_identification.get('write_strategy'),
            'anchor_column':    cached_identification.get('anchor_column'),
            'source_anchor':    cached_identification.get(
                'source_anchor',
                cached_identification.get('anchor_column'),
            ),
            'anchor_type':      cached_identification.get('anchor_type', ''),
            'column_mappings':  cached_identification.get('column_mappings') or {},
            'reasoning':        '[cached-from-preview: skipped find_identifier LLM call]',
        }
        # Preserve any extra cached fields the strategy may need (cross_tab
        # pivot/value cols, period_columns, label_column, etc.) so
        # _prepare_strategy_state can reconstruct strategy state without
        # the LLM. Unknown keys passthrough so this stays forward-compatible
        # with future identification fields.
        for _passthrough in (
            'pivot_source_col', 'value_source_col',
            'period_columns', 'label_column',
            'section_index', 'target_section_index',
        ):
            if _passthrough in cached_identification:
                identification[_passthrough] = cached_identification[_passthrough]
    else:
        identification = invoke(MAPPING_LAMBDA, {
            'tool': 'find_identifier',
            'inputs': {'target_schema': target_schema, 'source_schema': source_schema}
        })
        if not identification.get('success'):
            return (None, f"Sheet {sheet_name!r}: identifier failed — {identification.get('error')}")

    # Aggregate path: per-sheet column mapping logging so we can diff per
    # sheet how the AI mapped each tab independently. Critical for
    # debugging cross-sheet inconsistencies (sheet A maps Cases→Receiving,
    # sheet B maps Cases→Dispatched — we'd silently write to two
    # different target columns without this trace).
    _id_mappings = identification.get('column_mappings') or {}
    if _id_mappings:
        print(f"   sheet {sheet_name!r} column_mappings: {_id_mappings}")
    _id_reasoning = identification.get('reasoning')
    if _id_reasoning:
        print(f"   sheet {sheet_name!r} identification.reasoning: {_id_reasoning}")

    _prepare_strategy_state(identification, parse_result, source_schema, target_schema)

    write_strategy  = identification.get('write_strategy')
    anchor_column   = identification.get('anchor_column')
    source_anchor   = identification.get('source_anchor', anchor_column)
    anchor_type     = (identification.get('anchor_type') or '').lower()
    column_mappings = identification.get('column_mappings') or {}

    source_anchor_names = (
        source_anchor if isinstance(source_anchor, list)
        else ([source_anchor] if source_anchor else [])
    )
    is_date_anchor = (
        write_strategy == 'row_per_date'
        or 'date' in anchor_type
        or (isinstance(anchor_column, str) and 'date' in anchor_column.lower())
    )

    try:
        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
    except Exception:
        full_data = []

    return ({
        'sheet_name':          sheet_name,
        'parse_result':        parse_result,
        'source_schema':       source_schema,
        'identification':      identification,
        'full_data':           full_data or [],
        'source_anchor_names': source_anchor_names,
        'is_date_anchor':      is_date_anchor,
        'write_strategy':      write_strategy,
        'anchor_column':       anchor_column,
        'column_mappings':     column_mappings,
    }, None)


def _aggregate_build_anchor_map(per_sheet_state):
    """Build ``{anchor_value: src_row}`` for ONE sheet, skipping rows whose
    anchor is empty/N-A.

    The lookup_key inside each entry follows the same convention as the
    single-sheet path (raw for date anchors, lowercased otherwise). Returns
    ``{lookup_key: {'display': anchor_val, 'src_row': src_row}}`` so the
    caller knows the human-readable anchor for the conflict modal AND the
    normalized key for cross-sheet conflict detection.
    """
    anchor_map = {}
    is_date_anchor = per_sheet_state['is_date_anchor']
    source_anchor_names = per_sheet_state['source_anchor_names']

    for src_row in per_sheet_state['full_data']:
        parts = []
        for sa in source_anchor_names:
            val = src_row.get(sa)
            if val is None:
                continue
            normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
            if normed:
                parts.append(normed)
        if not parts:
            continue
        anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
        lookup_key = anchor_val if is_date_anchor else anchor_val.lower()
        anchor_map[lookup_key] = {'display': anchor_val, 'src_row': src_row}

    return anchor_map


def _preview_multi_sheet_aggregate_append(
    per_sheet_states, section_target, target_sheet_name, section_title,
    target_section_index, aggregated_sheet_names, aggregated_sections,
    is_section_aggregate,
):
    """Append-mode aggregate preview: every source row -> a new row appended
    at the bottom of the target section. No anchor matching, no cross-sheet
    conflicts, no orphan-skip semantics.

    Each row in ``appended_rows_preview`` carries:
      - ``anchor_value`` of the form ``"<sheet_name> #<N>"`` so the FE can
        render a per-source-tab badge AND the run path can match the
        ``allowed_append_anchors`` filter back to the originating row.
        We don't need this string to be a real anchor — append rows are
        identified positionally on the run side, not by anchor lookup.
      - ``cells`` projected through the per-sheet column_mappings; anchor
        and formula columns are stripped so we never overwrite live
        formulas or pollute identity columns.
      - ``source_sheet`` so the FE's diff renderer can show a per-row
        Source badge identical to the row-keyed aggregate path.
    """
    formula_col_set = set(section_target.get('formula_cols', []) or [])

    appended_rows_preview = []
    diff_total_cells = 0
    diff_truncated   = False

    for st in per_sheet_states:
        sheet_name      = st['sheet_name']
        # Section-aggregate sources carry a section title alongside the
        # parent tab name. Use the most-specific label for the row id so
        # two sections in the same tab don't collide on the
        # ``allowed_append_anchors`` filter on the run side.
        section_title_local = st.get('source_section_title')
        if section_title_local and section_title_local != sheet_name:
            row_label = f"{sheet_name} - {section_title_local}"
        else:
            row_label = sheet_name
        column_mappings = st.get('column_mappings') or {}
        full_data       = st.get('full_data') or []
        anchor_col_set_local = (
            set(st['anchor_column']) if isinstance(st['anchor_column'], list)
            else ({st['anchor_column']} if st['anchor_column'] else set())
        )
        # Strip anchor + formula columns from the writable mapping. The
        # anchor strip is a defensive no-op for append (anchor is
        # typically None) but keeps the projection consistent with the
        # row-keyed path so we never accidentally write into a target
        # identity column.
        sheet_mappings = {
            src: tgt for src, tgt in column_mappings.items()
            if tgt and tgt not in anchor_col_set_local and tgt not in formula_col_set
        }
        if not sheet_mappings:
            continue
        target_to_source = {tgt: src for src, tgt in sheet_mappings.items()}
        target_cols_to_write = list(sheet_mappings.values())

        for i, src_row in enumerate(full_data):
            cells = []
            for tgt_col in target_cols_to_write:
                src_col = target_to_source.get(tgt_col)
                if not src_col:
                    continue
                new_value = _format_cell_value(src_row.get(src_col))
                diff_total_cells += 1
                if diff_total_cells > MAX_DIFF_CELLS:
                    diff_truncated = True
                    continue
                cells.append({'column': tgt_col, 'new_value': new_value})
            if not cells:
                continue
            appended_rows_preview.append({
                'anchor_value': f"{row_label} #{i + 1}",
                'cells':        cells,
                'source_sheet': row_label,
            })

    label_aggregated_sheets = (
        [st.get('source_section_title') or st.get('sheet_name')
         for st in per_sheet_states]
        if is_section_aggregate
        else aggregated_sheet_names
    )
    final_strategy = (
        'multi_section_aggregate' if is_section_aggregate
        else 'multi_sheet_aggregate'
    )
    final_strategy_metadata = {
        'aggregate':              True,
        'conflict_resolutions':   {},
        'target_section_index':   target_section_index,
        'underlying_strategy':    'append',
        'anchor_columns':         None,
    }
    if is_section_aggregate:
        final_strategy_metadata['aggregated_sections'] = list(aggregated_sections or [])
    else:
        final_strategy_metadata['aggregated_sheet_names'] = aggregated_sheet_names

    # Aggregate column_mappings union for the response payload (preview
    # diff renderer reads this for header ordering).
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and tgt not in formula_col_set and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt

    agg_source_cols = []
    for st in per_sheet_states:
        for h in st['source_schema'].get('headers', []) or []:
            if h not in agg_source_cols:
                agg_source_cols.append(h)
    rows_in_source_total = sum(
        st['source_schema'].get('total_rows', 0) or 0 for st in per_sheet_states
    )
    sources_label_for_reasoning = ", ".join(
        repr(st.get('source_section_title') or st.get('sheet_name'))
        for st in per_sheet_states
    )

    print(
        f"   Aggregate-append diff: {len(appended_rows_preview)} new rows "
        f"from {len(per_sheet_states)} source(s) "
        f"(total cells: {diff_total_cells}, truncated: {diff_truncated})"
    )

    return {
        'success':          True,
        'preview':          True,
        'aggregate_mode':   True,
        'aggregated_sheets': label_aggregated_sheets,
        'write_strategy':   final_strategy,
        'underlying_strategy': 'append',
        'anchor_column':    None,
        'source_anchor':    None,
        'anchor_type':      '',
        'reasoning': (
            f"Aggregating {len(per_sheet_states)} source "
            f"{'section' if is_section_aggregate else 'sheet'}(s) ("
            + sources_label_for_reasoning
            + f") into target tab {target_sheet_name!r}"
            + (f" (section: {section_title!r})" if section_title else "")
            + ". Append-mode — every source row becomes a new row appended "
            "at the bottom of the target."
        ),
        'source_columns':   agg_source_cols,
        'target_headers':   list(section_target.get('headers', []) or []),
        'column_mappings':  agg_column_mappings,
        'unmapped_source':  [],
        'rows_in_source':   rows_in_source_total,
        'rows_in_target':   section_target.get('total_rows', 0) or 0,
        'source_col_types': {},
        'target_col_types': section_target.get('col_types', {}) or {},
        'formula_cols':     list(section_target.get('formula_cols', []) or []),
        'conflicts':        [],
        'empty_cells':      [],
        'appended_rows_preview': appended_rows_preview,
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   [],
        'rows_to_append':   [r['anchor_value'] for r in appended_rows_preview],
        'rows_to_update_count': 0,
        'rows_to_append_count': len(appended_rows_preview),
        'skipped_no_match': [],
        'is_empty_target':  bool(section_target.get('is_empty_target')),
        'header_row_count': section_target.get('header_row_count', 1) or 1,
        'composite_to_col_index': section_target.get('composite_to_col_index', {}) or {},
        'sheet_name':           None,
        'auto_selected_sheet':  None,
        'strategy_metadata':    final_strategy_metadata,
        'pivot_source_col':     None,
        'value_source_col':     None,
    }


def _preview_multi_sheet_aggregate(
    inputs, file_content, file_type, target_sheet_name, raw_values,
    target_schema, formula_cols, aggregated_sheet_names,
    target_section_index, conflict_choices,
    aggregated_sections=None,
):
    """Aggregate-mode preview: merge N source sheets OR sections into one target tab/section.

    See _plan_multi_sheet_aggregate / _plan_multi_section_aggregate for
    the gates. This function:
      1. Per source sheet (or section, when ``aggregated_sections`` is
         provided) → parse, structure, find_identifier, build a per-source
         ``{anchor: src_row}`` map (empty/N-A anchors silently skipped).
      2. Cross-source conflict scan — anchor present in 2+ sources becomes
         a "conflict" the user must resolve (or explicitly skip).
      3. If unresolved conflicts AND no ``conflict_choices`` provided →
         early-return ``requires_conflict_resolution=True`` with the rich
         candidate payload (every mapped column for every candidate row).
      4. Apply ``conflict_choices`` to merge into a single anchor map.
      5. Diff merged map vs target rows. Matched anchors → rows_to_update +
         per-cell conflicts/empty_cells. Unmatched (orphan) anchors →
         ``skipped_no_match`` panel (NOT rows_to_append — aggregate mode
         is update-only by design).

    The intra-tab path (aggregated_sections != None) is wired by passing
    a list of ``{'sheet_name': str, 'section': dict, 'source_section_index': int}``
    items. The function then calls ``_aggregate_parse_one_section`` per
    item instead of ``_aggregate_parse_one_sheet``. Everything else
    (conflict detection, merge, diff, return shape) is identical, so
    the FE ConflictModal renders intra-tab section conflicts using the
    exact same payload it uses for cross-tab sheet conflicts. The
    candidate label per source becomes the section title rather than
    the sheet name. ``write_strategy`` is set to ``'multi_section_aggregate'``
    on the intra-tab path so the confirm dispatcher can route correctly.

    The resulting payload follows the same shape as the single-sheet
    preview so the existing UI renders without changes, plus a few
    aggregate-only fields:
      ``aggregate_mode``, ``aggregated_sheets``, ``skipped_no_match``,
      ``requires_conflict_resolution``, ``conflicts_to_resolve``,
      ``strategy_metadata.aggregate``,
      ``strategy_metadata.aggregated_sheet_names`` /
      ``strategy_metadata.aggregated_sections``,
      ``strategy_metadata.conflict_resolutions``.
    """
    is_section_aggregate = bool(aggregated_sections)
    if is_section_aggregate:
        source_count = len(aggregated_sections)
    else:
        source_count = len(aggregated_sheet_names)
    print(
        f"Aggregate preview: {source_count} "
        f"{'section(s)' if is_section_aggregate else 'sheet(s)'} → "
        f"{target_sheet_name!r} (target_section_index={target_section_index})"
    )

    # Resolve target section schema (whole-sheet when section_index is None,
    # single-section slice otherwise). Reuses existing helpers so behavior
    # matches the single-sheet path verbatim.
    if target_section_index is None:
        section_target = dict(target_schema)
        section_title  = None
    else:
        sections_local = _detect_sections_local(raw_values or [])
        if 0 <= target_section_index < len(sections_local):
            section = sections_local[target_section_index]
            section_target = _build_section_target_schema(
                section, raw_values, target_sheet_name, formula_cols
            )
            section_title = section.get('title')
        else:
            return {
                'success': False,
                'error': (
                    f'Aggregate preview could not resolve target_section_index='
                    f'{target_section_index} against current target sheet.'
                ),
                'error_type': 'invalid_target_section',
            }

    # Per-source parse + structure + identify (sheet OR section path).
    per_sheet_states = []
    aggregated_errors = []
    if is_section_aggregate:
        for src_item in aggregated_sections:
            src_sheet_name = src_item.get('sheet_name')
            src_section    = src_item.get('section') or {}
            # Annotate the section with its parent index so
            # _aggregate_parse_one_section can echo it into per-section
            # state for the confirm path's re-parse.
            if 'source_section_index' in src_item:
                src_section = dict(src_section)
                src_section['__source_section_index'] = src_item['source_section_index']
            state, err = _aggregate_parse_one_section(
                file_content, file_type, src_sheet_name, src_section, section_target,
            )
            if err:
                return {'success': False, 'error': err, 'error_type': 'aggregate_section_failed'}
            per_sheet_states.append(state)
    else:
        for sheet_name in aggregated_sheet_names:
            state, err = _aggregate_parse_one_sheet(
                file_content, file_type, sheet_name, section_target
            )
            if err:
                # A single-sheet failure aborts aggregate preview — partial
                # aggregation would silently drop one tab's worth of rows
                # without telling the user.
                return {'success': False, 'error': err, 'error_type': 'aggregate_sheet_failed'}
            per_sheet_states.append(state)

    if not per_sheet_states:
        return {
            'success': False,
            'error': 'Aggregate preview produced no usable source sheets.',
            'error_type': 'aggregate_empty',
        }

    # The aggregate path requires every sheet to share an anchor strategy
    # so per-row diffing is consistent. If sheets disagree on strategy or
    # anchor column, bail and let the caller fall back to the picker.
    base_strategy = per_sheet_states[0]['write_strategy']
    base_anchor   = per_sheet_states[0]['anchor_column']
    for st in per_sheet_states[1:]:
        if st['write_strategy'] != base_strategy or st['anchor_column'] != base_anchor:
            return {
                'success': False,
                'error': (
                    f"Aggregate mode requires all sheets to share the same anchor "
                    f"strategy/column. Sheet {st['sheet_name']!r} resolved to "
                    f"strategy={st['write_strategy']!r} anchor={st['anchor_column']!r} "
                    f"vs base strategy={base_strategy!r} anchor={base_anchor!r}."
                ),
                'error_type': 'aggregate_strategy_drift',
            }

    # Append-strategy aggregate: target has no row-identity anchor (e.g.
    # an empty data area where the target tab carries headers only), so
    # per-row diffing isn't possible. Instead we project every source row
    # onto the target's writable columns and surface them as
    # ``appended_rows_preview`` exactly like the single-sheet append path.
    # Cross-sheet conflicts don't apply (no anchor → no clash semantics)
    # and intra-section duplicate handling is also skipped because
    # ``_detect_intra_section_anchor_conflicts`` is anchor-keyed. Each
    # source row contributes one new row at the bottom of the target tab.
    if base_strategy == 'append':
        return _preview_multi_sheet_aggregate_append(
            per_sheet_states         = per_sheet_states,
            section_target           = section_target,
            target_sheet_name        = target_sheet_name,
            section_title            = section_title,
            target_section_index     = target_section_index,
            aggregated_sheet_names   = aggregated_sheet_names,
            aggregated_sections      = aggregated_sections,
            is_section_aggregate     = is_section_aggregate,
        )

    if base_strategy not in ('row_per_date', 'row_per_entity', 'composite_key'):
        return {
            'success': False,
            'error': (
                f"Aggregate mode currently supports row-keyed strategies "
                f"(row_per_date, row_per_entity, composite_key). Got "
                f"{base_strategy!r}."
            ),
            'error_type': 'aggregate_unsupported_strategy',
        }

    is_date_anchor = per_sheet_states[0]['is_date_anchor']

    # Per-sheet anchor maps {lookup_key: {display, src_row}}
    per_sheet_maps = [
        (st['sheet_name'], _aggregate_build_anchor_map(st))
        for st in per_sheet_states
    ]

    # Cross-sheet conflict detection — same lookup_key in >=2 sheets.
    anchor_to_sheets = {}  # lookup_key -> [(sheet_name, display, src_row), ...]
    for sheet_name, m in per_sheet_maps:
        for lookup_key, entry in m.items():
            anchor_to_sheets.setdefault(lookup_key, []).append(
                (sheet_name, entry['display'], entry['src_row'])
            )

    # Resolve conflict_choices (frontend posts {anchor_display: sheet_name|"skip"}).
    # The keys come back stringified from JSON — normalize them so date /
    # composite anchors match regardless of casing variations.
    raw_choices = conflict_choices or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}

    norm_choices = {}
    for k, v in (raw_choices or {}).items():
        if k is None:
            continue
        norm_k = str(k) if is_date_anchor else str(k).lower()
        norm_choices[norm_k] = v

    conflicts_to_resolve = []
    unresolved_count = 0
    for lookup_key, candidates in anchor_to_sheets.items():
        if len(candidates) < 2:
            continue
        choice_key = lookup_key  # already normalized identically to anchor_map keys
        chosen = norm_choices.get(choice_key)
        if chosen is None:
            unresolved_count += 1
        # Build the candidate payload from each conflicting source row,
        # exposing every mapped (source -> target) column so the frontend
        # can render a side-by-side full row comparison.
        display_anchor = candidates[0][1]
        candidate_payload = []
        for sheet_name, _disp, src_row in candidates:
            # Look up that sheet's column mapping so we render columns the
            # user actually picked. Skip the anchor column itself — it's
            # the row identity, shown as the card header.
            st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
            mappings = st['column_mappings'] or {}
            anchor_col_set_local = (
                set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                else ({st['anchor_column']} if st['anchor_column'] else set())
            )
            row_data = {}
            for src_col, tgt_col in mappings.items():
                if not tgt_col or tgt_col in anchor_col_set_local:
                    continue
                row_data[tgt_col] = _format_cell_value(src_row.get(src_col))
            candidate_payload.append({
                'sheet_name': sheet_name,
                'row_data':   row_data,
            })
        conflicts_to_resolve.append({
            'anchor_value': str(display_anchor),
            'candidates':   candidate_payload,
        })

    if unresolved_count > 0:
        # Aggregate column_mappings union so the modal can derive headers if
        # it wants a deterministic column order across candidates.
        agg_column_mappings = {}
        for st in per_sheet_states:
            for src, tgt in (st['column_mappings'] or {}).items():
                if tgt and src not in agg_column_mappings:
                    agg_column_mappings[src] = tgt
        print(
            f"   Aggregate: {unresolved_count} unresolved conflict(s) of "
            f"{len(conflicts_to_resolve)} total — surfacing modal."
        )
        # Source-shape-aware modal copy. The intra-tab path lists section
        # titles instead of sheet names so the user reads "Outbound
        # Metrics, Inbound Metrics" not "TC-L06 March Data, TC-L06 April
        # Data". The candidates inside each conflict already carry the
        # right per-source label (sheet_name field reused as section
        # title for back-compat with the existing FE).
        agg_label_list = (
            [s.get('source_section_title') or s.get('sheet_name')
             for s in (per_sheet_states or [])]
            if is_section_aggregate
            else aggregated_sheet_names
        )
        modal_message = (
            f'Found {len(conflicts_to_resolve)} identifier(s) appearing in '
            f'multiple source {"sections" if is_section_aggregate else "sheets"}. '
            f'Pick which {"section" if is_section_aggregate else "sheet"} wins for each one.'
        )
        return {
            'success': True,
            'preview': True,
            'aggregate_mode': True,
            'requires_conflict_resolution': True,
            'conflict_kind': 'multi_section_aggregate' if is_section_aggregate else 'multi_sheet_aggregate',
            'aggregated_sheets': agg_label_list,
            'conflicts_to_resolve': conflicts_to_resolve,
            'column_mappings': agg_column_mappings,
            'write_strategy': (
                'multi_section_aggregate' if is_section_aggregate
                else 'multi_sheet_aggregate'
            ),
            'anchor_column': base_anchor,
            'message': modal_message,
        }

    # Build merged anchor map honoring conflict_choices (or last-sheet wins
    # for non-conflicts, which is a no-op since they appear in exactly one
    # sheet anyway).
    merged_anchor_map = {}      # lookup_key -> {display, sheet_name, src_row}
    skipped_via_choice = []     # [{sheet_name, anchor_value, row_data}]

    for lookup_key, candidates in anchor_to_sheets.items():
        if len(candidates) == 1:
            sheet_name, display, src_row = candidates[0]
            merged_anchor_map[lookup_key] = {
                'display':    display,
                'sheet_name': sheet_name,
                'src_row':    src_row,
            }
            continue
        choice = norm_choices.get(lookup_key)
        if choice == 'skip':
            # User explicitly dropped this identifier. Surface ALL
            # candidates in the skipped panel so they can see what was
            # discarded.
            for sheet_name, display, src_row in candidates:
                st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
                anchor_col_set_local = (
                    set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                    else ({st['anchor_column']} if st['anchor_column'] else set())
                )
                row_data = {}
                for src_col, tgt_col in (st['column_mappings'] or {}).items():
                    if not tgt_col or tgt_col in anchor_col_set_local:
                        continue
                    row_data[tgt_col] = _format_cell_value(src_row.get(src_col))
                skipped_via_choice.append({
                    'sheet_name':   sheet_name,
                    'anchor_value': str(display),
                    'row_data':     row_data,
                    'reason':       'user_skipped_conflict',
                })
            continue
        # Default to first candidate when the choice doesn't match any
        # known sheet (defensive — shouldn't happen because the modal
        # constrains selection to candidate sheet names).
        winner = next(
            (c for c in candidates if c[0] == choice),
            candidates[0],
        )
        sheet_name, display, src_row = winner
        merged_anchor_map[lookup_key] = {
            'display':    display,
            'sheet_name': sheet_name,
            'src_row':    src_row,
        }

    # Build diff vs target. Reuse the same logic shape as the single-sheet
    # preview — we walk target rows once, match against merged_anchor_map,
    # emit per-cell conflicts/empty_cells. Orphan source anchors go into
    # skipped_no_match (NOT rows_to_append).
    header_index = section_target.get('header_index', {})
    raw_rows     = section_target.get('raw_rows', [])
    section_data_rows = raw_rows[1:] if raw_rows else []

    # Aggregate column mappings (union across sheets) for the final
    # preview payload. write_mappings strips anchor + formula cols same as
    # single-sheet path so the diff loop sees only writable targets.
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt

    anchor_col_set = (
        set(base_anchor) if isinstance(base_anchor, list)
        else ({base_anchor} if base_anchor else set())
    )
    formula_col_set = set(section_target.get('formula_cols', []) or [])
    write_mappings = {
        k: v for k, v in agg_column_mappings.items()
        if v and v not in anchor_col_set and v not in formula_col_set
    }
    target_to_source = {tgt: src for src, tgt in write_mappings.items()}
    target_cols_to_write = list(write_mappings.values())

    conflicts          = []
    empty_cells        = []
    skipped_no_match   = list(skipped_via_choice)
    rows_to_update     = []
    diff_total_cells   = 0
    diff_truncated     = False

    anchor_cols = base_anchor if isinstance(base_anchor, list) else [base_anchor]
    anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

    # Walk target rows and emit cell-level diff for matched anchors.
    target_anchor_set = set()
    for row in section_data_rows:
        parts = []
        for ai in anchor_idxs:
            val = row[ai] if ai is not None and ai < len(row) else None
            if val:
                normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                if normed:
                    parts.append(normed)
        anchor_val = '|'.join(parts) if len(parts) > 1 else (parts[0] if parts else None)
        if not anchor_val:
            continue
        check = anchor_val if is_date_anchor else anchor_val.lower()
        target_anchor_set.add(check)
        merged_entry = merged_anchor_map.get(check)
        if not merged_entry:
            continue
        src_row = merged_entry['src_row']
        sheet_name_for_row = merged_entry['sheet_name']

        for col_name in target_cols_to_write:
            col_idx = header_index.get(col_name)
            if col_idx is None:
                continue
            existing = row[col_idx] if col_idx < len(row) else None
            existing_str = str(existing).strip() if existing is not None else ''
            if existing_str.startswith('='):
                continue
            source_col = target_to_source.get(col_name)
            new_raw    = src_row.get(source_col) if source_col else None
            new_value  = _format_cell_value(new_raw)
            if new_value == '' or new_raw is None:
                continue

            diff_total_cells += 1
            if diff_total_cells > MAX_DIFF_CELLS:
                diff_truncated = True
                continue

            # Use BARE anchor_value here so the FE's selectedDiffIds key
            # (`diff|<kind>|<anchor>|<column>`) and the writeOnly filter
            # (`allowed_diff_cells[*].anchor`) match the bare ``display``
            # value that ``_run_multi_sheet_aggregate`` compares against.
            # If we prefix with "[sheet_name] " here, the run-path filter
            # would silently drop every row (the comparison `str(display)
            # in allowed_anchor_strs` would never match). Sheet attribution
            # is carried separately via ``source_sheet`` so the FE can
            # render it as a small badge alongside the row identifier.
            if existing_str:
                conflicts.append({
                    'anchor_value':   anchor_val,
                    'column':         col_name,
                    'existing_value': existing_str,
                    'new_value':      new_value,
                    'source_sheet':   sheet_name_for_row,
                })
            else:
                empty_cells.append({
                    'anchor_value': anchor_val,
                    'column':       col_name,
                    'new_value':    new_value,
                    'source_sheet': sheet_name_for_row,
                })

        rows_to_update.append(str(anchor_val))

    # Orphan source anchors (valid id, no target match) → skipped_no_match.
    # Update-only by design: aggregate mode never appends new rows, so the
    # user can see what would have been dropped without it being silent.
    for lookup_key, merged_entry in merged_anchor_map.items():
        if lookup_key in target_anchor_set:
            continue
        sheet_name = merged_entry['sheet_name']
        src_row    = merged_entry['src_row']
        st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
        anchor_col_set_local = (
            set(st['anchor_column']) if isinstance(st['anchor_column'], list)
            else ({st['anchor_column']} if st['anchor_column'] else set())
        )
        row_data = {}
        for src_col, tgt_col in (st['column_mappings'] or {}).items():
            if not tgt_col or tgt_col in anchor_col_set_local:
                continue
            row_data[tgt_col] = _format_cell_value(src_row.get(src_col))
        skipped_no_match.append({
            'sheet_name':   sheet_name,
            'anchor_value': str(merged_entry['display']),
            'row_data':     row_data,
            'reason':       'no_match_in_target',
        })

    # Aggregate source headers + target headers for the preview header bar.
    agg_source_cols = []
    for st in per_sheet_states:
        for h in st['source_schema'].get('headers', []) or []:
            if h not in agg_source_cols:
                agg_source_cols.append(h)
    agg_target_headers = list(section_target.get('headers', []) or [])

    rows_in_source_total = sum(
        st['source_schema'].get('total_rows', 0) or 0 for st in per_sheet_states
    )

    print(
        f"   Aggregate diff: {len(conflicts)} overwrites + {len(empty_cells)} fills + "
        f"{len(rows_to_update)} matched anchors + {len(skipped_no_match)} skipped "
        f"(total cells: {diff_total_cells}, truncated: {diff_truncated})"
    )

    # Source-shape-aware modal/preview labels and strategy_metadata.
    # On the intra-tab path:
    #   - aggregated_sheets shows section titles instead of sheet names
    #     so the modal header reads "Outbound Metrics, Inbound Metrics"
    #   - write_strategy is 'multi_section_aggregate' so the confirm
    #     dispatcher (run_dynamic_mapping) routes to the section-aware
    #     run path
    #   - strategy_metadata.aggregated_sections persists the per-source
    #     {sheet_name, section, source_section_index} so the confirm
    #     re-parse can slice exactly the same rows as the preview
    #   - aggregated_sheet_names is omitted because the cross-tab
    #     dispatcher would mis-route the confirm if it saw both fields
    label_aggregated_sheets = (
        [st.get('source_section_title') or st.get('sheet_name')
         for st in per_sheet_states]
        if is_section_aggregate
        else aggregated_sheet_names
    )
    final_strategy = (
        'multi_section_aggregate' if is_section_aggregate
        else 'multi_sheet_aggregate'
    )
    final_strategy_metadata = {
        'aggregate':              True,
        'conflict_resolutions':   norm_choices,
        'target_section_index':   target_section_index,
        'underlying_strategy':    base_strategy,
        'anchor_columns':         base_anchor if isinstance(base_anchor, list) else None,
    }
    if is_section_aggregate:
        # Re-emit the input section list (each entry plain dict) so the
        # confirm round-trip preserves per-section parsing context. We
        # don't trust per_sheet_states['parse_result'] to round-trip
        # cleanly because it carries large arrays; the planner's
        # original (sheet_name, section) pair is sufficient.
        final_strategy_metadata['aggregated_sections'] = list(aggregated_sections or [])
    else:
        final_strategy_metadata['aggregated_sheet_names'] = aggregated_sheet_names
    sources_label_for_reasoning = ", ".join(
        repr(st.get('source_section_title') or st.get('sheet_name'))
        for st in per_sheet_states
    )
    return {
        'success':          True,
        'preview':          True,
        'aggregate_mode':   True,
        'aggregated_sheets': label_aggregated_sheets,
        'write_strategy':   final_strategy,
        'underlying_strategy': base_strategy,
        'anchor_column':    base_anchor,
        'source_anchor':    per_sheet_states[0]['identification'].get('source_anchor'),
        'anchor_type':      per_sheet_states[0]['identification'].get('anchor_type', ''),
        'reasoning': (
            f"Aggregating {len(per_sheet_states)} source "
            f"{'section' if is_section_aggregate else 'sheet'}(s) ("
            + sources_label_for_reasoning
            + f") into target tab {target_sheet_name!r}"
            + (f" (section: {section_title!r})" if section_title else "")
            + ". Update-only — orphan rows are listed but not written."
        ),
        'source_columns':   agg_source_cols,
        'target_headers':   agg_target_headers,
        'column_mappings':  write_mappings,
        'unmapped_source':  [],
        'rows_in_source':   rows_in_source_total,
        'rows_in_target':   section_target.get('total_rows', 0) or 0,
        'source_col_types': {},
        'target_col_types': section_target.get('col_types', {}) or {},
        'formula_cols':     list(section_target.get('formula_cols', []) or []),
        'conflicts':        conflicts,
        'empty_cells':      empty_cells,
        'appended_rows_preview': [],
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   rows_to_update,
        'rows_to_append':   [],
        'rows_to_update_count': len(rows_to_update),
        'rows_to_append_count': 0,
        'skipped_no_match': skipped_no_match,
        'is_empty_target':  bool(section_target.get('is_empty_target')),
        'header_row_count': section_target.get('header_row_count', 1) or 1,
        'composite_to_col_index': section_target.get('composite_to_col_index', {}) or {},
        'sheet_name':           None,
        'auto_selected_sheet':  None,
        'strategy_metadata':    final_strategy_metadata,
        'pivot_source_col':     None,
        'value_source_col':     None,
    }


def _run_multi_sheet_aggregate_append(
    inputs, per_sheet_states, section_target, target_sheet_name,
    target_section_index, sheet_id, credentials,
    aggregated_sheet_names, aggregated_sections, is_section_aggregate,
    source_count, raw_values,
):
    """Append-mode aggregate writer: project every source row through its
    per-sheet column_mappings, concatenate across sheets, and call
    ``append_rows`` once. Honors the FE's ``write_only.allowed_append_anchors``
    filter so the user can deselect rows in the preview.

    The anchor_value scheme matches the preview
    (``"<sheet_name> #<N>"``); the run side rebuilds the same string per
    source row and only writes rows whose anchor_value is in the allowed
    set (when the FE provided one — otherwise we write every row).
    """
    # Resolve target headers + formula columns (formula cols are stripped
    # from the projection so we never overwrite live formulas in the
    # target tab).
    target_headers = list(section_target.get('headers', []) or [])
    formula_col_set = set(section_target.get('formula_cols', []) or [])
    if not target_headers:
        return {
            'success': False,
            'error': 'Aggregate-append write: target section has no headers to project rows against.',
            'error_type': 'aggregate_append_no_target_headers',
        }

    # Optional per-row deselection. Mirrors the row-keyed path's handling
    # of ``write_only`` but keys off ``allowed_append_anchors`` instead of
    # ``allowed_diff_cells`` (append rows have no diff cells, the user
    # picks rows wholesale in the preview's "new rows" panel).
    write_only_raw = inputs.get('write_only')
    if isinstance(write_only_raw, str) and write_only_raw.strip():
        try:
            write_only_raw = json.loads(write_only_raw)
        except Exception:
            write_only_raw = None
    write_only = write_only_raw if isinstance(write_only_raw, dict) else None
    allowed_anchor_strs = None
    if write_only:
        anchors = write_only.get('allowed_append_anchors') or []
        allowed_anchor_strs = {str(a) for a in anchors if a is not None} or None

    rows_for_write = []
    skipped_unselected = 0
    diff_total_cells = 0
    contributing_sheet_anchors = []

    for st in per_sheet_states:
        sheet_name      = st['sheet_name']
        # Mirror the preview's row_label convention so the anchor_value
        # we rebuild here byte-matches the preview's so the
        # ``allowed_append_anchors`` filter actually filters.
        section_title_local = st.get('source_section_title')
        if section_title_local and section_title_local != sheet_name:
            row_label = f"{sheet_name} - {section_title_local}"
        else:
            row_label = sheet_name
        column_mappings = st.get('column_mappings') or {}
        full_data       = st.get('full_data') or []
        anchor_col_set_local = (
            set(st['anchor_column']) if isinstance(st['anchor_column'], list)
            else ({st['anchor_column']} if st['anchor_column'] else set())
        )
        # Mirror the preview's strip rules so we project the same set of
        # cells the user saw in the diff. If the strip removes every
        # mapping for a sheet (extremely unlikely — would mean the LLM
        # mapped only anchor + formula cols), skip silently.
        sheet_mappings = {
            src: tgt for src, tgt in column_mappings.items()
            if tgt and tgt not in anchor_col_set_local and tgt not in formula_col_set
        }
        if not sheet_mappings:
            continue
        target_to_source = {tgt: src for src, tgt in sheet_mappings.items()}

        for i, src_row in enumerate(full_data):
            anchor_value = f"{row_label} #{i + 1}"
            if allowed_anchor_strs is not None and anchor_value not in allowed_anchor_strs:
                skipped_unselected += 1
                continue

            row_list = [''] * len(target_headers)
            row_has_value = False
            for h_idx, h_name in enumerate(target_headers):
                src_col = target_to_source.get(h_name)
                if not src_col:
                    continue
                raw_val = src_row.get(src_col)
                if raw_val is None:
                    continue
                if isinstance(raw_val, str) and raw_val.strip() == '':
                    continue
                row_list[h_idx] = raw_val
                row_has_value = True
                diff_total_cells += 1

            if row_has_value:
                rows_for_write.append(row_list)
                contributing_sheet_anchors.append(anchor_value)

    print(
        f"   Aggregate-append prep: {len(rows_for_write)} rows ready, "
        f"{skipped_unselected} deselected via write_only "
        f"(total cells: {diff_total_cells})"
    )

    if not rows_for_write:
        return {
            'success': False,
            'error': (
                'Aggregate-append write produced no rows to append. '
                'Either the source sheets had no usable rows or every '
                'row was deselected in the review step.'
            ),
            'error_type': 'aggregate_empty_write',
            'aggregated_sheets': (
                [s.get('source_section_title') or s.get('section', {}).get('title')
                 for s in (aggregated_sections or [])]
                if is_section_aggregate
                else aggregated_sheet_names
            ),
        }

    # Append at the bottom of the target tab. The sheets agent's
    # append_rows tool finds the last filled row across the WHOLE tab
    # and inserts after it — for the empty-data-area APPEND case the
    # first row lands right under the header. Section-level append (when
    # target_section_index is not None) is intentionally not honored
    # here; the tab-level append matches the preview's
    # ``rows_in_target=0`` framing and is the only behavior the FE
    # currently exposes for append mode.
    append_result = invoke(SHEETS_LAMBDA, {
        'tool': 'append_rows',
        'inputs': {
            'sheet_id':   sheet_id,
            'sheet_name': target_sheet_name,
            'rows':       rows_for_write,
        },
        'credentials_dict': credentials,
    })

    rows_appended = int(append_result.get('rows_appended', 0) or 0)
    cells_updated = int(append_result.get('cells_updated', 0) or 0)
    success = bool(append_result.get('success')) and rows_appended > 0

    final_strategy = (
        'multi_section_aggregate' if is_section_aggregate
        else 'multi_sheet_aggregate'
    )
    label_aggregated_sheets = (
        [s.get('source_section_title') or s.get('section', {}).get('title')
         for s in (aggregated_sections or [])]
        if is_section_aggregate
        else aggregated_sheet_names
    )

    # Aggregated column_mappings union for the response (matches the
    # row-keyed path's response shape so the FE renders identically).
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and tgt not in formula_col_set and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt

    response = {
        'success':         success,
        'write_strategy':  final_strategy,
        'underlying_strategy': 'append',
        'anchor_column':   None,
        'rows_processed':  len(rows_for_write),
        'aggregated_sheets': label_aggregated_sheets,
        'column_mappings': agg_column_mappings,
        'write_result': {
            'success':       success,
            'rows_updated':  0,
            'rows_appended': rows_appended,
            'cells_updated': cells_updated,
            'orphans_skipped': 0,
            'deselected_skipped': skipped_unselected,
            'sheets_aggregated': source_count,
            'append_mode':   'sheet-bottom',
        },
    }
    if not success:
        response['error'] = (
            append_result.get('error')
            or 'Aggregate-append write returned zero appended rows.'
        )
    return response


def _run_multi_sheet_aggregate(inputs, aggregated_sheet_names, conflict_resolutions,
                                target_section_index, sheet_id, target_sheet_name,
                                credentials, aggregated_sections=None):
    """Confirm path for multi_sheet_aggregate AND multi_section_aggregate.

    Replays the preview's per-source parse → identify → merge using the
    user's conflict_resolutions, then writes ONLY matched rows into the
    target tab (update-only by design — orphan rows have already been
    surfaced as ``skipped_no_match`` in the preview and the user knows
    they are being dropped).

    When ``aggregated_sections`` is provided (intra-tab path), each entry
    is a ``{'sheet_name': str, 'section': dict, 'source_section_index': int}``
    item. Per-source parsing slices the source TAB to the section's row
    range so the confirm sees the exact same rows the preview saw. The
    write semantics are identical to the cross-tab path — same target
    section, same update-only contract.

    The write itself reuses the existing ``update_rows_by_date`` /
    ``update_rows_by_anchor`` sheets-agent tools — same primitives used by
    ``route_write`` for the single-sheet path. We never call
    ``append_rows`` from this path because aggregate mode forbids appends.
    """
    file_content = inputs['file_content']
    file_type    = inputs.get('file_type', 'xlsx')
    credentials_local = credentials
    is_section_aggregate = bool(aggregated_sections)
    source_count = (
        len(aggregated_sections) if is_section_aggregate
        else len(aggregated_sheet_names or [])
    )

    print(
        f"Aggregate write: {source_count} "
        f"{'section(s)' if is_section_aggregate else 'sheet(s)'} → "
        f"{target_sheet_name!r} (target_section_index={target_section_index})"
    )

    # Re-read target so we can rebuild a section_target identical to the
    # preview's. Saves us from trusting any cached schema fields the
    # frontend may have echoed back.
    safe_name = (
        f"'{target_sheet_name}'"
        if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
        else target_sheet_name
    )
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials_local
    })
    if not sheet_read.get('success'):
        return {
            'success': False,
            'error': f"Cannot read target sheet for aggregate write: {sheet_read.get('error')}",
            'error_type': 'aggregate_target_read_failed',
        }
    raw_values = sheet_read.get('data', sheet_read.get('values', []))

    formula_cols = detect_formula_columns(sheet_id,
                                          f"'{target_sheet_name}'" if ' ' in target_sheet_name else target_sheet_name,
                                          credentials_local)

    target_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_target_data',
        'inputs': {'raw_values': raw_values, 'sheet_name': target_sheet_name}
    })
    if not target_schema.get('success'):
        return {
            'success': False,
            'error': f"Cannot structure target for aggregate write: {target_schema.get('error')}",
            'error_type': 'aggregate_target_structure_failed',
        }
    existing_formula_cols = set(target_schema.get('formula_cols', []))
    existing_formula_cols.update(formula_cols)
    target_schema['formula_cols'] = list(existing_formula_cols)

    # Resolve section_target the same way preview does.
    if target_section_index is None:
        section_target = dict(target_schema)
    else:
        sections_local = _detect_sections_local(raw_values or [])
        if 0 <= target_section_index < len(sections_local):
            section = sections_local[target_section_index]
            section_target = _build_section_target_schema(
                section, raw_values, target_sheet_name,
                target_schema.get('formula_cols', []) or []
            )
        else:
            return {
                'success': False,
                'error': (
                    f'Aggregate write: target_section_index={target_section_index} '
                    f'out of range against current target sheet.'
                ),
                'error_type': 'aggregate_invalid_section',
            }

    # Per-source parse + identify (reuse the preview helper to keep
    # behavior identical between preview and confirm). The intra-tab
    # path (aggregated_sections) parses with section= per source so the
    # confirm sees the exact same row slice as the preview.
    per_sheet_states = []
    if is_section_aggregate:
        for src_item in aggregated_sections:
            src_sheet_name = src_item.get('sheet_name')
            src_section    = src_item.get('section') or {}
            if 'source_section_index' in src_item:
                src_section = dict(src_section)
                src_section['__source_section_index'] = src_item['source_section_index']
            state, err = _aggregate_parse_one_section(
                file_content, file_type, src_sheet_name, src_section, section_target,
            )
            if err:
                return {'success': False, 'error': err, 'error_type': 'aggregate_section_failed'}
            per_sheet_states.append(state)
    else:
        for sheet_name in aggregated_sheet_names:
            state, err = _aggregate_parse_one_sheet(
                file_content, file_type, sheet_name, section_target
            )
            if err:
                return {'success': False, 'error': err, 'error_type': 'aggregate_sheet_failed'}
            per_sheet_states.append(state)

    if not per_sheet_states:
        return {
            'success': False,
            'error': 'Aggregate write produced no usable source sheets.',
            'error_type': 'aggregate_empty',
        }

    base_strategy = per_sheet_states[0]['write_strategy']
    base_anchor   = per_sheet_states[0]['anchor_column']
    is_date_anchor = per_sheet_states[0]['is_date_anchor']
    is_composite = isinstance(base_anchor, list)
    anchor_cols = base_anchor if is_composite else [base_anchor]

    # Append-strategy aggregate: project every source row onto the
    # target's writable columns and call ``append_rows`` once with the
    # combined payload. No anchor matching, no conflict resolution
    # replay (the preview already returned a flat appended_rows_preview
    # so the FE has nothing to resolve here). This path mirrors the
    # preview's append branch and uses the same per-sheet column
    # mappings to project rows.
    if base_strategy == 'append':
        return _run_multi_sheet_aggregate_append(
            inputs                = inputs,
            per_sheet_states      = per_sheet_states,
            section_target        = section_target,
            target_sheet_name     = target_sheet_name,
            target_section_index  = target_section_index,
            sheet_id              = sheet_id,
            credentials           = credentials_local,
            aggregated_sheet_names= aggregated_sheet_names,
            aggregated_sections   = aggregated_sections,
            is_section_aggregate  = is_section_aggregate,
            source_count          = source_count,
            raw_values            = raw_values,
        )

    if base_strategy not in ('row_per_date', 'row_per_entity', 'composite_key'):
        return {
            'success': False,
            'error': (
                f"Aggregate write only supports row-keyed strategies; got "
                f"{base_strategy!r}."
            ),
            'error_type': 'aggregate_unsupported_strategy',
        }

    # Build per-sheet anchor maps + cross-sheet candidate map (mirrors
    # _preview_multi_sheet_aggregate exactly so the merged set matches).
    per_sheet_maps = [
        (st['sheet_name'], _aggregate_build_anchor_map(st))
        for st in per_sheet_states
    ]
    anchor_to_sheets = {}
    for sheet_name, m in per_sheet_maps:
        for lookup_key, entry in m.items():
            anchor_to_sheets.setdefault(lookup_key, []).append(
                (sheet_name, entry['display'], entry['src_row'])
            )

    # Normalize conflict_resolutions exactly the same way preview did.
    raw_choices = conflict_resolutions or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}
    norm_choices = {}
    for k, v in (raw_choices or {}).items():
        if k is None:
            continue
        norm_k = str(k) if is_date_anchor else str(k).lower()
        norm_choices[norm_k] = v

    # Build merged set: {lookup_key: (sheet_name, display, src_row)}.
    # Conflict-skip drops the entry entirely (no write for that anchor).
    # Unresolved conflicts at confirm time are a hard error — we don't
    # silently default — because the orchestrator is supposed to gate on
    # requires_conflict_resolution before letting the user confirm.
    merged = {}
    unresolved_conflicts = []
    for lookup_key, candidates in anchor_to_sheets.items():
        if len(candidates) == 1:
            merged[lookup_key] = candidates[0]
            continue
        choice = norm_choices.get(lookup_key)
        if choice == 'skip':
            continue
        if choice is None:
            unresolved_conflicts.append(candidates[0][1])
            continue
        winner = next((c for c in candidates if c[0] == choice), None)
        if winner is None:
            unresolved_conflicts.append(candidates[0][1])
            continue
        merged[lookup_key] = winner

    if unresolved_conflicts:
        return {
            'success': False,
            'error': (
                f"Aggregate write blocked by {len(unresolved_conflicts)} unresolved "
                f"conflict(s): {unresolved_conflicts[:5]}. "
                f"Re-run preview to resolve them."
            ),
            'error_type': 'aggregate_unresolved_conflicts',
        }

    # Per-sheet writable mappings (anchor + formula cols stripped). Aggregate
    # them into a target_to_source_per_sheet map so we know which source col
    # to read for each (sheet, target_col) pair when transforming.
    formula_col_set = set(section_target.get('formula_cols', []) or [])
    anchor_col_set = (set(anchor_cols) if anchor_cols else set())

    # Aggregated column_mappings union — used for the response payload only.
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and tgt not in anchor_col_set and tgt not in formula_col_set:
                if src not in agg_column_mappings:
                    agg_column_mappings[src] = tgt

    # Build the rows-to-write payload. Each merged entry produces one row
    # with: anchor field + every writable target column populated from
    # the WINNING sheet's source row. Orphan anchors (lookup_key not in
    # the target's anchor set) are skipped — that's the update-only
    # contract.
    target_anchor_set = set()
    header_index = section_target.get('header_index', {})
    raw_rows     = section_target.get('raw_rows', [])
    section_data_rows = raw_rows[1:] if raw_rows else []
    anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

    for row in section_data_rows:
        parts = []
        for ai in anchor_idxs:
            val = row[ai] if ai is not None and ai < len(row) else None
            if val:
                normed = _normalize_date_value(val) if is_date_anchor else str(val).strip()
                if normed:
                    parts.append(normed)
        if parts:
            anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
            check = anchor_val if is_date_anchor else anchor_val.lower()
            target_anchor_set.add(check)

    # Apply optional write_only filter (per-row checkboxes from the
    # frontend's review modal). For aggregate mode the allowed set comes
    # in as ``allowed_diff_cells[*].anchor`` exactly the same way as the
    # single-sheet path. ``allowed_append_anchors`` is ignored — aggregate
    # mode never appends.
    write_only_raw = inputs.get('write_only')
    if isinstance(write_only_raw, str) and write_only_raw.strip():
        try:
            write_only_raw = json.loads(write_only_raw)
        except Exception:
            write_only_raw = None
    write_only = write_only_raw if isinstance(write_only_raw, dict) else None
    allowed_anchor_strs = None
    if write_only:
        diff_cells = write_only.get('allowed_diff_cells') or []
        allowed_anchor_strs = {
            str(c.get('anchor')) for c in diff_cells
            if isinstance(c, dict) and c.get('anchor') is not None
        } or None

    rows_for_write = []
    matched_lookup_keys = []
    skipped_orphan = 0
    skipped_unselected = 0

    for lookup_key, (winner_sheet, display, src_row) in merged.items():
        if lookup_key not in target_anchor_set:
            skipped_orphan += 1
            continue
        if allowed_anchor_strs is not None and str(display) not in allowed_anchor_strs:
            skipped_unselected += 1
            continue

        st = next(s for s in per_sheet_states if s['sheet_name'] == winner_sheet)
        sheet_mappings = {
            k: v for k, v in (st['column_mappings'] or {}).items()
            if v and v not in anchor_col_set and v not in formula_col_set
        }
        target_to_source = {tgt: src for src, tgt in sheet_mappings.items()}

        row_data = {}
        for tgt_col in sheet_mappings.values():
            src_col = target_to_source.get(tgt_col)
            if not src_col:
                continue
            raw_val = src_row.get(src_col)
            if raw_val is None or (isinstance(raw_val, str) and raw_val.strip() == ''):
                # Skip empty source cells — never overwrite existing target
                # value with blanks. Same convention as the single-sheet
                # path (TC-D10 invariant).
                continue
            row_data[tgt_col] = raw_val

        if base_strategy == 'row_per_date' and not is_composite:
            rows_for_write.append({
                'date': display,
                'date_formatted': display,
                'row_data': row_data,
            })
        else:
            entry = dict(row_data)
            if is_composite and isinstance(display, str) and '|' in display:
                parts = display.split('|')
                for col, part in zip(anchor_cols, parts):
                    entry[col] = part.strip()
            else:
                entry[anchor_cols[0]] = display
            rows_for_write.append(entry)
        matched_lookup_keys.append(lookup_key)

    print(
        f"   Aggregate prep: {len(rows_for_write)} rows ready, "
        f"{skipped_orphan} orphan(s) dropped, "
        f"{skipped_unselected} deselected via write_only"
    )

    if not rows_for_write:
        return {
            'success': False,
            'error': (
                'Aggregate write found no matched rows to write. '
                'Either every source identifier was an orphan against the '
                'target tab, or the user deselected every row in the review '
                'step.'
            ),
            'error_type': 'aggregate_empty_write',
            'aggregated_sheets': (
                [s.get('source_section_title') or s.get('section', {}).get('title')
                 for s in (aggregated_sections or [])]
                if is_section_aggregate
                else aggregated_sheet_names
            ),
        }

    # Compute section row-range for Fix L pinning. Without this the
    # aggregate write could still touch cells in a sibling section that
    # happens to share an anchor value — same silent-corruption class
    # the single-sheet path solved with section_data_start_row /
    # section_data_end_row in route_write.
    section_data_start_row = None
    section_data_end_row = None
    if target_section_index is not None:
        sections_for_pin = _detect_sections_local(raw_values or [])
        if 0 <= target_section_index < len(sections_for_pin):
            sec = sections_for_pin[target_section_index]
            ds = sec.get('data_start')
            de = sec.get('data_end')
            if isinstance(ds, int) and isinstance(de, int) and de > ds:
                section_data_start_row = ds + 1
                section_data_end_row = de
                print(
                    f"   Aggregate write: section pin row {section_data_start_row}..{section_data_end_row} "
                    f"on target section #{target_section_index} '{sec.get('title')}'"
                )

    # Dispatch to the same sheets-agent tool the single-sheet path uses,
    # but never fall through to append. The orphan rows are intentionally
    # dropped — that's the aggregate contract.
    if base_strategy == 'row_per_date' and not is_composite:
        write_inputs = {
            'sheet_id':         sheet_id,
            'sheet_name':       target_sheet_name,
            'date_column_name': base_anchor,
            'rows_with_dates':  rows_for_write,
            'header_row':       0,
        }
        if section_data_start_row is not None:
            write_inputs['data_start_row'] = section_data_start_row
            write_inputs['data_end_row']   = section_data_end_row
        update_result = invoke(SHEETS_LAMBDA, {
            'tool': 'update_rows_by_date',
            'inputs': write_inputs,
            'credentials_dict': credentials_local,
        })
    else:
        write_inputs = {
            'sheet_id':      sheet_id,
            'sheet_name':    target_sheet_name,
            'anchor_column': base_anchor,
            'rows':          rows_for_write,
            'header_row':    0,
        }
        if section_data_start_row is not None:
            write_inputs['data_start_row'] = section_data_start_row
            write_inputs['data_end_row']   = section_data_end_row
        update_result = invoke(SHEETS_LAMBDA, {
            'tool': 'update_rows_by_anchor',
            'inputs': write_inputs,
            'credentials_dict': credentials_local,
        })

    rows_updated  = int(update_result.get('rows_updated', 0) or 0)
    cells_updated = int(update_result.get('cells_updated', 0) or 0)
    success = bool(update_result.get('success')) and rows_updated > 0

    final_strategy = (
        'multi_section_aggregate' if is_section_aggregate
        else 'multi_sheet_aggregate'
    )
    label_aggregated_sheets = (
        [s.get('source_section_title') or s.get('section', {}).get('title')
         for s in (aggregated_sections or [])]
        if is_section_aggregate
        else aggregated_sheet_names
    )
    response = {
        'success':         success,
        'write_strategy':  final_strategy,
        'underlying_strategy': base_strategy,
        'anchor_column':   base_anchor,
        'rows_processed':  len(rows_for_write),
        'aggregated_sheets': label_aggregated_sheets,
        'column_mappings': agg_column_mappings,
        'write_result': {
            'success':       success,
            'rows_updated':  rows_updated,
            'rows_appended': 0,            # aggregate mode never appends
            'cells_updated': cells_updated,
            'orphans_skipped': skipped_orphan,
            'deselected_skipped': skipped_unselected,
            'sheets_aggregated': source_count,
        },
    }
    if not success:
        response['error'] = (
            update_result.get('error')
            or 'Aggregate write returned zero updates — this usually means the '
               'target tab has no rows matching the merged anchor set.'
        )
    return response


# ============================================================================
# Multi-sheet COLUMN-MERGE preview + run
# ============================================================================
# Pairs with _plan_multi_sheet_column_merge. Two architectural differences
# from _preview_multi_sheet_aggregate / _run_multi_sheet_aggregate:
#
#   1. Per-anchor row construction reads cells from EVERY sheet that has a
#      matching anchor (not just one winner). Sheet A contributes its
#      columns, Sheet B contributes its columns, and a single target row
#      gets cells from both at once.
#   2. Cross-sheet conflicts fire when 2+ sheets define the SAME target
#      column with DIFFERENT values for the SAME anchor. This is now a
#      first-class flow (not a "defensive safety net"): the planner used
#      to enforce a ≤25%-overlap cap to keep this rare, but that cap was
#      removed to support workbooks where multiple tabs intentionally
#      contribute to the same target columns. When all owners agree on
#      a value the cell is silently merged; only genuine disagreement
#      surfaces a modal entry. N-way conflicts (3+ sheets disagreeing)
#      are supported — the modal lists every owning sheet as a candidate.
#
# Update-only by design (same as the aggregate path): orphan source
# anchors are listed in skipped_no_match but never appended, so existing
# target rows that the user did NOT include in the source workbook stay
# untouched.
# ============================================================================


def _preview_multi_sheet_column_merge(
    inputs, file_content, file_type, target_sheet_name, raw_values,
    target_schema, formula_cols, sheet_names, conflict_choices,
):
    """Column-merge preview: 2+ sheets share an anchor and contribute
    DIFFERENT target columns. Each target row's anchor is matched against
    every source sheet, and cells from MULTIPLE sheets are merged per row.

    Mirrors ``_preview_multi_sheet_aggregate``'s payload shape so the FE
    renders it without changes (the only NEW field is
    ``write_strategy='multi_sheet_column_merge'`` which the run dispatcher
    routes to ``_run_multi_sheet_column_merge``).
    """
    print(
        f"Column-merge preview: {len(sheet_names)} sheets → "
        f"{target_sheet_name!r}"
    )

    # Re-use _aggregate_parse_one_sheet for parse + structure + identify.
    # Each source sheet runs its own find_identifier call — important
    # because the target may have 100+ columns and only a subset is
    # meaningful per source.
    #
    # Cache reuse between previews: when this preview is the SECOND
    # round (e.g. after the user resolved an intra-section conflict
    # modal), the FE round-trips strategy_metadata.per_sheet_cache from
    # the FIRST preview. Replaying that cache skips the per-sheet
    # find_identifier LLM call (4-13s each) the same way the run path
    # does — which is the difference between "30s timeout" and "11s
    # safe" on column-merge re-previews.
    _meta_in = inputs.get('strategy_metadata') or {}
    if isinstance(_meta_in, str):
        try:
            _meta_in = json.loads(_meta_in)
        except Exception:
            _meta_in = {}
    cached_per_sheet_in = _meta_in.get('per_sheet_cache') or []
    cache_by_name_preview = {}
    if cached_per_sheet_in:
        for entry in cached_per_sheet_in:
            sn = entry.get('sheet_name')
            if sn:
                cache_by_name_preview[sn] = entry
        print(
            f"   column-merge re-preview: replaying cached identification "
            f"for {len(cache_by_name_preview)}/{len(sheet_names)} sheet(s) "
            f"— skipping find_identifier"
        )

    # Parallelize across sheets so per-sheet LLM wall-time is max(t_i)
    # instead of sum(t_i). The 30s API Gateway timeout is the primary
    # constraint here; on the example that triggered this work the two
    # sheets took 8s + 12s sequentially, so parallel cuts ~8s off
    # preview wall-time. Cap workers at 6 for the same reason as the
    # cross_tab_section path: avoid burning the mapping-agent's
    # account-wide concurrency budget on a single user request.
    parse_t0 = time.time()
    max_workers = max(1, min(6, len(sheet_names)))
    per_sheet_states_by_name = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _aggregate_parse_one_sheet,
                file_content, file_type, sn, target_schema,
                cache_by_name_preview.get(sn),
            ): sn
            for sn in sheet_names
        }
        for fut in as_completed(futures):
            sn = futures[fut]
            try:
                state, err = fut.result()
            except Exception as exc:
                return {
                    'success': False,
                    'error': f"Sheet {sn!r}: parse raised {type(exc).__name__}: {exc}",
                    'error_type': 'column_merge_sheet_failed',
                }
            if err:
                return {
                    'success': False, 'error': err,
                    'error_type': 'column_merge_sheet_failed',
                }
            per_sheet_states_by_name[sn] = state
    # Preserve original sheet order for downstream "first sheet is the
    # base anchor source" semantics — as_completed returns by finish
    # order, which would non-deterministically pick the base.
    per_sheet_states = [per_sheet_states_by_name[sn] for sn in sheet_names]
    print(
        f"   per-sheet parse+identify (parallel x{max_workers}, "
        f"cached={len(cache_by_name_preview)}/{len(sheet_names)}): "
        f"{(time.time() - parse_t0):.2f}s for {len(sheet_names)} sheet(s)"
    )

    # Build the per_sheet_cache once we have all per_sheet_states. Used
    # by every early-return below so a re-preview from any modal stage
    # (intra-section, cross-sheet conflict) re-uses the find_identifier
    # results from this round. The same shape is consumed by the run
    # path, so the same dict serves both.
    def _build_per_sheet_cache():
        out = []
        for s in per_sheet_states:
            ident = s.get('identification') or {}
            out.append({
                'sheet_name':       s.get('sheet_name'),
                'write_strategy':   s.get('write_strategy'),
                'anchor_column':    s.get('anchor_column'),
                'source_anchor':    ident.get('source_anchor', s.get('anchor_column')),
                'anchor_type':      ident.get('anchor_type', ''),
                'column_mappings':  s.get('column_mappings') or {},
                'pivot_source_col': ident.get('pivot_source_col'),
                'value_source_col': ident.get('value_source_col'),
                'period_columns':   ident.get('period_columns'),
                'label_column':     ident.get('label_column'),
            })
        return out

    # All sheets must share the same write_strategy and anchor column —
    # otherwise the per-row merge can't pick a consistent row identifier.
    base_strategy = per_sheet_states[0]['write_strategy']
    base_anchor   = per_sheet_states[0]['anchor_column']
    for st in per_sheet_states[1:]:
        if st['write_strategy'] != base_strategy or st['anchor_column'] != base_anchor:
            return {
                'success': False,
                'error': (
                    f"Column-merge requires all sheets to share the same anchor "
                    f"strategy/column. Sheet {st['sheet_name']!r} resolved to "
                    f"strategy={st['write_strategy']!r} anchor={st['anchor_column']!r} "
                    f"vs base strategy={base_strategy!r} anchor={base_anchor!r}."
                ),
                'error_type': 'column_merge_strategy_drift',
            }

    if base_strategy not in ('row_per_date', 'row_per_entity', 'composite_key'):
        return {
            'success': False,
            'error': (
                f"Column-merge currently supports row-keyed strategies only. "
                f"Got {base_strategy!r}."
            ),
            'error_type': 'column_merge_unsupported_strategy',
        }

    is_date_anchor = per_sheet_states[0]['is_date_anchor']

    # Intra-sheet duplicate handling (column-merge edition).
    #
    # The single-sheet preview path runs `_detect_intra_section_anchor_conflicts`
    # before building anchor maps so any source sheet with the same date
    # appearing on 2+ rows surfaces a modal asking the user which row wins.
    # The column-merge path was missing this — `_aggregate_build_anchor_map`
    # silently last-writes on duplicate keys, so a sheet with `19/01/2025`
    # on rows 11 AND 20 would lose row 11's data without warning.
    #
    # We accept ``intra_section_choices`` in two shapes for backward
    # compat with the existing FE wire format:
    #   * Flat:   {anchor: 'row_<N>'|'skip'}   — single-sheet legacy.
    #   * Nested: {sheet_name: {anchor: 'row_<N>'|'skip'}} — multi-sheet.
    # Nested takes precedence when both forms could apply, but if a sheet
    # is missing from a nested dict we silently fall back to the flat
    # form so a single batch of choices can resolve dupes spread across
    # one obvious source sheet without the FE having to nest them.
    raw_intra_choices = inputs.get('intra_section_choices')
    if raw_intra_choices is None:
        # Caller may stash on strategy_metadata when re-previewing after
        # the modal — check there too.
        _meta_in = inputs.get('strategy_metadata') or {}
        if isinstance(_meta_in, str):
            try:
                _meta_in = json.loads(_meta_in)
            except Exception:
                _meta_in = {}
        raw_intra_choices = _meta_in.get('intra_section_choices')
    norm_intra_all = _normalize_intra_section_choices(raw_intra_choices)
    is_nested_intra = bool(norm_intra_all) and all(
        isinstance(v, dict) for v in norm_intra_all.values()
    )

    # Apply per-sheet BEFORE building anchor maps. This way the maps
    # already reflect the user's pick and the cell-conflict scan below
    # doesn't see stale duplicate cells.
    if norm_intra_all:
        for st in per_sheet_states:
            sn = st['sheet_name']
            if is_nested_intra:
                sheet_choices = norm_intra_all.get(sn) or {}
            else:
                # Flat form — apply to whichever sheet's rows match each
                # anchor. Sheets without a matching anchor in the choice
                # dict pass through untouched (no-op for that sheet).
                sheet_choices = norm_intra_all
            if not sheet_choices:
                continue
            full_data_in = st['full_data'] or []
            full_data_filtered = _apply_intra_section_choices(
                full_data_in,
                sheet_choices,
                st['source_anchor_names'],
                st['is_date_anchor'],
            )
            if len(full_data_filtered) != len(full_data_in):
                print(
                    f"   Applied intra_section_choices to sheet {sn!r}: "
                    f"{len(full_data_in)} -> {len(full_data_filtered)} rows"
                )
                st['full_data'] = full_data_filtered
                # Patch parse_result too so any downstream consumer that
                # re-reads parse_result (e.g. transform_data, conflict
                # owner build) sees the same filtered set.
                if isinstance(st.get('parse_result'), dict):
                    st['parse_result']['full_data'] = full_data_filtered

    # Build the per-sheet set of EXPLICITLY-resolved anchor lookup keys.
    # When the user picks a winning row in the intra-section duplicate
    # modal, the chosen row's blank cells should propagate to target —
    # they're a deliberate "clear this cell" pick, not a stray empty
    # source we should ignore. Without this, choosing a row whose
    # `Meals Expenses` column is blank would silently keep the target's
    # existing value (TC-D10 invariant: skip blanks). The user-reported
    # case at 2026-05-10 — chosen row 19 has blank Meals Expenses for
    # 2025-01-19 / 2025-01-24 but target kept its old value — is what
    # this set fixes downstream in merged_cells construction and the
    # diff loop.
    #
    # The keys must match the lookup_key convention used by
    # `_aggregate_build_anchor_map`: raw normalized for date anchors,
    # lowercased otherwise. Otherwise downstream `lookup_key in
    # explicit_anchors` checks will silently miss.
    #
    # `'skip'` choices are EXCLUDED — those rows are dropped entirely
    # so there's no chosen row whose empties we'd want to honor.
    explicit_anchors_by_sheet = {}
    if norm_intra_all:
        for st in per_sheet_states:
            sn = st['sheet_name']
            if is_nested_intra:
                sheet_choices = norm_intra_all.get(sn) or {}
            else:
                sheet_choices = norm_intra_all
            keys = set()
            is_date = bool(st.get('is_date_anchor'))
            for k, v in (sheet_choices or {}).items():
                if k is None:
                    continue
                if v == 'skip':
                    continue
                norm_k = str(k) if is_date else str(k).lower()
                keys.add(norm_k)
            explicit_anchors_by_sheet[sn] = keys

    # Detect remaining intra-section duplicates per sheet AFTER applying
    # any prior choices. If multiple sheets have dupes, we collect them
    # all into a single modal payload so the user resolves everything
    # in one round instead of N round-trips.
    all_intra_conflicts = []
    for st in per_sheet_states:
        sn = st['sheet_name']
        sheet_conflicts = _detect_intra_section_anchor_conflicts(
            st['full_data'] or [],
            st['source_anchor_names'],
            st['column_mappings'] or {},
            st['is_date_anchor'],
        )
        for c in sheet_conflicts:
            # Annotate which source sheet this duplicate lives in so the
            # FE can group/label and the apply step routes the choice
            # back to the right sheet's full_data.
            c['source_sheet'] = sn
            # Re-label candidate so the FE's modal card title shows the
            # source tab name + the row number. The FE picks the label
            # via `cand.label || cand.sheet_name || candKey`, so we must
            # set cand.label (the highest-priority field) — overriding
            # the "Row N" the detector set for single-sheet back-compat.
            # For multi-sheet column-merge the row number alone is
            # ambiguous (Row 11 in WHICH sheet?), so we prepend the tab
            # name. choice_id="row_<N>" and row_index stay untouched so
            # the apply step still knows which 0-indexed row to keep.
            for cand in c.get('candidates', []):
                base_row_label = cand.get('label')
                if not base_row_label:
                    base_row_label = f"Row {cand.get('row_index', 0) + 1}"
                # Display: "Operational Cost — Row 11"
                composite_label       = f"{sn} — {base_row_label}"
                cand['label']         = composite_label
                cand['sheet_name']    = composite_label
                cand['source_sheet']  = sn
                cand['row_label']     = base_row_label
        all_intra_conflicts.extend(sheet_conflicts)

    if all_intra_conflicts:
        affected_sheets = sorted({c['source_sheet'] for c in all_intra_conflicts})
        print(
            f"   Column-merge intra-sheet duplicates detected: "
            f"{len(all_intra_conflicts)} across {affected_sheets}"
        )
        # Pass back enough context that re-previewing with the user's
        # picks lands on this same column-merge code path AND skips
        # the LLM round trip. per_sheet_cache is the critical bit:
        # without it, the second preview (after resolving the modal)
        # re-runs find_identifier from scratch and hits the 30s API
        # Gateway timeout.
        agg_column_mappings = {}
        for st in per_sheet_states:
            for src, tgt in (st['column_mappings'] or {}).items():
                if tgt and src not in agg_column_mappings:
                    agg_column_mappings[src] = tgt
        return {
            'success': True,
            'preview': True,
            'requires_conflict_resolution': True,
            'conflict_kind': 'intra_section',
            'conflicts_to_resolve': all_intra_conflicts,
            'aggregated_sheets': affected_sheets,
            'message': (
                f"Found {len(all_intra_conflicts)} duplicate identifier(s) "
                f"in source sheet(s) {affected_sheets!r}. Pick which row "
                f"wins for each one before merging."
            ),
            'write_strategy':  'multi_sheet_column_merge',
            'underlying_strategy': base_strategy,
            'anchor_column':   base_anchor,
            'column_mappings': agg_column_mappings,
            'strategy_metadata': {
                'column_merge': True,
                'sheet_names':  list(sheet_names),
                # Echo whatever choices we just applied so the FE can keep
                # them in state when re-previewing without the user having
                # to re-pick already-resolved dupes.
                'intra_section_choices': raw_intra_choices,
                'underlying_strategy':   base_strategy,
                'anchor_columns':        base_anchor if isinstance(base_anchor, list) else None,
                # CRITICAL: forward per_sheet_cache so the next preview
                # (the one that fires after the user resolves the modal)
                # skips the LLM call. Without this the second preview
                # re-runs find_identifier and hits 30s API Gateway
                # timeout — exactly the failure observed at
                # 2026-05-10T14:18:06 (31s wall-time).
                'per_sheet_cache':       _build_per_sheet_cache(),
            },
        }

    # Per-sheet anchor maps {lookup_key: {display, src_row}}
    per_sheet_maps = [
        (st['sheet_name'], _aggregate_build_anchor_map(st))
        for st in per_sheet_states
    ]

    # Whole target as the section_target (column-merge currently only
    # operates on flat targets, same constraint as the aggregate path
    # when target_section_index is None).
    section_target = dict(target_schema)
    anchor_col_set = (
        set(base_anchor) if isinstance(base_anchor, list)
        else ({base_anchor} if base_anchor else set())
    )
    formula_col_set = set(section_target.get('formula_cols', []) or [])

    # Build the per-cell ownership map: (anchor, target_col) → list of
    # (sheet_name, raw_value). Empty source values are skipped here so
    # cross-sheet conflict detection isn't polluted by blanks (TC-D10
    # invariant). Explicit-pick blanks are injected into merged_cells
    # AFTER cross-sheet logic so they only land on single-owner cells —
    # see the `explicit_anchors_by_sheet` block further down.
    cell_owners = {}
    anchor_to_display = {}
    for sheet_name, m in per_sheet_maps:
        st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
        sheet_mappings = {
            k: v for k, v in (st['column_mappings'] or {}).items()
            if v and v not in anchor_col_set and v not in formula_col_set
        }
        target_to_source_local = {tgt: src for src, tgt in sheet_mappings.items()}
        for lookup_key, entry in m.items():
            anchor_to_display.setdefault(lookup_key, entry['display'])
            for tgt_col, src_col in target_to_source_local.items():
                raw_val = entry['src_row'].get(src_col)
                if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
                    continue
                cell_owners.setdefault((lookup_key, tgt_col), []).append(
                    (sheet_name, raw_val)
                )

    # Cross-sheet cell conflicts: same (anchor, tgt_col) defined by 2+
    # sheets with DIFFERENT values. The planner's overlap guard makes
    # this rare; surface a modal when it happens so the user picks.
    raw_choices = conflict_choices or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}
    norm_choices = {}
    for k, v in (raw_choices or {}).items():
        if k is None:
            continue
        norm_k = str(k) if is_date_anchor else str(k).lower()
        norm_choices[norm_k] = v

    cell_conflicts = {}
    for (lookup_key, tgt_col), owners in cell_owners.items():
        if len(owners) < 2:
            continue
        distinct_values = {_format_cell_value(v) for _, v in owners}
        if len(distinct_values) <= 1:
            continue
        cell_conflicts[(lookup_key, tgt_col)] = owners

    conflicts_to_resolve = []
    unresolved_count = 0
    if cell_conflicts:
        # Group cell conflicts by anchor — one modal entry per anchor with
        # all the conflicting cells aggregated. Candidates are the sheets
        # involved.
        cells_per_anchor = {}
        for (lookup_key, tgt_col), owners in cell_conflicts.items():
            cells_per_anchor.setdefault(lookup_key, []).append((tgt_col, owners))
        for lookup_key, cells in cells_per_anchor.items():
            display = anchor_to_display.get(lookup_key, lookup_key)
            chosen = norm_choices.get(lookup_key)
            if chosen is None:
                unresolved_count += 1
            sheets_in_conflict = set()
            for tgt_col, owners in cells:
                for sn, _ in owners:
                    sheets_in_conflict.add(sn)
            # The modal asks the user "for THIS anchor, which sheet's
            # value wins?" The answer is only meaningful for cells that
            # ARE in conflict — non-overlapping cells (where only one
            # sheet has a value) get auto-merged regardless of the pick.
            # By trimming row_data to ONLY the conflicting target cols
            # for this anchor, the modal candidate cards show exactly
            # the cells the user is deciding between, which prevents
            # the (correct but confusing) "did I just lose all my
            # other columns?" reaction the multi-sheet column-merge
            # path triggers when sheets have lots of non-overlapping
            # columns mapped to the same target tab.
            conflicting_tgt_cols = {tc for (tc, _o) in cells}
            candidate_payload = []
            for sn in sorted(sheets_in_conflict):
                st = next(s for s in per_sheet_states if s['sheet_name'] == sn)
                anchor_map = next(m for nn, m in per_sheet_maps if nn == sn)
                src_row = anchor_map.get(lookup_key, {}).get('src_row', {})
                anchor_col_set_local = (
                    set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                    else ({st['anchor_column']} if st['anchor_column'] else set())
                )
                row_data = {}
                for src_col, tc in (st['column_mappings'] or {}).items():
                    if not tc or tc in anchor_col_set_local:
                        continue
                    if tc not in conflicting_tgt_cols:
                        # Non-conflicting cell — irrelevant to the user's
                        # decision (auto-merged downstream regardless of
                        # which sheet they pick). Hide it from the modal.
                        continue
                    row_data[tc] = _format_cell_value(src_row.get(src_col))
                candidate_payload.append({
                    'sheet_name': sn,
                    'row_data':   row_data,
                })
            conflicts_to_resolve.append({
                'anchor_value': str(display),
                'candidates':   candidate_payload,
                # Tell the FE which target columns are actually in
                # conflict, so it can render a "and N other cells will
                # be auto-merged from non-conflicting sheets" hint. Same
                # info the modal already shows in row_data, but explicit
                # so a future FE rev can surface it without re-deriving.
                'conflicting_columns': sorted(conflicting_tgt_cols),
            })

    if unresolved_count > 0:
        agg_column_mappings = {}
        for st in per_sheet_states:
            for src, tgt in (st['column_mappings'] or {}).items():
                if tgt and src not in agg_column_mappings:
                    agg_column_mappings[src] = tgt
        print(
            f"   Column-merge: {unresolved_count} unresolved cell-conflict(s) "
            f"of {len(conflicts_to_resolve)} total — surfacing modal."
        )
        return {
            'success': True,
            'preview': True,
            'aggregate_mode': True,
            'requires_conflict_resolution': True,
            # We re-use the multi_sheet_aggregate conflict_kind so the FE
            # renders the cross-sheet picker UI (same shape: per-anchor
            # candidates, each with sheet_name + row_data). Distinguishing
            # this flavor in the FE isn't necessary — same picker works.
            'conflict_kind': 'multi_sheet_aggregate',
            'aggregated_sheets': list(sheet_names),
            'conflicts_to_resolve': conflicts_to_resolve,
            'column_mappings': agg_column_mappings,
            'write_strategy': 'multi_sheet_column_merge',
            'anchor_column': base_anchor,
            'message': (
                f'Found {len(conflicts_to_resolve)} identifier(s) where multiple '
                f'sheets disagree on a column value. Pick which sheet wins for each.'
            ),
            'strategy_metadata': {
                'column_merge': True,
                'sheet_names':  list(sheet_names),
                # Echo previously-resolved intra-section choices so they
                # stay applied when the user picks cross-sheet winners
                # and the FE re-previews. Without this echo the FE has
                # to re-send them and the second preview re-detects the
                # already-resolved intra-section dupes.
                'intra_section_choices': raw_intra_choices,
                'underlying_strategy':   base_strategy,
                'anchor_columns':        base_anchor if isinstance(base_anchor, list) else None,
                # Cache hit on the next preview (cross-sheet conflict
                # resolved → re-preview lands here). Same correctness +
                # performance argument as the intra-section return.
                'per_sheet_cache':       _build_per_sheet_cache(),
            },
        }

    # No unresolved conflicts — build merged_cells honoring user picks
    # (which only matter if a cell IS a conflict; for unique cells the
    # single owner wins).
    merged_cells = {}
    for (lookup_key, tgt_col), owners in cell_owners.items():
        if len(owners) == 1:
            sn, val = owners[0]
            merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)
            continue
        distinct_values = {_format_cell_value(v) for _, v in owners}
        if len(distinct_values) == 1:
            sn, val = owners[0]
            merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)
            continue
        choice = norm_choices.get(lookup_key)
        if choice == 'skip':
            continue
        winner = next((o for o in owners if o[0] == choice), owners[0])
        sn, val = winner
        merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)

    # Inject EXPLICIT-EMPTY writes from intra-section row picks. When the
    # user picked Row N in the duplicate modal AND Row N has a blank
    # cell at some column, we want the target cell to be CLEARED (the
    # user's pick is authoritative). The cell_owners loop above skipped
    # those blanks to keep cross-sheet conflict detection sane, so we
    # add them back here — but only on (anchor, tgt_col) pairs that
    # NO sheet has already claimed with a non-empty value. This way:
    #   * Single-owner blank: target gets cleared (user's intent).
    #   * Cross-sheet column where another sheet has a real value:
    #     untouched, the non-empty wins (a row pick shouldn't blank
    #     out a column owned by a different sheet).
    if explicit_anchors_by_sheet:
        for sheet_name, explicit_anchors in explicit_anchors_by_sheet.items():
            if not explicit_anchors:
                continue
            try:
                st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
                anchor_map = next(m for nn, m in per_sheet_maps if nn == sheet_name)
            except StopIteration:
                continue
            sheet_mappings = {
                k: v for k, v in (st['column_mappings'] or {}).items()
                if v and v not in anchor_col_set and v not in formula_col_set
            }
            for anchor_key in explicit_anchors:
                entry = anchor_map.get(anchor_key)
                if not entry:
                    continue
                src_row = entry.get('src_row') or {}
                existing_anchor_cells = merged_cells.get(anchor_key, {})
                for src_col, tgt_col in sheet_mappings.items():
                    if tgt_col in existing_anchor_cells:
                        continue
                    if (anchor_key, tgt_col) in cell_owners:
                        continue
                    raw_val = src_row.get(src_col)
                    is_empty = (
                        raw_val is None
                        or (isinstance(raw_val, str) and not raw_val.strip())
                    )
                    if not is_empty:
                        continue
                    merged_cells.setdefault(anchor_key, {})[tgt_col] = (sheet_name, '')

    # Diff vs target — walk target rows, look up merged cells per anchor,
    # emit per-cell overwrites / fills / no-ops.
    header_index = section_target.get('header_index', {})
    raw_rows     = section_target.get('raw_rows', [])
    section_data_rows = raw_rows[1:] if raw_rows else []
    anchor_cols = base_anchor if isinstance(base_anchor, list) else [base_anchor]
    anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

    # Union of contributed target cols across all sheets — what we'll
    # actually consider writing. Pull from BOTH cell_owners (non-empty
    # owner contributions) and merged_cells (which now includes the
    # explicit-empty injections from intra_section_choices), so a row
    # pick whose only mapped column is blank still gets a chance to
    # clear the matching target cell.
    target_cols_to_write = sorted(
        {tgt_col for (_lk, tgt_col) in cell_owners.keys()}
        | {tc for cells in merged_cells.values() for tc in cells.keys()}
    )

    conflicts        = []   # cell-level overwrites (existing != new)
    empty_cells      = []   # target cell empty, source has value
    no_op_cells      = []   # source value equals target value
    skipped_no_match = []
    rows_to_update   = []
    diff_total_cells = 0
    diff_truncated   = False

    target_anchor_set = set()
    for row in section_data_rows:
        parts = []
        for ai in anchor_idxs:
            val = row[ai] if ai is not None and ai < len(row) else None
            if val:
                normed = (
                    _normalize_date_value(val) if is_date_anchor
                    else str(val).strip()
                )
                if normed:
                    parts.append(normed)
        anchor_val = '|'.join(parts) if len(parts) > 1 else (parts[0] if parts else None)
        if not anchor_val:
            continue
        check = anchor_val if is_date_anchor else anchor_val.lower()
        target_anchor_set.add(check)

        cells_for_anchor = merged_cells.get(check)
        if not cells_for_anchor:
            continue

        # Per-row tracker: any_cell_emitted = at least one cell was
        # classified into conflicts / empty_cells / no_op_cells. We
        # include no-op cells in the row count because the user
        # explicitly asked to see ALL matched anchors in the preview
        # (even when every cell happens to be a no-op) so they can
        # un-check cells before confirming. Same semantics as the
        # cross_tab × section aggregate path's
        # `if row_diff_cells > 0 or row_no_op_cells > 0` gate.
        any_cell_emitted = False
        for tgt_col in target_cols_to_write:
            owner = cells_for_anchor.get(tgt_col)
            if not owner:
                continue
            sn, raw_val = owner
            new_value = _format_cell_value(raw_val)
            # NOTE: don't skip when new_value is empty. Empties in
            # merged_cells now come ONLY from explicit intra-section
            # row picks (the cell_owners loop above still gates
            # incidental blanks), so an empty here means the user
            # deliberately chose to clear this cell. Letting it
            # through classifies it as a conflict (overwrite-to-blank)
            # if target had a value, or a no-op if target was already
            # empty — both correct.
            col_idx = header_index.get(tgt_col)
            if col_idx is None:
                continue
            existing = row[col_idx] if col_idx < len(row) else None
            existing_str = str(existing).strip() if existing is not None else ''
            if existing_str.startswith('='):
                continue

            diff_total_cells += 1
            if diff_total_cells > MAX_DIFF_CELLS:
                diff_truncated = True
                continue

            if existing_str and existing_str != new_value:
                conflicts.append({
                    'anchor_value':   anchor_val,
                    'column':         tgt_col,
                    'existing_value': existing_str,
                    'new_value':      new_value,
                    'source_sheet':   sn,
                })
            elif not existing_str and new_value:
                empty_cells.append({
                    'anchor_value': anchor_val,
                    'column':       tgt_col,
                    'new_value':    new_value,
                    'source_sheet': sn,
                })
            elif existing_str == new_value:
                no_op_cells.append({
                    'anchor_value':   anchor_val,
                    'column':         tgt_col,
                    'new_value':      new_value,
                    'existing_value': existing_str,
                    'source_sheet':   sn,
                })
            else:
                # existing_str == '' and new_value == '': both blank,
                # nothing to do, skip without counting.
                continue
            any_cell_emitted = True
        if any_cell_emitted:
            rows_to_update.append(str(anchor_val))

    # Orphan source anchors → skipped_no_match. Update-only contract.
    for lookup_key, cells in merged_cells.items():
        if lookup_key in target_anchor_set:
            continue
        display = anchor_to_display.get(lookup_key, lookup_key)
        sheets_for_orphan = sorted({sn for sn, _ in cells.values()})
        merged_row_data = {
            tc: _format_cell_value(v) for tc, (sn, v) in cells.items()
        }
        skipped_no_match.append({
            'sheet_name':   ', '.join(sheets_for_orphan),
            'anchor_value': str(display),
            'row_data':     merged_row_data,
            'reason':       'no_match_in_target',
        })

    # Aggregate column mappings union for the response payload.
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt
    write_mappings = {
        k: v for k, v in agg_column_mappings.items()
        if v and v not in anchor_col_set and v not in formula_col_set
    }

    agg_source_cols = []
    for st in per_sheet_states:
        for h in st['source_schema'].get('headers', []) or []:
            if h not in agg_source_cols:
                agg_source_cols.append(h)
    agg_target_headers = list(section_target.get('headers', []) or [])
    rows_in_source_total = sum(
        st['source_schema'].get('total_rows', 0) or 0
        for st in per_sheet_states
    )

    print(
        f"   Column-merge diff: {len(conflicts)} overwrites + "
        f"{len(empty_cells)} fills + {len(no_op_cells)} no-ops + "
        f"{len(rows_to_update)} matched anchors + "
        f"{len(skipped_no_match)} orphans "
        f"(cells: {diff_total_cells}, truncated: {diff_truncated})"
    )

    # Capture the LLM identification result PER SHEET so the confirm
    # path can replay the merge without re-calling find_identifier on
    # each sheet. This is what brings the run path under the 30s API
    # Gateway timeout for multi-sheet writes — without it, the run
    # repeats ~17s of LLM work the preview already did.
    #
    # We deliberately stash only the small identification fields, NOT
    # parse_result or full_data: the response payload is bounded by
    # API Gateway's 10 MB response cap and Lambda's 6 MB sync-invoke
    # cap, and full_data for big xlsx files easily exceeds both.
    final_strategy_metadata = {
        'column_merge':         True,
        'sheet_names':          list(sheet_names),
        'conflict_resolutions': norm_choices,
        'underlying_strategy':  base_strategy,
        'anchor_columns':       base_anchor if isinstance(base_anchor, list) else None,
        # Echo any intra-section choices the user already resolved so a
        # later re-preview from the diff modal (e.g. "back" button) keeps
        # the row picks applied without re-prompting.
        'intra_section_choices': raw_intra_choices,
        # Per-sheet identification cache — the confirm-side
        # _run_multi_sheet_column_merge reads this and skips the LLM
        # call for every sheet listed here. ALSO consumed by the
        # preview-side cache lookup at the top of this function so a
        # re-preview from any modal stage skips the LLM too.
        'per_sheet_cache':      _build_per_sheet_cache(),
    }

    sources_label = ", ".join(repr(sn) for sn in sheet_names)
    return {
        'success':          True,
        'preview':          True,
        'aggregate_mode':   True,
        'aggregated_sheets': list(sheet_names),
        'write_strategy':   'multi_sheet_column_merge',
        'underlying_strategy': base_strategy,
        'anchor_column':    base_anchor,
        'source_anchor':    per_sheet_states[0]['identification'].get('source_anchor'),
        'anchor_type':      per_sheet_states[0]['identification'].get('anchor_type', ''),
        'reasoning': (
            f"Merging columns from {len(per_sheet_states)} source sheet(s) ("
            + sources_label
            + f") into target tab {target_sheet_name!r}. Each anchor row in "
            f"the target gets cells from whichever sheet provides them. "
            f"Update-only — orphan rows are listed but not written."
        ),
        'source_columns':   agg_source_cols,
        'target_headers':   agg_target_headers,
        'column_mappings':  write_mappings,
        'unmapped_source':  [],
        'rows_in_source':   rows_in_source_total,
        'rows_in_target':   section_target.get('total_rows', 0) or 0,
        'source_col_types': {},
        'target_col_types': section_target.get('col_types', {}) or {},
        'formula_cols':     list(section_target.get('formula_cols', []) or []),
        'conflicts':        conflicts,
        'empty_cells':      empty_cells,
        'no_op_cells':      no_op_cells,
        'appended_rows_preview': [],
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   rows_to_update,
        'rows_to_append':   [],
        'rows_to_update_count': len(rows_to_update),
        'rows_to_append_count': 0,
        'skipped_no_match': skipped_no_match,
        'is_empty_target':  bool(section_target.get('is_empty_target')),
        'header_row_count': section_target.get('header_row_count', 1) or 1,
        'composite_to_col_index': section_target.get('composite_to_col_index', {}) or {},
        'sheet_name':           None,
        'auto_selected_sheet':  None,
        'strategy_metadata':    final_strategy_metadata,
        'pivot_source_col':     None,
        'value_source_col':     None,
    }


def _run_multi_sheet_column_merge(
    inputs, sheet_names, conflict_resolutions,
    sheet_id, target_sheet_name, credentials,
    cached_per_sheet=None,
):
    """Confirm path for multi_sheet_column_merge.

    Replays the preview's per-sheet parse + per-cell merge using the
    user's conflict_resolutions, then writes ONLY matched rows into the
    target tab via the SAME ``update_rows_by_date`` /
    ``update_rows_by_anchor`` sheets-agent tools the aggregate path uses.

    Update-only (orphan anchors are silently skipped), same as
    ``_run_multi_sheet_aggregate``. The crucial difference vs aggregate
    is row construction: each row's row_data combines cells from every
    sheet that has a matching anchor, so a single target row can pick
    up Sheet A's inventory cols AND Sheet B's expense cols at once.

    ``cached_per_sheet`` is the preview's ``strategy_metadata.per_sheet_cache``
    list. When present, each entry's ``column_mappings`` /
    ``write_strategy`` / ``anchor_column`` is replayed verbatim, skipping
    the find_identifier LLM call entirely. This is the optimization that
    keeps the column-merge confirm under API Gateway's 30s timeout for
    typical 2-3 sheet writes.
    """
    file_content = inputs['file_content']
    file_type    = inputs.get('file_type', 'xlsx')
    credentials_local = credentials

    print(
        f"Column-merge write: {len(sheet_names)} sheets → {target_sheet_name!r}"
    )

    safe_name = (
        f"'{target_sheet_name}'"
        if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
        else target_sheet_name
    )
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials_local,
    })
    if not sheet_read.get('success'):
        return {
            'success': False,
            'error': f"Cannot read target sheet for column-merge write: {sheet_read.get('error')}",
            'error_type': 'column_merge_target_read_failed',
        }
    raw_values = sheet_read.get('data', sheet_read.get('values', []))

    formula_cols = detect_formula_columns(
        sheet_id,
        f"'{target_sheet_name}'" if ' ' in target_sheet_name else target_sheet_name,
        credentials_local,
    )

    target_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_target_data',
        'inputs': {'raw_values': raw_values, 'sheet_name': target_sheet_name},
    })
    if not target_schema.get('success'):
        return {
            'success': False,
            'error': f"Cannot structure target for column-merge write: {target_schema.get('error')}",
            'error_type': 'column_merge_target_structure_failed',
        }
    existing_formula_cols = set(target_schema.get('formula_cols', []))
    existing_formula_cols.update(formula_cols)
    target_schema['formula_cols'] = list(existing_formula_cols)

    section_target = dict(target_schema)

    # Build {sheet_name: cached_identification} so we can pass it through
    # to _aggregate_parse_one_sheet and skip the find_identifier LLM call
    # for every sheet the preview already mapped. Preview stashes this in
    # strategy_metadata.per_sheet_cache; legacy bundles that pre-date
    # this optimization just send None and we fall through to the LLM
    # path unchanged.
    cache_by_name = {}
    if cached_per_sheet:
        for entry in cached_per_sheet:
            sn = entry.get('sheet_name')
            if sn:
                cache_by_name[sn] = entry
        if cache_by_name:
            print(
                f"   column-merge confirm: replaying cached identification "
                f"for {len(cache_by_name)} sheet(s) — skipping find_identifier"
            )

    # Parallelize across sheets just like the preview path. With
    # cached_per_sheet present, each task only spends time on parse_file
    # + structure_source_data (no LLM), which is bound by Lambda
    # round-trip latency rather than wall-time work, so parallelism
    # still helps even after the LLM is removed.
    parse_t0 = time.time()
    max_workers = max(1, min(6, len(sheet_names)))
    per_sheet_states_by_name = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _aggregate_parse_one_sheet,
                file_content, file_type, sn, section_target,
                cache_by_name.get(sn),
            ): sn
            for sn in sheet_names
        }
        for fut in as_completed(futures):
            sn = futures[fut]
            try:
                state, err = fut.result()
            except Exception as exc:
                return {
                    'success': False,
                    'error': f"Sheet {sn!r}: parse raised {type(exc).__name__}: {exc}",
                    'error_type': 'column_merge_sheet_failed',
                }
            if err:
                return {
                    'success': False, 'error': err,
                    'error_type': 'column_merge_sheet_failed',
                }
            per_sheet_states_by_name[sn] = state
    per_sheet_states = [per_sheet_states_by_name[sn] for sn in sheet_names]
    print(
        f"   per-sheet parse (parallel x{max_workers}, "
        f"cached={len(cache_by_name)}/{len(sheet_names)}): "
        f"{(time.time() - parse_t0):.2f}s"
    )

    base_strategy = per_sheet_states[0]['write_strategy']
    base_anchor   = per_sheet_states[0]['anchor_column']
    is_date_anchor = per_sheet_states[0]['is_date_anchor']
    is_composite = isinstance(base_anchor, list)
    anchor_cols = base_anchor if is_composite else [base_anchor]

    if base_strategy not in ('row_per_date', 'row_per_entity', 'composite_key'):
        return {
            'success': False,
            'error': (
                f"Column-merge supports row-keyed strategies only; "
                f"got {base_strategy!r}."
            ),
            'error_type': 'column_merge_unsupported_strategy',
        }

    # Apply intra_section_choices per sheet BEFORE building anchor maps,
    # mirroring the preview-side logic. Without this, the run path's
    # _aggregate_build_anchor_map would silently last-write on duplicate
    # anchors even though preview already asked the user to resolve them
    # — meaning the user's row pick gets ignored on confirm. Accept both
    # the flat ({anchor: choice}) and nested ({sheet: {anchor: choice}})
    # shapes, same back-compat treatment as preview.
    raw_intra_choices = inputs.get('intra_section_choices')
    if raw_intra_choices is None:
        _meta_in = inputs.get('strategy_metadata') or {}
        if isinstance(_meta_in, str):
            try:
                _meta_in = json.loads(_meta_in)
            except Exception:
                _meta_in = {}
        raw_intra_choices = _meta_in.get('intra_section_choices')
    norm_intra_all = _normalize_intra_section_choices(raw_intra_choices)
    is_nested_intra = bool(norm_intra_all) and all(
        isinstance(v, dict) for v in norm_intra_all.values()
    )
    if norm_intra_all:
        for st in per_sheet_states:
            sn = st['sheet_name']
            sheet_choices = (
                norm_intra_all.get(sn) or {}
                if is_nested_intra
                else norm_intra_all
            )
            if not sheet_choices:
                continue
            full_data_in = st['full_data'] or []
            full_data_filtered = _apply_intra_section_choices(
                full_data_in,
                sheet_choices,
                st['source_anchor_names'],
                st['is_date_anchor'],
            )
            if len(full_data_filtered) != len(full_data_in):
                print(
                    f"   Run-side applied intra_section_choices to sheet "
                    f"{sn!r}: {len(full_data_in)} -> "
                    f"{len(full_data_filtered)} rows"
                )
                st['full_data'] = full_data_filtered
                if isinstance(st.get('parse_result'), dict):
                    st['parse_result']['full_data'] = full_data_filtered

    # Mirror the preview-side `explicit_anchors_by_sheet` build so the
    # confirm path also honors blank cells from the user's chosen rows
    # (e.g., picking the Operational Cost row whose Meals Expenses is
    # empty for 2025-01-19 should clear the target's Meals Expenses for
    # that date, not preserve the existing target value). Keys are
    # normalized to match `_aggregate_build_anchor_map`'s lookup_key.
    explicit_anchors_by_sheet = {}
    if norm_intra_all:
        for st in per_sheet_states:
            sn = st['sheet_name']
            if is_nested_intra:
                sheet_choices = norm_intra_all.get(sn) or {}
            else:
                sheet_choices = norm_intra_all
            keys = set()
            is_date = bool(st.get('is_date_anchor'))
            for k, v in (sheet_choices or {}).items():
                if k is None:
                    continue
                if v == 'skip':
                    continue
                norm_k = str(k) if is_date else str(k).lower()
                keys.add(norm_k)
            explicit_anchors_by_sheet[sn] = keys

    per_sheet_maps = [
        (st['sheet_name'], _aggregate_build_anchor_map(st))
        for st in per_sheet_states
    ]

    raw_choices = conflict_resolutions or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}
    norm_choices = {}
    for k, v in (raw_choices or {}).items():
        if k is None:
            continue
        norm_k = str(k) if is_date_anchor else str(k).lower()
        norm_choices[norm_k] = v

    formula_col_set = set(section_target.get('formula_cols', []) or [])
    anchor_col_set = (set(anchor_cols) if anchor_cols else set())

    cell_owners = {}
    anchor_to_display = {}
    for sheet_name, m in per_sheet_maps:
        st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
        sheet_mappings = {
            k: v for k, v in (st['column_mappings'] or {}).items()
            if v and v not in anchor_col_set and v not in formula_col_set
        }
        target_to_source_local = {tgt: src for src, tgt in sheet_mappings.items()}
        for lookup_key, entry in m.items():
            anchor_to_display.setdefault(lookup_key, entry['display'])
            for tgt_col, src_col in target_to_source_local.items():
                raw_val = entry['src_row'].get(src_col)
                if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
                    continue
                cell_owners.setdefault((lookup_key, tgt_col), []).append(
                    (sheet_name, raw_val)
                )

    merged_cells = {}
    unresolved_conflicts = []
    for (lookup_key, tgt_col), owners in cell_owners.items():
        if len(owners) == 1:
            sn, val = owners[0]
            merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)
            continue
        distinct_values = {_format_cell_value(v) for _, v in owners}
        if len(distinct_values) == 1:
            sn, val = owners[0]
            merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)
            continue
        choice = norm_choices.get(lookup_key)
        if choice == 'skip':
            continue
        if choice is None:
            unresolved_conflicts.append(
                anchor_to_display.get(lookup_key, lookup_key)
            )
            continue
        # Edge case: user picked a sheet at the ANCHOR level (modal
        # aggregates across all conflicting cells for that anchor), but
        # this specific cell's owner-set may not include the chosen
        # sheet (when different cells of the same anchor have
        # different overlapping sheet sets). This is more common now
        # that the planner allows arbitrary cross-sheet column overlap,
        # so the fallback path matters. Match the preview's graceful
        # behavior (winner = ... or owners[0]) rather than aborting
        # the whole write — the user's intent was "pick a winner for
        # this anchor" and any cell that lacks that sheet still gets
        # a deterministic value (the first owner seen during cell_owners
        # construction). A fully per-cell modal would let the user
        # choose, but that's a UX change tracked separately.
        winner = next((o for o in owners if o[0] == choice), owners[0])
        sn, val = winner
        if winner[0] != choice:
            print(
                f"   column-merge-write: anchor {lookup_key!r} cell "
                f"{tgt_col!r} — user picked {choice!r} but only "
                f"{[o[0] for o in owners]} own this cell; falling "
                f"back to {winner[0]!r}"
            )
        merged_cells.setdefault(lookup_key, {})[tgt_col] = (sn, val)

    # Mirror the preview-side explicit-empty injection. The intra-section
    # row pick is authoritative — empty cells in the chosen row should
    # CLEAR the corresponding target cells, not silently leave the
    # target's existing value in place. We only inject on (anchor,
    # tgt_col) pairs no other sheet has claimed with a non-empty value
    # so a row pick can't accidentally blank out a cross-sheet
    # column where another sheet has a real value.
    if explicit_anchors_by_sheet:
        injected_count = 0
        for sheet_name, explicit_anchors in explicit_anchors_by_sheet.items():
            if not explicit_anchors:
                continue
            try:
                st = next(s for s in per_sheet_states if s['sheet_name'] == sheet_name)
                anchor_map = next(m for nn, m in per_sheet_maps if nn == sheet_name)
            except StopIteration:
                continue
            sheet_mappings = {
                k: v for k, v in (st['column_mappings'] or {}).items()
                if v and v not in anchor_col_set and v not in formula_col_set
            }
            for anchor_key in explicit_anchors:
                entry = anchor_map.get(anchor_key)
                if not entry:
                    continue
                src_row = entry.get('src_row') or {}
                existing_anchor_cells = merged_cells.get(anchor_key, {})
                for src_col, tgt_col in sheet_mappings.items():
                    if tgt_col in existing_anchor_cells:
                        continue
                    if (anchor_key, tgt_col) in cell_owners:
                        continue
                    raw_val = src_row.get(src_col)
                    is_empty = (
                        raw_val is None
                        or (isinstance(raw_val, str) and not raw_val.strip())
                    )
                    if not is_empty:
                        continue
                    merged_cells.setdefault(anchor_key, {})[tgt_col] = (sheet_name, '')
                    injected_count += 1
        if injected_count:
            print(
                f"   Run-side explicit-empty injection: {injected_count} "
                f"cell(s) marked for clear-write from intra-section picks."
            )

    if unresolved_conflicts:
        return {
            'success': False,
            'error': (
                f"Column-merge write blocked by {len(unresolved_conflicts)} "
                f"unresolved conflict(s): {unresolved_conflicts[:5]}. "
                f"Re-run preview to resolve them."
            ),
            'error_type': 'column_merge_unresolved_conflicts',
        }

    # Build target anchor set + write_only filter (per-cell from FE).
    target_anchor_set = set()
    header_index = section_target.get('header_index', {})
    raw_rows     = section_target.get('raw_rows', [])
    section_data_rows = raw_rows[1:] if raw_rows else []
    anchor_idxs = [header_index.get(ac) for ac in anchor_cols]

    for row in section_data_rows:
        parts = []
        for ai in anchor_idxs:
            val = row[ai] if ai is not None and ai < len(row) else None
            if val:
                normed = (
                    _normalize_date_value(val) if is_date_anchor
                    else str(val).strip()
                )
                if normed:
                    parts.append(normed)
        if parts:
            anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
            check = anchor_val if is_date_anchor else anchor_val.lower()
            target_anchor_set.add(check)

    write_only_raw = inputs.get('write_only')
    if isinstance(write_only_raw, str) and write_only_raw.strip():
        try:
            write_only_raw = json.loads(write_only_raw)
        except Exception:
            write_only_raw = None
    write_only = write_only_raw if isinstance(write_only_raw, dict) else None
    allowed_diff_cells = None
    if write_only:
        diff_cells = write_only.get('allowed_diff_cells') or []
        allowed_diff_cells = {
            (str(c.get('anchor')), c.get('column'))
            for c in diff_cells
            if isinstance(c, dict)
            and c.get('anchor') is not None
            and c.get('column')
        } or None

    rows_for_write = []
    skipped_orphan = 0
    skipped_unselected = 0

    for lookup_key, cells in merged_cells.items():
        if lookup_key not in target_anchor_set:
            skipped_orphan += 1
            continue
        display = anchor_to_display.get(lookup_key, lookup_key)
        row_data = {}
        for tgt_col, (sn, raw_val) in cells.items():
            if allowed_diff_cells is not None:
                if (str(display), tgt_col) not in allowed_diff_cells:
                    skipped_unselected += 1
                    continue
            row_data[tgt_col] = raw_val
        if not row_data:
            continue
        if base_strategy == 'row_per_date' and not is_composite:
            rows_for_write.append({
                'date': display,
                'date_formatted': display,
                'row_data': row_data,
            })
        else:
            entry = dict(row_data)
            if is_composite and isinstance(display, str) and '|' in display:
                parts = display.split('|')
                for col, part in zip(anchor_cols, parts):
                    entry[col] = part.strip()
            else:
                entry[anchor_cols[0]] = display
            rows_for_write.append(entry)

    print(
        f"   Column-merge prep: {len(rows_for_write)} rows ready, "
        f"{skipped_orphan} orphan(s), "
        f"{skipped_unselected} cell(s) deselected via write_only"
    )

    if not rows_for_write:
        return {
            'success': False,
            'error': (
                'Column-merge write found no matched rows to write. Either every '
                'source identifier was an orphan against the target tab, or '
                'every cell was deselected.'
            ),
            'error_type': 'column_merge_empty_write',
            'aggregated_sheets': sheet_names,
        }

    # Aggregated column_mappings union — for the response payload only.
    agg_column_mappings = {}
    for st in per_sheet_states:
        for src, tgt in (st['column_mappings'] or {}).items():
            if tgt and tgt not in anchor_col_set and tgt not in formula_col_set:
                if src not in agg_column_mappings:
                    agg_column_mappings[src] = tgt

    # Dispatch write — same primitives the aggregate path uses.
    if base_strategy == 'row_per_date' and not is_composite:
        write_inputs = {
            'sheet_id':         sheet_id,
            'sheet_name':       target_sheet_name,
            'date_column_name': base_anchor,
            'rows_with_dates':  rows_for_write,
            'header_row':       0,
        }
        update_result = invoke(SHEETS_LAMBDA, {
            'tool': 'update_rows_by_date',
            'inputs': write_inputs,
            'credentials_dict': credentials_local,
        })
    else:
        write_inputs = {
            'sheet_id':      sheet_id,
            'sheet_name':    target_sheet_name,
            'anchor_column': base_anchor,
            'rows':          rows_for_write,
            'header_row':    0,
        }
        update_result = invoke(SHEETS_LAMBDA, {
            'tool': 'update_rows_by_anchor',
            'inputs': write_inputs,
            'credentials_dict': credentials_local,
        })

    rows_updated  = int(update_result.get('rows_updated', 0) or 0)
    cells_updated = int(update_result.get('cells_updated', 0) or 0)
    success = bool(update_result.get('success')) and rows_updated > 0

    response = {
        'success':         success,
        'write_strategy':  'multi_sheet_column_merge',
        'underlying_strategy': base_strategy,
        'anchor_column':   base_anchor,
        'rows_processed':  len(rows_for_write),
        'aggregated_sheets': sheet_names,
        'column_mappings': agg_column_mappings,
        'write_result': {
            'success':          success,
            'rows_updated':     rows_updated,
            'rows_appended':    0,
            'cells_updated':    cells_updated,
            'orphans_skipped':  skipped_orphan,
            'deselected_skipped': skipped_unselected,
            'sheets_merged':    len(sheet_names),
        },
    }
    if not success:
        response['error'] = (
            update_result.get('error')
            or 'Column-merge write returned zero updates — usually means the '
               'target tab has no rows matching the merged anchor set.'
        )
    return response


# ============================================================================
# Cross-tab × per-source-section aggregate preview/run
# ============================================================================
# Pairs with _plan_cross_tab_section_aggregate. For each route_group
# (target_section -> [list of (sheet, source_section)]) the same merge logic
# the cross-tab aggregate uses runs PER GROUP, then per-group diffs are
# merged into one preview payload. Conflict candidates carry a composite
# choice_id `<sheet>||<section>||row_<N>` so the FE conflict modal can
# uniquely identify each row when the same anchor appears in 2+ source
# locations within the SAME target bucket. This unifies intra-section dups
# (same source section, same anchor, multiple rows) and cross-tab dups
# (anchor in source-Inbound for both March and April tabs) into ONE modal.
# ============================================================================

# Composite choice_id delimiter. Avoids common XLSX header chars and the
# sheet-name colon convention used in existing route_results aggregations.
_CT_CHOICE_DELIM = '||'


def _ct_make_choice_id(sheet_name, section_title, row_idx):
    """Stable per-candidate id used as the modal radio key on the FE side
    AND as the lookup key on the confirm path. row_idx is the 0-based
    position within the source section's full_data list (NOT the absolute
    spreadsheet row, because that depends on header_row offsets that don't
    round-trip via JSON cleanly)."""
    s = (sheet_name or '').replace(_CT_CHOICE_DELIM, '_')
    t = (section_title or '').replace(_CT_CHOICE_DELIM, '_')
    return f"{s}{_CT_CHOICE_DELIM}{t}{_CT_CHOICE_DELIM}row_{int(row_idx)}"


def _ct_parse_choice_id(choice_id):
    """Returns (sheet_name, section_title, row_idx) or None for 'skip' /
    malformed. Used by the run path to look up the chosen row in the
    re-parsed per-section state dicts."""
    if not choice_id or choice_id == 'skip':
        return None
    parts = str(choice_id).split(_CT_CHOICE_DELIM)
    if len(parts) != 3:
        return None
    sheet, section, row_token = parts
    if not row_token.startswith('row_'):
        return None
    try:
        return (sheet, section, int(row_token[len('row_'):]))
    except ValueError:
        return None


def _ct_build_candidates_per_anchor(per_section_states, is_date_anchor):
    """Walk every (sheet, section) state and collect ALL rows per anchor key
    — intentionally NOT collapsing dups (unlike _aggregate_build_anchor_map).
    The caller then surfaces anchors with len(candidates)>=2 as conflicts.

    Returns ``{lookup_key: [{'sheet_name', 'section_title', 'row_idx',
    'src_row', 'display'}, ...]}``. Order within a key reflects scan order
    (sheet order, then row order) so the FE renders candidates in a
    predictable sequence.
    """
    candidates = {}  # lookup_key -> list of candidate dicts
    for st in per_section_states:
        sheet_name    = st['sheet_name']
        section_title = st.get('source_section_title') or sheet_name
        source_anchor_names = st['source_anchor_names']
        for row_idx, src_row in enumerate(st['full_data']):
            parts = []
            for sa in source_anchor_names:
                val = src_row.get(sa)
                if val is None:
                    continue
                normed = (
                    _normalize_date_value(val) if is_date_anchor
                    else str(val).strip()
                )
                if normed:
                    parts.append(normed)
            if not parts:
                continue
            anchor_val = '|'.join(parts) if len(parts) > 1 else parts[0]
            lookup_key = anchor_val if is_date_anchor else anchor_val.lower()
            candidates.setdefault(lookup_key, []).append({
                'sheet_name':    sheet_name,
                'section_title': section_title,
                'row_idx':       row_idx,
                'src_row':       src_row,
                'display':       anchor_val,
            })
    return candidates


def _ct_pick_winner_from_candidates(candidates_for_key, choice_id):
    """Return the chosen candidate dict from the list, by matching the
    composite choice_id.

    Match-order — strictest to loosest, falling through on no-match:
      1. Exact composite (sheet || section || row_<N>) — the canonical form
         the FE should send. Disambiguates intra-section duplicates.
      2. Bare sheet_name (legacy fallback) — picks the first candidate whose
         sheet_name matches. Lets a stale FE bundle that hasn't been
         redeployed since the cross-tab × section feature shipped continue
         to work for the (common) case where each candidate has a unique
         sheet_name. Will silently pick the first matching row when the
         same sheet contributes multiple candidates (unavoidable — the
         old payload has no row info).
      3. First candidate (true last resort) — only fires when neither
         composite parse nor sheet_name match yielded a hit. Logged so
         we notice the silent-default in CloudWatch.

    'skip' short-circuits to None (drops the anchor entirely)."""
    if choice_id == 'skip':
        return None
    parsed = _ct_parse_choice_id(choice_id) if choice_id else None
    if parsed:
        s_name, s_title, r_idx = parsed
        for c in candidates_for_key:
            if (c['sheet_name'] == s_name
                    and c['section_title'] == s_title
                    and c['row_idx'] == r_idx):
                return c
        # Composite parsed but didn't match. Try sheet+section without row#
        # — covers the case where the FE sent a stale row_idx but the
        # (sheet, section) pair is still unambiguous in this candidate set.
        sheet_section_hits = [
            c for c in candidates_for_key
            if c['sheet_name'] == s_name and c['section_title'] == s_title
        ]
        if len(sheet_section_hits) == 1:
            print(
                f"   ct-pick: composite row# stale, fell back to unique "
                f"(sheet,section)=({s_name!r},{s_title!r}) match"
            )
            return sheet_section_hits[0]
    # Tier 2: bare sheet_name match (legacy FE payload shape — pre-choice_id
    # FE was sending {anchor_value: sheet_name}). Pick the FIRST candidate
    # whose sheet_name equals the choice. Safe whenever each candidate has
    # a unique sheet_name (i.e. cross-tab conflicts only — no intra-section
    # dups). Becomes ambiguous if the same sheet contributes multiple rows;
    # in that case we land on the earliest, which mirrors pre-feature
    # behavior so we don't regress the no-intra-dup workflows.
    if choice_id and isinstance(choice_id, str):
        sheet_hits = [
            c for c in candidates_for_key if c['sheet_name'] == choice_id
        ]
        if sheet_hits:
            if len(sheet_hits) > 1:
                print(
                    f"   ct-pick: legacy bare sheet_name {choice_id!r} matched "
                    f"{len(sheet_hits)} candidates — picking first (FE upgrade "
                    f"required to disambiguate intra-section dups)"
                )
            else:
                print(
                    f"   ct-pick: legacy bare sheet_name {choice_id!r} matched"
                )
            return sheet_hits[0]
    print(
        f"   ct-pick: choice {choice_id!r} did not match any candidate — "
        f"falling back to first ({candidates_for_key[0].get('sheet_name')!r}>"
        f"{candidates_for_key[0].get('section_title')!r}#"
        f"{candidates_for_key[0].get('row_idx')})"
    )
    return candidates_for_key[0]


def _preview_cross_tab_section_aggregate(
    file_content, file_type, target_sheet_name, raw_values,
    target_schema, formula_cols, route_groups, conflict_choices,
):
    """Per-target-section bucket aggregate preview.

    For each route_group {target_section_index, sources: [(sheet, section)]}:
      1. Parse each source via _aggregate_parse_one_section (existing helper).
      2. Build per-anchor candidate list (all rows from all sources, NOT
         collapsing intra-section dups).
      3. Emit a conflict for any anchor with 2+ candidates.
      4. Merge per-anchor winner from conflict_choices into a flat anchor map.
      5. Diff merged map vs target section rows -> rows_to_update + per-cell
         conflicts/empty_cells. Orphan source anchors -> skipped_no_match.

    All per-bucket diffs/conflicts/skipped_no_match get aggregated into ONE
    preview payload with write_strategy='cross_tab_section_aggregate'.

    Conflict envelope shape (FE-compatible):
      conflicts_to_resolve = [
        {
          'anchor_value': 'X',
          'target_section_title': 'Inbound',
          'candidates': [
            {'choice_id': 'March_Data||Inbound Metrix||row_3',
             'label':     'March_Data > Inbound Metrix > Row 4',
             'sheet_name': 'March_Data',           # back-compat
             'source_section_title': 'Inbound Metrix',
             'row_idx':   3,
             'row_data':  {'Trucks': '5', 'Pallets': '100', ...}},
            ...
          ],
        },
        ...
      ]
    """
    print(
        f"Cross-tab × section aggregate preview: {len(route_groups)} target "
        f"section bucket(s) on tab {target_sheet_name!r}"
    )

    # Resolve conflict_choices once at the top — same shape contract as the
    # cross-tab aggregate: {anchor_value: choice_id|"skip"}. Defense-in-depth
    # JSON parse mirrors what _preview_multi_sheet_aggregate does.
    raw_choices = conflict_choices or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}
    if not isinstance(raw_choices, dict):
        raw_choices = {}
    print(
        f"   cross-tab-section: raw_choices received = "
        f"{json.dumps(raw_choices, default=str)[:500]}"
    )

    bucket_results = []
    all_conflicts_to_resolve = []
    unresolved_total = 0

    # Detect target sections ONCE — Phase 1's bucket loop used to call
    # _detect_sections_local on every iteration even though raw_values
    # never changes. With N buckets that's N redundant scans of the
    # raw_values matrix; harmless for small targets but pure waste.
    sections_local_all = _detect_sections_local(raw_values or [])

    # Phase 1a: compute per-bucket section_target schemas (no LLM calls,
    # purely local). Validates target indices up front so we fail fast.
    bucket_section_targets = []
    for group_idx, group in enumerate(route_groups):
        tgt_idx = group['target_section_index']
        if not (0 <= tgt_idx < len(sections_local_all)):
            return {
                'success': False,
                'error': (
                    f"Cross-tab × section preview: target_section_index="
                    f"{tgt_idx} out of range (target has "
                    f"{len(sections_local_all)} section(s))"
                ),
                'error_type': 'cross_tab_section_invalid_target',
            }
        bucket_section_targets.append(_build_section_target_schema(
            sections_local_all[tgt_idx], raw_values,
            target_sheet_name, formula_cols,
        ))

    # Phase 1b: parallelize ALL per-source LLM identify calls across ALL
    # buckets. Without this, each (bucket × source) parse runs sequentially
    # and a 2-bucket × 2-source TC-L06 takes ~23 s of identify time alone
    # — pushing total preview past API Gateway's 29 s integration timeout
    # and surfacing as a 504 to the FE (the Lambda finishes successfully
    # but the user has already navigated away).
    #
    # Each task is one (group_idx, src_idx, src) parse. Results land back
    # in per_bucket_states[group_idx][src_idx] in original order so the
    # downstream conflict-scan loop sees the same structure as before.
    # ThreadPoolExecutor is safe here because identify() ultimately makes
    # an HTTP call to the mapping-agent Lambda (not CPU-bound, so the GIL
    # doesn't cap us).
    parse_tasks = []
    for group_idx, group in enumerate(route_groups):
        section_target = bucket_section_targets[group_idx]
        for src_idx, src in enumerate(group['sources']):
            src_section = dict(src['section'])
            src_section['__source_section_index'] = src.get('source_section_index')
            parse_tasks.append((group_idx, src_idx, src, src_section, section_target))

    parse_t0 = time.time()
    parse_results_by_key = {}
    # Cap workers at 6 — anything higher risks the mapping-agent Lambda
    # account-wide concurrency throttle on a single user request, and the
    # realistic worst case (3 buckets × 3 sources) is 9 tasks anyway.
    max_workers = max(1, min(6, len(parse_tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _aggregate_parse_one_section,
                file_content, file_type, src['sheet_name'],
                src_section, section_target,
            ): (group_idx, src_idx, src, src_section, section_target)
            for (group_idx, src_idx, src, src_section, section_target) in parse_tasks
        }
        for fut in as_completed(futures):
            (group_idx, src_idx, src, _, _) = futures[fut]
            try:
                state, err = fut.result()
            except Exception as exc:
                return {
                    'success': False,
                    'error': (
                        f"Bucket #{group_idx} "
                        f"(src {src['sheet_name']!r}): "
                        f"unexpected parse error: {exc}"
                    ),
                    'error_type': 'cross_tab_section_parse_exception',
                }
            if err:
                tgt_title = route_groups[group_idx].get('target_section_title')
                return {
                    'success': False,
                    'error': (
                        f"Bucket #{group_idx} "
                        f"(target {tgt_title!r}): {err}"
                    ),
                    'error_type': 'cross_tab_section_parse_failed',
                }
            # _aggregate_parse_one_section overwrites state['sheet_name']
            # with the SECTION title (a quirk for the intra-tab path
            # where all sections share one tab). For cross-tab × section
            # we need both the actual sheet name AND the section title
            # preserved so the conflict modal can label candidates as
            # "March_Data > Inbound Metrix > Row 1" and the choice_id
            # uniquely identifies (sheet, section, row#) triples even
            # when two tabs both have an "Inbound Metrics" section.
            state['sheet_name'] = src['sheet_name']
            state['source_section_title'] = (
                src.get('source_section_title')
                or state.get('source_section_title')
            )
            parse_results_by_key[(group_idx, src_idx)] = state
    print(
        f"   cross-tab-section: parallel parse of {len(parse_tasks)} "
        f"section(s) finished in {time.time() - parse_t0:.1f}s "
        f"(max_workers={max_workers})"
    )

    # Phase 1c: walk the buckets in original order (so per_section_states
    # ordering is deterministic — candidates_per_key iteration must match
    # what the FE saw on the first preview, or the choice_id round-trip
    # picks the wrong winner).
    for group_idx, group in enumerate(route_groups):
        tgt_idx        = group['target_section_index']
        tgt_title      = group.get('target_section_title')
        sources        = group['sources']
        section_target = bucket_section_targets[group_idx]

        per_section_states = [
            parse_results_by_key[(group_idx, si)] for si in range(len(sources))
        ]
        print(
            f"   bucket #{group_idx} ({tgt_title!r}): per-section states = "
            + ", ".join(
                f"({st['sheet_name']!r} > {st.get('source_section_title')!r}, "
                f"{len(st['full_data'])} rows)"
                for st in per_section_states
            )
        )

        # All sources in a bucket share the same write_strategy / anchor /
        # column_mappings (they all map to the SAME target section). Take
        # the first as canonical.
        canon = per_section_states[0]
        base_strategy = canon['write_strategy']
        if base_strategy not in ('row_per_date', 'row_per_entity', 'composite_key'):
            return {
                'success': False,
                'error': (
                    f"Cross-tab × section aggregate currently supports row-keyed "
                    f"strategies only. Bucket #{group_idx} target {tgt_title!r} "
                    f"got {base_strategy!r}."
                ),
                'error_type': 'cross_tab_section_unsupported_strategy',
            }
        is_date_anchor = canon['is_date_anchor']
        base_anchor    = canon['anchor_column']

        candidates_per_key = _ct_build_candidates_per_anchor(
            per_section_states, is_date_anchor,
        )

        bucket_conflicts = []
        bucket_unresolved = 0
        for lookup_key, cands in candidates_per_key.items():
            if len(cands) < 2:
                continue
            chosen = raw_choices.get(lookup_key)
            if chosen is None:
                bucket_unresolved += 1
            display_anchor = cands[0]['display']
            cand_payload = []
            for cand in cands:
                # Find the matching state dict so we know which mapped
                # columns to render for THIS candidate. Different sources
                # may have different column mappings (rare, but possible
                # if find_identifier picks slightly different mappings
                # per section).
                st = next(
                    s for s in per_section_states
                    if s['sheet_name'] == cand['sheet_name']
                    and (s.get('source_section_title') or s['sheet_name'])
                       == cand['section_title']
                )
                mappings = st['column_mappings'] or {}
                anchor_col_set_local = (
                    set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                    else ({st['anchor_column']} if st['anchor_column'] else set())
                )
                row_data = {}
                for src_col, tgt_col in mappings.items():
                    if not tgt_col or tgt_col in anchor_col_set_local:
                        continue
                    row_data[tgt_col] = _format_cell_value(
                        cand['src_row'].get(src_col)
                    )
                choice_id = _ct_make_choice_id(
                    cand['sheet_name'],
                    cand['section_title'],
                    cand['row_idx'],
                )
                cand_payload.append({
                    'choice_id':            choice_id,
                    'label': (
                        f"{cand['sheet_name']} > {cand['section_title']} > "
                        f"Row {cand['row_idx'] + 1}"
                    ),
                    'sheet_name':           cand['sheet_name'],
                    'source_section_title': cand['section_title'],
                    'row_idx':              cand['row_idx'],
                    'row_data':             row_data,
                })
            bucket_conflicts.append({
                'anchor_value':         str(display_anchor),
                'target_section_title': tgt_title,
                'target_section_index': tgt_idx,
                'candidates':           cand_payload,
            })
        all_conflicts_to_resolve.extend(bucket_conflicts)
        unresolved_total += bucket_unresolved

        bucket_results.append({
            'group_idx':            group_idx,
            'target_section_index': tgt_idx,
            'target_section_title': tgt_title,
            'sources':              sources,
            'per_section_states':   per_section_states,
            'section_target':       section_target,
            'candidates_per_key':   candidates_per_key,
            'is_date_anchor':       is_date_anchor,
            'base_strategy':        base_strategy,
            'base_anchor':          base_anchor,
        })

    # Phase 2: if any unresolved conflicts, surface modal — DO NOT compute
    # diffs (the user's pick changes which row's column values get diffed).
    if unresolved_total > 0:
        sources_for_label = []
        for g in route_groups:
            for s in g['sources']:
                tag = f"{s['sheet_name']} > {s['source_section_title']}"
                if tag not in sources_for_label:
                    sources_for_label.append(tag)
        modal_message = (
            f'Found {len(all_conflicts_to_resolve)} identifier(s) appearing in '
            f'multiple source rows that route to the same target section. '
            f'Pick which source row wins for each one.'
        )
        # Aggregate column mappings across all buckets for the FE diff table
        agg_column_mappings = {}
        for br in bucket_results:
            for st in br['per_section_states']:
                for src, tgt in (st['column_mappings'] or {}).items():
                    if tgt and src not in agg_column_mappings:
                        agg_column_mappings[src] = tgt
        return {
            'success': True,
            'preview': True,
            'aggregate_mode': True,
            'requires_conflict_resolution': True,
            'conflict_kind': 'cross_tab_section_aggregate',
            'aggregated_sheets': sources_for_label,
            'conflicts_to_resolve': all_conflicts_to_resolve,
            'column_mappings': agg_column_mappings,
            'write_strategy': 'cross_tab_section_aggregate',
            'anchor_column': bucket_results[0]['base_anchor'] if bucket_results else None,
            'message': modal_message,
        }

    # Phase 3: All conflicts resolved (or none existed). Compute per-bucket
    # diffs vs target rows + merge into a unified preview payload.
    rows_in_source_total = 0
    rows_in_target_total = 0
    diff_total_cells     = 0
    diff_truncated       = False
    all_conflicts        = []
    all_empty_cells      = []
    all_no_op_cells      = []   # cells where source value equals target value
    all_rows_to_update   = []
    all_skipped_no_match = []
    all_target_headers   = []
    agg_column_mappings  = {}
    # No-op tracking: cells where the chosen source value equals the target's
    # current value are now SURFACED to the user (not hidden) in their own
    # `no_op_cells` array so the preview UI can render them in the diff table
    # with an "UNCHANGED" type + checkbox. The user expects to see EVERY cell
    # the writer would touch — even no-ops — and have the option to uncheck
    # any of them. Hiding them was an unsolicited UX decision that backfired.
    no_op_cells_total       = 0
    rows_already_matching   = 0
    per_bucket_summary      = []

    for br in bucket_results:
        per_section_states = br['per_section_states']
        section_target     = br['section_target']
        candidates_per_key = br['candidates_per_key']
        is_date_anchor     = br['is_date_anchor']
        tgt_title          = br['target_section_title']

        # Merge winner per anchor (silent for N=1, choice for N>=2)
        merged_anchor_map = {}
        for lookup_key, cands in candidates_per_key.items():
            if len(cands) == 1:
                w = cands[0]
                merged_anchor_map[lookup_key] = {
                    'display':    w['display'],
                    'src_row':    w['src_row'],
                    'sheet_name': w['sheet_name'],
                    'section_title': w['section_title'],
                }
                continue
            chosen = raw_choices.get(lookup_key)
            if chosen == 'skip':
                # Surface every dropped candidate in the skipped panel
                for c in cands:
                    st = next(
                        s for s in per_section_states
                        if s['sheet_name'] == c['sheet_name']
                        and (s.get('source_section_title') or s['sheet_name'])
                            == c['section_title']
                    )
                    anchor_col_set_local = (
                        set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                        else ({st['anchor_column']} if st['anchor_column'] else set())
                    )
                    row_data = {}
                    for src_col, tgt_col in (st['column_mappings'] or {}).items():
                        if not tgt_col or tgt_col in anchor_col_set_local:
                            continue
                        row_data[tgt_col] = _format_cell_value(
                            c['src_row'].get(src_col)
                        )
                    all_skipped_no_match.append({
                        'sheet_name':           c['sheet_name'],
                        'source_section_title': c['section_title'],
                        'target_section_title': tgt_title,
                        'anchor_value':         str(c['display']),
                        'row_data':             row_data,
                        'reason':               'user_skipped_conflict',
                    })
                continue
            winner = _ct_pick_winner_from_candidates(cands, chosen)
            if winner is None:
                continue
            # Diagnostic: verify which candidate actually won. If the user
            # picked April but March wins, this print will show it directly
            # in CloudWatch — no need to instrument the FE.
            cand_summary = ", ".join(
                f"({c['sheet_name']!r}>{c['section_title']!r}#{c['row_idx']}"
                f" trucks={c['src_row'].get('Trucks')!r})"
                for c in cands
            )
            print(
                f"   pick anchor={lookup_key!r} chosen={chosen!r} "
                f"winner=({winner['sheet_name']!r}>"
                f"{winner['section_title']!r}#{winner['row_idx']}) "
                f"cands=[{cand_summary}]"
            )
            merged_anchor_map[lookup_key] = {
                'display':       winner['display'],
                'src_row':       winner['src_row'],
                'sheet_name':    winner['sheet_name'],
                'section_title': winner['section_title'],
            }

        # Diff merged map vs target section rows. Mirrors
        # _preview_multi_sheet_aggregate's diff loop verbatim — same anchor-
        # match-by-normalized-key, same per-cell conflict/empty_cell emit.
        header_index      = section_target.get('header_index', {})
        raw_rows          = section_target.get('raw_rows', [])
        section_data_rows = raw_rows[1:] if raw_rows else []

        # Aggregate column mappings across this bucket's sources for the diff
        bucket_mappings = {}
        for st in per_section_states:
            for src, tgt in (st['column_mappings'] or {}).items():
                if tgt and src not in bucket_mappings:
                    bucket_mappings[src] = tgt

        anchor_col_set = (
            set(br['base_anchor']) if isinstance(br['base_anchor'], list)
            else ({br['base_anchor']} if br['base_anchor'] else set())
        )
        formula_col_set = set(section_target.get('formula_cols', []) or [])
        write_mappings = {
            k: v for k, v in bucket_mappings.items()
            if v and v not in anchor_col_set and v not in formula_col_set
        }
        # Add to global agg_column_mappings for the unified payload
        for src, tgt in bucket_mappings.items():
            if tgt and src not in agg_column_mappings:
                agg_column_mappings[src] = tgt
        # Track unique target headers for the unified payload
        for h in section_target.get('headers', []) or []:
            if h not in all_target_headers:
                all_target_headers.append(h)

        rows_in_target_total += len(section_data_rows)
        # For the source row count, sum unique anchors in the merged map.
        rows_in_source_total += len(merged_anchor_map)

        # Walk target rows, find anchor match in merged_anchor_map
        target_anchor_col = next(
            (h for h in section_target.get('headers', []) if h in anchor_col_set),
            None,
        )
        if target_anchor_col is None:
            # Fallback: take first column. This is a defensive degraded path.
            target_anchor_col = (section_target.get('headers') or [None])[0]
        anchor_col_idx = header_index.get(target_anchor_col)

        # DIAG: dump diff loop preconditions so we can see why some target
        # rows aren't matching merged_anchor_map keys (esp. for the 5-vs-2
        # discrepancy in the cross-tab × section aggregate path).
        try:
            _diag_target_anchors = []
            for _r in (section_data_rows or [])[:30]:
                if anchor_col_idx is not None and anchor_col_idx < len(_r):
                    _v = _r[anchor_col_idx]
                    _n = (_normalize_date_value(_v) if is_date_anchor
                          else (str(_v).strip() if _v is not None else ''))
                    _diag_target_anchors.append({'raw': str(_v)[:30], 'normed': _n})
            print(
                f"   diag bucket {tgt_title!r}: anchor_col={target_anchor_col!r} "
                f"idx={anchor_col_idx} headers={section_target.get('headers')} "
                f"section_data_rows={len(section_data_rows)} "
                f"is_date_anchor={is_date_anchor} "
                f"merged_keys={list(merged_anchor_map.keys())} "
                f"target_first_30={_diag_target_anchors}"
            )
        except Exception as _e:
            print(f"   diag dump failed: {_e!r}")

        matched_keys = set()
        # Per-bucket counters drive the per-bucket summary block at the
        # bottom of this loop. Initialize fresh for each bucket so the
        # FE sees an accurate breakdown of cells_changed vs cells_already_matched
        # vs rows_already_matching for THIS target section.
        bucket_no_op_cells       = 0
        bucket_diff_cells        = 0
        bucket_rows_with_changes = 0
        bucket_rows_all_match    = 0
        for r_offset, row in enumerate(section_data_rows):
            if anchor_col_idx is None or anchor_col_idx >= len(row):
                continue
            tgt_anchor_val = row[anchor_col_idx]
            if tgt_anchor_val is None or str(tgt_anchor_val).strip() == '':
                continue
            normed = (
                _normalize_date_value(tgt_anchor_val) if is_date_anchor
                else str(tgt_anchor_val).strip()
            )
            lookup = normed if is_date_anchor else normed.lower()
            entry = merged_anchor_map.get(lookup)
            if not entry:
                continue
            matched_keys.add(lookup)
            src_row = entry['src_row']
            # Per-row tracking: count how many cells in THIS row had a real
            # diff vs how many were no-ops, so a row whose every mapped cell
            # equals target counts toward `bucket_rows_all_match` (visible to
            # the user as "X source rows already up-to-date") rather than
            # disappearing silently. The previous behavior buried these as
            # invisible no-ops, leading to the user-reported "where did my
            # other source rows go?" confusion.
            row_no_op_cells = 0
            row_diff_cells  = 0
            for src_col, tgt_col in write_mappings.items():
                tgt_col_idx = header_index.get(tgt_col)
                if tgt_col_idx is None or tgt_col_idx >= len(row):
                    continue
                old_value = row[tgt_col_idx]
                new_value = src_row.get(src_col)
                old_str = '' if old_value is None else str(old_value).strip()
                new_str = '' if new_value is None else str(new_value).strip()
                if not new_str:
                    continue
                # KEY NAME PARITY: FE reads `c.existing_value` for the
                # current-cell display (DynamicMapping.jsx line 2308) — NOT
                # `c.old_value`. Emitting the wrong key makes every Current
                # column render as "(empty)" via FE's formatValue(undefined)
                # → fallback. Match the legacy multi-sheet aggregate shape
                # (line 5709) verbatim: anchor_value / column / existing_value
                # / new_value / source_sheet. We add `target_section_title`
                # and `source_section` for the cross-tab × section context
                # but those are extras, not replacements for the canonical
                # keys.
                cell = {
                    'column':         tgt_col,
                    'existing_value': _format_cell_value(old_value),
                    'new_value':      _format_cell_value(new_value),
                    'source_sheet':   entry['sheet_name'],
                    'source_section': entry['section_title'],
                }
                # Three-way bucketing — REAL diff vs FILL-empty-cell vs
                # NO-OP (source value matches target value byte-for-byte).
                # All three classes are surfaced to the FE diff table so
                # the user can review and uncheck any of them. The cap
                # MAX_DIFF_CELLS is shared across all three classes (a
                # no-op row in the table costs the same render budget as
                # an overwrite row); we increment the table_rows counter
                # FIRST and gate ALL three appends on the same threshold
                # so we don't silently truncate one class while another
                # gets through.
                table_rows_so_far = (
                    len(all_conflicts) + len(all_empty_cells) + len(all_no_op_cells)
                )
                if table_rows_so_far >= MAX_DIFF_CELLS:
                    diff_truncated = True
                    # Counters still increment so totals-strip / per-bucket
                    # summary stay accurate even when truncated; just don't
                    # populate the array.
                    if old_str == new_str:
                        no_op_cells_total += 1
                        bucket_no_op_cells += 1
                        row_no_op_cells    += 1
                    else:
                        diff_total_cells += 1
                        bucket_diff_cells  += 1
                        row_diff_cells     += 1
                    continue
                if old_str == new_str:
                    no_op_cells_total += 1
                    bucket_no_op_cells += 1
                    row_no_op_cells    += 1
                    all_no_op_cells.append({
                        'anchor_value':         str(entry['display']),
                        'target_section_title': tgt_title,
                        **cell,
                    })
                    continue
                diff_total_cells += 1
                bucket_diff_cells  += 1
                row_diff_cells     += 1
                if old_str:
                    all_conflicts.append({
                        'anchor_value':         str(entry['display']),
                        'target_section_title': tgt_title,
                        **cell,
                    })
                else:
                    all_empty_cells.append({
                        'anchor_value':         str(entry['display']),
                        'target_section_title': tgt_title,
                        **cell,
                    })
            # Only track the row in `all_rows_to_update` if it actually had
            # at least one cell to write (real diff OR no-op — both go to
            # the writer). Tally row-level "all matched" so the FE can show
            # "Y source rows already up-to-date" alongside the cell count.
            if row_diff_cells > 0 or row_no_op_cells > 0:
                all_rows_to_update.append({
                    'anchor_value':         str(entry['display']),
                    'target_section_title': tgt_title,
                    'source_sheet':         entry['sheet_name'],
                    'source_section':       entry['section_title'],
                })
                if row_diff_cells > 0:
                    bucket_rows_with_changes += 1
                else:
                    bucket_rows_all_match += 1
                    rows_already_matching += 1

        # Orphans: anchors in merged map that didn't match any target row
        for lookup_key, entry in merged_anchor_map.items():
            if lookup_key in matched_keys:
                continue
            st = next(
                s for s in per_section_states
                if s['sheet_name'] == entry['sheet_name']
                and (s.get('source_section_title') or s['sheet_name'])
                    == entry['section_title']
            )
            anchor_col_set_local = (
                set(st['anchor_column']) if isinstance(st['anchor_column'], list)
                else ({st['anchor_column']} if st['anchor_column'] else set())
            )
            row_data = {}
            for src_col, tgt_col in (st['column_mappings'] or {}).items():
                if not tgt_col or tgt_col in anchor_col_set_local:
                    continue
                row_data[tgt_col] = _format_cell_value(
                    entry['src_row'].get(src_col)
                )
            all_skipped_no_match.append({
                'sheet_name':           entry['sheet_name'],
                'source_section_title': entry['section_title'],
                'target_section_title': tgt_title,
                'anchor_value':         str(entry['display']),
                'row_data':             row_data,
                'reason':               'no_target_match',
            })

        # Per-bucket summary so the FE can render a "By target section"
        # breakdown showing the user that EACH bucket was processed, even
        # if some had only no-op writes. Without this, a bucket whose
        # source rows all matched target byte-for-byte would be invisible
        # in the preview totals (which only count cells_to_overwrite +
        # cells_to_fill across ALL buckets) and the user concludes the
        # bucket was dropped entirely.
        per_bucket_summary.append({
            'target_section_index':    br['target_section_index'],
            'target_section_title':    tgt_title,
            'sources': [
                {
                    'sheet_name':           s['sheet_name'],
                    'source_section_title': s['source_section_title'],
                }
                for s in br['sources']
            ],
            'cells_to_overwrite':      bucket_diff_cells,
            'cells_already_matched':   bucket_no_op_cells,
            'rows_with_changes':       bucket_rows_with_changes,
            'rows_already_matching':   bucket_rows_all_match,
            'rows_skipped_no_match':   sum(
                1 for s in all_skipped_no_match
                if s.get('target_section_title') == tgt_title
            ),
        })

    # Build the strategy_metadata that confirm path needs to replay.
    # route_groups is JSON-serializable (the section dicts are plain dicts).
    final_strategy_metadata = {
        'cross_tab_section_aggregate': True,
        'route_groups':                route_groups,
        'conflict_resolutions':        raw_choices,
    }
    sources_for_label = []
    for g in route_groups:
        for s in g['sources']:
            tag = f"{s['sheet_name']} > {s['source_section_title']}"
            if tag not in sources_for_label:
                sources_for_label.append(tag)
    return {
        'success':          True,
        'preview':          True,
        'aggregate_mode':   True,
        'aggregated_sheets': sources_for_label,
        'write_strategy':   'cross_tab_section_aggregate',
        'underlying_strategy': bucket_results[0]['base_strategy'] if bucket_results else None,
        'anchor_column':    bucket_results[0]['base_anchor'] if bucket_results else None,
        'source_anchor':    (
            bucket_results[0]['per_section_states'][0]['identification'].get('source_anchor')
            if bucket_results and bucket_results[0]['per_section_states']
            else None
        ),
        'anchor_type':      (
            bucket_results[0]['per_section_states'][0]['identification'].get('anchor_type', '')
            if bucket_results and bucket_results[0]['per_section_states']
            else ''
        ),
        'reasoning': (
            f"Cross-tab × per-section aggregate: "
            + "; ".join(
                f"{br['target_section_title']!r} <- "
                + ", ".join(
                    f"{s['sheet_name']}.{s['source_section_title']}"
                    for s in br['sources']
                )
                for br in bucket_results
            )
            + ". Update-only — orphan rows are listed but not written."
        ),
        'source_columns':   list({h for st in (
            sst for br in bucket_results for sst in br['per_section_states']
        ) for h in (st.get('source_schema', {}).get('headers') or [])}),
        'target_headers':   all_target_headers,
        'column_mappings':  agg_column_mappings,
        'unmapped_source':  [],
        'rows_in_source':   rows_in_source_total,
        'rows_in_target':   rows_in_target_total,
        'source_col_types': {},
        'target_col_types': {},
        'formula_cols':     list(formula_cols or []),
        'conflicts':        all_conflicts,
        'empty_cells':      all_empty_cells,
        # No-op cells are now FIRST-CLASS rows in the diff table (FE renders
        # them as type='no_op' with an UNCHANGED badge + checkbox). The user
        # explicitly requested visibility into every cell the writer would
        # touch, including those whose target value already matches source.
        # Hiding them was an unsolicited UX decision; surface them and let
        # the user uncheck the ones they don't want.
        'no_op_cells':      all_no_op_cells,
        'appended_rows_preview': [],
        'diff_truncated':   diff_truncated,
        'diff_total_cells': diff_total_cells,
        'rows_to_update':   all_rows_to_update,
        'rows_to_append':   [],
        'rows_to_update_count': len(all_rows_to_update),
        'rows_to_append_count': 0,
        # No-op aggregate counters — kept for the optional "By target section"
        # breakdown panel and as a quick "X cells will be written without any
        # value change" advisory. The cells themselves are now in `no_op_cells`
        # above so the user can review and uncheck individual ones.
        'cells_already_matched':  no_op_cells_total,
        'rows_already_matching':  rows_already_matching,
        'per_bucket_summary':     per_bucket_summary,
        'skipped_no_match': all_skipped_no_match,
        'is_empty_target':  False,
        'header_row_count': 1,
        'composite_to_col_index': {},
        'sheet_name':       None,
        'auto_selected_sheet': None,
        'strategy_metadata': final_strategy_metadata,
        'pivot_source_col': None,
        'value_source_col': None,
    }


def _run_cross_tab_section_aggregate(
    inputs, route_groups, conflict_resolutions, sheet_id, target_sheet_name,
    credentials,
):
    """Confirm path for cross_tab_section_aggregate. Mirrors the preview's
    per-bucket loop but writes via update_rows_by_date / update_rows_by_anchor
    against each bucket's target section row range (Fix L pinning).

    Buckets are written sequentially. A failure in one bucket aborts the
    whole call — partial writes would leave the target tab in an
    inconsistent state vs the preview the user just confirmed.
    """
    file_content = inputs['file_content']
    file_type    = inputs.get('file_type', 'xlsx')

    print(
        f"Cross-tab × section aggregate write: {len(route_groups)} target "
        f"section bucket(s) on tab {target_sheet_name!r}"
    )

    # Re-read target so the bucket section_targets are fresh.
    safe_name = (
        f"'{target_sheet_name}'"
        if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
        else target_sheet_name
    )
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials,
    })
    if not sheet_read.get('success'):
        return {
            'success': False,
            'error': f"Cannot read target for cross-tab × section write: {sheet_read.get('error')}",
            'error_type': 'cross_tab_section_target_read_failed',
        }
    raw_values = sheet_read.get('data', sheet_read.get('values', []))
    formula_cols = detect_formula_columns(sheet_id, safe_name, credentials)
    target_schema = invoke(MAPPING_LAMBDA, {
        'tool': 'structure_target_data',
        'inputs': {'raw_values': raw_values, 'sheet_name': target_sheet_name}
    })
    if not target_schema.get('success'):
        return {
            'success': False,
            'error': f"Cannot structure target: {target_schema.get('error')}",
            'error_type': 'cross_tab_section_target_structure_failed',
        }
    existing_formula_cols = set(target_schema.get('formula_cols', []) or [])
    existing_formula_cols.update(formula_cols)
    target_schema['formula_cols'] = list(existing_formula_cols)
    sections_local = _detect_sections_local(raw_values or [])

    # Normalize choices once
    raw_choices = conflict_resolutions or {}
    if isinstance(raw_choices, str):
        try:
            raw_choices = json.loads(raw_choices)
        except Exception:
            raw_choices = {}
    if not isinstance(raw_choices, dict):
        raw_choices = {}

    # Parse write_only filter (per-cell checkboxes from the preview UI).
    # Each entry is {kind, anchor, column, target_section_title}; we build
    # a (target_section_title, anchor_str, column) allow-set so two cells
    # that share (anchor, column) but live in different target sections
    # (e.g. both Inbound and Outbound have a "2025-03-01" / "Trucks") can
    # be deselected independently. Falls back to (None, anchor, column)
    # when target_section_title is omitted (legacy clients) — that path
    # behaves identically to the old anchor+column matching for any
    # bucket whose tgt_title is also None. allowed_cells_set==None means
    # "no filter sent — write everything".
    write_only_raw = inputs.get('write_only')
    if isinstance(write_only_raw, str) and write_only_raw.strip():
        try:
            write_only_raw = json.loads(write_only_raw)
        except Exception as _err:
            print(f"   write_only payload was not valid JSON ({_err}); ignoring filter")
            write_only_raw = None
    write_only = write_only_raw if isinstance(write_only_raw, dict) else None
    # The filter has TWO modes that depend on what shape the FE sent:
    #   1. SECTION-AWARE (modern FE): every allowed_diff_cell carries a
    #      target_section_title, so we can distinguish two cells that
    #      share (anchor, column) but live in different target sections.
    #      Allow-set keys on (target_section_title, anchor, column).
    #   2. ANCHOR-ONLY (legacy FE): no entries carry target_section_title.
    #      Allow-set keys on (anchor, column) — same shape as the legacy
    #      multi-sheet aggregate filter.
    # Mixing the two would cause a section-aware filter to silently fall
    # through to anchor-only matching for the cells that DO have tst,
    # defeating the whole purpose of section-aware deselection.
    allowed_cells_set = None
    section_aware_filter = False
    if write_only:
        diff_cells = write_only.get('allowed_diff_cells') or []
        # Detect filter mode: section-aware iff ANY entry has tst. (We
        # require all-or-nothing — partial-tst payloads would be ambiguous,
        # so we treat them as section-aware which fails closed: cells
        # without tst would only match if their bucket's tst is also
        # None / missing.)
        section_aware_filter = any(
            isinstance(c, dict) and c.get('target_section_title') is not None
            for c in diff_cells
        )
        allowed_cells_set = set()
        for c in diff_cells:
            if not isinstance(c, dict):
                continue
            a = c.get('anchor')
            col = c.get('column')
            if a is None or col is None:
                continue
            if section_aware_filter:
                tst = c.get('target_section_title')
                allowed_cells_set.add((
                    None if tst is None else str(tst),
                    str(a), str(col),
                ))
            else:
                allowed_cells_set.add((str(a), str(col)))
        if not allowed_cells_set:
            allowed_cells_set = None
        mode = "section-aware" if section_aware_filter else "anchor-only"
        print(
            f"   write_only filter active ({mode}): "
            f"{len(allowed_cells_set or set())} cell(s) allowed across all buckets"
        )

    grand_updated   = 0
    grand_appended  = 0
    grand_cells     = 0
    grand_cells_skipped = 0   # cells dropped by writeOnly filter (FE checkbox)
    grand_rows_skipped  = 0   # rows where every cell was unchecked
    per_bucket      = []

    # Pre-validate target indices + build per-bucket section_target
    # schemas (no LLM, purely local) so we fail fast on bad indices BEFORE
    # spinning up the parallel parse pool.
    bucket_section_targets = []
    for group_idx, group in enumerate(route_groups):
        tgt_idx = group['target_section_index']
        if not (0 <= tgt_idx < len(sections_local)):
            return {
                'success': False,
                'error': (
                    f"Cross-tab × section write: target_section_index={tgt_idx} "
                    f"out of range against current target."
                ),
                'error_type': 'cross_tab_section_invalid_target',
            }
        bucket_section_targets.append(_build_section_target_schema(
            sections_local[tgt_idx], raw_values, target_sheet_name,
            target_schema.get('formula_cols', []) or [],
        ))

    # Parallel per-source parse — same shape as the preview path. The
    # write Lambda can also blow past API Gateway's 29 s timeout if the
    # user confirms a 3-bucket × 2-source plan; without parallelization
    # they'd see "Confirm" silently fail with a 504 even though the
    # write succeeded server-side. Tasks key on (group_idx, src_idx) and
    # we replay them into per_section_states in original order so the
    # candidate-merge step sees a deterministic ordering identical to
    # the preview's (preserves choice_id round-trip semantics).
    parse_tasks = []
    for group_idx, group in enumerate(route_groups):
        section_target = bucket_section_targets[group_idx]
        for src_idx, src in enumerate(group['sources']):
            src_section = dict(src['section'])
            src_section['__source_section_index'] = src.get('source_section_index')
            parse_tasks.append((group_idx, src_idx, src, src_section, section_target))

    parse_t0 = time.time()
    parse_results_by_key = {}
    max_workers = max(1, min(6, len(parse_tasks)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _aggregate_parse_one_section,
                file_content, file_type, src['sheet_name'],
                src_section, section_target,
            ): (group_idx, src_idx, src, src_section, section_target)
            for (group_idx, src_idx, src, src_section, section_target) in parse_tasks
        }
        for fut in as_completed(futures):
            (group_idx, src_idx, src, _, _) = futures[fut]
            try:
                state, err = fut.result()
            except Exception as exc:
                return {
                    'success': False,
                    'error': (
                        f"Bucket #{group_idx} "
                        f"(src {src['sheet_name']!r}): "
                        f"unexpected parse error: {exc}"
                    ),
                    'error_type': 'cross_tab_section_parse_exception',
                }
            if err:
                tgt_title = route_groups[group_idx].get('target_section_title')
                return {
                    'success': False,
                    'error': f"Bucket #{group_idx} ({tgt_title!r}): {err}",
                    'error_type': 'cross_tab_section_parse_failed',
                }
            # Same fix as preview path: preserve the actual sheet name
            # (the helper overwrites it with the section title for the
            # intra-tab flow). Without this, both March's and April's
            # candidates would have sheet_name=section_title which the
            # choice_id round-trip cannot disambiguate.
            state['sheet_name'] = src['sheet_name']
            state['source_section_title'] = (
                src.get('source_section_title')
                or state.get('source_section_title')
            )
            parse_results_by_key[(group_idx, src_idx)] = state
    print(
        f"   cross-tab-section write: parallel parse of {len(parse_tasks)} "
        f"section(s) finished in {time.time() - parse_t0:.1f}s "
        f"(max_workers={max_workers})"
    )

    for group_idx, group in enumerate(route_groups):
        tgt_idx        = group['target_section_index']
        tgt_title      = group.get('target_section_title')
        sources        = group['sources']
        section_target = bucket_section_targets[group_idx]

        per_section_states = [
            parse_results_by_key[(group_idx, si)] for si in range(len(sources))
        ]
        canon = per_section_states[0]
        is_date_anchor = canon['is_date_anchor']
        base_anchor    = canon['anchor_column']
        base_strategy  = canon['write_strategy']

        candidates_per_key = _ct_build_candidates_per_anchor(
            per_section_states, is_date_anchor,
        )

        # Apply choices to pick winners
        winners_by_key = {}
        for lookup_key, cands in candidates_per_key.items():
            if len(cands) == 1:
                winners_by_key[lookup_key] = cands[0]
                continue
            chosen = raw_choices.get(lookup_key)
            if chosen == 'skip':
                continue
            w = _ct_pick_winner_from_candidates(cands, chosen)
            if w is not None:
                winners_by_key[lookup_key] = w
                print(
                    f"   write pick anchor={lookup_key!r} chosen={chosen!r} "
                    f"winner=({w['sheet_name']!r}>{w['section_title']!r}#{w['row_idx']})"
                )

        # Build transformed rows for the bucket — only the winner src_row
        # contributes. _aggregate_build_anchor_map's pattern is mirrored
        # but we already have winners in hand.
        bucket_mappings = {}
        for st in per_section_states:
            for src, tgt in (st['column_mappings'] or {}).items():
                if tgt and src not in bucket_mappings:
                    bucket_mappings[src] = tgt
        anchor_col_set_local = (
            set(base_anchor) if isinstance(base_anchor, list)
            else ({base_anchor} if base_anchor else set())
        )
        write_mappings = {
            k: v for k, v in bucket_mappings.items()
            if v and v not in anchor_col_set_local
        }
        # Resolve target anchor column for both writer-shape branches below.
        anchor_target_col = next(
            (h for h in section_target.get('headers', []) if h in anchor_col_set_local),
            None,
        )
        # Build the writer-input rows. update_rows_by_date and
        # update_rows_by_anchor expect DIFFERENT row shapes:
        #   - update_rows_by_date wants
        #     {date_formatted: '...', date: '...', row_data: {col: val, ...}}
        #     with the anchor (date) at the TOP level and the column-value
        #     payload NESTED under `row_data`. Mirrors the legacy
        #     multi-sheet aggregate write path (lines 6157-6161 historical).
        #   - update_rows_by_anchor wants a FLAT dict where anchor columns
        #     and data columns coexist as siblings — the function iterates
        #     row_data.items() directly and skips entries whose key is in
        #     anchor_col_set.
        # Passing the wrong shape silently produces 0 cell updates and
        # surfaces as "No matching dates found in sheet" — exactly the user-
        # visible failure we just hit. Branch by base_strategy here so each
        # writer gets a payload it actually understands.
        data_rows_for_writer = []
        bucket_cells_skipped_unselected = 0
        bucket_rows_skipped_all_unselected = 0
        for lookup_key, w in winners_by_key.items():
            src_row = w['src_row']
            display_str = str(w['display'])
            payload_cols = {}
            for src_col, tgt_col in write_mappings.items():
                v = src_row.get(src_col)
                if v is None or str(v).strip() == '':
                    continue
                # Cell-level writeOnly filter. In section-aware mode the
                # key includes target_section_title so two buckets sharing
                # (anchor, column) (e.g. both Inbound and Outbound have
                # "2025-03-01" / "Trucks") can be deselected independently.
                # In anchor-only mode (legacy FE payload) we fall back to
                # the historical (anchor, column) match.
                if allowed_cells_set is not None:
                    if section_aware_filter:
                        tst_str = None if tgt_title is None else str(tgt_title)
                        key = (tst_str, display_str, str(tgt_col))
                    else:
                        key = (display_str, str(tgt_col))
                    if key not in allowed_cells_set:
                        bucket_cells_skipped_unselected += 1
                        continue
                payload_cols[tgt_col] = v
            if not payload_cols:
                # Every cell of this row was unchecked → drop the whole
                # row to avoid a wasted writer call with empty row_data.
                bucket_rows_skipped_all_unselected += 1
                continue
            if base_strategy == 'row_per_date':
                data_rows_for_writer.append({
                    'date':           display_str,
                    'date_formatted': display_str,
                    'row_data':       payload_cols,
                })
            else:
                row_data = dict(payload_cols)
                if anchor_target_col:
                    row_data[anchor_target_col] = w['display']
                data_rows_for_writer.append(row_data)
        if allowed_cells_set is not None and (
            bucket_cells_skipped_unselected or bucket_rows_skipped_all_unselected
        ):
            print(
                f"   Bucket #{group_idx} ({tgt_title!r}): writeOnly filter "
                f"dropped {bucket_cells_skipped_unselected} cell(s) and "
                f"{bucket_rows_skipped_all_unselected} fully-unchecked row(s)"
            )
        grand_cells_skipped += bucket_cells_skipped_unselected
        grand_rows_skipped  += bucket_rows_skipped_all_unselected

        if not data_rows_for_writer:
            print(f"   Bucket #{group_idx} ({tgt_title!r}): no rows after dedupe; skipping.")
            per_bucket.append({
                'target_section_index': tgt_idx,
                'target_section_title': tgt_title,
                'rows_updated':         0,
                'rows_appended':        0,
                'cells_updated':        0,
            })
            continue

        # Resolve target section row-range pin (Fix L) so the sheets-agent
        # writer only touches rows inside this bucket's target section,
        # not the whole tab. Uses sections_local[tgt_idx] (detected at
        # line 7131 from the freshly-read raw_values) — this is the
        # CORRECT source dict, NOT some leftover `section` name from a
        # different scope. data_start is 0-indexed against raw_values
        # (data row 0 = row "data_start"); the sheets-agent writer
        # expects 1-indexed sheet rows where row 1 IS the first row
        # in the spreadsheet, so we add +1 for that 1-indexing AND
        # implicitly account for the header row already being above
        # data_start (data_start already points AT the first data row).
        target_section_dict = sections_local[tgt_idx]
        ds = target_section_dict.get('data_start')
        de = target_section_dict.get('data_end')
        section_data_start_row = ds + 1 if isinstance(ds, int) else None
        section_data_end_row   = de       if isinstance(de, int) and de > (ds or 0) else None
        # Also pass the section's header_row (0-indexed against the WHOLE
        # tab's raw_values) so the sheets-agent reads the correct header
        # row when looking up the anchor column. Without this, the writer
        # defaults to header_row=0 — which for OPS_DASHBOARD reads
        # ['Inbound Metrics'] (the title row of the FIRST section) instead
        # of the actual ['Date','Trucks','Pallets'] / ['Date','Dispatched',
        # 'Cases'] headers, and bails with "Date column 'Date' not found
        # in headers". For the second section (Outbound), header_row points
        # to row 13 in the user's OPS_DASHBOARD (its actual header row).
        section_header_row = target_section_dict.get('header_row')

        # Pick the right writer based on strategy. Cross-tab × section
        # aggregate is update-only by design (no append); orphans were
        # already surfaced in skipped_no_match during preview.
        target_anchor_col = next(
            (h for h in section_target.get('headers', []) if h in anchor_col_set_local),
            None,
        )
        # Build the writer args. update_rows_by_date and update_rows_by_anchor
        # take DIFFERENT param names for the same logical concept — the date
        # tool wants `date_column_name` + `rows_with_dates` (legacy from when
        # only date anchors were supported), the anchor tool wants
        # `anchor_column` + `rows`. Passing `anchor_column` to the date tool
        # would crash with `TypeError: update_rows_by_date() got an unexpected
        # keyword argument 'anchor_column'`. Branch on strategy so each tool
        # gets the kwargs it actually expects.
        if base_strategy == 'row_per_date':
            tool_name = 'update_rows_by_date'
            write_inputs = {
                'sheet_id':         sheet_id,
                'sheet_name':       target_sheet_name,
                'date_column_name': target_anchor_col,
                'rows_with_dates':  data_rows_for_writer,
            }
        else:
            tool_name = 'update_rows_by_anchor'
            write_inputs = {
                'sheet_id':      sheet_id,
                'sheet_name':    target_sheet_name,
                'anchor_column': target_anchor_col,
                'rows':          data_rows_for_writer,
            }
        if isinstance(section_header_row, int):
            write_inputs['header_row'] = section_header_row
        if section_data_start_row is not None:
            write_inputs['data_start_row'] = section_data_start_row
        if section_data_end_row is not None:
            write_inputs['data_end_row'] = section_data_end_row

        write_result = invoke(SHEETS_LAMBDA, {
            'tool': tool_name,
            'inputs': write_inputs,
            'credentials_dict': credentials,
        })
        if not write_result.get('success'):
            return {
                'success': False,
                'error': (
                    f"Bucket #{group_idx} ({tgt_title!r}) write failed: "
                    f"{write_result.get('error')}"
                ),
                'error_type': 'cross_tab_section_write_failed',
                'write_result': write_result,
            }
        rows_updated  = write_result.get('rows_updated', 0) or 0
        rows_appended = write_result.get('rows_appended', 0) or 0
        cells_updated = write_result.get('cells_updated', 0) or 0
        grand_updated  += rows_updated
        grand_appended += rows_appended
        grand_cells    += cells_updated
        per_bucket.append({
            'target_section_index': tgt_idx,
            'target_section_title': tgt_title,
            'rows_updated':         rows_updated,
            'rows_appended':        rows_appended,
            'cells_updated':        cells_updated,
            'tool':                 tool_name,
        })
        print(
            f"   Bucket #{group_idx} ({tgt_title!r}): "
            f"{rows_updated} updated, {rows_appended} appended, "
            f"{cells_updated} cells via {tool_name}"
        )

    # Surface writeOnly skip counters in the response so the FE post-write
    # toast can reflect what was filtered out by the user's checkbox state
    # (e.g. "Wrote 6 cells, 8 cells skipped per your selection").
    write_result_payload = {
        'rows_updated':  grand_updated,
        'rows_appended': grand_appended,
        'cells_updated': grand_cells,
        'per_bucket':    per_bucket,
    }
    if allowed_cells_set is not None:
        write_result_payload['cells_skipped_unselected'] = grand_cells_skipped
        write_result_payload['rows_skipped_unselected']  = grand_rows_skipped
    return {
        'success':       True,
        'rows_processed': sum(b['rows_updated'] for b in per_bucket),
        'write_strategy': 'cross_tab_section_aggregate',
        'write_result': write_result_payload,
    }


def _run_multi_sheet_auto_route(inputs, routes, sheet_id, target_sheet_name, credentials):
    """Confirm path for multi_sheet_section strategy.

    Iterates the route plan the preview produced and writes each source sheet
    into its matched target section. Per-route prep runs independently
    (parse → transform → write) so one route's transform failure can surface
    without corrupting another route's write.

    Write itself delegates to ``_write_multi_section`` which already chooses
    the best-matching section for the transformed columns — since each route
    only carries headers matching ONE section, the auto-pick inside converges
    on the intended section for every route.
    """
    file_content = inputs['file_content']
    file_type    = inputs.get('file_type', 'xlsx')
    safe_name    = (
        f"'{target_sheet_name}'"
        if ' ' in target_sheet_name and not target_sheet_name.startswith("'")
        else target_sheet_name
    )

    total_updated  = 0
    total_appended = 0
    total_cells    = 0
    aggregated_errors = []
    per_route_results = []

    for route in routes:
        sheet_name    = route.get('sheet_name')
        # Source-section slice (intra-tab path). None for cross-tab path,
        # which behaves identically to before. When present, we parse the
        # source TAB but slice out only this section's rows so the
        # transform sees the exact same rows the preview saw.
        source_section       = route.get('source_section')
        source_section_title = route.get('source_section_title') or (
            source_section.get('title') if isinstance(source_section, dict) else None
        )
        section_title = route.get('section_title')
        section_idx   = route.get('section_index')
        route_strategy = route.get('write_strategy') or 'append'
        route_anchor   = route.get('anchor_column')
        route_mappings = route.get('column_mappings') or {}
        route_source_anchor = route.get('source_anchor', route_anchor)

        scope_label = (
            f"sheet={sheet_name!r}/section={source_section_title!r}"
            if source_section
            else f"sheet={sheet_name!r}"
        )
        print(f"Auto-route write: {scope_label} → section #{section_idx} {section_title!r} "
              f"(strategy={route_strategy})")

        parse_inputs = {
            'file_content': file_content,
            'file_type':    file_type,
            'sheet_name':   sheet_name,
        }
        if source_section:
            parse_inputs['section'] = source_section
        parse_result = invoke(MAPPING_LAMBDA, {
            'tool': 'parse_file',
            'inputs': parse_inputs,
        })
        if not parse_result.get('success'):
            aggregated_errors.append(
                f"{scope_label}: parse failed — {parse_result.get('error')}"
            )
            continue

        # Re-run structure_source_data on the auto-route confirm path so
        # any grouped-header rewrite of ``full_data`` is applied. Without
        # this the route's cached ``column_mappings`` (composite-keyed,
        # built during the preview run) would point at columns that
        # don't exist in the freshly parsed ``parse_result['full_data']``,
        # producing 0 transformed rows and an empty silent write.
        _route_src = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_source_data',
            'inputs': {'parse_result': parse_result}
        })
        if _route_src.get('success'):
            _corrected_full_data = _route_src.get('full_data')
            if _corrected_full_data is not None:
                parse_result['full_data'] = _corrected_full_data

        anchor_col_set = set(route_anchor) if isinstance(route_anchor, list) else ({route_anchor} if route_anchor else set())
        write_mappings = {k: v for k, v in route_mappings.items()
                          if v and v not in anchor_col_set}

        transform_result = invoke(MAPPING_LAMBDA, {
            'tool': 'transform_data',
            'inputs': {'source_data': parse_result.get('full_data'), 'mappings': write_mappings}
        })
        if not transform_result.get('success'):
            aggregated_errors.append(
                f"{sheet_name!r}: transform failed — {transform_result.get('error')}"
            )
            continue

        transformed = transform_result.get('transformed_data', [])
        if isinstance(transformed, str):
            transformed = json.loads(transformed)

        for row in transformed:
            for k in [k for k, v in row.items() if v is None or (isinstance(v, str) and v.strip() == '')]:
                row.pop(k, None)

        try:
            full_data = parse_result.get('full_data', '[]')
            if isinstance(full_data, str):
                full_data = json.loads(full_data)
            source_anchors = route_source_anchor if isinstance(route_source_anchor, list) else (
                [route_source_anchor] if route_source_anchor else []
            )
            for i, row in enumerate(transformed):
                if i < len(full_data) and source_anchors:
                    parts = []
                    for sa in source_anchors:
                        val = full_data[i].get(sa)
                        if val is not None:
                            normed = _normalize_date_value(val)
                            parts.append(normed or str(val))
                    if parts:
                        row['_anchor_value'] = '|'.join(parts) if len(parts) > 1 else parts[0]
        except Exception as e:
            print(f"   Warning: could not pair anchor values for route {sheet_name!r}: {e}")

        write_result = _write_multi_section(
            anchor_column=route_anchor,
            transformed=transformed,
            sheet_id=sheet_id,
            sheet_name=target_sheet_name,
            safe_name=safe_name,
            credentials=credentials,
            header_row_count=1,
            composite_to_col_index={},
            target_section_index=section_idx,
        )

        per_route_results.append({
            'sheet_name':    sheet_name,
            'section_index': section_idx,
            'section_title': section_title,
            'write_result':  write_result,
        })

        if write_result.get('success'):
            total_updated  += int(write_result.get('rows_updated', 0) or 0)
            total_appended += int(write_result.get('rows_appended', 0) or 0)
            total_cells    += int(write_result.get('cells_updated', 0) or 0)
        else:
            aggregated_errors.append(
                f"{sheet_name!r} → {section_title!r}: "
                f"{write_result.get('error') or 'write failed'}"
            )

    overall_success = (total_updated + total_appended + total_cells) > 0 and not aggregated_errors

    response = {
        'success': overall_success,
        'write_strategy': 'multi_sheet_section',
        'anchor_column':  None,
        'rows_processed': sum(
            int(r.get('write_result', {}).get('rows_updated', 0) or 0)
            + int(r.get('write_result', {}).get('rows_appended', 0) or 0)
            for r in per_route_results
        ),
        'column_mappings': {},
        'write_result': {
            'success':        overall_success,
            'rows_updated':   total_updated,
            'rows_appended':  total_appended,
            'cells_updated':  total_cells,
            'sections_written': len([r for r in per_route_results
                                     if r.get('write_result', {}).get('success')]),
            'routes':         per_route_results,
        },
    }
    if aggregated_errors:
        response['write_result']['errors'] = aggregated_errors
        if not overall_success:
            response['error'] = '; '.join(aggregated_errors)
    return response


def _write_multi_section(anchor_column, transformed, sheet_id, sheet_name,
                         safe_name, credentials, header_row_count=1,
                         composite_to_col_index=None,
                         section_override=None,
                         target_section_index=None):
    """Write data to a multi-section sheet, matching the source to the correct section.

    Uses a **sort-merge** strategy by default:
      - Merges source rows with the target section's existing rows by anchor
        (e.g. Date). Matching anchors become updates; new anchors become
        appends slotted into chronological order.
      - If the section would overflow its current capacity, calls
        ``insert_rows`` to shift subsequent sections down — this is what
        prevents TC-L03 from dumping 05/01 rows at the sheet bottom just
        because the template's sections are tightly stacked.

    Section selection precedence (highest first):
      1. ``section_override`` (a pre-resolved section dict) — used by the
         multi-sheet auto-route so the writer uses the route's pinned
         section instead of re-running :func:`_pick_best_section`.
      2. ``target_section_index`` (an integer index into the target's
         sections) — set by ``find_identifier`` when its multi-section
         pre-resolver picked a non-first section. This is the
         single-sheet path's analog of ``section_override`` and prevents
         the auto-pick tie-breaker from landing on the wrong section
         when the source's columns fit two sections to similar degrees.
      3. ``_pick_best_section`` auto-pick — falls back to scoring the
         transformed columns against every detected section.
    """
    sheet_read = invoke(SHEETS_LAMBDA, {
        'tool': 'read_sheet',
        'inputs': {'sheet_id': sheet_id, 'range_name': safe_name},
        'credentials_dict': credentials
    })
    if not sheet_read.get('success'):
        return sheet_read

    raw_values = sheet_read.get('data', [])

    sections = _detect_sections_local(raw_values)
    if not sections:
        return {'success': False, 'error': 'No sections detected in target sheet'}

    if section_override is not None:
        override_title = (section_override.get('title') or '').strip().lower()
        best_section = None
        for s in sections:
            if (s.get('title') or '').strip().lower() == override_title and \
               s.get('header_row') == section_override.get('header_row'):
                best_section = s
                break
        if best_section is None:
            best_section = section_override
    elif target_section_index is not None:
        try:
            tsi = int(target_section_index)
        except (TypeError, ValueError):
            tsi = None
        if tsi is not None and 0 <= tsi < len(sections):
            best_section = sections[tsi]
            print(f"   Multi-section: pinned to section #{tsi} "
                  f"'{best_section.get('title')}' via target_section_index")
        else:
            # Out-of-range index — fall through to auto-pick rather than
            # failing the write outright. The auto-pick already handles
            # the "source columns match exactly one section" common case.
            print(f"   Multi-section: target_section_index={target_section_index!r} "
                  f"is out of range (sections={len(sections)}); "
                  f"falling back to _pick_best_section auto-pick")
            transformed_cols = set()
            for row in transformed:
                for k in row.keys():
                    if k != '_anchor_value':
                        transformed_cols.add(_norm_header(k))
            best_section, _best_score = _pick_best_section(sections, transformed_cols)
    else:
        transformed_cols = set()
        for row in transformed:
            for k in row.keys():
                if k != '_anchor_value':
                    transformed_cols.add(_norm_header(k))

        best_section, _best_score = _pick_best_section(sections, transformed_cols)

    if not best_section:
        return {'success': False, 'error': 'Could not match source data to any section'}

    print(f"   Multi-section: matched to section '{best_section['title']}' "
          f"(rows {best_section['data_start']+1}-{best_section['data_end']})")

    sec_headers = best_section['headers']
    sec_header_index = best_section['header_index']

    anchor_col = anchor_column
    if not anchor_col:
        for h in sec_headers:
            if h and h.strip():
                anchor_col = h.strip()
                break

    is_date_anchor = bool(anchor_col) and 'date' in anchor_col.lower()
    if not is_date_anchor and anchor_col:
        # Peek at a few existing anchor values — if any normalize as a date
        # we'll treat the column as date-like so sort order is chronological
        # instead of lexicographic on the raw string.
        anchor_idx = sec_header_index.get(anchor_col)
        if anchor_idx is None:
            norm_target = _norm_header(anchor_col)
            for h, idx in sec_header_index.items():
                if _norm_header(h) == norm_target:
                    anchor_idx = idx
                    break
        if anchor_idx is not None:
            sample_rows = raw_values[best_section['data_start']:best_section['data_end']]
            for r in sample_rows[:5]:
                if anchor_idx < len(r) and r[anchor_idx]:
                    if _normalize_date_value(str(r[anchor_idx])):
                        is_date_anchor = True
                        break

    return _sort_merge_section_rows(
        section=best_section,
        sections=sections,
        transformed_rows=transformed,
        raw_values=raw_values,
        anchor_column=anchor_col,
        is_date_anchor=is_date_anchor,
        sheet_id=sheet_id,
        sheet_name=sheet_name,
        safe_name=safe_name,
        credentials=credentials,
    )


def detect_formula_columns(sheet_id, range_name, credentials):
    """Read the first few rows with FORMULA render option to detect formula columns."""
    try:
        formula_read = invoke(SHEETS_LAMBDA, {
            'tool': 'read_sheet',
            'inputs': {
                'sheet_id': sheet_id,
                'range_name': range_name,
                'value_render_option': 'FORMULA'
            },
            'credentials_dict': credentials
        })
        if not formula_read.get('success'):
            print(f"   Warning: formula detection failed: {formula_read.get('error')}")
            return []

        formula_rows = formula_read.get('data', [])
        if len(formula_rows) < 2:
            return []

        headers = [str(h).strip() for h in formula_rows[0]]
        formula_cols = set()
        for row in formula_rows[1:6]:
            for i, cell in enumerate(row):
                if i < len(headers) and isinstance(cell, str) and cell.strip().startswith('='):
                    formula_cols.add(headers[i])

        if formula_cols:
            print(f"   Detected formula columns: {sorted(formula_cols)}")
        return list(formula_cols)
    except Exception as e:
        print(f"   Warning: formula detection error: {e}")
        return []


# Cap on total cells rendered in the preview diff payload
# (conflicts + empty_cells + appended_rows_preview). Keeps response under ~1 MB
# for any reasonably sized sheet; excess cells are counted but not emitted and
# the UI surfaces a "N more not shown" note via diff_truncated / diff_total_cells.
def _recover_cross_tab_metadata(parse_result, cached_mappings, cached_anchor):
    """Re-derive ``pivot_source_col`` and ``value_source_col`` on the confirm
    path when the frontend did not echo them back (stale bundle, dropped
    field, etc.). Uses the flat source rows we already parsed and the
    cached column_mappings (whose values are target headers post-pivot).

    Returns ``(pivot_source_col, value_source_col)`` or ``(None, None)`` if
    no clear pivot column can be found.
    """
    try:
        source_cols = list(parse_result.get('columns') or [])
        if len(source_cols) < 3:
            return (None, None)

        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
        if not full_data:
            return (None, None)

        anchor = cached_anchor if isinstance(cached_anchor, str) else (
            cached_anchor[0] if isinstance(cached_anchor, (list, tuple)) and cached_anchor else None
        )
        target_header_set = {
            str(v).strip().lower()
            for v in (cached_mappings or {}).values()
            if v
        }
        if not target_header_set:
            return (None, None)

        candidates = [c for c in source_cols if c != anchor]
        if len(candidates) < 2:
            return (None, None)

        best = None
        for col in candidates:
            sample_vals = set()
            for row in full_data[:25]:
                v = row.get(col)
                if v is None:
                    continue
                s = str(v).strip().lower()
                if s:
                    sample_vals.add(s)
                if len(sample_vals) >= 12:
                    break
            if not sample_vals:
                continue
            overlap = sample_vals & target_header_set
            if len(overlap) < 2:
                continue
            ratio = len(overlap) / len(sample_vals)
            score = ratio + 0.05 * len(overlap)
            if best is None or score > best[0]:
                best = (score, col)

        if not best:
            return (None, None)

        pivot_src = best[1]
        remaining = [c for c in candidates if c != pivot_src]
        value_src = remaining[0] if remaining else None
        if not value_src:
            return (None, None)
        return (pivot_src, value_src)
    except Exception as e:
        print(f"   cross_tab metadata recovery failed: {e}")
        return (None, None)


def _pivot_source_for_cross_tab(identification, parse_result, source_schema, target_schema):
    """Pre-pivot a flat (row_entity, pivot, value) source into wide form so
    the rest of the pipeline (preview diff, transform_data, _write_cross_tab)
    can treat it like a normal row_per_date / row_per_entity upsert.

    Mutates `parse_result['full_data']`, `source_schema['headers']`,
    `source_schema['total_rows']`, and `identification['column_mappings']`
    in place. Returns True if a pivot was performed, False otherwise.

    Example:
      source rows: [{Date, Category=Electronics, Revenue=5000},
                    {Date, Category=Apparel,     Revenue=3000}]
      →            [{Date, Electronics=5000, Apparel=3000}]
    """
    if identification.get('write_strategy') != 'cross_tab':
        return False

    pivot_src = identification.get('pivot_source_col')
    value_src = identification.get('value_source_col')
    row_src = identification.get('source_anchor')
    row_tgt = identification.get('anchor_column')
    if not (pivot_src and value_src and row_src and row_tgt):
        print("   cross_tab missing pivot/value/anchor — skipping pre-pivot")
        return False

    try:
        full_data = parse_result.get('full_data', '[]')
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
    except Exception as e:
        print(f"   cross_tab pre-pivot: could not load source rows: {e}")
        return False

    if not full_data:
        return False

    # Target column header lookup (case-insensitive): pivot values will map
    # to target headers when their lowercase form matches.
    target_headers = [h for h in (target_schema.get('headers') or []) if h]
    tgt_by_lower = {str(h).strip().lower(): h for h in target_headers}

    # Group source rows by row-anchor value; aggregate pivot→value pairs.
    # Ordered dict preserves source row order for diff readability.
    from collections import OrderedDict
    grouped = OrderedDict()
    used_pivot_targets = []  # ordered list of matched target columns
    seen_targets = set()
    unmatched_pivots = set()

    for row in full_data:
        row_key_val = row.get(row_src)
        if row_key_val is None or str(row_key_val).strip() == '':
            continue
        pivot_val = row.get(pivot_src)
        value_val = row.get(value_src)
        if pivot_val is None or str(pivot_val).strip() == '':
            continue

        group_key = str(row_key_val)
        if group_key not in grouped:
            grouped[group_key] = {row_src: row_key_val}

        pivot_key_lower = str(pivot_val).strip().lower()
        tgt_col = tgt_by_lower.get(pivot_key_lower)
        if not tgt_col:
            # Pivot value doesn't exist as a target column — skip (can't
            # write it anywhere). Track for a single log summary.
            unmatched_pivots.add(str(pivot_val).strip())
            continue

        grouped[group_key][tgt_col] = value_val
        if tgt_col not in seen_targets:
            seen_targets.add(tgt_col)
            used_pivot_targets.append(tgt_col)

    pivoted_rows = list(grouped.values())
    if not pivoted_rows:
        print("   cross_tab pre-pivot produced zero rows — leaving source untouched")
        return False

    if unmatched_pivots:
        print(
            f"   cross_tab pre-pivot: dropped {len(unmatched_pivots)} pivot value(s) "
            f"with no matching target column: {sorted(unmatched_pivots)}"
        )

    new_headers = [row_src] + used_pivot_targets
    new_mappings = {row_src: row_tgt}
    for t in used_pivot_targets:
        new_mappings[t] = t  # identity — pivot value name == target column name

    # Store as a JSON string so transform_data (which uses pd.read_json)
    # can parse it directly on both the cached and non-cached run paths.
    # Preview code that consumes full_data re-parses if needed.
    parse_result['full_data'] = json.dumps(pivoted_rows, default=str)
    source_schema['headers'] = new_headers
    source_schema['total_rows'] = len(pivoted_rows)
    # Rebuild col_samples so downstream heuristics don't see stale data
    col_samples = {}
    for h in new_headers:
        samples = []
        for r in pivoted_rows[:5]:
            v = r.get(h)
            if v is not None and str(v).strip() != '':
                samples.append(v)
        col_samples[h] = samples
    source_schema['col_samples'] = col_samples

    identification['column_mappings'] = new_mappings

    print(
        f"   cross_tab pre-pivoted: {len(full_data)} flat rows → "
        f"{len(pivoted_rows)} wide rows, columns: {new_headers}"
    )
    return True


def _prepare_strategy_state(identification, parse_result, source_schema, target_schema):
    """Apply strategy-specific pre-transform setup. Runs on both the preview
    and the run paths so they stay in lock-step.

    Currently only ``cross_tab`` needs active preparation (flat-to-wide
    pivot). The other structural strategies route through existing
    pipelines:

    * ``multi_section`` — source slicing already happens at Step 0b via
      ``detect_source_sections`` + ``parse_file(section=...)``.
    * ``key_value`` — label column resolution happens inside
      ``find_identifier`` via ``_detect_key_value_layout``.
    * ``horizontal`` / ``row_per_*`` / ``composite_key`` / ``append`` —
      no extra state to apply; they run on the raw parsed rows.

    Returning ``True`` means this helper mutated the inputs so callers
    may need to re-read ``identification['column_mappings']`` etc.
    """
    strategy = identification.get('write_strategy')
    if strategy == 'cross_tab':
        return _pivot_source_for_cross_tab(
            identification, parse_result, source_schema, target_schema
        )
    return False


MAX_DIFF_CELLS = 500


def _preview_anchor_cells(anchor_col_set, source_anchor_names, src_row,
                          fallback_anchor_str, is_date_anchor):
    """Build the synthetic "anchor value" cells that get prepended to each
    ``appended_rows_preview`` row.

    The anchor column(s) are stripped from ``write_mappings`` because they
    are used for row *identity*, not cell updates — but the user still
    needs to SEE the Date (or other anchor) value on every new row in the
    preview, otherwise the date appears to be silently dropped
    (TC-L08 regression).

    When we have a source row AND know which source columns correspond to
    the anchor, we emit one cell per anchor column with the per-column
    value (so a composite anchor like ``[Store, Week]`` still displays as
    two distinct cells). Otherwise we fall back to a single cell using the
    already-computed composite ``fallback_anchor_str``. We never emit a
    cell for rows whose fallback is a positional placeholder
    (``row_1`` / ``row_2``) unless we actually have a source row to pull
    real values from — otherwise the display would be a misleading
    ``Date: row_1``.
    """
    anchor_cols = [c for c in (anchor_col_set or []) if c]
    if not anchor_cols:
        return []

    out = []
    if src_row and source_anchor_names:
        for tgt_anchor, src_anchor in zip(anchor_cols, source_anchor_names):
            if not src_anchor:
                continue
            raw = src_row.get(src_anchor)
            if raw is None:
                continue
            v = _format_cell_value(raw)
            if is_date_anchor:
                normed = _normalize_date_value(raw)
                if normed:
                    v = normed
            out.append({'column': tgt_anchor, 'new_value': v})
        if out:
            return out

    if fallback_anchor_str and not str(fallback_anchor_str).startswith('row_'):
        return [{
            'column':    anchor_cols[0],
            'new_value': str(fallback_anchor_str),
        }]
    return []


def _format_cell_value(val):
    """Convert a raw cell value to a concise display string for preview diffs.

    Handles pandas/JSON-serialized source values (mostly str/int/float) as well
    as target values read from Google Sheets (mostly strings). Dates are
    collapsed to YYYY-MM-DD so the current -> new diff stays readable.
    """
    from datetime import datetime as _dt, date as _date, time as _time

    if val is None:
        return ""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, _dt):
        if val.hour == 0 and val.minute == 0 and val.second == 0 and val.microsecond == 0:
            return val.strftime('%Y-%m-%d')
        return val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(val, _date):
        return val.strftime('%Y-%m-%d')
    if isinstance(val, _time):
        return val.strftime('%H:%M:%S')
    if isinstance(val, float):
        if val != val:  # NaN
            return ""
        if val.is_integer():
            iv = int(val)
            if 1e12 < iv < 1e14:
                try:
                    return datetime.utcfromtimestamp(iv / 1000).strftime('%Y-%m-%d')
                except (ValueError, OSError):
                    pass
            return str(iv)
        return f"{round(val, 6):g}"
    if isinstance(val, int):
        if 1e12 < val < 1e14:
            try:
                return datetime.utcfromtimestamp(val / 1000).strftime('%Y-%m-%d')
            except (ValueError, OSError):
                pass
        return str(val)

    s = str(val).strip()
    if not s:
        return ""
    # Try epoch milliseconds (pandas to_json default for datetime columns)
    try:
        ts = int(float(s))
        if 1e12 < ts < 1e14:
            return datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d')
    except (ValueError, TypeError, OSError):
        pass
    # Collapse ISO datetimes with a midnight time to plain dates
    if s.endswith(' 00:00:00'):
        s = s[:-9]
    return s


def _normalize_date_value(val):
    """Normalize a date value to YYYY-MM-DD for matching between source and target.

    Handles the common wire formats we've seen in production:
      - Plain dates:          "2025-03-01", "03/01/2025"
      - ISO datetimes:        "2025-03-01T00:00:00", "2025-03-01T00:00:00.000Z"
      - **Space-separated datetimes** (what ``str(pd.Timestamp)`` produces
        and what Google Sheets returns for DATE-TIME-formatted cells):
        "2025-03-01 00:00:00", "2025-03-01 0:00:0". Missing this was the
        cause of the TC-L06 duplicate-row bug — source anchors arrived as
        space-separated datetimes and never matched the target's plain
        "2025-03-01" cells, so sort-merge treated them as different keys.
      - Epoch ms (pandas to_json default for datetime columns)
    Falls through to a final "take the first 10 chars if they look like
    YYYY-MM-DD" heuristic so unknown trailing noise doesn't break matching.
    """
    s = str(val).strip()
    if not s:
        return None

    try:
        ts = int(float(s))
        if 1e12 < ts < 1e14:
            return datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d')
    except (ValueError, TypeError, OSError):
        pass

    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f',
                '%Y-%m-%d %H:%M',
                '%d-%b-%y', '%d-%b-%Y', '%m/%d/%Y', '%d/%m/%Y',
                '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y',
                '%b %d, %Y', '%B %d, %Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    # Google Sheets sometimes returns "0:00:0" (single-digit components,
    # no zero-padding) which strptime rejects — try a loose split fallback.
    if ' ' in s:
        date_part = s.split(' ', 1)[0]
        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(date_part, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue

    return s


def _col_index_to_letter(col_index):
    """Convert 0-based column index to Excel column letter (A, B, ..., Z, AA, ...)."""
    result = ""
    col_index += 1
    while col_index > 0:
        col_index -= 1
        result = chr(65 + (col_index % 26)) + result
        col_index //= 26
    return result


def extract_sheet_id(url):
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot extract sheet ID from: {url}")


def extract_gid(url):
    """Extract the gid (tab identifier) from a Google Sheets URL, if present."""
    m = re.search(r'[#&?]gid=(\d+)', url)
    return int(m.group(1)) if m else None


def resolve_sheet_name(sheet_id, target_sheet_name, target_sheet_url, credentials):
    """
    Resolve the actual tab name. If the caller-provided name doesn't exist,
    fall back to matching the gid from the URL, then to the first tab.
    """
    meta = invoke(SHEETS_LAMBDA, {
        'tool': 'get_sheet_metadata',
        'inputs': {'sheet_id': sheet_id},
        'credentials_dict': credentials
    })

    if not meta.get('success'):
        print(f"   Could not fetch metadata, using provided name: {target_sheet_name}")
        return target_sheet_name

    tabs = meta.get('sheets', [])
    if not tabs:
        return target_sheet_name

    tab_names = [t['title'] for t in tabs]
    print(f"   Available tabs: {tab_names}")

    if target_sheet_name in tab_names:
        print(f"   Tab '{target_sheet_name}' found in spreadsheet")
        return target_sheet_name

    gid = extract_gid(target_sheet_url)
    if gid is not None:
        for tab in tabs:
            if tab.get('sheetId') == gid:
                resolved = tab['title']
                print(f"   Resolved gid={gid} to tab '{resolved}'")
                return resolved

    first_tab = tabs[0]['title']
    print(f"   '{target_sheet_name}' not found, falling back to first tab: '{first_tab}'")
    return first_tab

