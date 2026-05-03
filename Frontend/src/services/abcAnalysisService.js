/**
 * ABC Analysis Service
 * Handles file upload and ABC analysis via AWS Lambda
 * ✅ UPDATED: Backend handles Google credentials via Secrets Manager
 */

import { abcApi } from '../apiHelpers';  // ✅ CORRECT - matches your filename

/**
 * Convert file to base64
 */
const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

/**
 * Run ABC Analysis
 * ✅ UPDATED: No longer needs Google credentials - backend handles it!
 */
export const runABCAnalysis = async (file, options = {}) => {
  try {
    // Convert file to base64
    const fileData = await fileToBase64(file);
    
    // Prepare request payload
    const payload = {
      file_data: fileData,
      date_column: options.dateColumn || 'Transdate',
      item_column: options.itemColumn || 'Itemcode',
      quantity_column: options.quantityColumn || 'Qtyordered',
      description_column: options.descriptionColumn || 'Description',
      uom_column: options.uomColumn || 'Qtyuom',
      a_threshold: options.aThreshold || 70.0,
      b_threshold: options.bThreshold || 90.0,
    };
    
    // Call API using abcApi from apiHelpers (gets JWT token automatically)
    const result = await abcApi.runAnalysis(payload);
    
    if (!result.success) {
      throw new Error(result.error || 'ABC Analysis failed');
    }
    
    return result;
    
  } catch (error) {
    console.error('ABC Analysis error:', error);
    
    // Handle specific errors
    if (error.response) {
      const errorData = error.response.data;
      throw new Error(errorData.error || `API error: ${error.response.status}`);
    } else {
      throw new Error(error.message || 'Failed to connect to ABC Analysis service');
    }
  }
};

/**
 * Format analysis results for display
 */
export const formatAnalysisResults = (apiResult) => {
  return {
    totalItems: apiResult.total_items || 0,
    totalTransactions: apiResult.total_transactions || 0,
    monthsAnalyzed: apiResult.months_analyzed || [],
    categoryA: {
      count: apiResult.class_a_count || 0,
      percentage: calculatePercentage(apiResult.class_a_count, apiResult.total_items),
      value: apiResult.a_contribution || apiResult.a_threshold || 70,
    },
    categoryB: {
      count: apiResult.class_b_count || 0,
      percentage: calculatePercentage(apiResult.class_b_count, apiResult.total_items),
      value: apiResult.b_contribution || (apiResult.b_threshold - apiResult.a_threshold) || 20,
    },
    categoryC: {
      count: apiResult.class_c_count || 0,
      percentage: calculatePercentage(apiResult.class_c_count, apiResult.total_items),
      value: apiResult.c_contribution || (100 - apiResult.b_threshold) || 10,
    },
    sheetUrl: apiResult.sheet_url,
    sheetId: apiResult.sheet_id,
    processedAt: new Date().toLocaleString(),
    monthlySummary: apiResult.monthly_summary || {},
  };
};

const calculatePercentage = (count, total) => {
  if (!total || total === 0) return 0;
  return Math.round((count / total) * 100);
};