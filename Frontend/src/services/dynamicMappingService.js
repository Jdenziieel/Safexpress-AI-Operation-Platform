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
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_sheet_url', targetSheetUrl);
    formData.append('target_sheet_name', options.targetSheetName || 'Sheet1');
    formData.append('tool', 'preview_dynamic_mapping');
    if (options.sectionIndex !== undefined && options.sectionIndex !== null) {
      formData.append('section_index', String(options.sectionIndex));
    }

    const result = await dynamicMappingApi.upload(formData);

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
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_sheet_url', targetSheetUrl);
    formData.append('target_sheet_name', options.targetSheetName || 'Sheet1');
    formData.append('tool', 'run_dynamic_mapping');
    if (options.sectionIndex !== undefined && options.sectionIndex !== null) {
      formData.append('section_index', String(options.sectionIndex));
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

    const result = await dynamicMappingApi.upload(formData);

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