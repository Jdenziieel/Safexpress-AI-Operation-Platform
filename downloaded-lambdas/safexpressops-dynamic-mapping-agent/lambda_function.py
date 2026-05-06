import json
import boto3
import os
import re
import base64
import struct
import zipfile
import io
from datetime import datetime

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

    print(f"Step 0: Resolving target sheet tab name...")
    target_sheet_name = resolve_sheet_name(sheet_id, target_sheet_name, target_sheet_url, credentials)

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

    if use_cache:
        print("Using cached preview results (skipping AI call)")
        write_strategy  = cached_strategy
        anchor_column   = cached_anchor
        column_mappings = cached_mappings
        source_anchor   = inputs.get('source_anchor', cached_anchor)
        formula_col_set = set(cached_formulas or [])

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
        cached_source_schema = {
            'headers': list((parse_result.get('columns') or [])),
            'total_rows': parse_result.get('row_count', 0),
            'col_samples': {},
        }
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
            identification = invoke(MAPPING_LAMBDA, {
                'tool': 'find_identifier',
                'inputs': {'target_schema': target_schema, 'source_schema': source_schema}
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
        composite_to_col_index=ctci
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

        if len(sheets_list) >= 2:
            picked = _auto_pick_source_sheet(sheets_list)
            if picked is not None:
                sheet_name = picked
                auto_selected_sheet = picked
                print(f"   Auto-picked source sheet '{picked}' "
                      f"(scores: {[(s.get('name'), s.get('score')) for s in sheets_list]})")
            else:
                print(f"   Multi-sheet detected ({len(sheets_list)}). Returning picker response.")
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
        identification = invoke(MAPPING_LAMBDA, {
            'tool': 'find_identifier',
            'inputs': {'target_schema': target_schema, 'source_schema': source_schema}
        })
        print(f"   identification success: {identification.get('success')}")
        print(f"   identification error: {identification.get('error')}")
        print(f"   write_strategy: {identification.get('write_strategy')}")
        print(f"   anchor_column: {identification.get('anchor_column')}")
        if not identification.get('success'):
            return {'success': False, 'error': f"Identifier detection failed: {identification.get('error')}"}

    # Apply strategy-specific prep (cross_tab pivot, etc.) so the diff
    # generation + rows_to_update/append split below can treat the data as
    # a flat upsert. Mutates identification + parse_result + schemas.
    _prepare_strategy_state(identification, parse_result, source_schema, target_schema)

    write_strategy  = identification.get('write_strategy')
    anchor_column   = identification.get('anchor_column')
    column_mappings = identification.get('column_mappings', {})

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
    data_rows    = raw_rows[1:] if raw_rows else []

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


def route_write(write_strategy, anchor_column, transformed,
                target_headers, sheet_id, sheet_name, credentials,
                header_row_count=1, composite_to_col_index=None):

    safe_name = f"'{sheet_name}'" if ' ' in sheet_name and not sheet_name.startswith("'") else sheet_name
    header_row = max(header_row_count - 1, 0)

    # For grouped headers, remap composite "Group > Sub" keys to just "Sub"
    if header_row_count > 1 and composite_to_col_index:
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

    if write_strategy in ('row_per_date', 'row_per_entity', 'composite_key'):
        rows_for_update = []
        anchor_to_row_data = {}
        is_composite = isinstance(anchor_column, list)
        anchor_cols = anchor_column if is_composite else [anchor_column]

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

        if write_strategy == 'row_per_date' and not is_composite:
            update_result = invoke(SHEETS_LAMBDA, {
                'tool': 'update_rows_by_date',
                'inputs': {
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_name,
                    'date_column_name': anchor_column,
                    'rows_with_dates': rows_for_update,
                    'header_row': header_row
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
                    'anchor_column': anchor_column,
                    'rows': rows_for_update,
                    'header_row': header_row
                },
                'credentials_dict': credentials
            })
            unmatched = update_result.get('unmatched_anchors', [])

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
            header_read = invoke(SHEETS_LAMBDA, {
                'tool': 'read_sheet',
                'inputs': {'sheet_id': sheet_id, 'range_name': f"{safe_name}!1:1"},
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
        if anchor_column:
            ac = anchor_column if isinstance(anchor_column, str) else anchor_column[0]
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
                                    header_row_count, composite_to_col_index)

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
                if len(header_vals) >= 2:
                    sec_headers = [str(c).strip() for c in header_row]
                    sec_header_index = {h: idx for idx, h in enumerate(sec_headers) if h}
                    data_start = i + 2
                    data_end = data_start
                    while data_end < len(raw_values):
                        r = raw_values[data_end]
                        ne = [c for c in r if c and str(c).strip()]
                        if len(ne) == 0 or (len(ne) == 1 and data_end > data_start):
                            break
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
        section_index  = route['section_index']
        section        = target_sections[section_index]
        section_title  = section.get('title')

        print(f"   Auto-route: previewing '{sheet_name}' → section #{section_index} '{section_title}'")

        parse_result = invoke(MAPPING_LAMBDA, {
            'tool': 'parse_file',
            'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
        })
        if not parse_result.get('success'):
            return {
                'success': False,
                'error': f"Route parse failed for sheet {sheet_name!r}: {parse_result.get('error')}"
            }

        source_schema = invoke(MAPPING_LAMBDA, {
            'tool': 'structure_source_data',
            'inputs': {'parse_result': parse_result}
        })
        if not source_schema.get('success'):
            return {
                'success': False,
                'error': f"Route structure failed for sheet {sheet_name!r}: {source_schema.get('error')}"
            }

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
            identification = invoke(MAPPING_LAMBDA, {
                'tool': 'find_identifier',
                'inputs': {'target_schema': section_target, 'source_schema': source_schema}
            })
            if not identification.get('success'):
                return {
                    'success': False,
                    'error': f"Route identifier failed for sheet {sheet_name!r}: {identification.get('error')}"
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
            'sheet_name':      sheet_name,
            'section_index':   section_index,
            'section_title':   section_title,
            'write_strategy':  route_strategy,
            'anchor_column':   route_anchor,
            'source_anchor':   route_source_anchor,
            'anchor_type':     identification.get('anchor_type'),
            'column_mappings': route_mappings,
            'rows_to_update':  len(rows_to_update_route),
            'rows_to_append':  len(rows_to_append_route),
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
        section_title = route.get('section_title')
        section_idx   = route.get('section_index')
        route_strategy = route.get('write_strategy') or 'append'
        route_anchor   = route.get('anchor_column')
        route_mappings = route.get('column_mappings') or {}
        route_source_anchor = route.get('source_anchor', route_anchor)

        print(f"Auto-route write: sheet={sheet_name!r} → section #{section_idx} {section_title!r} "
              f"(strategy={route_strategy})")

        parse_result = invoke(MAPPING_LAMBDA, {
            'tool': 'parse_file',
            'inputs': {'file_content': file_content, 'file_type': file_type, 'sheet_name': sheet_name}
        })
        if not parse_result.get('success'):
            aggregated_errors.append(
                f"{sheet_name!r}: parse failed — {parse_result.get('error')}"
            )
            continue

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
                         section_override=None):
    """Write data to a multi-section sheet, matching the source to the correct section.

    Uses a **sort-merge** strategy by default:
      - Merges source rows with the target section's existing rows by anchor
        (e.g. Date). Matching anchors become updates; new anchors become
        appends slotted into chronological order.
      - If the section would overflow its current capacity, calls
        ``insert_rows`` to shift subsequent sections down — this is what
        prevents TC-L03 from dumping 05/01 rows at the sheet bottom just
        because the template's sections are tightly stacked.

    ``section_override`` — optional pre-resolved section dict (used by
    multi-sheet auto-route so the writer uses the route's pinned section
    instead of re-running :func:`_pick_best_section` on a subset of columns).
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

