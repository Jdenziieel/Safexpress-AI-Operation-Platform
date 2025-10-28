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


  // --- UPLOAD to Knowledge Base ---
  const handleUploadToKB = async () => {
    if (!chunkedOutput) {
      setError('No processed chunks available to upload.');
      return;
    }

  setIsUploadingToKB(true);
  setError('');

  try {
      const response = await axios.post('http://safexpressops-alb-366822214.ap-southeast-1.elb.amazonaws.com/api/upload-pdf/', formData, {
        chunks: chunkedOutput.chunks,
        document_metadata: chunkedOutput.document_metadata,
        source_filename: selectedFile?.name || 'unknown.pdf'
      });

      if (response.data.success) {
        alert('Successfully uploaded to Knowledge Base!');
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
  

  // --- Get all boxes for a given page (used for highlighting) ---
  const getAllBoxesForPage = (pageNumber) => {
  if (!chunkedOutput?.chunks) return [];
  const currentPageInfo = pageDimensions[pageNumber];
  if (!currentPageInfo) return [];

  const scaleX = currentPageInfo.width / currentPageInfo.originalWidth;
  const scaleY = currentPageInfo.height / currentPageInfo.originalHeight;

  return chunkedOutput.chunks
    .filter(c => c.metadata?.page === pageNumber)
    .flatMap(c => {
      if (Array.isArray(c.metadata?.boxes)) {
        return c.metadata.boxes.map(b => ({
          left: b.l * scaleX,
          top: b.t * scaleY,
          width: (b.r - b.l) * scaleX,
          height: (b.b - b.t) * scaleY,
          chunkId: c.id,
        }));
      } else if (c.metadata?.box) {
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
  formData.append('pdf_file', selectedFile); // Changed from 'file' to 'pdf_file'

  setIsLoading(true);
  setError('');
  setJsonOutput(null);
  setChunkedOutput(null);

  try {
    // Get JWT token
    const token = localStorage.getItem('access_token'); // Or however you store it
    
    if (!token) {
      setError('Authentication required. Please log in.');
      return;
    }

    // Call your Django backend instead of Flask
    const response = await axios.post(
      'http://safexpressops-alb-366822214.ap-southeast-1.elb.amazonaws.com/api/upload-pdf/',
      formData,
      {
        headers: { 
          'Content-Type': 'multipart/form-data',
          'Authorization': `Bearer ${token}` // Add authentication
        },
      }
    );
    
    // Your Django endpoint returns the Lambda response
    setChunkedOutput(response.data);
    
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
  } finally {
    setIsLoading(false);
  }
};

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

    const pageNumber = chunk.metadata?.page;
    const currentPageInfo = pageDimensions[pageNumber];

    // Calculate the highlight box coordinates (logic moved from old handleMouseEnter)
    if (pageNumber && currentPageInfo) {
      const scaleX = currentPageInfo.width / currentPageInfo.originalWidth;
      const scaleY = currentPageInfo.height / currentPageInfo.originalHeight;
      let scaledBoxes = [];

      if (Array.isArray(chunk.metadata?.boxes)) {
        scaledBoxes = chunk.metadata.boxes.map(b => ({
          left: b.l * scaleX,
          top: b.t * scaleY,
          width: (b.r - b.l) * scaleX,
          height: (b.b - b.t) * scaleY,
        }));
      } else if (chunk.metadata?.box) {
        const b = chunk.metadata.box;
        scaledBoxes.push({
          left: b.l * scaleX,
          top: b.t * scaleY,
          width: (b.r - b.l) * scaleX,
          height: (b.b - b.t) * scaleY,
        });
      }
      setHighlightBox({ page: pageNumber, boxes: scaledBoxes });
    }

    // Scroll the PDF page into view
    if (pageNumber && pageRefs.current[pageNumber - 1]) {
      pageRefs.current[pageNumber - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
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

  return (
    <div className="documentextraction-page">
      <div className="documentextraction-container">
        <header className="documentextraction-header-row">
          <div>
            <h1 className="documentextraction-header-title">PDF Grounding Tool</h1>
            <p className="documentextraction-header-subtitle">Upload a PDF to see its content split into chunks with their locations highlighted.</p>
          </div>
          {/* Upload button in header, matches ReportAnalysis new-report-button */}
          {!showUpload && (
            <button
              className="action-button new-upload-button"
              onClick={() => {
                setShowUpload(true);
                setShowPreview(false);
                setSelectedFile(null);
                setPdfPreviewFile(null);
                setJsonOutput(null);
                setChunkedOutput(null);
                setError("");
              }}
            >
              <span>Upload PDF</span>
            </button>
          )}
        </header>

        {/* Step 2: Show upload box only when "Upload a PDF" is clicked AND no file has been selected yet */}
        {showUpload && (
          <div className="upload-section">
            <div
              className={`upload-box ${dragActive ? "drag-active" : ""}`}
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
            >
              {!selectedFile ? (
                <>
                  <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none">
                    <path d="M12 4v8" stroke="#26326e" strokeWidth="2.2" strokeLinecap="round"/>
                    <path d="M8 8l4-4 4 4" stroke="#26326e" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
                    <rect x="4" y="16" width="16" height="3" rx="1.5" fill="#26326e"/>
                  </svg>
                  <p>Select your file or drag and drop</p>
                  <small>PDF files accepted</small>
                  <label className="browse-btn">
                    Browse
                    <input type="file" accept=".pdf" hidden onChange={handleFileChange} />
                  </label>
                </>
              ) : (
                <>
                  <div className="selected-file-box">
                    <svg className="selected-file-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                      <path d="M12 16V8m0 0l-4 4m4-4l4 4m6 4v2a2 2 0 01-2 2H4a2 2 0 01-2-2v-2"/>
                    </svg>
                    <p className="selected-file-label">Selected file:</p>
                    <span className="selected-file-name">{selectedFile.name}</span>
                    <div className="selected-file-actions">
                      <button className="action-button cancel-btn" onClick={() => { setSelectedFile(null); setPdfPreviewFile(null); setShowPreview(false); }}>
                        Cancel
                      </button>
                      <button className="action-button continue-btn" onClick={() => { setShowUpload(false); setShowPreview(true); setPdfPreviewFile(selectedFile); }}>
                        Continue
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* Show action buttons once a file is selected (moved to PDF preview card) */}
        {/* Only show upload to KB button after PDF is parsed, inside PDF preview/parse card */}

    {showPreview && selectedFile && ( 
      <div className="main-content-area">
        {/* PDF Preview Column */}
        <div className="pdf-preview-container">
          <div className="pdf-preview-header">
            <h2>PDF Preview</h2>
            <button className="action-button new-upload-button" onClick={handleParse} disabled={isLoading}>
              {isLoading ? (
                "Uploading..."
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" fill="#fff" viewBox="0 0 24 24">
                  <path d="M12 16V8m0 0l-4 4m4-4l4 4m6 4v2a2 2 0 01-2 2H4a2 2 0 01-2-2v-2" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                </svg>
              )}
            </button>
          </div>
          <div className="pdf-document-wrapper">
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
                    <Page pageNumber={index + 1} width={600} onRenderSuccess={onPageRenderSuccess} />

                  {/* Always draw all boxes for this page */}
                  {getAllBoxesForPage(index + 1).map((b, i) => {
                    const isHovered = highlightBox && highlightBox.page === index + 1 && 
                                      highlightBox.boxes?.some(hb =>
                                        Math.abs(hb.left - b.left) < 1 &&
                                        Math.abs(hb.top - b.top) < 1
                                      );

                    return (
                      <div
                        key={`highlight_${index}_${i}`}
                        className={`highlight-box ${isHovered ? 'hovered' : ''}`}
                        style={{
                          left: `${b.left}px`,
                          top: `${b.top}px`,
                          width: `${b.width}px`,
                          height: `${b.height}px`,
                        }}
                      />
                    );
                  })}
 
                </div>
              ))}
            </Document>
            ) : (
              <div className="placeholder">Select a PDF file to preview</div>
            )}
          </div>
        </div>

        {/* Parsed Output Column (with toggle) */}
        <div className="parsed-output-container">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2>Parse</h2>
            {chunkedOutput?.chunks?.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => setChunkView('markdown')}
                  className={chunkView === 'markdown' ? 'active-tab' : ''}
                >
                  Markdown
                </button>
                <button
                  onClick={() => setChunkView('json')}
                  className={chunkView === 'json' ? 'active-tab' : ''}
                >
                  JSON
                </button>
              </div>
            )}
          </div>


          <div className="content-container">
            {isLoading && <p className="placeholder">Processing...</p>}
            {!isLoading && !jsonOutput && !chunkedOutput && (
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
                      content={editText} // keep as HTML
                      onChange={(html) => setEditText(html)} // do NOT turndown tables
                    />



                    <div className="edit-controls">
                      <button className="edit-button save" onClick={() => handleSave(index)}>Save</button>
                      <button className="edit-button cancel" onClick={handleCancel}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  // --- DISPLAY VIEW (Corrected) ---
                  <>
                    <div className="chunk-header">
                      <strong>Page {chunk.metadata?.page || 'N/A'}</strong>
                      <span className="chunk-type">{chunk.metadata?.type}</span>
                      
                      {/* Restored Metadata */}
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
    </div>
    </div>
  );
}

export default DocumentExtraction;