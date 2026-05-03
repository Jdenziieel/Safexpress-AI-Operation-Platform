import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableHeader } from '@tiptap/extension-table-header';
import { TableCell } from '@tiptap/extension-table-cell';
import { useEditor, EditorContent } from '@tiptap/react';
import { Document, Page, pdfjs } from 'react-pdf';
import { useMemo } from 'react';
import { marked } from 'marked';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import StarterKit from '@tiptap/starter-kit'
import TurndownService from 'turndown';
import { gfm } from 'turndown-plugin-gfm';
import { Upload, File as FileIcon, X, FileText, CheckCircle2, CheckCircle, History, Database, Trash2, FileCode, Filter, AlertTriangle } from 'lucide-react';
import DeleteConfirmationModal from './DeleteConfirmationModal';
import { kbApi } from '../api';
import { saveDocumentToStorage, loadDocumentFromStorage, clearDocumentStorage } from '../token';
import { useWebSocketPdf } from '../hooks/useWebSocketPdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import '../css/DocumentExtraction.css';

// Setup for the PDF.js worker (required by react-pdf)
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

// Configure marked to keep line breaks
marked.setOptions({
  breaks: true,   // <-- this preserves \n as <br>
});

// Create a TurndownService instance
const turndownService = new TurndownService({ headingStyle: 'atx' });

// Add GitHub-flavored markdown plugin (tables, strikethrough, etc.)
turndownService.use(gfm);

// Preserve line breaks (<br> -> \n)
turndownService.addRule("lineBreaks", {
  filter: "br",
  replacement: () => "\n",
});

// Human-readable date formatter for ISO 8601 timestamps in Manila time.
// Handles values like "2026-04-29T10:56:02.323928+00:00" → "Apr 29, 2026, 6:56 PM".
// Returns the original value untouched if it can't be parsed (e.g. "—",
// already-formatted strings, null/undefined) so we never accidentally
// render "Invalid Date" to the user.
const formatHumanDate = (value, { withSeconds = false } = {}) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('en-PH', {
    timeZone: 'Asia/Manila',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hour12: true,
  });
};

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.15rem', fontWeight: 800 }} {...props}>
      <Icon size={20} />
    </button>
    <span style={{ 
      position: 'absolute', 
      top: '100%', 
      left: '50%', 
      transform: 'translateX(-50%)', 
      marginTop: '8px',
      padding: '6px 12px', 
      background: '#27336e', 
      color: 'white', 
      borderRadius: '6px', 
      fontSize: '0.85rem', 
      fontWeight: 600,
      whiteSpace: 'nowrap',
      opacity: 0,
      pointerEvents: 'none',
      transition: 'opacity 0.2s',
      zIndex: 1000
    }} className="button-tooltip">{children}</span>
  </div>
);



const TiptapEditor = ({ content, onChange }) => {
  const editor = useEditor({
    extensions: [StarterKit, 
        Table.configure({
        resizable: true, // Allows resizing columns
        }),
        TableRow,
        TableHeader,
        TableCell,], // Provides basic text formatting (bold, italic, etc.)
    content: content,
    onUpdate: ({ editor }) => {
    onChange(editor.getHTML('\n')); // instead of getText()
  },
  });

  return <EditorContent editor={editor} />;
};

function DocumentExtraction() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [jsonOutput, setJsonOutput] = useState(null);
  const [chunkedOutput, setChunkedOutput] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [pdfPreviewFile, setPdfPreviewFile] = useState(null);
  // const [hoveredChunkIndex, setHoveredChunkIndex] = useState(null);
  // const [hoveredChunk, setHoveredChunk] = useState(null);
  const [selectedChunkId, setSelectedChunkId] = useState(null);
  const [numPages, setNumPages] = useState(null);
  const [pageDimensions, setPageDimensions] = useState({});
  const pageRefs = useRef([]);
  const pdfWrapperRef = useRef(null);
  const [pdfPageWidth, setPdfPageWidth] = useState(600);
  const [isViewerOpen, setIsViewerOpen] = useState(false);
  const [viewerTab, setViewerTab] = useState('parsed'); 
  // const [chunkDisplayMode, setChunkDisplayMode] = useState('regular'); //removed
  const [chunkView, setChunkView] = useState('markdown'); 
  const [dragActive, setDragActive] = useState(false);
  const [editingChunkIndex, setEditingChunkIndex] = useState(null); // Tracks which chunk is being edited
  const [editText, setEditText] = useState(""); // Holds the text while editing
  const [highlightBox, setHighlightBox] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const [isUploadingToKB, setIsUploadingToKB] = useState(false);
  const [uploadHistory, setUploadHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showParsedModal, setShowParsedModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('upload_date');
  const [sortOrder, setSortOrder] = useState('desc');
  const [showSortMenu, setShowSortMenu] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;
  const [showDuplicateModal, setShowDuplicateModal] = useState(false);
  const [duplicateInfo, setDuplicateInfo] = useState(null);
  const [showOverrideConfirm, setShowOverrideConfirm] = useState(false);
  const [forceReplaceMode, setForceReplaceMode] = useState(false); // Track if we're overriding
  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [versionHistoryData, setVersionHistoryData] = useState(null);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [isUploadedToKB, setIsUploadedToKB] = useState(false);
  const [showUploadConfirmModal, setShowUploadConfirmModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [persistedFilename, setPersistedFilename] = useState(null); // Filename from localStorage (when file object not available)
  const [processingProgress, setProcessingProgress] = useState(null); // Progress percentage for AI processing
  
  // Refs to track pending operations
  const pendingResolveRef = useRef(null);
  const pendingRejectRef = useRef(null);
  const pendingFileNameRef = useRef(null);

  // WebSocket hook for real-time PDF processing updates
  const handleWsProgress = useCallback((data) => {
    console.log('[WS] Progress:', data);
    setProcessingProgress(data.progress);
    setError(`AI processing: ${data.message} (${data.progress}%)`);
  }, []);

  const handleWsComplete = useCallback((data) => {
    console.log('[WS] Complete:', data);
    setProcessingProgress(100);
    setError(''); // Clear progress message
    
    // Resolve pending promise with result
    if (pendingResolveRef.current) {
      pendingResolveRef.current(data.result);
      pendingResolveRef.current = null;
      pendingRejectRef.current = null;
    }
    
    // Update UI
    setChunkedOutput(data.result);
    if (pendingFileNameRef.current) {
      saveDocumentToStorage(data.result, pendingFileNameRef.current, false);
      setPersistedFilename(pendingFileNameRef.current);
      pendingFileNameRef.current = null;
    }
    setIsLoading(false);
  }, []);

  const handleWsError = useCallback((data) => {
    console.error('[WS] Error:', data);
    setProcessingProgress(null);
    setError(`AI processing failed: ${data.error}`);
    
    // Reject pending promise
    if (pendingRejectRef.current) {
      pendingRejectRef.current(new Error(data.error));
      pendingResolveRef.current = null;
      pendingRejectRef.current = null;
    }
    setIsLoading(false);
  }, []);

  const { 
    isConnected: wsConnected, 
    connectionId: wsConnectionId,
    progress: wsProgress,
    progressMessage: wsProgressMessage,
    connect: wsConnect,
    disconnect: wsDisconnect,
    resetState: wsResetState
  } = useWebSocketPdf({
    onProgress: handleWsProgress,
    onComplete: handleWsComplete,
    onError: handleWsError
  });

  // Connect WebSocket on mount
  useEffect(() => {
    wsConnect();
    return () => wsDisconnect();
  }, [wsConnect, wsDisconnect]);

  // Load persisted document data from localStorage on component mount
  useEffect(() => {
    const savedData = loadDocumentFromStorage();
    if (savedData) {
      setChunkedOutput(savedData.chunkedOutput);
      setPersistedFilename(savedData.filename);
      setForceReplaceMode(savedData.forceReplaceMode);
      setShowPreview(true); // Show the preview panel with the persisted data
    }
  }, []);

  // --- Helper: Wait for WebSocket result or fallback to polling ---
  // Why this is more complex than `await pollJobStatus`:
  //   - The WS path is fast and has progress updates, but the connection
  //     can silently die (API Gateway idle reaping, proxy timeouts, lost
  //     WiFi). Without a fallback the user sat staring at a stale spinner
  //     until the 5-min hard timeout, even though the job had already
  //     finished server-side.
  //   - We now race the WebSocket against a polling loop that starts
  //     ~30s after the request fires. Whichever path completes first
  //     wins; the other becomes a harmless no-op via the `settled` guard.
  const SOFT_POLL_FALLBACK_MS = 30 * 1000;
  const HARD_TIMEOUT_MS = 5 * 60 * 1000;

  const waitForResult = async (jobId, fileName, useWs = true) => {
    if (useWs && wsConnected && wsConnectionId) {
      console.log(`[PDF] Using WebSocket for job ${jobId} (with poll fallback)`);
      pendingFileNameRef.current = fileName;

      return new Promise((resolve, reject) => {
        let settled = false;

        const settleResolve = (result) => {
          if (settled) return;
          settled = true;
          pendingResolveRef.current = null;
          pendingRejectRef.current = null;
          resolve(result);
        };
        const settleReject = (err) => {
          if (settled) return;
          settled = true;
          pendingResolveRef.current = null;
          pendingRejectRef.current = null;
          reject(err);
        };

        // The existing WebSocket handlers (handleWsComplete / handleWsError)
        // call pendingResolveRef.current(result) / pendingRejectRef.current(err).
        // Routing them through `settled` makes them idempotent and lets the
        // polling fallback share the same resolution path.
        pendingResolveRef.current = settleResolve;
        pendingRejectRef.current = settleReject;

        const hardTimeout = setTimeout(() => {
          settleReject(new Error(
            `Processing timeout - no response received in ${HARD_TIMEOUT_MS / 1000}s`
          ));
        }, HARD_TIMEOUT_MS);

        // Parallel polling fallback. We don't cancel the WS — whichever
        // path completes first calls `settleResolve` and the other becomes
        // a no-op. Polling silently absorbs transient errors so a temporary
        // status-check failure doesn't kill the job we're still waiting on.
        setTimeout(async () => {
          if (settled) return;
          console.warn(
            `[PDF] No WebSocket completion after ${SOFT_POLL_FALLBACK_MS / 1000}s `
            + `for job ${jobId}. Starting parallel polling fallback.`
          );
          let attempt = 0;
          const POLL_INTERVAL = 5000;
          const MAX_POLL_ATTEMPTS = 60;
          while (!settled && attempt < MAX_POLL_ATTEMPTS) {
            try {
              const statusResponse = await kbApi.post('/api/pdf/parse-pdf', {
                check_status: true,
                job_id: jobId,
              });
              if (settled) return;
              const status = statusResponse.data?.status;
              if (status === 'complete') {
                console.log(`[PDF] Poll fallback completed job ${jobId} ahead of WS`);
                clearTimeout(hardTimeout);
                settleResolve(statusResponse.data.result);
                return;
              }
              if (status === 'failed') {
                clearTimeout(hardTimeout);
                settleReject(new Error(
                  statusResponse.data?.error || 'AI processing failed'
                ));
                return;
              }
              // Still processing — wait and try again.
            } catch (pollErr) {
              // Don't surface — keep waiting for WS or a successful poll.
              console.warn(
                `[PDF] Poll fallback attempt ${attempt} errored: ${pollErr?.message || pollErr}`
              );
            }
            await new Promise((r) => setTimeout(r, POLL_INTERVAL));
            attempt += 1;
          }
        }, SOFT_POLL_FALLBACK_MS);
      });
    }

    // No WebSocket available — straight polling.
    console.log(`[PDF] WebSocket unavailable, polling job ${jobId}`);
    return pollJobStatus(jobId, fileName);
  };

  // --- Helper: Poll for async job completion (fallback) ---
  const pollJobStatus = async (jobId, fileName, maxAttempts = 60, interval = 5000) => {
    let attempts = 0;
    
    while (attempts < maxAttempts) {
      try {
        const statusResponse = await kbApi.post('/api/pdf/parse-pdf', {
          check_status: true,
          job_id: jobId
        });
        
        const status = statusResponse.data.status;
        
        if (status === 'complete') {
          setError(''); // Clear any status messages
          return statusResponse.data.result;
        }
        
        if (status === 'failed') {
          const error = statusResponse.data.error || 'Processing failed';
          throw new Error(`AI processing failed: ${error}`);
        }
        
        // Status is 'processing' - wait and retry
        setError(`AI processing in progress... (${Math.floor(attempts * interval / 1000)}s elapsed)`);
        await new Promise(resolve => setTimeout(resolve, interval));
        attempts++;
        
      } catch (err) {
        if (attempts >= maxAttempts - 1) {
          throw new Error(`Job polling timeout after ${maxAttempts * interval / 1000} seconds`);
        }
        throw err;
      }
    }
    
    throw new Error('Processing timeout - job did not complete in time');
  };

  // Fetch upload history from API when modal opens
  useEffect(() => {
    if (showHistory) {
      fetchUploadHistory();
    }
  }, [showHistory, currentPage, sortBy, sortOrder]);

  // Close sort menu when clicking outside
  const fetchUploadHistory = async () => {
    setIsLoadingHistory(true);
    setHistoryError('');
    
    try {
      const offset = (currentPage - 1) * itemsPerPage;
      const orderDir = sortOrder.toUpperCase();
      
      const response = await kbApi.get(
        '/api/kb/list-kb',
        {
          params: {
            limit: itemsPerPage,
            offset: offset,
            order_by: sortBy,
            order_dir: orderDir
          }
        }
      );
      
      if (response.data.success) {
        setUploadHistory(response.data.documents);
        setTotalDocuments(response.data.total_count);
      }
    } catch (err) {
      console.error('Error fetching upload history:', err);
      setHistoryError('Failed to load upload history');
    } finally {
      setIsLoadingHistory(false);
    }
  };

  // Close sort menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (showSortMenu && !event.target.closest('.de-sort-btn') && !event.target.closest('.sort-dropdown-menu')) {
        setShowSortMenu(false);
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showSortMenu]);

  // Client-side search filter (API handles sorting and pagination)
  const getFilteredHistory = () => {
    if (!searchQuery.trim()) {
      return uploadHistory;
    }
    
    return uploadHistory.filter(item =>
      item.file_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.uploaded_by?.toLowerCase().includes(searchQuery.toLowerCase())
    );
  };

  // Get paginated data (API handles pagination)
  const getPaginatedHistory = () => {
    const filtered = getFilteredHistory();
    return {
      items: filtered,
      totalPages: Math.ceil(totalDocuments / itemsPerPage),
      totalItems: totalDocuments
    };
  };

  // Reset to page 1 when search or sort changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, sortBy, sortOrder]);

  // Get the current filename (from selectedFile or persisted)
  const getCurrentFilename = () => selectedFile?.name || persistedFilename || 'unknown.pdf';

  // --- UPLOAD to Knowledge Base ---
  const handleUploadToKB = async () => {
    if (!chunkedOutput) {
      setError('No processed chunks available to upload.');
      return;
    }

    const currentFilename = getCurrentFilename();

  setIsUploadingToKB(true);
  setError('');

  try {
      const response = await kbApi.post('/api/kb/upload-to-kb', {
        file_name: currentFilename,
        chunks: chunkedOutput.chunks,
        page_count: chunkedOutput.document_metadata?.page_count || 0,
        content_hash: chunkedOutput.content_hash,
        file_size_bytes: chunkedOutput.file_size_bytes,
        replace_existing: forceReplaceMode,
        metadata: chunkedOutput.document_metadata,
        // Forward the S3 key of the uploaded PDF so kb_upload can persist
        // it on the KB_Documents row. kb_delete uses this later to remove
        // the original PDF from S3, preventing orphaned uploads/. Will be
        // undefined for the base64 (file_data) path — backend treats it
        // as optional.
        s3_key: chunkedOutput.s3_key,
        // Include token/cost info from AI processing for analytics
        // Check top-level first (direct response), then processing_info (nested)
        tokens_used: chunkedOutput.tokens_used || chunkedOutput.processing_info?.tokens_used || chunkedOutput.processing_info?.total_tokens || 0,
        cost_usd: chunkedOutput.cost_usd || chunkedOutput.processing_info?.cost_usd || 0
      });

      // Lambda returns 201 on success with doc_id, file_name, chunks_uploaded, version, message
      if (response.status === 201 || response.data.doc_id) {
        // Show success modal
        setUploadSuccess({
          filename: currentFilename,
          chunks: response.data.chunks_uploaded || chunkedOutput.chunks.length,
          action: forceReplaceMode ? 'replaced' : 'uploaded',
          version: response.data.version || 1,
          doc_id: response.data.doc_id,
          message: response.data.message
        });
        setShowSuccessModal(true);
        // Hide the upload button after successful upload
        setIsUploadedToKB(true);
        setForceReplaceMode(false); // Reset force replace mode after successful upload
        clearDocumentStorage(); // Clear persisted data after successful upload
        
        // Refresh the upload history if the history panel is open
        if (showHistory) {
          fetchUploadHistory();
        }
      } else {
        throw new Error(response.data.message || 'Upload failed');
      }
    } catch (err) {
      if (err.response) {
        setError(`Upload Error ${err.response.status}: ${err.response.data.error || 'Server error'}`);
      } else if (err.request) {
        setError('Network Error: Could not connect to the server.');
      } else {
        setError(`Unexpected error: ${err.message}`);
      }
    } finally {
      setIsUploadingToKB(false);
    }
  };

  // --- Force Reparse (when user confirms override) ---
  const handleForceReparse = async () => {
    if (!selectedFile) {
      setError('No file selected.');
      return;
    }

    // Close modals and set force replace mode
    setShowOverrideConfirm(false);
    setShowDuplicateModal(false);
    setForceReplaceMode(true); // Mark that next upload should force replace

    setIsLoading(true);
    setProcessingProgress(0);  // Reset progress
    setError('');
    setJsonOutput(null);
    setChunkedOutput(null);
    setIsUploadedToKB(false);
    clearDocumentStorage(); // Clear any previously persisted data

    try {
      // Step 1: Request pre-signed S3 upload URL
      const urlResponse = await kbApi.post('/api/pdf/parse-pdf', {
        request_upload_url: true,
        file_name: selectedFile.name
      });

      if (!urlResponse.data.upload_url) {
        throw new Error('Failed to get upload URL');
      }

      const { upload_url, s3_key } = urlResponse.data;

      // Step 2: Upload file directly to S3
      const uploadResponse = await fetch(upload_url, {
        method: 'PUT',
        body: selectedFile,
        headers: {
          'Content-Type': 'application/pdf'
        }
      });

      if (!uploadResponse.ok) {
        throw new Error('Failed to upload file to S3');
      }

      // Step 3: Parse the uploaded PDF with AI chunking (async pattern)
      const parseResponse = await kbApi.post('/api/pdf/parse-pdf', {
        s3_key: s3_key,
        file_name: selectedFile.name,
        force_reparse: true,
        use_ai: true,  // Enable AI-powered semantic chunking
        connection_id: wsConnectionId || undefined  // WebSocket connection for real-time updates
      });

      // Check if async job was started
      if (parseResponse.data.status === 'processing') {
        const jobId = parseResponse.data.job_id;
        const useWs = parseResponse.data.use_websocket || false;
        // Wait for result via WebSocket or poll
        const result = await waitForResult(jobId, selectedFile.name, useWs);
        
        setChunkedOutput(result);
        saveDocumentToStorage(result, selectedFile.name, true);
        setPersistedFilename(selectedFile.name);
      } else {
        // Immediate response (non-AI or already completed)
        setChunkedOutput(parseResponse.data);
        saveDocumentToStorage(parseResponse.data, selectedFile.name, true);
        setPersistedFilename(selectedFile.name);
      }
      // After successful parse, user can click "Upload to KB" which will use force_replace
    } catch (err) {
      if (err.response?.status === 401) {
        setError('Authentication failed. Please log in again.');
      } else if (err.response) {
        setError(`Error ${err.response.status}: ${err.response.data.error || 'Server error'}`);
      } else if (err.request) {
        setError('Network Error: Could not connect to the server.');
      } else {
        setError(`Unexpected error: ${err.message}`);
      }
      setForceReplaceMode(false); // Reset on error
    } finally {
      setIsLoading(false);
    }
  };

  // --- Fetch Version History ---
  const fetchVersionHistory = async (fileName) => {
    setIsLoadingVersions(true);
    try {
      const response = await kbApi.get(`/api/kb/document-versions/${encodeURIComponent(fileName)}`);
      if (response.data.success) {
        setVersionHistoryData(response.data);
        setShowHistory(false); // Close history modal before opening version history
        setShowVersionHistory(true);
      }
    } catch (err) {
      console.error('Error fetching version history:', err);
      setError('Failed to load version history');
    } finally {
      setIsLoadingVersions(false);
    }
  };
  

  // --- Get all boxes for a given page (used for highlighting) ---
  const getAllBoxesForPage = (pageNumber) => {
  if (!chunkedOutput?.chunks) return [];
  const currentPageInfo = pageDimensions[pageNumber];
  if (!currentPageInfo) return [];

  const scaleX = currentPageInfo.width / currentPageInfo.originalWidth;
  const scaleY = currentPageInfo.height / currentPageInfo.originalHeight;

  return chunkedOutput.chunks
    .flatMap(c => {
      // Handle multiple boxes (cross-page content)
      if (Array.isArray(c.metadata?.boxes)) {
        return c.metadata.boxes
          .filter(b => b.page === pageNumber) // Filter boxes by page
          .map(b => ({
            left: b.l * scaleX,
            top: b.t * scaleY,
            width: (b.r - b.l) * scaleX,
            height: (b.b - b.t) * scaleY,
            chunkId: c.id,
          }));
      } 
      // Handle single box (same-page content)
      else if (c.metadata?.box && c.metadata?.page === pageNumber) {
        const b = c.metadata.box;
        return [{
          left: b.l * scaleX,
          top: b.t * scaleY,
          width: (b.r - b.l) * scaleX,
          height: (b.b - b.t) * scaleY,
          chunkId: c.id,
        }];
      }
      return [];
    });
};



  // --- Drag & Drop Handlers ---
  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const dtFiles = e.dataTransfer?.files;
    if (dtFiles && dtFiles[0]) {
      handleFileChange({ target: { files: dtFiles } });
    }
  };


  // Handle file selection
  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (file && file.type === 'application/pdf') {
      setSelectedFile(file);
      // Do NOT set pdfPreviewFile here; only set after Continue is clicked
      setJsonOutput(null);
      setChunkedOutput(null);
      setError('');
      setIsUploadedToKB(false); // Reset upload state for new file
      setForceReplaceMode(false); // Reset force replace mode for new file
      setPersistedFilename(null); // Clear persisted filename
      clearDocumentStorage(); // Clear any previously persisted document data
    } else {
      setError('Please select a valid PDF file.');
    }
  };

  // Handle document parsing (now returns fully processed chunks)
 const handleParse = async () => {
  if (!selectedFile) {
    setError('Please select a PDF file first.');
    return;
  }
  
  setIsLoading(true);
  setProcessingProgress(0);  // Reset progress
  setError('');
  setJsonOutput(null);
  setChunkedOutput(null);
  setIsUploadedToKB(false); // Reset upload state for new parsing
  setForceReplaceMode(false); // Reset force replace mode for new parsing
  clearDocumentStorage(); // Clear any previously persisted data

  try {
    // Step 1: Request pre-signed S3 upload URL
    const urlResponse = await kbApi.post('/api/pdf/parse-pdf', {
      request_upload_url: true,
      file_name: selectedFile.name
    });

    if (!urlResponse.data.upload_url) {
      throw new Error('Failed to get upload URL');
    }

    const { upload_url, s3_key } = urlResponse.data;

    // Step 2: Upload file directly to S3
    const uploadResponse = await fetch(upload_url, {
      method: 'PUT',
      body: selectedFile,
      headers: {
        'Content-Type': 'application/pdf'
      }
    });

    if (!uploadResponse.ok) {
      throw new Error('Failed to upload file to S3');
    }

    // Step 3: Parse the uploaded PDF with AI chunking (async pattern)
    const parseResponse = await kbApi.post('/api/pdf/parse-pdf', {
      s3_key: s3_key,
      file_name: selectedFile.name,
      use_ai: true,  // Enable AI-powered semantic chunking
      connection_id: wsConnectionId || undefined  // WebSocket connection for real-time updates
    });

    // Check if async job was started
    if (parseResponse.data.status === 'processing') {
      const jobId = parseResponse.data.job_id;
      const useWs = parseResponse.data.use_websocket || false;
      
      // Wait for result via WebSocket or poll
      const result = await waitForResult(jobId, selectedFile.name, useWs);
      
      setChunkedOutput(result);
      saveDocumentToStorage(result, selectedFile.name, false);
      setPersistedFilename(selectedFile.name);
    } else {
      // Immediate response (non-AI or already completed)
      setChunkedOutput(parseResponse.data);
      saveDocumentToStorage(parseResponse.data, selectedFile.name, false);
      setPersistedFilename(selectedFile.name);
    }
    
  } catch (err) {
    if (err.response?.status === 409) {
      // Duplicate detected
      const detail = err.response.data.detail;
      setDuplicateInfo(detail);
      setShowDuplicateModal(true);
      setError(''); // Clear error since we're showing modal
    } else if (err.response?.status === 401) {
      setError('Authentication failed. Please log in again.');
    } else if (err.response) {
      setError(`Error ${err.response.status}: ${err.response.data.error || 'Server error'}`);
    } else if (err.request) {
      setError('Network Error: Could not connect to the server.');
    } else {
      setError(`Unexpected error: ${err.message}`);
    }
  } finally {
    setIsLoading(false);
  }
};

//  const handleParse = async () => {
//   if (!selectedFile) {
//     setError('Please select a PDF file first.');
//     return;
//   }
  
//   const formData = new FormData();
//   formData.append('pdf_file', selectedFile); // Changed from 'file' to 'pdf_file'

//   setIsLoading(true);
//   setError('');
//   setJsonOutput(null);
//   setChunkedOutput(null);

//   try {
//     // Get JWT token
//     const token = localStorage.getItem('access_token'); // Or however you store it
    
//     if (!token) {
//       setError('Authentication required. Please log in.');
//       return;
//     }

//     // Call your Django backend instead of Flask
//     const response = await axios.post(
//       'http://safexpressops-alb-366822214.ap-southeast-1.elb.amazonaws.com/api/upload-pdf/',
//       formData,
//       {
//         headers: { 
//           'Content-Type': 'multipart/form-data',
//           'Authorization': `Bearer ${token}` // Add authentication
//         },
//       }
//     );
    
//     // Your Django endpoint returns the Lambda response
//     setChunkedOutput(response.data);
    
//   } catch (err) {
//     if (err.response?.status === 401) {
//       setError('Authentication failed. Please log in again.');
//     } else if (err.response) {
//       setError(`Error ${err.response.status}: ${err.response.data.error || 'Server error'}`);
//     } else if (err.request) {
//       setError('Network Error: Could not connect to the server.');
//     } else {
//       setError(`Unexpected error: ${err.message}`);
//     }
//   } finally {
//     setIsLoading(false);
//   }
// };

  useEffect(() => {
    const el = pdfWrapperRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry.contentRect.width);
      if (w > 0) setPdfPageWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Handle PDF document load success
  const onDocumentLoadSuccess = ({ numPages }) => {
    setNumPages(numPages);
  };

  // Handle page render success
  const onPageRenderSuccess = (page) => {
    const pageNumber = page.pageNumber;
    const viewport = page.getViewport({ scale: 1.0 });
    setPageDimensions(prev => ({
      ...prev,
      [pageNumber]: {
        width: page.width,
        height: page.height,
        originalWidth: viewport.width,
        originalHeight: viewport.height,
      }
    }));
  };

  const handleChunkClick = (chunk) => {
    // If clicking the already selected chunk, deselect it. Otherwise, select the new one.
    if (chunk.id === selectedChunkId) {
      setSelectedChunkId(null);
    } else {
      setSelectedChunkId(chunk.id);
    }
  };


  // ✅ ADD this useEffect hook to react to changes in the selected chunk
  useEffect(() => {
    // If no chunk is selected, clear the highlight
    if (!selectedChunkId) {
      setHighlightBox(null);
      return;
    }

    // Find the full chunk object from the ID
    const chunk = chunkedOutput?.chunks.find(c => c.id === selectedChunkId);
    if (!chunk) return;

    // Handle cross-page chunks (multiple boxes)
    if (Array.isArray(chunk.metadata?.boxes)) {
      // For cross-page chunks, create highlight data for each page
      const multiPageHighlight = {
        isMultiPage: true,
        chunkId: selectedChunkId,
        pages: chunk.metadata.boxes.map(box => box.page)
      };
      setHighlightBox(multiPageHighlight);
      
      // Scroll to the first page
      const firstPage = chunk.metadata.boxes[0]?.page || chunk.metadata?.page;
      if (firstPage && pageRefs.current[firstPage - 1]) {
        pageRefs.current[firstPage - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      return;
    }

    // Handle single-page chunks (single box)
    const pageNumber = chunk.metadata?.page;
    const currentPageInfo = pageDimensions[pageNumber];

    if (pageNumber && currentPageInfo && chunk.metadata?.box) {
      const scaleX = currentPageInfo.width / currentPageInfo.originalWidth;
      const scaleY = currentPageInfo.height / currentPageInfo.originalHeight;
      const b = chunk.metadata.box;
      
      const scaledBox = {
        left: b.l * scaleX,
        top: b.t * scaleY,
        width: (b.r - b.l) * scaleX,
        height: (b.b - b.t) * scaleY,
      };
      
      setHighlightBox({ page: pageNumber, boxes: [scaledBox], chunkId: selectedChunkId });
      
      // Scroll the PDF page into view
      if (pageRefs.current[pageNumber - 1]) {
        pageRefs.current[pageNumber - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [selectedChunkId, chunkedOutput, pageDimensions]); // Dependencies for the effect


  // 1. Edit: Markdown -> HTML for TipTap
  const handleEdit = (index) => {
    setEditingChunkIndex(index);

    const mdText = chunkedOutput.chunks[index].text;

    // Convert markdown to HTML for TipTap
    const html = marked(mdText, { breaks: true });
    setEditText(html);
  };

  // 2. Save: HTML -> Markdown for storage
  const handleSave = (index) => {
    const updatedChunks = [...chunkedOutput.chunks];

    // Convert TipTap HTML back to Markdown
    const markdown = turndownService.turndown(editText);

    updatedChunks[index].text = markdown;

    setChunkedOutput({ ...chunkedOutput, chunks: updatedChunks });

    setEditingChunkIndex(null);
    setEditText("");
  };



  // When a user clicks "Cancel"
  const handleCancel = () => {
    setEditingChunkIndex(null);
    setEditText("");
  };

  // Handle delete from upload history
  const handleDeleteHistory = async (docId) => {
    const doc = uploadHistory.find(item => item.doc_id === docId);
    setDocumentToDelete({ docId, fileName: doc?.file_name || 'Unknown Document' });
    setShowDeleteModal(true);
  };

  const confirmDelete = async () => {
    if (!documentToDelete) return;
    
    setIsDeleting(true);
    try {
      await kbApi.delete(`/api/kb/delete/${documentToDelete.docId}`);
      // Refresh history
      await fetchUploadHistory();
      // Close modal
      setShowDeleteModal(false);
      setDocumentToDelete(null);
    } catch (err) {
      console.error('Error deleting document:', err);
      alert('Failed to delete document: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsDeleting(false);
    }
  };

  const cancelDelete = () => {
    if (!isDeleting) {
      setShowDeleteModal(false);
      setDocumentToDelete(null);
    }
  };

  // Helper function to close all modals
  const closeAllModals = () => {
    setShowParsedModal(false);
    setShowDuplicateModal(false);
    setShowOverrideConfirm(false);
    setShowVersionHistory(false);
    setShowUploadConfirmModal(false);
    setShowSuccessModal(false);
    setShowHistory(false);
    setShowDeleteModal(false);
  };

  return (
    <div className="documentextraction-page">
      <div className="documentextraction-container">
        <header className="documentextraction-header-row">
          <div>
            <h1 className="documentextraction-header-title">Document Extraction</h1>
            <p className="documentextraction-header-subtitle">Upload a PDF to see its content split into chunks with their locations highlighted.</p>
          </div>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <ActionButton
              icon={History}
              className="de-history-btn"
              onClick={() => setShowHistory(true)}
            >
              Processing History ({totalDocuments})
            </ActionButton>
            {/* Show Upload New PDF button when in preview mode or when we have restored chunks */}
            {(showPreview || (chunkedOutput && !selectedFile)) && (
              <>
                <input
                  type="file"
                  accept=".pdf"
                  onChange={(e) => {
                    handleFileChange(e);
                    setShowPreview(false);
                    setPdfPreviewFile(null);
                    setChunkedOutput(null);
                    setJsonOutput(null);
                    setIsUploadedToKB(false); // Reset upload state
                    clearDocumentStorage(); // Clear persisted data when selecting new file
                  }}
                  style={{ display: 'none' }}
                  id="new-pdf-file-input"
                />
                <ActionButton
                  icon={Upload}
                  className="de-upload-btn"
                  onClick={() => document.getElementById('new-pdf-file-input').click()}
                >
                  Upload New PDF
                </ActionButton>
              </>
            )}
            {chunkedOutput?.chunks?.length > 0 && !isUploadedToKB && (
              <ActionButton
                icon={Database}
                className="de-kb-btn"
                onClick={() => setShowUploadConfirmModal(true)}
                disabled={isUploadingToKB}
              >
                {isUploadingToKB ? 'Uploading...' : 'Upload to Knowledge Base'}
              </ActionButton>
            )}
          </div>
        </header>

        {/* PDF Upload Card - Only show when NOT previewing AND we don't have restored chunks */}
        {!showPreview && !chunkedOutput && (
          <div className="de-card-container">
            <div className="kb-card">
              <div className="kb-card-header">
                <h3>
                  Document Extraction
                </h3>
                <span className="kb-card-badge source">Document Selection</span>
              </div>
              <div className="kb-card-body">
                {!selectedFile ? (
                  <div className="kb-card-empty">
                    <FileIcon size={48} className="kb-empty-icon" />
                    <p>No document selected</p>
                    <input
                      type="file"
                      accept=".pdf"
                      onChange={handleFileChange}
                      style={{ display: 'none' }}
                      id="pdf-file-input"
                    />
                    <button
                      className="kb-card-button primary"
                      onClick={() => document.getElementById('pdf-file-input').click()}
                    >
                      Browse Files
                    </button>
                    <span className="kb-file-formats">PDF documents only</span>
                  </div>
                ) : (
                  <div className="kb-card-content">
                    <div className="kb-file-display">
                      <FileText size={40} className="kb-file-icon-large" />
                      <div className="kb-file-details">
                        <div className="kb-file-name-large">{selectedFile.name}</div>
                        <div className="kb-file-size">{(selectedFile.size / 1024).toFixed(2)} KB</div>
                      </div>
                    </div>
                    <div className="kb-card-actions">
                      <button
                        className="kb-card-button secondary"
                        onClick={() => { 
                          setSelectedFile(null); 
                          setPdfPreviewFile(null); 
                          setShowPreview(false); 
                          setChunkedOutput(null);
                          setJsonOutput(null);
                          setPersistedFilename(null);
                          setForceReplaceMode(false);
                          clearDocumentStorage(); // Clear persisted document data
                        }}
                      >
                        <X size={18} />
                        Clear Selection
                      </button>
                      <button
                        className="kb-card-button primary"
                        onClick={() => { 
                          setShowUpload(false); 
                          setShowPreview(true); 
                          setPdfPreviewFile(selectedFile); 
                        }}
                      >
                        <CheckCircle2 size={18} />
                        Preview & Process
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

    {/* Show preview section if we have a selected file OR restored chunks from localStorage */}
    {((showPreview && selectedFile) || (chunkedOutput && !selectedFile)) && (
      <>
        {/* PDF Preview Header with Parse Button - Above Card */}
        {!chunkedOutput && selectedFile && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 style={{ margin: 0 }}>PDF Preview</h2>
            <ActionButton
              icon={FileCode}
              className="de-parse-btn"
              onClick={handleParse}
              disabled={isLoading}
            >
              {isLoading ? 'Processing...' : 'Parse PDF'}
            </ActionButton>
          </div>
        )}
        
        {/* Header for restored session (chunks from localStorage without selectedFile) */}
        {chunkedOutput && !selectedFile && persistedFilename && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', padding: '12px 16px', backgroundColor: '#f0f9ff', borderRadius: '8px', border: '1px solid #bae6fd' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <FileText size={24} style={{ color: '#0284c7' }} />
              <div>
                <div style={{ fontWeight: 600, color: '#0c4a6e' }}>{persistedFilename}</div>
                <div style={{ fontSize: '12px', color: '#64748b' }}>
                  {chunkedOutput.chunks?.length || 0} chunks • Restored from previous session
                </div>
              </div>
            </div>
            <button
              className="kb-card-button secondary"
              onClick={() => {
                setChunkedOutput(null);
                setPersistedFilename(null);
                setForceReplaceMode(false);
                clearDocumentStorage();
                setShowUpload(true);
              }}
              style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Upload size={16} />
              Select New File
            </button>
          </div>
        )}
        
        <div className="main-content-area" style={{ minHeight: '800px', alignItems: 'stretch' }}>
          {/* PDF Preview Column - Only show if we have a file to preview */}
          {selectedFile && (
          <div className="pdf-preview-container">
          <div className="pdf-document-wrapper" ref={pdfWrapperRef} style={{ flex: 1, overflow: 'auto' }}>
            {pdfPreviewFile ? (
              <Document file={pdfPreviewFile} onLoadSuccess={onDocumentLoadSuccess}>
                {Array(numPages)
                  .fill()
                  .map((_, index) => (
                  <div
                    key={`page_container_${index + 1}`}
                    ref={(el) => (pageRefs.current[index] = el)}
                    className="pdf-page-container"
                  >
                    <div style={{ position: 'relative', display: 'inline-block' }}>
                      <Page pageNumber={index + 1} width={pdfPageWidth} onRenderSuccess={onPageRenderSuccess} />
                      
                      {/* Overlay for highlight boxes positioned over the page */}
                      <div className="highlight-box-overlay">
                        {getAllBoxesForPage(index + 1).map((b, i) => {
                          // For multi-page chunks, check if this chunk ID matches the selected one
                          const isSelected = highlightBox?.isMultiPage 
                            ? b.chunkId === highlightBox.chunkId
                            : highlightBox && highlightBox.chunkId === b.chunkId;

                          return (
                            <div
                              key={`highlight_${index}_${i}`}
                              className={`highlight-box ${isSelected ? 'hovered' : ''}`}
                              style={{
                                position: 'absolute',
                                left: `${b.left}px`,
                                top: `${b.top}px`,
                                width: `${b.width}px`,
                                height: `${b.height}px`,
                                pointerEvents: 'none',
                              }}
                            />
                          );
                        })}
                      </div>
                    </div>
                  </div>
              ))}
            </Document>
            ) : (
              <div className="placeholder">Click "Preview & Process" to view the PDF</div>
            )}
          </div>
        </div>
          )}

        {/* Parsed Content Column */}
        <div className="parsed-output-container">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2>Parsed Content</h2>
            {chunkedOutput?.chunks?.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                <ActionButton
                  icon={FileText}
                  className={chunkView === 'markdown' ? 'de-view-btn active' : 'de-view-btn'}
                  onClick={() => setChunkView('markdown')}
                >
                  Markdown
                </ActionButton>
                <ActionButton
                  icon={FileCode}
                  className={chunkView === 'json' ? 'de-view-btn active' : 'de-view-btn'}
                  onClick={() => setChunkView('json')}
                >
                  JSON
                </ActionButton>
              </div>
            )}
          </div>
          <div className="content-container">
            {isLoading && (
              <div className="de-progress-container">
                <p className="placeholder">Processing... {processingProgress > 0 ? `${processingProgress}%` : ''}</p>
                {processingProgress > 0 && (
                  <div className="de-progress-bar">
                    <div 
                      className="de-progress-fill" 
                      style={{ width: `${processingProgress}%` }}
                    />
                  </div>
                )}
              </div>
            )}
            {!isLoading && !chunkedOutput && (
              <p className="placeholder">Parsed content will appear here.</p>
            )}

            {chunkView === 'markdown' && chunkedOutput?.chunks?.map((chunk, index) => (
              <div
                key={`chunk_text_${index}`}
                onClick={() => handleChunkClick(chunk)}
                className={`markdown-chunk ${chunk.id === selectedChunkId ? 'selected' : ''}`}
              >
                {editingChunkIndex === index ? (
                  <div className="chunk-editor">
                    <TiptapEditor
                      content={editText}
                      onChange={(html) => setEditText(html)}
                    />
                    <div className="edit-controls">
                      <button className="edit-button save" onClick={() => handleSave(index)}>Save</button>
                      <button className="edit-button cancel" onClick={handleCancel}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="chunk-header">
                      <strong>Page {chunk.metadata?.page || 'N/A'}</strong>
                      <span className="chunk-type">{chunk.metadata?.type}</span>
                      {chunk.metadata?.level && (
                        <span className="heading-level">H{chunk.metadata.level}</span>
                      )}
                      {chunk.metadata?.section && (
                        <span className="chunk-section">{chunk.metadata.section}</span>
                      )}
                      {Array.isArray(chunk.metadata?.tags) && chunk.metadata.tags.length > 0 && (
                        <span style={{ fontSize: 12, color: '#6aa84f' }}>
                          {chunk.metadata.tags.join(', ')}
                        </span>
                      )}
                      <div className="chunk-actions">
                        <button className="edit-button" onClick={() => handleEdit(index)}>Edit</button>
                      </div>
                    </div>
                    <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                      {chunk.text}
                    </ReactMarkdown>
                  </>
                )}
              </div>
            ))}

            {chunkView === 'json' && chunkedOutput?.chunks?.map((chunk, index) => {
              const safeString = JSON.stringify(chunk, null, 2);
              return (
                <pre
                  key={`json_chunk_${index}`}
                  onClick={() => handleChunkClick(chunk)}
                  className={`json-chunk ${chunk.id === selectedChunkId ? 'selected' : ''}`}
                >
                  <code>{safeString}</code>
                </pre>
              );
            })}
          </div>
          </div>
        </div>
      </>
    )}

      {/* Parsed Content Modal */}
      {showParsedModal && (
        <div className="modal-backdrop" onClick={() => setShowParsedModal(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ color: '#ffffff' }}>Parsed Content</h2>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                {chunkedOutput?.chunks?.length > 0 && (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <ActionButton
                      icon={FileText}
                      className={chunkView === 'markdown' ? 'de-view-btn active' : 'de-view-btn'}
                      onClick={() => setChunkView('markdown')}
                    >
                      Markdown View
                    </ActionButton>
                    <ActionButton
                      icon={FileCode}
                      className={chunkView === 'json' ? 'de-view-btn active' : 'de-view-btn'}
                      onClick={() => setChunkView('json')}
                    >
                      JSON View
                    </ActionButton>
                  </div>
                )}
                <button
                  onClick={() => setShowParsedModal(false)}
                  className="history-modal-header-close-btn"
                >
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="history-modal-body">
              {isLoading && <p className="placeholder">Processing...</p>}
              {!isLoading && !chunkedOutput && (
                <p className="placeholder">No parsed content available.</p>
              )}

              {chunkView === 'markdown' && chunkedOutput?.chunks?.map((chunk, index) => (
                <div
                  key={`chunk_text_${index}`}
                  onClick={() => handleChunkClick(chunk)}
                  className={`markdown-chunk ${chunk.id === selectedChunkId ? 'selected' : ''}`}
                >
                  {editingChunkIndex === index ? (
                    <div className="chunk-editor">
                      <TiptapEditor
                        content={editText}
                        onChange={(html) => setEditText(html)}
                      />
                      <div className="edit-controls">
                        <button className="edit-button save" onClick={() => handleSave(index)}>Save</button>
                        <button className="edit-button cancel" onClick={handleCancel}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="chunk-header">
                        <strong>Page {chunk.metadata?.page || 'N/A'}</strong>
                        <span className="chunk-type">{chunk.metadata?.type}</span>
                        {chunk.metadata?.level && (
                          <span className="heading-level">H{chunk.metadata.level}</span>
                        )}
                        {chunk.metadata?.section && (
                          <span className="chunk-section">{chunk.metadata.section}</span>
                        )}
                        {Array.isArray(chunk.metadata?.tags) && chunk.metadata.tags.length > 0 && (
                          <span style={{ fontSize: 12, color: '#6aa84f' }}>
                            {chunk.metadata.tags.join(', ')}
                          </span>
                        )}
                        <div className="chunk-actions">
                          <button className="edit-button" onClick={() => handleEdit(index)}>Edit</button>
                        </div>
                      </div>
                      <ReactMarkdown rehypePlugins={[rehypeRaw]}>
                        {chunk.text}
                      </ReactMarkdown>
                    </>
                  )}
                </div>
              ))}

              {chunkView === 'json' && chunkedOutput?.chunks?.map((chunk, index) => {
                const safeString = JSON.stringify(chunk, null, 2);
                return (
                  <pre
                    key={`json_chunk_${index}`}
                    onClick={() => handleChunkClick(chunk)}
                    className={`json-chunk ${chunk.id === selectedChunkId ? 'selected' : ''}`}
                  >
                    <code>{safeString}</code>
                  </pre>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Duplicate Detection Modal */}
      {showDuplicateModal && duplicateInfo && (
        <div className="modal-backdrop" onClick={() => setShowDuplicateModal(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '600px' }}
          >
            <div className="history-modal-header">
              <h2>
                Duplicate Document Detected
              </h2>
              <button
                onClick={() => setShowDuplicateModal(false)}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              <div name="duplicate-info">
                <p>
                  {duplicateInfo.message}
                </p>
                {duplicateInfo.existing_doc && (
                  <div className='existing-doc-details'>
                    <h3 className='existing-doc-details-h3'>Existing Document Details:</h3>
                    <table className='existing-doc-details-table'>
                      <tbody className='existing-doc-details-tbody'>
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>File Name:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{duplicateInfo.existing_doc.file_name}</td>
                        </tr>
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>Uploaded By:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{duplicateInfo.existing_doc.uploaded_by || 'Unknown'}</td>
                        </tr>
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>Upload Date:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{duplicateInfo.existing_doc.upload_date}</td>
                        </tr>
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>Chunks:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{duplicateInfo.existing_doc.chunks}</td>
                        </tr>
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>File Size:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{(duplicateInfo.existing_doc.file_size_bytes / 1024).toFixed(2)} KB</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}
                {duplicateInfo.cost_saved && (
                  <div style={{ padding: '12px', background: '#26326e', borderRadius: '6px', border: '1px solid #a5d8f0', marginBottom: '12px' }}>
                    <p style={{ margin: 0, fontSize: '0.9rem', color: '#ffffff' }}><strong>Cost Optimization:</strong> {duplicateInfo.cost_saved}</p>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                <button
                  onClick={() => setShowDuplicateModal(false)}
                  className="pagination-btn"
                  style={{ background: '#e5e7eb', color: '#374151', border: '1px solid #d1d5db' }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowDuplicateModal(false);
                    setShowOverrideConfirm(true);
                  }}
                  className="pagination-btn"
                  style={{ background: '#26326e', color: '#ffffff', fontWeight: '700' }}
                >
                  Override
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Override Confirmation Modal */}
      {showOverrideConfirm && (
        <div className="modal-backdrop" onClick={() => setShowOverrideConfirm(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '500px' }}
          >
            <div className="history-modal-header" style={{ background: '#fdb016', borderBottom: '2px solid #27336e' }}>
              <h2 style={{ color: '#27336e', display: 'flex', alignItems: 'center', gap: '8px' }}>
                Confirm Override
              </h2>
              <button
                onClick={() => setShowOverrideConfirm(false)}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              <div style={{ marginBottom: '20px' }}>
                <p style={{ fontSize: '1rem', color: '#27336e', marginBottom: '12px', fontWeight: '600' }}>
                  Are you sure you want to override the existing document?
                </p>
                <p style={{ fontSize: '0.9rem', color: '#6b7280', lineHeight: '1.6' }}>
                  This will create a new version and archive the current document. 
                  The previous version will be saved in the version history.
                </p>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                <button
                  onClick={() => setShowOverrideConfirm(false)}
                  className="pagination-btn"
                  style={{ background: '#e5e7eb', color: '#374151', border: '1px solid #d1d5db' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleForceReparse}
                  disabled={isLoading}
                  className="pagination-btn"
                  style={{ 
                    background: isLoading ? '#9ca3af' : '#fdb016', 
                    color: isLoading ? 'white' : '#27336e', 
                    border: isLoading ? '1px solid #9ca3af' : '1px solid #fdb016',
                    cursor: isLoading ? 'not-allowed' : 'pointer',
                    opacity: isLoading ? 0.6 : 1,
                    fontWeight: '700'
                  }}
                >
                  {isLoading ? 'Processing...' : 'Yes, Override'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Version History Modal */}
      {showVersionHistory && versionHistoryData && (
        <div className="modal-backdrop" onClick={() => setShowVersionHistory(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '700px' }}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#ffffff' }}>
                Version History
              </h2>
              <button
                onClick={() => setShowVersionHistory(false)}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              <h3 style={{ marginBottom: '12px', color: '#27336e', fontSize: '1.1rem', fontWeight: '700' }}>
                {versionHistoryData.file_name}
              </h3>
              <p style={{ fontSize: '0.9rem', color: '#6b7280', marginBottom: '20px', fontWeight: '600' }}>
                Total Versions: {versionHistoryData.total_versions}
              </p>
              
              {/* Current Version */}
              {versionHistoryData.current_version && (
                <div style={{ marginBottom: '16px', padding: '16px', borderRadius: '8px', border: '1px solid #fdb016', background: '#fff8ef' }}>
                  <div style={{ display: 'inline-block', padding: '4px 12px', borderRadius: '20px', fontSize: '0.8rem', fontWeight: '700', background: '#27336e', color: 'white', marginBottom: '12px' }}>
                    Current (v{versionHistoryData.current_version.version})
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '150px' }}><strong>Uploaded:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{formatHumanDate(versionHistoryData.current_version.upload_date)}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '150px' }}><strong>Uploaded By:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{versionHistoryData.current_version.uploaded_by}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '150px' }}><strong>Chunks:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{versionHistoryData.current_version.chunks}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '150px' }}><strong>Size:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{(versionHistoryData.current_version.file_size_bytes / 1024).toFixed(2)} KB</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* Previous Versions */}
              {versionHistoryData.version_history && versionHistoryData.version_history.length > 0 && (
                <div style={{ marginTop: '20px' }}>
                  <h4 style={{ margin: '0 0 12px 0', color: '#6b7280', fontSize: '0.95rem', fontWeight: '700' }}>Previous Versions</h4>
                  {versionHistoryData.version_history.map((version, idx) => (
                    <div key={version.version_id} style={{ marginBottom: '16px', padding: '16px', borderRadius: '8px', border: '1px solid #d1d5db', background: '#f9fafb' }}>
                      <div style={{ display: 'inline-block', padding: '4px 12px', borderRadius: '20px', fontSize: '0.8rem', fontWeight: '700', background: '#9ca3af', color: 'white', marginBottom: '12px' }}>
                        v{version.version} (Archived)
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <tbody>
                          <tr>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '180px' }}><strong>Originally Uploaded:</strong></td>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{formatHumanDate(version.upload_date)}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '180px' }}><strong>Archived On:</strong></td>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{formatHumanDate(version.archived_date)}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '180px' }}><strong>Uploaded By:</strong></td>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{version.uploaded_by}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '180px' }}><strong>Chunks:</strong></td>
                            <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{version.chunks}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}

              {/* No history message */}
              {(!versionHistoryData.version_history || versionHistoryData.version_history.length === 0) && (
                <p style={{ textAlign: 'center', color: '#9ca3af', marginTop: '20px', fontSize: '0.9rem' }}>
                  No previous versions available.
                </p>
              )}
              
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                <button
                  onClick={() => setShowVersionHistory(false)}
                  className="pagination-btn"
                  style={{ background: '#27336e', color: 'white', border: '1px solid #27336e' }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Upload Success Modal */}
      {/* Upload Confirmation Modal */}
      {showUploadConfirmModal && (
        <div className="modal-backdrop" onClick={() => setShowUploadConfirmModal(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '500px' }}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                {/* <Database size={24} /> */}
                Confirm Upload to Knowledge Base
              </h2>
              <button
                onClick={() => setShowUploadConfirmModal(false)}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              <div style={{ marginBottom: '20px' }}>
                <p style={{ fontSize: '1rem', color: '#333', marginBottom: '16px' }}>
                  Are you sure you want to upload this document to the Knowledge Base?
                </p>
                <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '16px', border: '1px solid #e5e7eb' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>File Name:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{getCurrentFilename()}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>Total Chunks:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{chunkedOutput?.chunks?.length || 0}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '140px' }}><strong>Pages:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{chunkedOutput?.document_metadata?.page_count || 0}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                <button
                  onClick={() => setShowUploadConfirmModal(false)}
                  className="pagination-btn"
                  style={{ background: '#f3f4f6', color: '#374151', border: '1px solid #d1d5db' }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setShowUploadConfirmModal(false);
                    handleUploadToKB();
                  }}
                  className="pagination-btn"
                  style={{ background: '#27336e', color: 'white', border: '1px solid #27336e' }}
                >
                  Confirm Upload
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isUploadingToKB && (
        <div className="modal-backdrop">
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '420px', textAlign: 'center' }}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                Uploading to Knowledge Base
              </h2>
            </div>
            <div className="history-modal-body">
              <div className="de-progress-container">
                <Database size={40} style={{ color: '#27336e', marginBottom: '8px' }} />
                <p style={{ fontSize: '1rem', color: '#333', margin: '0 0 16px 0' }}>
                  Uploading {chunkedOutput?.chunks?.length || 0} chunks to the vector database...
                </p>
                <div className="de-progress-bar" style={{ maxWidth: '300px' }}>
                  <div className="de-progress-fill" style={{ width: '100%', animation: 'pulse 1.5s ease-in-out infinite' }} />
                </div>
                <p style={{ fontSize: '0.85rem', color: '#9ca3af', marginTop: '12px' }}>
                  Please wait, this may take a moment.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {showSuccessModal && uploadSuccess && (
        <div className="modal-backdrop" onClick={() => {
          setShowSuccessModal(false);
          setShowHistory(true);
        }}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '550px' }}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                Upload Successful
              </h2>
              <button
                onClick={() => {
                  setShowSuccessModal(false);
                  setShowHistory(true);
                }}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              <div style={{ marginBottom: '20px' }}>
                <p style={{ fontSize: '1rem', color: '#27336e', marginBottom: '16px', fontWeight: '600' }}>
                  Successfully {uploadSuccess.action} document to Knowledge Base!
                </p>
                <div style={{ background: '#f9fafb', borderRadius: '8px', padding: '16px', border: '1px solid #e5e7eb' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '160px' }}><strong>File Name:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{uploadSuccess.filename}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '160px' }}><strong>Chunks Processed:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>{uploadSuccess.chunks}</td>
                      </tr>
                      {uploadSuccess.version && (
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '160px' }}><strong>Version:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>v{uploadSuccess.version}</td>
                        </tr>
                      )}
                      {uploadSuccess.previousVersion && (
                        <tr>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '160px' }}><strong>Previous Version:</strong></td>
                          <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#4b5563' }}>v{uploadSuccess.previousVersion.version_number} (Archived)</td>
                        </tr>
                      )}
                      <tr>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#6b7280', width: '160px' }}><strong>Status:</strong></td>
                        <td style={{ padding: '8px 0', fontSize: '0.9rem', color: '#27336e', fontWeight: 'bold' }}>Ready for Search</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '16px', borderTop: '1px solid #e5e7eb' }}>
                <button
                  onClick={() => {
                    setShowSuccessModal(false);
                    setShowHistory(true);
                  }}
                  className="pagination-btn"
                  style={{ background: '#27336e', color: '#ffffff', border: '1px solid #27336e' }}
                >
                  View Processing History
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Processing History Modal */}
      {showHistory && (
        <div className="modal-backdrop" onClick={() => setShowHistory(false)}>
          <div
            className="history-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="history-modal-header" style={{ background: '#27336e', borderBottom: '2px solid #fdb016' }}>
              <h2 style={{ color: '#ffffff' }}>Processing History</h2>
              <button
                onClick={() => setShowHistory(false)}
                className="history-modal-header-close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="history-modal-body">
              {/* Search and Filter Controls */}
              <div style={{ display: 'flex', gap: '16px', marginBottom: '24px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="Search by file name or user..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="history-search-input"
                />
                <div style={{ position: 'relative' }}>
                  <ActionButton
                    icon={Filter}
                    className={`de-sort-btn ${showSortMenu ? 'is-active' : ''}`}
                    onClick={() => setShowSortMenu(!showSortMenu)}
                  >
                    Sort & Filter
                  </ActionButton>
                  {showSortMenu && (
                    <div className="sort-dropdown-menu">
                      <div className="sort-section">
                        <label>Sort By:</label>
                        <select
                          value={sortBy}
                          onChange={(e) => setSortBy(e.target.value)}
                          className="sort-select"
                        >
                          <option value="upload_date">Date</option>
                          <option value="file_name">File Name</option>
                          <option value="chunks">Chunks</option>
                          <option value="file_size_bytes">File Size</option>
                        </select>
                      </div>
                      <div className="sort-section">
                        <label>Order:</label>
                        <button
                          onClick={() => {
                            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
                          }}
                          className="sort-order-btn"
                        >
                          {sortOrder === 'asc' ? '↑ Ascending' : '↓ Descending'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {(() => {
                const paginatedData = getPaginatedHistory();
                return (
                  <>
                    {isLoadingHistory ? (
                      <p className="placeholder">Loading...</p>
                    ) : historyError ? (
                      <p className="error-message">{historyError}</p>
                    ) : paginatedData.totalItems === 0 ? (
                      <p className="placeholder">No processing history found.</p>
                    ) : (
                      <>
                        <table className="history-table">
                          <thead>
                            <tr>
                              <th>File Name</th>
                              <th>Upload Date</th>
                              <th>File Size</th>
                              <th>Chunks</th>
                              <th>Uploaded By</th>
                              <th>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {paginatedData.items.map((item) => {
                              // Parse ISO date and format for Philippine time display
                              const uploadDate = new Date(item.upload_date);
                              const phTime = uploadDate.toLocaleString('en-PH', {
                                timeZone: 'Asia/Manila',
                                year: 'numeric',
                                month: '2-digit',
                                day: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit',
                                hour12: true
                              });
                              
                              return (
                                <tr key={item.doc_id}>
                                  <td>{item.file_name}</td>
                                  <td>{phTime}</td>
                                  <td>{item.file_size_formatted}</td>
                                  <td>{item.chunks}</td>
                                  <td>{item.uploaded_by || 'Unknown User'}</td>
                                  <td>
                                    <div className="action-btns">
                                      <button
                                        className="history-icon-btn"
                                        onClick={() => fetchVersionHistory(item.file_name)}
                                        title="View Version History"
                                      >
                                        <History size={16} />
                                      </button>
                                      <button
                                        className="delete-btn"
                                        onClick={() => handleDeleteHistory(item.doc_id)}
                                        title="Delete"
                                      >
                                        <Trash2 size={16} />
                                      </button>
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                        
                        {/* Pagination Controls */}
                        {paginatedData.totalPages > 1 && (
                          <div className="pagination-controls">
                            <button
                              className="pagination-btn"
                              onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                              disabled={currentPage === 1}
                            >
                              Previous
                            </button>
                            <span className="pagination-info">
                              Page {currentPage} of {paginatedData.totalPages} ({paginatedData.totalItems} total)
                            </span>
                            <button
                              className="pagination-btn"
                              onClick={() => setCurrentPage(prev => Math.min(paginatedData.totalPages, prev + 1))}
                              disabled={currentPage === paginatedData.totalPages}
                            >
                              Next
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Modal Viewer */}
      {isViewerOpen && (
        <div className="modal-backdrop" onClick={() => setIsViewerOpen(false)}>
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '80vw',
              maxWidth: 1000,
              height: '80vh',
              background: '#1e1e1e',
              color: '#ddd',
              borderRadius: 8,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
            }}
          >
            <div
              className="modal-header"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 16px',
                borderBottom: '1px solid #333',
              }}
            >
              <div>
                <button
                  onClick={() => setViewerTab('parsed')}
                  className={viewerTab === 'parsed' ? 'active-tab' : ''}
                  style={{
                    marginRight: 8,
                    padding: '6px 10px',
                    background: viewerTab === 'parsed' ? '#2d2d2d' : '#1e1e1e',
                    border: '1px solid #444',
                    color: '#ddd',
                    borderRadius: 4,
                    cursor: 'pointer',
                  }}
                >
                  Parsed
                </button>
                <button
                  onClick={() => setViewerTab('smart')}
                  className={viewerTab === 'smart' ? 'active-tab' : ''}
                  style={{
                    padding: '6px 10px',
                    background: viewerTab === 'smart' ? '#2d2d2d' : '#1e1e1e',
                    border: '1px solid #444',
                    color: '#ddd',
                    borderRadius: 4,
                    cursor: 'pointer',
                  }}
                >
                  Smart
                </button>
              </div>
              <button
                onClick={() => setIsViewerOpen(false)}
                style={{
                  padding: '6px 10px',
                  background: '#1e1e1e',
                  border: '1px solid #444',
                  color: '#ddd',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                Close
              </button>
            </div>

            <div className="modal-body" style={{ flex: 1, overflow: 'auto', padding: 16 }}>
              {viewerTab === 'parsed' && (
                <>
                  {jsonOutput?.simplified ? (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordWrap: 'break-word',
                      background: '#111',
                      padding: 12,
                      borderRadius: 6,
                      border: '1px solid #333',
                    }}
                      >
                    {JSON.stringify(jsonOutput.simplified, null, 2)}
                  </pre>
                ) : (
                  <p className="placeholder">No parsed output yet. Parse a PDF first.</p>
                )}
                </>
              )}

              {viewerTab === 'smart' && (
                <>
                  {chunkedOutput?.chunks?.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      {chunkedOutput.chunks.map((chunk, idx) => (
                        <div
                          key={`smart_chunk_${idx}`}
                          style={{
                            padding: 12,
                            background: '#111',
                            borderRadius: 6,
                            border: '1px solid #333',
                          }}
                        >
                          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                            <strong>Page {chunk.metadata?.page ?? 'N/A'}</strong>
                            <span
                              style={{
                                fontSize: 12,
                                padding: '2px 6px',
                                border: '1px solid #444',
                                borderRadius: 4,
                                background: '#222',
                              }}
                            >
                              {chunk.metadata?.type}
                            </span>
                            {chunk.metadata?.section && (
                              <span style={{ fontSize: 12, color: '#aaa' }}>{chunk.metadata.section}</span>
                            )}
                            {Array.isArray(chunk.metadata?.tags) && chunk.metadata.tags.length > 0 && (
                              <span style={{ fontSize: 12, color: '#6aa84f' }}>
                                {chunk.metadata.tags.join(', ')}
                              </span>
                            )}
                          </div>

                          <ReactMarkdown rehypePlugins={[rehypeRaw]}>{chunk.text || ''}</ReactMarkdown>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="placeholder">No smart chunks yet. Click "Process Chunks".</p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        isOpen={showDeleteModal}
        onClose={cancelDelete}
        onConfirm={confirmDelete}
        documentName={documentToDelete?.fileName}
        isDeleting={isDeleting}
      />
    </div>
    </div>
  );
}

export default DocumentExtraction;