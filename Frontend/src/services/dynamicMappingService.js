 import { dynamicMappingApi } from '../apiHelpers';

export const fetchTargetTabs = async (targetSheetUrl) => {
  try {
    const formData = new FormData();
    formData.append('target_sheet_url', targetSheetUrl);
    formData.append('tool', 'fetch_tabs');

    const result = await dynamicMappingApi.upload(formData);

    if (!result.success) {
      throw new Error(result.error || 'Failed to fetch sheet tabs');
    }

    return result;
  } catch (error) {
    throw new Error(error.message || 'Failed to connect to spreadsheet');
  }
};

export const previewDynamicMapping = async (file, targetSheetUrl, options = {}) => {
  try {
    console.log('Starting Dynamic Mapping Preview...');
    console.log('   File:', file.name, `(${(file.size / 1024).toFixed(2)} KB)`);
    console.log('   Target:', targetSheetUrl);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_sheet_url', targetSheetUrl);
    formData.append('target_sheet_name', options.targetSheetName || 'Sheet1');
    formData.append('tool', 'preview_dynamic_mapping');
    if (options.sectionIndex !== undefined && options.sectionIndex !== null) {
      formData.append('section_index', String(options.sectionIndex));
    }
    if (options.sheetName) {
      formData.append('sheet_name', String(options.sheetName));
    }
    // Once the user picks a target tab from the multi-tab anchor-overlap
    // picker, echo it back so the backend skips Step 0c and writes to the
    // chosen tab instead of looping the picker.
    if (options.targetTabChosen) {
      formData.append('target_tab_chosen', String(options.targetTabChosen));
    }
    // Multi-sheet aggregate: once the user has resolved cross-sheet
    // identifier conflicts in the new modal, echo their picks back so
    // the backend can build the merged anchor map and skip the
    // requires_conflict_resolution branch.
    if (options.conflictChoices && typeof options.conflictChoices === 'object'
        && Object.keys(options.conflictChoices).length > 0) {
      formData.append('conflict_choices', JSON.stringify(options.conflictChoices));
    }
    // Same-section duplicate row resolution. Different shape from
    // conflictChoices: keys are still anchor values, but the chosen value
    // is "row_<N>" (0-indexed source row position) or "skip". The backend
    // uses these to filter source rows BEFORE structure/transform so
    // duplicates the user resolved never reach the writer.
    if (options.intraSectionChoices && typeof options.intraSectionChoices === 'object'
        && Object.keys(options.intraSectionChoices).length > 0) {
      formData.append('intra_section_choices', JSON.stringify(options.intraSectionChoices));
    }

    console.log('   Sending preview request...');
    const result = await dynamicMappingApi.upload(formData);
    console.log('   Preview complete:', result);

    if (!result.success) {
      throw new Error(result.error || 'Preview failed');
    }

    return result;

  } catch (error) {
    console.error('Preview error:', error);
    throw new Error(error.message || 'Failed to preview dynamic mapping');
  }
};


export const runDynamicMapping = async (file, targetSheetUrl, options = {}) => {
  try {
    console.log('Running Dynamic Mapping...');
    console.log('   File:', file.name, `(${(file.size / 1024).toFixed(2)} KB)`);
    console.log('   Target:', targetSheetUrl);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_sheet_url', targetSheetUrl);
    formData.append('target_sheet_name', options.targetSheetName || 'Sheet1');
    formData.append('tool', 'run_dynamic_mapping');
    if (options.sectionIndex !== undefined && options.sectionIndex !== null) {
      formData.append('section_index', String(options.sectionIndex));
    }
    if (options.sheetName) {
      formData.append('sheet_name', String(options.sheetName));
    }
    if (options.targetTabChosen) {
      formData.append('target_tab_chosen', String(options.targetTabChosen));
    }
    // Aggregate confirm: caller already ran preview with conflict_choices
    // and got an aggregate strategy_metadata back. Forward both so the
    // backend can replay the merge identically without re-prompting.
    if (options.conflictChoices && typeof options.conflictChoices === 'object'
        && Object.keys(options.conflictChoices).length > 0) {
      formData.append('conflict_choices', JSON.stringify(options.conflictChoices));
    }
    // Same-section duplicate-row resolution: forward to the run path so
    // the cached confirm filters source rows identically to how preview
    // built the filtered preview the user just approved.
    if (options.intraSectionChoices && typeof options.intraSectionChoices === 'object'
        && Object.keys(options.intraSectionChoices).length > 0) {
      formData.append('intra_section_choices', JSON.stringify(options.intraSectionChoices));
    }

    if (options.previewCache) {
      const pc = options.previewCache;
      if (pc.write_strategy) formData.append('write_strategy', pc.write_strategy);
      if (pc.anchor_column) formData.append('anchor_column',
        Array.isArray(pc.anchor_column) ? JSON.stringify(pc.anchor_column) : pc.anchor_column);
      if (pc.source_anchor) formData.append('source_anchor',
        Array.isArray(pc.source_anchor) ? JSON.stringify(pc.source_anchor) : pc.source_anchor);
      if (pc.column_mappings) formData.append('column_mappings', JSON.stringify(pc.column_mappings));
      if (pc.formula_cols) formData.append('formula_cols', JSON.stringify(pc.formula_cols));
      if (pc.header_row_count > 1) formData.append('header_row_count', pc.header_row_count);
      if (pc.composite_to_col_index && Object.keys(pc.composite_to_col_index).length)
        formData.append('composite_to_col_index', JSON.stringify(pc.composite_to_col_index));
      // Per-strategy state envelope — single JSON field carries pivot/value
      // columns, period columns, label column, section index, composite
      // anchor list, etc. Backend applies strategy-specific prep from this.
      if (pc.strategy_metadata && typeof pc.strategy_metadata === 'object') {
        formData.append('strategy_metadata', JSON.stringify(pc.strategy_metadata));
      }
      // Legacy per-field fallbacks (kept for one release so older bundles
      // still work against the new backend and vice versa).
      if (pc.pivot_source_col) formData.append('pivot_source_col', pc.pivot_source_col);
      if (pc.value_source_col) formData.append('value_source_col', pc.value_source_col);
    }

    // Per-row write filter from the preview UI checkboxes. When present,
    // the backend trims transformed rows to only those whose anchor /
    // (anchor, column) tuple is in the allow-list. Omitted entirely on
    // the "all selected" default path so legacy behavior is preserved.
    if (options.writeOnly
        && typeof options.writeOnly === 'object'
        && (
          (options.writeOnly.allowed_diff_cells || []).length > 0
          || (options.writeOnly.allowed_append_anchors || []).length > 0
        )
    ) {
      formData.append('write_only', JSON.stringify(options.writeOnly));
    }

    console.log('   Sending run request...');
    const result = await dynamicMappingApi.upload(formData);
    console.log('   Mapping complete:', result);

    if (!result.success) {
      throw new Error(result.error || 'Dynamic mapping failed');
    }

    return result;

  } catch (error) {
    console.error('Run error:', error);
    throw new Error(error.message || 'Failed to run dynamic mapping');
  }
};

export const formatPreviewResult = (result) => {
  const mappings = result.column_mappings || {};
  const mappedCount = Object.values(mappings).filter(Boolean).length;
  const unmappedCols = Object.entries(mappings)
    .filter(([, tgt]) => !tgt)
    .map(([src]) => src);

  return {
    writeStrategy:    result.write_strategy,
    anchorColumn:     result.anchor_column,
    sourceAnchor:     result.source_anchor,
    anchorType:       result.anchor_type,
    reasoning:        result.reasoning,
    rowsInSource:     result.rows_in_source || 0,
    rowsInTarget:     result.rows_in_target || 0,
    columnMappings:   mappings,
    mappedCount,
    unmappedColumns:  unmappedCols,
    sourceColTypes:   result.source_col_types || {},
    targetColTypes:   result.target_col_types || {},
  };
};

/**
 * Format run result for display in the success message
 */
export const formatRunResult = (result) => {
  return {
    writeStrategy:   result.write_strategy,
    anchorColumn:    result.anchor_column,
    rowsProcessed:   result.rows_processed || 0,
    reasoning:       result.reasoning,
    columnMappings:  result.column_mappings || {},
    writeResult:     result.write_result || {},
  };
};