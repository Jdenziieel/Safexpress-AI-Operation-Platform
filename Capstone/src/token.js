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