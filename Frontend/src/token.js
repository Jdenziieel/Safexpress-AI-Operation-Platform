// global variables for tokens

export const ACCESS_TOKEN = 'access';
export const REFRESH_TOKEN = 'refresh';
export const GOOGLE_ACCESS_TOKEN = 'google_access_token';
// export const GOOGLE_REFRESH_TOKEN = 'google_refresh_token';  Not quite sure how to use this as of now

// Document extraction storage keys
export const PARSED_DOCUMENT_DATA = 'parsed_document_data';  // Stores chunkedOutput
export const PARSED_DOCUMENT_FILENAME = 'parsed_document_filename';  // Stores filename
export const FORCE_REPLACE_MODE = 'force_replace_mode';  // Stores forceReplaceMode state

/**
 * Clear all document extraction related data from localStorage.
 * Call this on logout or when starting a completely new upload.
 */
export const clearDocumentStorage = () => {
  localStorage.removeItem(PARSED_DOCUMENT_DATA);
  localStorage.removeItem(PARSED_DOCUMENT_FILENAME);
  localStorage.removeItem(FORCE_REPLACE_MODE);
};

/**
 * Save parsed document data to localStorage.
 * @param {Object} chunkedOutput - The parsed chunks from the backend
 * @param {string} filename - The name of the parsed file
 * @param {boolean} forceReplaceMode - Whether we're in override mode
 */
export const saveDocumentToStorage = (chunkedOutput, filename, forceReplaceMode = false) => {
  try {
    localStorage.setItem(PARSED_DOCUMENT_DATA, JSON.stringify(chunkedOutput));
    localStorage.setItem(PARSED_DOCUMENT_FILENAME, filename);
    localStorage.setItem(FORCE_REPLACE_MODE, JSON.stringify(forceReplaceMode));
  } catch (e) {
    console.warn('Failed to save document data to localStorage:', e);
  }
};

/**
 * Load parsed document data from localStorage.
 * @returns {Object|null} Object with chunkedOutput, filename, forceReplaceMode or null if not found
 */
export const loadDocumentFromStorage = () => {
  try {
    const chunkedOutput = localStorage.getItem(PARSED_DOCUMENT_DATA);
    const filename = localStorage.getItem(PARSED_DOCUMENT_FILENAME);
    const forceReplaceMode = localStorage.getItem(FORCE_REPLACE_MODE);
    
    if (chunkedOutput && filename) {
      return {
        chunkedOutput: JSON.parse(chunkedOutput),
        filename: filename,
        forceReplaceMode: forceReplaceMode ? JSON.parse(forceReplaceMode) : false
      };
    }
  } catch (e) {
    console.warn('Failed to load document data from localStorage:', e);
  }
  return null;
};

// ---------------------------------------------------------------------
// Workload Analysis state persistence
// ---------------------------------------------------------------------
//
// Survives page refresh. Stores a single JSON blob:
//   {
//     version: 1,
//     activeTab: 'inbound' | 'outbound',
//     inbound:  { basis, workers, palletCards, rateOverrides, lastResults },
//     outbound: { ... same shape ... },
//     savedAt:  ISO timestamp
//   }
//
// The blob is versioned so future schema changes can bump it and old data
// is silently discarded instead of crashing the page.

export const WORKLOAD_STATE_KEY = 'workload-analysis:v1:state';
export const WORKLOAD_STATE_VERSION = 1;

/**
 * Persist the full workload analysis state. Writes are wrapped in try/catch
 * so an exceeded localStorage quota only logs a warning instead of breaking
 * the calculator.
 */
export const saveWorkloadState = (state) => {
  try {
    const payload = {
      version: WORKLOAD_STATE_VERSION,
      savedAt: new Date().toISOString(),
      ...state,
    };
    localStorage.setItem(WORKLOAD_STATE_KEY, JSON.stringify(payload));
    return true;
  } catch (e) {
    console.warn('[workload] Failed to persist state (likely quota exceeded):', e);
    return false;
  }
};

/**
 * Load the workload analysis state. Returns `null` if there is no saved
 * state, the version doesn't match, or the JSON is corrupted.
 */
export const loadWorkloadState = () => {
  try {
    const raw = localStorage.getItem(WORKLOAD_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== WORKLOAD_STATE_VERSION) {
      return null;
    }
    return parsed;
  } catch (e) {
    console.warn('[workload] Failed to load saved state:', e);
    return null;
  }
};

export const clearWorkloadState = () => {
  localStorage.removeItem(WORKLOAD_STATE_KEY);
};