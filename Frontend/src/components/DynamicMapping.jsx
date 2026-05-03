import React, { useState, useRef, useEffect } from "react";
import { Upload, File, X, FileText, CheckCircle2, Search } from "lucide-react";
import Swal from "sweetalert2";
import "../css/KnowledgeBase.css";
import {
  previewDynamicMapping,
  runDynamicMapping,
  fetchTargetTabs,
} from "../services/dynamicMappingService";

const ActionButton = ({ icon: Icon, children, className = "", ...props }) => {
  const isDisabled = Boolean(props.disabled);
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        className={`main-card-btn ${className}`}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "12px",
          fontSize: "1.15rem",
          fontWeight: 800,
        }}
        {...props}
      >
        <Icon size={20} />
      </button>
      {!isDisabled && (
        <span
          style={{
            position: "absolute",
            top: "100%",
            left: "50%",
            transform: "translateX(-50%)",
            marginTop: "8px",
            padding: "6px 12px",
            background: "#26326e",
            color: "white",
            borderRadius: "6px",
            fontSize: "0.85rem",
            fontWeight: 600,
            whiteSpace: "nowrap",
            opacity: 0,
            pointerEvents: "none",
            transition: "opacity 0.2s",
            zIndex: 1000,
          }}
          className="button-tooltip"
        >
          {children}
        </span>
      )}
    </div>
  );
};

function DynamicMapping() {
  const [targetFileUrl, setTargetFileUrl] = useState("");
  const [availableTabs, setAvailableTabs] = useState([]);
  const [selectedTab, setSelectedTab] = useState("");
  const [spreadsheetTitle, setSpreadsheetTitle] = useState("");
  const [isLoadingTabs, setIsLoadingTabs] = useState(false);
  const [tabsError, setTabsError] = useState("");
  const [isTargetConnected, setIsTargetConnected] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);

  const [showDuplicateModal, setShowDuplicateModal] = useState(false);
  const [duplicateFileInfo, setDuplicateFileInfo] = useState(null);
  const [pendingFile, setPendingFile] = useState(null);

  const [showCompareModal, setShowCompareModal] = useState(false);
  const [existingFileContent, setExistingFileContent] = useState(null);
  const [newFileContent, setNewFileContent] = useState(null);

  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [diffShowAll, setDiffShowAll] = useState(false);
  const [appendedExpanded, setAppendedExpanded] = useState(false);

  // Section picker state (only used when the backend returns
  // requires_section_selection === true for a multi-section source file).
  const [showSectionPicker, setShowSectionPicker] = useState(false);
  const [sectionsToPick, setSectionsToPick] = useState([]);
  const [selectedSectionIndex, setSelectedSectionIndex] = useState(0);
  const [sectionSearch, setSectionSearch] = useState("");
  const [chosenSectionIndex, setChosenSectionIndex] = useState(null);

  // Smart progress state. Replaces the old stuck-at-40% bar.
  // progressLabel is a real phase name the backend is actually executing;
  // processingProgress interpolates over the phase's configured duration
  // so the bar never freezes, and progressElapsedSec reassures the user
  // that the system is alive even when AI takes 15-20s.
  const [progressLabel, setProgressLabel] = useState("");
  const [progressElapsedSec, setProgressElapsedSec] = useState(0);
  const progressTickRef = useRef(null);
  const progressCancelledRef = useRef(false);

  const sourceFileInputRef = useRef(null);

  useEffect(() => {
    if (!targetFileUrl.includes("docs.google.com/spreadsheets/d/")) {
      setAvailableTabs([]);
      setSelectedTab("");
      setSpreadsheetTitle("");
      setIsTargetConnected(false);
      setTabsError("");
      return;
    }

    let cancelled = false;
    setIsLoadingTabs(true);
    setTabsError("");

    const timer = setTimeout(async () => {
      try {
        const result = await fetchTargetTabs(targetFileUrl);
        if (cancelled) return;
        setAvailableTabs(result.tabs || []);
        setSelectedTab(result.auto_selected || (result.tabs?.[0]?.title ?? ""));
        setSpreadsheetTitle(result.spreadsheet_title || "");
        setIsTargetConnected(true);
      } catch (err) {
        if (cancelled) return;
        setTabsError(err.message || "Failed to connect to spreadsheet");
        setIsTargetConnected(false);
      } finally {
        if (!cancelled) setIsLoadingTabs(false);
      }
    }, 800);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [targetFileUrl]);

  // Cleanup the smart-progress interval on unmount so it never outlives the
  // component (prevents setState-after-unmount warnings if the user navigates
  // away mid-preview).
  useEffect(() => {
    return () => {
      if (progressTickRef.current) {
        clearInterval(progressTickRef.current);
        progressTickRef.current = null;
      }
    };
  }, []);

  // Smart progress: drive the bar from real backend phases with typical
  // durations calibrated from CloudWatch. Percent interpolates within each
  // phase on a 200ms tick so the bar never freezes. Labels are truthful —
  // the backend really does execute them in this order. The AI phase is the
  // longest one and the place where users previously thought the app was
  // stuck; showing an elapsed-time counter kills that perception.
  const PROGRESS_PHASES = [
    { label: "Reading target sheet...",      pctEnd: 15, ms: 2500 },
    { label: "Parsing your file...",          pctEnd: 25, ms: 1500 },
    { label: "Structuring data...",           pctEnd: 40, ms: 2000 },
    { label: "Analyzing columns with AI...",  pctEnd: 80, ms: 18000 },
    { label: "Building diff preview...",      pctEnd: 95, ms: 3000 },
    { label: "Almost done...",                pctEnd: 99, ms: 30000 },
  ];

  const startSmartProgress = () => {
    if (progressTickRef.current) {
      clearInterval(progressTickRef.current);
      progressTickRef.current = null;
    }
    progressCancelledRef.current = false;
    setProgressElapsedSec(0);
    setProcessingProgress(0);
    setProgressLabel(PROGRESS_PHASES[0].label);

    const startedAt = Date.now();
    progressTickRef.current = setInterval(() => {
      if (progressCancelledRef.current) return;
      const elapsedMs = Date.now() - startedAt;
      setProgressElapsedSec(Math.floor(elapsedMs / 1000));

      let phaseStartPct = 0;
      let phaseStartMs = 0;
      for (const phase of PROGRESS_PHASES) {
        const phaseEndMs = phaseStartMs + phase.ms;
        if (elapsedMs <= phaseEndMs) {
          const phaseFraction = (elapsedMs - phaseStartMs) / phase.ms;
          const pct = phaseStartPct + phaseFraction * (phase.pctEnd - phaseStartPct);
          setProgressLabel(phase.label);
          setProcessingProgress(Math.min(99, Math.round(pct)));
          return;
        }
        phaseStartPct = phase.pctEnd;
        phaseStartMs = phaseEndMs;
      }
      // Past the final phase cap — hold at 99 so the "done" jump is visible.
      setProgressLabel(PROGRESS_PHASES[PROGRESS_PHASES.length - 1].label);
      setProcessingProgress(99);
    }, 200);
  };

  const finishSmartProgress = ({ success }) => {
    progressCancelledRef.current = true;
    if (progressTickRef.current) {
      clearInterval(progressTickRef.current);
      progressTickRef.current = null;
    }
    if (success) {
      setProcessingProgress(100);
      setProgressLabel("Complete");
    }
  };

  const handleTargetUrlChange = (e) => {
    setTargetFileUrl(e.target.value);
    setIsTargetConnected(false);
    setAvailableTabs([]);
    setSelectedTab("");
    setTabsError("");
  };

  const checkForDuplicate = (file) => {
    const duplicateByName = uploadedFiles.find((f) => f.name === file.name);
    const fileSizeKB = (file.size / 1024).toFixed(2);
    const fileType = file.type.includes("pdf")
      ? "PDF"
      : file.type.includes("csv")
        ? "CSV"
        : file.type.includes("spreadsheet")
          ? "XLSX"
          : "Unknown";
    const duplicateBySize = uploadedFiles.find(
      (f) => f.size === fileSizeKB + " KB" && f.type === fileType,
    );
    if (duplicateByName) return { type: "name", file: duplicateByName };
    if (duplicateBySize) return { type: "content", file: duplicateBySize };
    return null;
  };

  const handleSourceFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validTypes = [
      "application/pdf",
      "text/csv",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ];

    if (!validTypes.includes(file.type)) {
      Swal.fire({
        icon: "error",
        title: "Invalid File Type",
        text: "Only PDF, CSV, and XLSX files are accepted.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
      return;
    }

    if (!isTargetConnected) {
      Swal.fire({
        icon: "warning",
        title: "Target Not Connected",
        text: "Please paste a Google Sheets URL and wait for it to connect first.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
      return;
    }

    const duplicate = checkForDuplicate(file);
    if (duplicate) {
      setPendingFile(file);
      setDuplicateFileInfo(duplicate);
      setShowDuplicateModal(true);
      if (sourceFileInputRef.current) sourceFileInputRef.current.value = "";
      return;
    }

    await uploadFile(file);
  };

  const uploadFile = async (file, action = "new") => {
    setIsProcessing(true);
    setProcessingProgress(0);

    try {
      const progressInterval = setInterval(() => {
        setProcessingProgress((prev) => {
          if (prev >= 90) { clearInterval(progressInterval); return 90; }
          return prev + 15;
        });
      }, 200);

      await new Promise((resolve) => setTimeout(resolve, 1500));
      clearInterval(progressInterval);
      setProcessingProgress(100);

      const fileType = file.type.includes("pdf")
        ? "PDF"
        : file.type.includes("csv")
          ? "CSV"
          : file.type.includes("spreadsheet")
            ? "XLSX"
            : "Unknown";

      if (action === "override") {
        setUploadedFiles((prev) =>
          prev.map((f) => {
            if (f.name === file.name) {
              return {
                ...f,
                size: (file.size / 1024).toFixed(2) + " KB",
                uploadedAt: new Date().toLocaleString(),
                rawFile: file,
              };
            }
            return f;
          }),
        );
        Swal.fire({
          icon: "success", title: "Success!",
          text: "File overridden successfully!",
          confirmButtonColor: "#26326e", timer: 2000,
          customClass: { popup: "swal-inter-font" },
        });
      } else if (action === "keepboth") {
        const newUpload = {
          id: Date.now(),
          name: file.name.replace(/(\.[^.]+)$/, ` (${uploadedFiles.length + 1})$1`),
          type: fileType,
          size: (file.size / 1024).toFixed(2) + " KB",
          uploadedAt: new Date().toLocaleString(),
          rawFile: file,
        };
        setUploadedFiles((prev) => [...prev, newUpload]);
        Swal.fire({
          icon: "success", title: "Success!",
          text: "File uploaded successfully with new name!",
          confirmButtonColor: "#26326e", timer: 2000,
          customClass: { popup: "swal-inter-font" },
        });
      } else {
        const newUpload = {
          id: Date.now(),
          name: file.name,
          type: fileType,
          size: (file.size / 1024).toFixed(2) + " KB",
          uploadedAt: new Date().toLocaleString(),
          rawFile: file,
        };
        setUploadedFiles((prev) => [...prev, newUpload]);
        Swal.fire({
          icon: "success", title: "Success!",
          text: "File uploaded successfully!",
          confirmButtonColor: "#26326e", timer: 2000,
          customClass: { popup: "swal-inter-font" },
        });
      }

      if (sourceFileInputRef.current) sourceFileInputRef.current.value = "";
    } catch (error) {
      console.error("Error uploading file:", error);
      Swal.fire({
        icon: "error", title: "Upload Failed",
        text: "Failed to upload file. Please try again.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
    } finally {
      setIsProcessing(false);
      setProcessingProgress(0);
    }
  };

  const handleRemoveUploadedFile = (fileId) => {
    setUploadedFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  const readFileContent = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target.result;
        if (file.type === "text/plain") {
          resolve({ type: "text", content });
        } else if (file.type.includes("pdf")) {
          resolve({ type: "pdf", content: "PDF Preview", info: `PDF Document - ${(file.size / 1024).toFixed(2)} KB` });
        } else if (file.type.includes("word")) {
          resolve({ type: "docx", content: "DOCX Preview", info: `Word Document - ${(file.size / 1024).toFixed(2)} KB` });
        } else {
          resolve({ type: "unknown", content: "Preview not available" });
        }
      };
      reader.onerror = reject;
      if (file.type === "text/plain") { reader.readAsText(file); }
      else { reader.readAsArrayBuffer(file); }
    });
  };

  const handleDuplicateAction = async (action) => {
    if (action === "cancel") {
      setShowDuplicateModal(false);
      setPendingFile(null);
      setDuplicateFileInfo(null);
      return;
    }
    if (action === "compare") {
      try {
        setShowDuplicateModal(false);
        const existingFileData = {
          name: duplicateFileInfo.file.name,
          type: duplicateFileInfo.file.type === "PDF"
            ? "application/pdf"
            : duplicateFileInfo.file.type === "DOCX"
              ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              : "text/plain",
          size: duplicateFileInfo.file.size,
          uploadedAt: duplicateFileInfo.file.uploadedAt,
          content: `Existing file content preview\nFile: ${duplicateFileInfo.file.name}\nSize: ${duplicateFileInfo.file.size}\nUploaded: ${duplicateFileInfo.file.uploadedAt}\n\nNote: Full content comparison available when backend is connected.`,
        };
        const newContent = await readFileContent(pendingFile);
        setExistingFileContent({ ...existingFileData, preview: existingFileData.content });
        setNewFileContent({
          name: pendingFile.name,
          type: pendingFile.type,
          size: (pendingFile.size / 1024).toFixed(2) + " KB",
          preview: newContent.content || newContent.info || "Content preview",
        });
        setShowCompareModal(true);
      } catch (error) {
        console.error("Error reading file:", error);
        alert("Failed to load file contents for comparison");
      }
      return;
    }
    setShowDuplicateModal(false);
    if (pendingFile) {
      await uploadFile(pendingFile, action);
      setPendingFile(null);
      setDuplicateFileInfo(null);
    }
  };

  const handleCompareAction = async (action) => {
    setShowCompareModal(false);
    if (action === "back") { setShowDuplicateModal(true); return; }
    if (action === "cancel") {
      setPendingFile(null);
      setDuplicateFileInfo(null);
      setExistingFileContent(null);
      setNewFileContent(null);
      return;
    }
    if (pendingFile) {
      await uploadFile(pendingFile, action);
      setPendingFile(null);
      setDuplicateFileInfo(null);
      setExistingFileContent(null);
      setNewFileContent(null);
    }
  };

  const handleProcess = async () => {
    if (!isTargetConnected || uploadedFiles.length === 0) {
      Swal.fire({
        icon: "warning",
        title: "Incomplete Data",
        text: "Please connect a Google Sheet and upload at least one source file.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
      return;
    }

    const fileToProcess = uploadedFiles[0];

    const result = await Swal.fire({
      icon: "question",
      title: "Process Files",
      html: `<strong>Target:</strong> ${spreadsheetTitle || "Google Sheets"} → <em>${selectedTab}</em><br>
             <strong>Source File:</strong> ${fileToProcess.name}<br><br>
             This will first preview the mapping before writing anything.`,
      showCancelButton: true,
      confirmButtonText: "Preview Mapping",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#26326e",
      cancelButtonColor: "#6b7280",
      customClass: { popup: "swal-inter-font" },
    });

    if (!result.isConfirmed) return;

    setChosenSectionIndex(null);
    await runPreview({ sectionIndex: null });
  };

  // Run (or re-run) the preview. Shared by the first attempt and the
  // section-picker resubmit flow. When the backend returns
  // requires_section_selection, we surface the card picker instead of the
  // diff modal and wait for the user to pick a section before resubmitting.
  const runPreview = async ({ sectionIndex }) => {
    const fileToProcess = uploadedFiles[0];
    if (!fileToProcess) return;

    setIsProcessing(true);
    startSmartProgress();

    try {
      const preview = await previewDynamicMapping(
        fileToProcess.rawFile,
        targetFileUrl,
        { targetSheetName: selectedTab, sectionIndex },
      );

      if (preview && preview.requires_section_selection) {
        finishSmartProgress({ success: false });
        setSectionsToPick(preview.sections || []);
        setSelectedSectionIndex(0);
        setSectionSearch("");
        setShowSectionPicker(true);
        return;
      }

      finishSmartProgress({ success: true });
      setPreviewData(preview);
      setDiffShowAll(false);
      setAppendedExpanded(false);
      setShowPreviewModal(true);
    } catch (error) {
      console.error("Process error:", error);
      finishSmartProgress({ success: false });
      Swal.fire({
        icon: "error",
        title: "Processing Failed",
        text: error.message || "Something went wrong.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
    } finally {
      setIsProcessing(false);
      setTimeout(() => {
        setProcessingProgress(0);
        setProgressLabel("");
        setProgressElapsedSec(0);
      }, 400);
    }
  };

  const handleConfirmSection = async () => {
    if (sectionsToPick.length === 0) return;
    const idx = selectedSectionIndex;
    setChosenSectionIndex(idx);
    setShowSectionPicker(false);
    await runPreview({ sectionIndex: idx });
  };

  const handleConfirmMapping = async () => {
    if (!previewData) return;
    setIsConfirming(true);

    try {
      const fileToProcess = uploadedFiles[0];

      const result = await runDynamicMapping(
        fileToProcess.rawFile,
        targetFileUrl,
        {
          targetSheetName: selectedTab,
          previewCache: previewData,
          sectionIndex: chosenSectionIndex,
        },
      );

      setShowPreviewModal(false);

      if (result.success) {
        const wr = result.write_result || {};
        const lines = [
          `<strong>Strategy:</strong> ${result.write_strategy?.replace(/_/g, " ")}`,
          `<strong>Rows updated:</strong> ${wr.rows_updated ?? 0}`,
          `<strong>Rows appended:</strong> ${wr.rows_appended ?? 0}`,
        ];
        if (wr.cells_updated) lines.push(`<strong>Cells updated:</strong> ${wr.cells_updated}`);
        if (wr.section) lines.push(`<strong>Section:</strong> ${wr.section}`);
        if (result.anchor_column) lines.push(`<strong>Anchor column:</strong> ${Array.isArray(result.anchor_column) ? result.anchor_column.join(", ") : result.anchor_column}`);
        Swal.fire({
          icon: "success",
          title: "Done!",
          html: lines.join("<br>"),
          confirmButtonColor: "#26326e",
          customClass: { popup: "swal-inter-font" },
        });
      } else {
        throw new Error(result.error || "Write failed");
      }
    } catch (error) {
      console.error("Confirm error:", error);
      Swal.fire({
        icon: "error",
        title: "Write Failed",
        text: error.message || "Something went wrong.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
    } finally {
      setIsConfirming(false);
    }
  };

  return (
    <div className="knowledge-base-page">
      <div className="knowledge-base-container">
        <div className="knowledge-base-header-row">
          <div>
            <h1 className="knowledge-base-header-title">Dynamic Mapping</h1>
            <div className="knowledge-base-header-subtitle">
              Upload source files to the target Google Sheets
            </div>
          </div>
          <div className="knowledge-base-header-actions">
            <ActionButton
              icon={CheckCircle2}
              className="knowledge-base-header-action-button-process"
              onClick={handleProcess}
              disabled={!isTargetConnected || uploadedFiles.length === 0}
            >
              Process Files
            </ActionButton>
          </div>
        </div>

        <div className="kb-cards-container">

          {/* Target File Card */}
          <div className="kb-card">
            <div className="kb-card-header">
              <h3>Target File</h3>
              <span className="kb-card-badge target">Google Sheets</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: "100%" }}>

                <div style={{ marginBottom: "16px" }}>
                  <label style={{ display: "block", fontWeight: "600", marginBottom: "8px", color: "#1f2937", fontSize: "0.9rem" }}>
                    Google Sheets URL
                  </label>
                  <input
                    type="url"
                    value={targetFileUrl}
                    onChange={handleTargetUrlChange}
                    placeholder="https://docs.google.com/spreadsheets/d/..."
                    style={{ width: "100%", padding: "12px", border: "1px solid #d1d5db", borderRadius: "8px", fontSize: "0.9rem", fontFamily: "Inter, sans-serif" }}
                  />
                </div>

                {isLoadingTabs && (
                  <div style={{
                    display: "flex", alignItems: "center", gap: "10px",
                    padding: "12px 16px", background: "#eff6ff", borderRadius: "8px",
                    marginBottom: "16px", fontSize: "0.9rem", color: "#1e40af", fontWeight: 600,
                  }}>
                    Connecting to spreadsheet...
                  </div>
                )}

                {tabsError && !isLoadingTabs && (
                  <div style={{
                    padding: "12px 16px", background: "#fef2f2", borderRadius: "8px",
                    marginBottom: "16px", fontSize: "0.9rem", color: "#991b1b",
                  }}>
                    {tabsError}
                  </div>
                )}

                {availableTabs.length > 0 && !isLoadingTabs && (
                  <>
                    <div style={{ marginBottom: "20px" }}>
                      <label style={{ display: "block", fontWeight: "600", marginBottom: "8px", color: "#1f2937", fontSize: "0.9rem" }}>
                        Sheet Tab
                      </label>
                      <select
                        value={selectedTab}
                        onChange={(e) => setSelectedTab(e.target.value)}
                        style={{
                          width: "100%", padding: "12px", border: "1px solid #d1d5db",
                          borderRadius: "8px", fontSize: "0.9rem", fontFamily: "Inter, sans-serif",
                          background: "white", cursor: "pointer",
                        }}
                      >
                        {availableTabs.map((tab) => (
                          <option key={tab.sheetId} value={tab.title}>
                            {tab.title}
                          </option>
                        ))}
                      </select>
                      <span style={{ fontSize: "0.78rem", color: "#6b7280", marginTop: "4px", display: "block" }}>
                        Auto-detected from your URL
                      </span>
                    </div>

                    <div className="kb-file-display">
                      <CheckCircle2 size={40} className="kb-file-icon-large success" />
                      <div className="kb-file-details">
                        <div className="kb-file-name-large">{spreadsheetTitle || "Google Sheets Connected"}</div>
                        <div className="kb-file-status">
                          <CheckCircle2 size={14} />
                          Sheet: {selectedTab}
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Source File Card */}
          <div className="kb-card">
            <div className="kb-card-header">
              <h3>Source Files</h3>
              <span className="kb-card-badge source">Upload History</span>
            </div>
            <div className="kb-card-body">
              <div className="kb-card-content" style={{ width: "100%" }}>
                <input
                  ref={sourceFileInputRef}
                  type="file"
                  accept=".pdf,.csv,.xlsx"
                  onChange={handleSourceFileSelect}
                  style={{ display: "none" }}
                />
                <button
                  className="kb-card-button primary"
                  onClick={() => sourceFileInputRef.current?.click()}
                  disabled={!isTargetConnected || isProcessing}
                  style={{ width: "100%", marginBottom: "20px" }}
                >
                  <Upload size={18} />
                  {isProcessing ? `Uploading... ${processingProgress}%` : "Upload Source File"}
                </button>

                {!isTargetConnected && (
                  <div className="kb-empty-hint" style={{ textAlign: "center", marginBottom: "20px" }}>
                    Paste a valid Google Sheets URL above to enable uploads
                  </div>
                )}

                {isProcessing && (
                  <div style={{ marginBottom: "20px" }}>
                    <div className="kb-progress-bar">
                      <div className="kb-progress-fill" style={{ width: `${processingProgress}%` }}></div>
                    </div>
                    <div style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      marginTop: "8px", fontSize: "0.85rem", color: "#374151",
                    }}>
                      <span style={{ fontWeight: 600 }}>{progressLabel || "Starting..."}</span>
                      <span style={{ color: "#6b7280", fontFamily: "ui-monospace, Menlo, Consolas, monospace" }}>
                        {progressElapsedSec}s · {processingProgress}%
                      </span>
                    </div>
                  </div>
                )}

                {uploadedFiles.length > 0 ? (
                  <div style={{ maxHeight: "300px", overflowY: "auto" }}>
                    <h4 style={{ fontSize: "0.9rem", fontWeight: "700", marginBottom: "12px", color: "#1f2937" }}>
                      Uploaded Files ({uploadedFiles.length})
                    </h4>
                    {uploadedFiles.map((file) => (
                      <div key={file.id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        padding: "12px", background: "#f9fafb", borderRadius: "8px",
                        marginBottom: "8px", border: "1px solid #e5e7eb",
                      }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "12px", flex: 1 }}>
                          <FileText size={24} color="#26326e" />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: "600", fontSize: "0.9rem", color: "#1f2937", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {file.name}
                            </div>
                            <div style={{ fontSize: "0.8rem", color: "#6b7280", marginTop: "4px" }}>
                              <span style={{ background: "#dbeafe", color: "#1e40af", padding: "2px 8px", borderRadius: "4px", fontWeight: "600", marginRight: "8px" }}>
                                {file.type}
                              </span>
                              {file.size} • {file.uploadedAt}
                            </div>
                          </div>
                        </div>
                        <button
                          onClick={() => handleRemoveUploadedFile(file.id)}
                          style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", padding: "4px" }}
                        >
                          <X size={18} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="kb-card-empty">
                    <File size={48} className="kb-empty-icon" />
                    <p>No files uploaded yet</p>
                    <span className="kb-file-formats">PDF, XLSX, and CSV</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Compare Files Modal */}
        {showCompareModal && existingFileContent && newFileContent && (
          <div className="duplicate-modal-overlay" onClick={() => handleCompareAction("cancel")}>
            <div className="compare-modal" onClick={(e) => e.stopPropagation()}>
              <div className="duplicate-modal-header">
                <Search size={32} color="#3b82f6" />
                <h2>Compare Files</h2>
                <button className="duplicate-modal-close" onClick={() => handleCompareAction("cancel")}><X size={20} /></button>
              </div>
              <div className="compare-modal-body">
                <div className="compare-columns">
                  <div className="compare-column">
                    <div className="compare-column-header existing">
                      <FileText size={20} />
                      <div>
                        <div className="compare-column-title">Existing File</div>
                        <div className="compare-column-subtitle">{existingFileContent.name}</div>
                      </div>
                    </div>
                    <div className="compare-column-meta">
                      <div className="compare-meta-item"><strong>Size:</strong> {existingFileContent.size}</div>
                      <div className="compare-meta-item"><strong>Uploaded:</strong> {existingFileContent.uploadedAt}</div>
                      <div className="compare-meta-item"><strong>Type:</strong> {existingFileContent.type}</div>
                    </div>
                    <div className="compare-column-content">
                      <div className="compare-preview-label">Content Preview:</div>
                      <pre className="compare-preview">{existingFileContent.preview}</pre>
                    </div>
                  </div>
                  <div className="compare-column">
                    <div className="compare-column-header new">
                      <Upload size={20} />
                      <div>
                        <div className="compare-column-title">New File</div>
                        <div className="compare-column-subtitle">{newFileContent.name}</div>
                      </div>
                    </div>
                    <div className="compare-column-meta">
                      <div className="compare-meta-item"><strong>Size:</strong> {newFileContent.size}</div>
                      <div className="compare-meta-item"><strong>Type:</strong> {newFileContent.type}</div>
                    </div>
                    <div className="compare-column-content">
                      <div className="compare-preview-label">Content Preview:</div>
                      <pre className="compare-preview">{newFileContent.preview}</pre>
                    </div>
                  </div>
                </div>
                <div className="compare-difference-summary">
                  <strong>Summary:</strong>{" "}
                  {existingFileContent.size === newFileContent.size ? "Files have the same size" : "Files have different sizes"}
                </div>
              </div>
              <div className="compare-modal-actions">
                <button className="duplicate-action-btn back" onClick={() => handleCompareAction("back")}><FileText size={18} /> Back to Options</button>
                <button className="duplicate-action-btn override" onClick={() => handleCompareAction("override")}><Upload size={18} /> Use New File</button>
                <button className="duplicate-action-btn keepboth" onClick={() => handleCompareAction("keepboth")}><CheckCircle2 size={18} /> Keep Both</button>
                <button className="duplicate-action-btn cancel" onClick={() => handleCompareAction("cancel")}><X size={18} /> Cancel</button>
              </div>
            </div>
          </div>
        )}

        {/* Duplicate File Modal */}
        {showDuplicateModal && duplicateFileInfo && (
          <div className="duplicate-modal-overlay" onClick={() => handleDuplicateAction("cancel")}>
            <div className="duplicate-modal" onClick={(e) => e.stopPropagation()}>
              <div className="duplicate-modal-header">
                <FileText size={32} color="#fcb117" />
                <h2>Duplicate File Detected</h2>
                <button className="duplicate-modal-close" onClick={() => handleDuplicateAction("cancel")}><X size={20} /></button>
              </div>
              <div className="duplicate-modal-body">
                <p className="duplicate-modal-message">
                  {duplicateFileInfo.type === "name"
                    ? `A file named "${duplicateFileInfo.file.name}" already exists.`
                    : `A file with similar content already exists: "${duplicateFileInfo.file.name}"`}
                </p>
                <div className="duplicate-file-info">
                  <div className="duplicate-file-item">
                    <div className="duplicate-file-label">Existing File:</div>
                    <div className="duplicate-file-details">
                      <FileText size={18} />
                      <span>{duplicateFileInfo.file.name}</span>
                      <span className="duplicate-file-meta">{duplicateFileInfo.file.size} • {duplicateFileInfo.file.uploadedAt}</span>
                    </div>
                  </div>
                  <div className="duplicate-file-item">
                    <div className="duplicate-file-label">New File:</div>
                    <div className="duplicate-file-details">
                      <FileText size={18} />
                      <span>{pendingFile?.name}</span>
                      <span className="duplicate-file-meta">{(pendingFile?.size / 1024).toFixed(2)} KB</span>
                    </div>
                  </div>
                </div>
                <div className="duplicate-modal-question">What would you like to do?</div>
              </div>
              <div className="duplicate-modal-actions">
                <button className="duplicate-action-btn override" onClick={() => handleDuplicateAction("override")}><Upload size={18} /> Override Existing</button>
                <button className="duplicate-action-btn keepboth" onClick={() => handleDuplicateAction("keepboth")}><CheckCircle2 size={18} /> Keep Both Files</button>
                <button className="duplicate-action-btn compare" onClick={() => handleDuplicateAction("compare")}><Search size={18} /> Compare Files</button>
                <button className="duplicate-action-btn cancel" onClick={() => handleDuplicateAction("cancel")}><X size={18} /> Cancel Upload</button>
              </div>
            </div>
          </div>
        )}

        {/* Section Picker Modal (multi-section source files) */}
        {showSectionPicker && sectionsToPick.length >= 2 && (() => {
          const filtered = sectionsToPick
            .map((s, i) => ({ ...s, originalIndex: i }))
            .filter((s) => {
              if (!sectionSearch.trim()) return true;
              const q = sectionSearch.trim().toLowerCase();
              return (
                (s.title || "").toLowerCase().includes(q) ||
                (s.headers || []).some((h) => String(h).toLowerCase().includes(q))
              );
            });
          const showSearch = sectionsToPick.length >= 5;
          return (
            <div
              className="duplicate-modal-overlay"
              onClick={() => setShowSectionPicker(false)}
              onKeyDown={(e) => {
                const currentFilteredIdx = filtered.findIndex((s) => s.originalIndex === selectedSectionIndex);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  const next = filtered[(currentFilteredIdx + 1) % filtered.length];
                  if (next) setSelectedSectionIndex(next.originalIndex);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  const prev = filtered[(currentFilteredIdx - 1 + filtered.length) % filtered.length];
                  if (prev) setSelectedSectionIndex(prev.originalIndex);
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  handleConfirmSection();
                } else if (e.key === "Escape") {
                  setShowSectionPicker(false);
                }
              }}
              tabIndex={0}
            >
              <div
                className="duplicate-modal"
                style={{ maxWidth: "720px", width: "90%" }}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="duplicate-modal-header">
                  <FileText size={32} color="#26326e" />
                  <h2>Multiple Sections Detected</h2>
                  <button className="duplicate-modal-close" onClick={() => setShowSectionPicker(false)}><X size={20} /></button>
                </div>

                <div className="duplicate-modal-body">
                  <p style={{ color: "#374151", fontSize: "0.95rem", marginBottom: "12px" }}>
                    Your file contains <strong>{sectionsToPick.length} sections</strong>. Pick the one you want to write to the target sheet. Each section is mapped independently.
                  </p>

                  {showSearch && (
                    <input
                      type="text"
                      placeholder="Search by title or column..."
                      value={sectionSearch}
                      onChange={(e) => setSectionSearch(e.target.value)}
                      style={{
                        width: "100%", padding: "10px 12px",
                        border: "1px solid #d1d5db", borderRadius: "8px",
                        fontSize: "0.9rem", marginBottom: "12px",
                        boxSizing: "border-box",
                      }}
                      autoFocus
                    />
                  )}

                  <div style={{ maxHeight: "60vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: "10px" }}>
                    {filtered.length === 0 && (
                      <div style={{ color: "#6b7280", fontStyle: "italic", padding: "12px" }}>
                        No sections match your search.
                      </div>
                    )}
                    {filtered.map((section) => {
                      const isSelected = section.originalIndex === selectedSectionIndex;
                      return (
                        <div
                          key={section.originalIndex}
                          onClick={() => setSelectedSectionIndex(section.originalIndex)}
                          onDoubleClick={handleConfirmSection}
                          style={{
                            cursor: "pointer",
                            padding: "14px 16px",
                            borderRadius: "8px",
                            border: isSelected ? "2px solid #26326e" : "1px solid #e5e7eb",
                            background: isSelected ? "#eef2ff" : "#f9fafb",
                            transition: "all 0.12s",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                            <div style={{ fontWeight: 700, color: "#26326e", fontSize: "1rem" }}>
                              {section.title || `Section ${section.originalIndex + 1}`}
                            </div>
                            <span style={{
                              background: "#dcfce7", color: "#166534",
                              padding: "3px 10px", borderRadius: "12px",
                              fontSize: "0.75rem", fontWeight: 700,
                            }}>
                              {section.row_count} {section.row_count === 1 ? "row" : "rows"}
                            </span>
                          </div>

                          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "10px" }}>
                            {(section.headers || []).filter(Boolean).map((h, hi) => (
                              <span
                                key={hi}
                                style={{
                                  background: "#dbeafe", color: "#1e40af",
                                  padding: "3px 10px", borderRadius: "10px",
                                  fontSize: "0.78rem", fontWeight: 600,
                                }}
                              >
                                {h}
                              </span>
                            ))}
                          </div>

                          {Array.isArray(section.preview_rows) && section.preview_rows.length > 0 && (
                            <div style={{
                              background: "white",
                              border: "1px solid #e5e7eb",
                              borderRadius: "6px",
                              padding: "8px",
                              fontSize: "0.78rem",
                              fontFamily: "ui-monospace, Menlo, Consolas, monospace",
                              color: "#4b5563",
                              overflowX: "auto",
                            }}>
                              {section.preview_rows.map((row, ri) => (
                                <div key={ri} style={{ whiteSpace: "nowrap" }}>
                                  {row.map((c, ci) => (
                                    <span key={ci} style={{ marginRight: "12px" }}>
                                      {c !== "" ? c : <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty)</span>}
                                    </span>
                                  ))}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ fontSize: "0.78rem", color: "#6b7280", marginTop: "10px" }}>
                    Tip: use <kbd style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: "4px" }}>↑</kbd> / <kbd style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: "4px" }}>↓</kbd> to navigate, <kbd style={{ background: "#f3f4f6", padding: "1px 6px", borderRadius: "4px" }}>Enter</kbd> to confirm.
                  </div>
                </div>

                <div className="duplicate-modal-actions">
                  <button className="duplicate-action-btn cancel" onClick={() => setShowSectionPicker(false)}>
                    <X size={18} /> Cancel
                  </button>
                  <button
                    className="duplicate-action-btn compare"
                    onClick={handleConfirmSection}
                    disabled={filtered.length === 0}
                    style={{ opacity: filtered.length === 0 ? 0.5 : 1 }}
                  >
                    <CheckCircle2 size={18} /> Use this section
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Preview Modal */}
        {showPreviewModal && previewData && (
          <div className="duplicate-modal-overlay" onClick={() => setShowPreviewModal(false)}>
            <div
              className="duplicate-modal"
              style={{ maxWidth: "760px", width: "90%" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="duplicate-modal-header">
                <CheckCircle2 size={32} color="#26326e" />
                <h2>Mapping Preview</h2>
                <button className="duplicate-modal-close" onClick={() => setShowPreviewModal(false)}><X size={20} /></button>
              </div>

              <div className="duplicate-modal-body">

                {/* Strategy + anchor badges */}
                <div style={{ marginBottom: "16px" }}>
                  <span style={{
                    background: "#dbeafe", color: "#1e40af",
                    padding: "4px 12px", borderRadius: "20px",
                    fontWeight: "700", fontSize: "0.85rem",
                  }}>
                    {previewData.write_strategy?.replace(/_/g, " ").toUpperCase()}
                  </span>
                  {previewData.anchor_column && (
                    <span style={{
                      background: "#dcfce7", color: "#166534",
                      padding: "4px 12px", borderRadius: "20px",
                      fontWeight: "700", fontSize: "0.85rem", marginLeft: "8px",
                    }}>
                      Anchor: {previewData.anchor_column}
                    </span>
                  )}
                </div>

                {/* Reasoning */}
                {previewData.reasoning && (
                  <p style={{ color: "#6b7280", fontSize: "0.9rem", marginBottom: "16px", fontStyle: "italic" }}>
                    "{previewData.reasoning}"
                  </p>
                )}

                {/* Empty-target notice */}
                {previewData.is_empty_target && (
                  <div style={{
                    background: "#ecfeff",
                    border: "1px solid #a5f3fc",
                    borderRadius: "8px",
                    padding: "12px 14px",
                    marginBottom: "16px",
                    color: "#0e7490",
                    fontSize: "0.88rem",
                    lineHeight: 1.5,
                  }}>
                    <strong>Target sheet is empty.</strong> Your file&apos;s column
                    headers will be written into row&nbsp;1 of the target, and all
                    {" "}{previewData.rows_in_source || 0} source rows will be
                    appended as new data.
                  </div>
                )}

                {/* Stats row */}
                <div style={{ display: "flex", gap: "16px", marginBottom: "16px" }}>
                  <div style={{ background: "#f9fafb", padding: "12px", borderRadius: "8px", flex: 1, textAlign: "center" }}>
                    <div style={{ fontSize: "1.4rem", fontWeight: "800", color: "#26326e" }}>{previewData.rows_in_source || 0}</div>
                    <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Source rows</div>
                  </div>
                  <div style={{ background: "#f9fafb", padding: "12px", borderRadius: "8px", flex: 1, textAlign: "center" }}>
                    <div style={{ fontSize: "1.4rem", fontWeight: "800", color: "#26326e" }}>{previewData.rows_in_target || 0}</div>
                    <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Target rows</div>
                  </div>
                  <div style={{ background: "#f9fafb", padding: "12px", borderRadius: "8px", flex: 1, textAlign: "center" }}>
                    <div style={{ fontSize: "1.4rem", fontWeight: "800", color: "#26326e" }}>
                      {Object.values(previewData.column_mappings || {}).filter(Boolean).length}
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Columns mapped</div>
                  </div>
                </div>

                {/* Upsert split: update vs append counts */}
                {(previewData.rows_to_update?.length > 0 || previewData.rows_to_append?.length > 0) && (
                  <div style={{ display: "flex", gap: "12px", marginBottom: "16px" }}>
                    <div style={{ background: "#eff6ff", padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center", border: "1px solid #bfdbfe" }}>
                      <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#1e40af" }}>
                        {previewData.rows_to_update?.length || 0}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "#3b82f6", fontWeight: 600 }}>rows to update</div>
                    </div>
                    <div style={{ background: "#f0fdf4", padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center", border: "1px solid #bbf7d0" }}>
                      <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#166534" }}>
                        {previewData.rows_to_append?.length || 0}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "#16a34a", fontWeight: 600 }}>new rows to append</div>
                    </div>
                  </div>
                )}

                {/* Column mappings table */}
                <div style={{ maxHeight: "200px", overflowY: "auto", border: "1px solid #e5e7eb", borderRadius: "8px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                    <thead>
                      <tr style={{ background: "#f3f4f6" }}>
                        <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Source Column</th>
                        <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Target Column</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(previewData.column_mappings || {}).map(([src, tgt], i) => (
                        <tr key={i} style={{ borderTop: "1px solid #e5e7eb", background: tgt ? "white" : "#fef2f2" }}>
                          <td style={{ padding: "8px 12px", color: "#374151" }}>{src}</td>
                          <td style={{ padding: "8px 12px" }}>
                            {tgt ? (
                              <span style={{ color: "#166534", fontWeight: "600" }}>{tgt}</span>
                            ) : (
                              <span style={{ color: "#dc2626", fontSize: "0.8rem" }}>No match found</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Unmapped warning */}
                {previewData.unmapped_source?.length > 0 && (
                  <div style={{
                    marginTop: "12px", padding: "10px 14px",
                    background: "#fef3c7", borderRadius: "8px",
                    fontSize: "0.85rem", color: "#92400e",
                  }}>
                    ⚠️ {previewData.unmapped_source.length} column(s) could not be mapped and will be skipped.
                  </div>
                )}

                {/* Changes preview: current -> new diff for every cell that will change */}
                {(() => {
                  const conflicts = previewData.conflicts || [];
                  const emptyCells = previewData.empty_cells || [];
                  const appendedRows = previewData.appended_rows_preview || [];
                  const overwriteCount = conflicts.length;
                  const fillCount = emptyCells.length;
                  const newRowCount = appendedRows.length;
                  const appendedCellCount = appendedRows.reduce(
                    (sum, r) => sum + (r.cells?.length || 0), 0);

                  if (overwriteCount === 0 && fillCount === 0 && newRowCount === 0) {
                    return null;
                  }

                  const DIFF_CAP = 200;
                  const diffRows = [
                    ...conflicts.map((c) => ({
                      type: "overwrite",
                      anchor: c.anchor_value,
                      column: c.column,
                      current: c.existing_value,
                      next: c.new_value,
                    })),
                    ...emptyCells.map((c) => ({
                      type: "fill",
                      anchor: c.anchor_value,
                      column: c.column,
                      current: "",
                      next: c.new_value,
                    })),
                  ];
                  const diffsVisible = diffShowAll ? diffRows : diffRows.slice(0, DIFF_CAP);
                  const diffHidden = Math.max(0, diffRows.length - diffsVisible.length);

                  const formatValue = (v) => {
                    if (v === null || v === undefined || v === "") {
                      return <em style={{ color: "#9ca3af" }}>(empty)</em>;
                    }
                    const s = String(v);
                    return s.length > 60 ? s.slice(0, 57) + "..." : s;
                  };
                  const formatAnchor = (a) =>
                    typeof a === "string" && a.includes("|") ? a.replace(/\|/g, " + ") : a;

                  return (
                    <>
                      {/* Totals strip */}
                      <div style={{ display: "flex", gap: "12px", marginTop: "16px", marginBottom: "12px" }}>
                        <div style={{
                          background: "#fef2f2", border: "1px solid #fecaca",
                          padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center",
                        }}>
                          <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#991b1b" }}>
                            {overwriteCount}
                          </div>
                          <div style={{ fontSize: "0.78rem", color: "#b91c1c", fontWeight: 600 }}>
                            cells to overwrite
                          </div>
                        </div>
                        <div style={{
                          background: "#f0fdf4", border: "1px solid #bbf7d0",
                          padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center",
                        }}>
                          <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#166534" }}>
                            {fillCount}
                          </div>
                          <div style={{ fontSize: "0.78rem", color: "#16a34a", fontWeight: 600 }}>
                            cells to fill
                          </div>
                        </div>
                        <div style={{
                          background: "#fff7ed", border: "1px solid #fed7aa",
                          padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center",
                        }}>
                          <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#92400e" }}>
                            {newRowCount}
                          </div>
                          <div style={{ fontSize: "0.78rem", color: "#c2410c", fontWeight: 600 }}>
                            new rows to append
                          </div>
                        </div>
                      </div>

                      {/* Truncation banner from backend cap */}
                      {previewData.diff_truncated && (
                        <div style={{
                          marginBottom: "12px", padding: "10px 14px",
                          background: "#fef3c7", borderRadius: "8px",
                          fontSize: "0.85rem", color: "#92400e",
                        }}>
                          <strong>Preview truncated.</strong> Showing the first{" "}
                          {overwriteCount + fillCount + appendedCellCount} of{" "}
                          {previewData.diff_total_cells} cells.
                          The confirm action will still write every matched cell.
                        </div>
                      )}

                      {/* Changes preview table */}
                      {diffRows.length > 0 && (
                        <>
                          <div style={{
                            fontSize: "0.95rem", fontWeight: 700, color: "#26326e",
                            marginBottom: "8px",
                          }}>
                            Changes preview
                          </div>
                          <div style={{
                            maxHeight: "320px", overflowY: "auto",
                            border: "1px solid #e5e7eb", borderRadius: "8px",
                          }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                              <thead>
                                <tr style={{ background: "#f3f4f6", position: "sticky", top: 0 }}>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Row</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Column</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Current</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>New</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Type</th>
                                </tr>
                              </thead>
                              <tbody>
                                {diffsVisible.map((d, i) => {
                                  const isOverwrite = d.type === "overwrite";
                                  const rowBg = isOverwrite ? "#fef2f2" : "#f0fdf4";
                                  const leftBorder = isOverwrite ? "4px solid #ef4444" : "4px solid #22c55e";
                                  return (
                                    <tr key={i} style={{
                                      borderTop: "1px solid #e5e7eb",
                                      background: rowBg,
                                      borderLeft: leftBorder,
                                    }}>
                                      <td style={{ padding: "8px 12px", color: "#1f2937", fontWeight: 600 }}>
                                        {formatAnchor(d.anchor)}
                                      </td>
                                      <td style={{ padding: "8px 12px", color: "#4b5563" }} title={d.column}>
                                        {d.column}
                                      </td>
                                      <td style={{
                                        padding: "8px 12px", color: "#6b7280",
                                        fontFamily: "'Courier New', monospace",
                                      }} title={typeof d.current === "string" ? d.current : undefined}>
                                        {formatValue(d.current)}
                                      </td>
                                      <td style={{
                                        padding: "8px 12px", color: "#26326e", fontWeight: 700,
                                        fontFamily: "'Courier New', monospace",
                                      }} title={typeof d.next === "string" ? d.next : undefined}>
                                        {formatValue(d.next)}
                                      </td>
                                      <td style={{ padding: "8px 12px" }}>
                                        <span style={{
                                          background: isOverwrite ? "#fee2e2" : "#dcfce7",
                                          color: isOverwrite ? "#991b1b" : "#166534",
                                          padding: "4px 12px", borderRadius: "20px",
                                          fontWeight: 700, fontSize: "0.7rem",
                                          textTransform: "uppercase", letterSpacing: "0.5px",
                                          whiteSpace: "nowrap",
                                        }}>
                                          {isOverwrite ? "Overwrite" : "Fill"}
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                          {diffHidden > 0 && (
                            <button
                              type="button"
                              onClick={() => setDiffShowAll(true)}
                              style={{
                                marginTop: "8px", padding: "8px 16px",
                                background: "white", color: "#26326e",
                                border: "1px solid #d1d5db", borderRadius: "8px",
                                fontFamily: "Inter, sans-serif", fontWeight: 700,
                                fontSize: "0.85rem", cursor: "pointer",
                              }}
                            >
                              Show all {diffRows.length} changes ({diffHidden} more)
                            </button>
                          )}
                        </>
                      )}

                      {/* New rows to append panel */}
                      {appendedRows.length > 0 && (
                        <div style={{
                          marginTop: "16px",
                          border: "1px solid #e5e7eb", borderRadius: "8px",
                          overflow: "hidden",
                        }}>
                          <button
                            type="button"
                            onClick={() => setAppendedExpanded((v) => !v)}
                            style={{
                              width: "100%", textAlign: "left", cursor: "pointer",
                              padding: "12px 16px", border: "none",
                              background: "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)",
                              color: "#92400e", fontWeight: 700,
                              fontFamily: "Inter, sans-serif", fontSize: "0.95rem",
                              display: "flex", justifyContent: "space-between", alignItems: "center",
                            }}
                          >
                            <span>New rows to append ({appendedRows.length})</span>
                            <span style={{ fontSize: "0.85rem" }}>
                              {appendedExpanded ? "Hide" : "Show"}
                            </span>
                          </button>
                          {appendedExpanded && (
                            <div style={{
                              maxHeight: "320px", overflowY: "auto",
                              background: "white", padding: "12px 16px",
                            }}>
                              {appendedRows.map((row, i) => (
                                <div key={i} style={{
                                  marginBottom: i === appendedRows.length - 1 ? 0 : "12px",
                                  paddingBottom: i === appendedRows.length - 1 ? 0 : "12px",
                                  borderBottom: i === appendedRows.length - 1 ? "none" : "1px solid #e5e7eb",
                                }}>
                                  <div style={{
                                    fontSize: "0.85rem", fontWeight: 700, color: "#26326e",
                                    marginBottom: "6px",
                                  }}>
                                    {formatAnchor(row.anchor_value)}
                                  </div>
                                  <div style={{
                                    display: "grid",
                                    gridTemplateColumns: "minmax(160px, 1fr) 1fr",
                                    rowGap: "4px", columnGap: "12px",
                                    fontSize: "0.8rem",
                                  }}>
                                    {(row.cells || []).map((cell, j) => (
                                      <React.Fragment key={j}>
                                        <div style={{ color: "#6b7280" }} title={cell.column}>
                                          {cell.column}
                                        </div>
                                        <div style={{
                                          color: "#26326e", fontWeight: 600,
                                          fontFamily: "'Courier New', monospace",
                                        }} title={typeof cell.new_value === "string" ? cell.new_value : undefined}>
                                          {formatValue(cell.new_value)}
                                        </div>
                                      </React.Fragment>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  );
                })()}

              </div>

              <div className="duplicate-modal-actions">
                <button
                  className="duplicate-action-btn cancel"
                  onClick={() => setShowPreviewModal(false)}
                  disabled={isConfirming}
                >
                  <X size={18} /> Cancel
                </button>
                <button
                  className="duplicate-action-btn override"
                  onClick={handleConfirmMapping}
                  disabled={isConfirming}
                >
                  <CheckCircle2 size={18} />
                  {isConfirming ? "Writing..." : "Confirm & Write to Sheet"}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

export default DynamicMapping;