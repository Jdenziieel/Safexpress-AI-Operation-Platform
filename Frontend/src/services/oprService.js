import { oprApi } from '../apiHelpers';

const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

export const previewOPR = async (file, targetSheetUrl) => {
  const fileData = await fileToBase64(file);
  const result = await oprApi.preview({
    file_data: fileData,
    target_sheet_url: targetSheetUrl,
    workflow_type: 'preview'
  });
  if (!result.success) throw new Error(result.error || 'Preview failed');
  return result;
};

export const processOPR = async (file, targetSheetUrl, approvedMappings = null) => {
  const fileData = await fileToBase64(file);
  const result = await oprApi.process({
    file_data: fileData,
    target_sheet_url: targetSheetUrl,
    workflow_type: 'process',
    approved_mappings: approvedMappings
  });
  if (!result.success) throw new Error(result.error || 'Processing failed');
  return result;
};