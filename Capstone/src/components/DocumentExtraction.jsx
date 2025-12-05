import React, { useState, useRef, useEffect } from 'react';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableHeader } from '@tiptap/extension-table-header';
import { TableCell } from '@tiptap/extension-table-cell';
import { useEditor, EditorContent } from '@tiptap/react';
import { Document, Page, pdfjs } from 'react-pdf';
import { useMemo } from 'react';
import { marked } from 'marked';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import StarterKit from '@tiptap/starter-kit'
import TurndownService from 'turndown';
import { gfm } from 'turndown-plugin-gfm';
import { Upload, File as FileIcon, X, FileText, CheckCircle2, History, Database, Trash2, FileCode, Filter, ArrowUpDown } from 'lucide-react';
import DeleteConfirmationModal from './DeleteConfirmationModal';
import { ACCESS_TOKEN, saveDocumentToStorage, loadDocumentFromStorage, clearDocumentStorage } from '../token';
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
      background: '#26326e', 
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
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [persistedFilename, setPersistedFilename] = useState(null); // Filename from localStorage (when file object not available)

  // Load persisted document data from localStorage on component mount
  useEffect(() => {
    const savedData = loadDocumentFromStorage();
    if (savedData) {
      setChunkedOutput(savedData.chunkedOutput);
      setPersistedFilename(savedData.filename);
      setForceReplaceMode(savedData.forceReplaceMode);
      setShowPreview(true); // Show the preview panel with the persisted data
      console.log('[DocumentExtraction] Loaded persisted document:', savedData.filename);
    }
  }, []);

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
      
      const response = await axios.get(
        'http://127.0.0.1:8009/kb/list-kb',
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
      // DEBUG: Log what we're sending
      console.log('[DEBUG] Uploading to KB with data:', {
        chunks_count: chunkedOutput.chunks?.length,
        has_document_metadata: !!chunkedOutput.document_metadata,
        source_filename: currentFilename,
        content_hash: chunkedOutput.content_hash,
        file_size_bytes: chunkedOutput.file_size_bytes,
        forceReplaceMode: forceReplaceMode
      });
      
      // Get the access token
      const token = localStorage.getItem(ACCESS_TOKEN);
      
      if (!token) {
        setError('Authentication required. Please log in.');
        return;
      }
      
      const response = await axios.post('http://127.0.0.1:8009/kb/upload-to-kb', {
        chunks: chunkedOutput.chunks,
        document_metadata: chunkedOutput.document_metadata,
        source_filename: currentFilename,
        content_hash: chunkedOutput.content_hash,
        file_size_bytes: chunkedOutput.file_size_bytes,
        force_replace: forceReplaceMode // Use force_replace if we're in override mode
      }, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.data.success) {
        // Show success modal
        setUploadSuccess({
          filename: currentFilename,
          chunks: chunkedOutput.chunks.length,
          action: response.data.action,
          version: response.data.version,
          previousVersion: response.data.version_info?.previous_version
        });
        setShowSuccessModal(true);
        // Hide the upload button after successful upload
        setIsUploadedToKB(true);
        setForceReplaceMode(false); // Reset force replace mode after successful upload
        clearDocumentStorage(); // Clear persisted data after successful upload
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
    
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('force_reparse', 'true'); // Skip duplicate check

    setIsLoading(true);
    setError('');
    setJsonOutput(null);
    setChunkedOutput(null);
    setIsUploadedToKB(false);
    clearDocumentStorage(); // Clear any previously persisted data

    try {
      const response = await axios.post(
        'http://127.0.0.1:8009/pdf/parse-pdf',
        formData,
        {
          headers: { 
            'Content-Type': 'multipart/form-data'
          },
        }
      );
      setChunkedOutput(response.data);
      // Save to localStorage with forceReplaceMode=true for persistence
      saveDocumentToStorage(response.data, selectedFile.name, true);
      setPersistedFilename(selectedFile.name);
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
      const response = await axios.get(`http://127.0.0.1:8009/kb/document-versions/${encodeURIComponent(fileName)}`);
      if (response.data.success) {
        setVersionHistoryData(response.data);
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
  
  const formData = new FormData();
  formData.append('file', selectedFile); 

  setIsLoading(true);
  setError('');
  setJsonOutput(null);
  setChunkedOutput(null);
  setIsUploadedToKB(false); // Reset upload state for new parsing
  setForceReplaceMode(false); // Reset force replace mode for new parsing
  clearDocumentStorage(); // Clear any previously persisted data

  try {
    // Local Flask development (port 8009)
    const response = await axios.post(
      'http://127.0.0.1:8009/pdf/parse-pdf',
      formData,
      {
        headers: { 
          'Content-Type': 'multipart/form-data'
        },
      }
    );  
    setChunkedOutput(response.data);
    // Save to localStorage for persistence across page refresh
    saveDocumentToStorage(response.data, selectedFile.name, false);
    setPersistedFilename(selectedFile.name);
    
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
      await axios.delete(`http://127.0.0.1:8009/kb/delete/${documentToDelete.docId}`);
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
            {chunkedOutput?.chunks?.length > 0 && !isUploadedToKB && (
              <ActionButton
                icon={Database}
                className="de-kb-btn"
                onClick={handleUploadToKB}
                disabled={isUploadingToKB}
              >
                {isUploadingToKB ? 'Uploading...' : 'Upload to Knowledge Base'}
              </ActionButton>
            )}
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
          </div>
        </header>

        {/* PDF Upload Card - Only show when NOT previewing AND we don't have restored chunks */}
        {!showPreview && !chunkedOutput && (
          <div className="de-card-container">
            <div className="kb-card">
              <div className="kb-card-header">
                <h3>
                  <Upload size={20} />
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
                      <Upload size={18} />
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
          <div className="pdf-document-wrapper" style={{ flex: 1, overflow: 'auto' }}>
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
                      <Page pageNumber={index + 1} width={600} onRenderSuccess={onPageRenderSuccess} />
                      
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
            {isLoading && <p className="placeholder">Processing...</p>}
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
            className="parsed-content-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="parsed-modal-header">
              <h2>Parsed Content</h2>
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
                  className="close-btn"
                >
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="parsed-modal-body">
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
            className="duplicate-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="duplicate-modal-header">
              <h2>⚠️ Duplicate Document Detected</h2>
              <button
                onClick={() => setShowDuplicateModal(false)}
                className="close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="duplicate-modal-body">
              <div className="duplicate-message">
                <p className="duplicate-main-message">{duplicateInfo.message}</p>
                {duplicateInfo.existing_doc && (
                  <div className="duplicate-details">
                    <h3>Existing Document Details:</h3>
                    <table className="duplicate-info-table">
                      <tbody>
                        <tr>
                          <td><strong>File Name:</strong></td>
                          <td>{duplicateInfo.existing_doc.file_name}</td>
                        </tr>
                        <tr>
                          <td><strong>Uploaded By:</strong></td>
                          <td>{duplicateInfo.existing_doc.uploaded_by || 'Unknown'}</td>
                        </tr>
                        <tr>
                          <td><strong>Upload Date:</strong></td>
                          <td>{duplicateInfo.existing_doc.upload_date}</td>
                        </tr>
                        <tr>
                          <td><strong>Chunks:</strong></td>
                          <td>{duplicateInfo.existing_doc.chunks}</td>
                        </tr>
                        <tr>
                          <td><strong>File Size:</strong></td>
                          <td>{(duplicateInfo.existing_doc.file_size_bytes / 1024).toFixed(2)} KB</td>
                        </tr>
                      </tbody>
                    </table>
                    <button
                      className="version-history-btn"
                      onClick={() => fetchVersionHistory(duplicateInfo.existing_doc.file_name)}
                      disabled={isLoadingVersions}
                    >
                      <History size={16} />
                      {isLoadingVersions ? 'Loading...' : 'View Version History'}
                    </button>
                  </div>
                )}
                {duplicateInfo.cost_saved && (
                  <div className="duplicate-cost-saved">
                    <p>💰 <strong>Cost Optimization:</strong> {duplicateInfo.cost_saved}</p>
                  </div>
                )}
                {duplicateInfo.suggestion && (
                  <div className="duplicate-suggestion">
                    <p><strong>Suggestion:</strong> {duplicateInfo.suggestion}</p>
                  </div>
                )}
              </div>
              <div className="duplicate-actions">
                <button
                  className="duplicate-btn secondary"
                  onClick={() => setShowDuplicateModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="duplicate-btn warning"
                  onClick={() => setShowOverrideConfirm(true)}
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
            className="duplicate-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '450px' }}
          >
            <div className="duplicate-modal-header" style={{ background: '#ff9800' }}>
              <h2>⚠️ Confirm Override</h2>
              <button
                onClick={() => setShowOverrideConfirm(false)}
                className="close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="duplicate-modal-body">
              <div className="duplicate-message">
                <p className="duplicate-main-message" style={{ color: '#e65100' }}>
                  Are you sure you want to override the existing document?
                </p>
                <p style={{ fontSize: '0.9rem', color: '#666', marginTop: '10px' }}>
                  This will create a new version and archive the current document. 
                  The previous version will be saved in the version history.
                </p>
              </div>
              <div className="duplicate-actions">
                <button
                  className="duplicate-btn secondary"
                  onClick={() => setShowOverrideConfirm(false)}
                >
                  Cancel
                </button>
                <button
                  className="duplicate-btn danger"
                  onClick={handleForceReparse}
                  disabled={isLoading}
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
            className="duplicate-modal version-history-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '600px' }}
          >
            <div className="duplicate-modal-header" style={{ background: '#2196f3' }}>
              <h2><History size={20} style={{ marginRight: '8px' }} />Version History</h2>
              <button
                onClick={() => setShowVersionHistory(false)}
                className="close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="duplicate-modal-body">
              <h3 style={{ marginBottom: '15px', color: '#333' }}>
                {versionHistoryData.file_name}
              </h3>
              <p style={{ fontSize: '0.9rem', color: '#666', marginBottom: '15px' }}>
                Total Versions: {versionHistoryData.total_versions}
              </p>
              
              {/* Current Version */}
              {versionHistoryData.current_version && (
                <div className="version-item current">
                  <div className="version-badge current">
                    Current (v{versionHistoryData.current_version.version})
                  </div>
                  <table className="duplicate-info-table">
                    <tbody>
                      <tr>
                        <td><strong>Uploaded:</strong></td>
                        <td>{versionHistoryData.current_version.upload_date}</td>
                      </tr>
                      <tr>
                        <td><strong>Uploaded By:</strong></td>
                        <td>{versionHistoryData.current_version.uploaded_by}</td>
                      </tr>
                      <tr>
                        <td><strong>Chunks:</strong></td>
                        <td>{versionHistoryData.current_version.chunks}</td>
                      </tr>
                      <tr>
                        <td><strong>Size:</strong></td>
                        <td>{(versionHistoryData.current_version.file_size_bytes / 1024).toFixed(2)} KB</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* Previous Versions */}
              {versionHistoryData.version_history && versionHistoryData.version_history.length > 0 && (
                <div className="previous-versions">
                  <h4 style={{ margin: '20px 0 10px', color: '#666' }}>Previous Versions</h4>
                  {versionHistoryData.version_history.map((version, idx) => (
                    <div key={version.version_id} className="version-item archived">
                      <div className="version-badge archived">
                        v{version.version} (Archived)
                      </div>
                      <table className="duplicate-info-table">
                        <tbody>
                          <tr>
                            <td><strong>Originally Uploaded:</strong></td>
                            <td>{version.upload_date}</td>
                          </tr>
                          <tr>
                            <td><strong>Archived On:</strong></td>
                            <td>{version.archived_date}</td>
                          </tr>
                          <tr>
                            <td><strong>Uploaded By:</strong></td>
                            <td>{version.uploaded_by}</td>
                          </tr>
                          <tr>
                            <td><strong>Chunks:</strong></td>
                            <td>{version.chunks}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}

              {/* No history message */}
              {(!versionHistoryData.version_history || versionHistoryData.version_history.length === 0) && (
                <p style={{ textAlign: 'center', color: '#999', marginTop: '20px' }}>
                  No previous versions available.
                </p>
              )}
              
              <div className="duplicate-actions" style={{ marginTop: '20px' }}>
                <button
                  className="duplicate-btn primary"
                  onClick={() => setShowVersionHistory(false)}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Upload Success Modal */}
      {showSuccessModal && uploadSuccess && (
        <div className="modal-backdrop" onClick={() => {
          setShowSuccessModal(false);
          setShowHistory(true);
        }}>
          <div
            className="duplicate-modal"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '500px' }}
          >
            <div className="duplicate-modal-header" style={{ background: '#4caf50' }}>
              <h2>✅ Upload Successful</h2>
              <button
                onClick={() => {
                  setShowSuccessModal(false);
                  setShowHistory(true);
                }}
                className="close-btn"
              >
                <X size={20} />
              </button>
            </div>
            <div className="duplicate-modal-body">
              <div className="duplicate-message">
                <p className="duplicate-main-message" style={{ color: '#2e7d32' }}>
                  Successfully {uploadSuccess.action} document to Knowledge Base!
                </p>
                <div className="duplicate-details">
                  <table className="duplicate-info-table">
                    <tbody>
                      <tr>
                        <td><strong>File Name:</strong></td>
                        <td>{uploadSuccess.filename}</td>
                      </tr>
                      <tr>
                        <td><strong>Chunks Processed:</strong></td>
                        <td>{uploadSuccess.chunks}</td>
                      </tr>
                      {uploadSuccess.version && (
                        <tr>
                          <td><strong>Version:</strong></td>
                          <td>v{uploadSuccess.version}</td>
                        </tr>
                      )}
                      {uploadSuccess.previousVersion && (
                        <tr>
                          <td><strong>Previous Version:</strong></td>
                          <td>v{uploadSuccess.previousVersion.version_number} (Archived)</td>
                        </tr>
                      )}
                      <tr>
                        <td><strong>Status:</strong></td>
                        <td style={{ color: '#4caf50', fontWeight: 'bold' }}>Ready for Search</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="duplicate-actions">
                <button
                  className="duplicate-btn primary"
                  onClick={() => {
                    setShowSuccessModal(false);
                    setShowHistory(true);
                  }}
                  style={{ background: '#4caf50' }}
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
            <div className="history-modal-header">
              <h2>Processing History</h2>
              <button
                onClick={() => setShowHistory(false)}
                className="close-btn"
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
                    icon={ArrowUpDown}
                    className="de-sort-btn"
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