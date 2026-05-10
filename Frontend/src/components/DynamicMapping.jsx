import React, { useState, useRef, useEffect } from "react";
// File is aliased to FileIcon so the global Web API `File` constructor
// stays accessible inside this module. Without the alias, lucide-react's
// `File` icon component shadows the global, and `new File([bytes], ...)`
// in buildUploadableFile collapses to `new <ReactIcon>(...)` after
// minification — which throws "Tx is not a constructor" at runtime.
import { Upload, File as FileIcon, X, FileText, CheckCircle2, Search } from "lucide-react";
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

  // Per-row write selection. The user can deselect individual rows in the
  // preview diff and the appended-rows panel; only checked rows are sent
  // to run_dynamic_mapping. Stored as a Set of stable row IDs:
  //   - diff cells:    "diff|<type>|<anchor>|<column>"
  //   - appended rows: "append|<index>"
  // Default is "all selected" so the existing behavior is preserved when
  // the user just clicks Confirm without touching any boxes.
  const [selectedDiffIds, setSelectedDiffIds] = useState(() => new Set());
  const [selectedAppendIds, setSelectedAppendIds] = useState(() => new Set());

  // Section picker state (only used when the backend returns
  // requires_section_selection === true for a multi-section source file).
  const [showSectionPicker, setShowSectionPicker] = useState(false);
  const [sectionsToPick, setSectionsToPick] = useState([]);
  const [selectedSectionIndex, setSelectedSectionIndex] = useState(0);
  const [sectionSearch, setSectionSearch] = useState("");
  const [chosenSectionIndex, setChosenSectionIndex] = useState(null);

  // Sheet picker state (used when the backend returns
  // requires_sheet_selection === true for a multi-sheet source xlsx).
  // Mirrors the section picker exactly — user picks one sheet, we re-run
  // preview with sheet_name, then the confirm call echoes the same name.
  const [showSheetPicker, setShowSheetPicker] = useState(false);
  const [sheetsToPick, setSheetsToPick] = useState([]);
  const [selectedSheetIndex, setSelectedSheetIndex] = useState(0);
  const [sheetSearch, setSheetSearch] = useState("");
  const [chosenSourceSheetName, setChosenSourceSheetName] = useState(null);

  // Target-tab picker state (used when the backend returns
  // requires_target_tab_selection === true because 2+ tabs in the target
  // spreadsheet share rows with the source's anchor column). The picker
  // is gated server-side on ENABLE_TARGET_TAB_PICKER; when disabled, this
  // state never engages.
  const [showTargetTabPicker, setShowTargetTabPicker] = useState(false);
  const [targetTabsToPick, setTargetTabsToPick] = useState([]);
  const [selectedTargetTabIndex, setSelectedTargetTabIndex] = useState(0);
  const [targetTabSearch, setTargetTabSearch] = useState("");
  const [chosenTargetTab, setChosenTargetTab] = useState(null);
  const [targetTabAnchorCol, setTargetTabAnchorCol] = useState("");

  // Cross-sheet conflict resolution state (used when the backend's
  // multi_sheet_aggregate path returns requires_conflict_resolution).
  // For each conflicting identifier (e.g. "2025-03-01") the user picks
  // which source sheet should win, or "skip" to drop it entirely. The
  // resolved map is then echoed back to preview AND confirm so the
  // backend builds the same merged anchor map both times.
  const [showConflictModal, setShowConflictModal] = useState(false);
  // Tracks which card index is picked per anchor. The backend payload uses
  // `conflictChoices[anchor] = choice_id|sheet_name` for round-tripping the
  // user's pick, but the UI rendering uses INDEX-based selection so two
  // cards that happen to share the same backend value (e.g. both labeled
  // "Inbound Metrics" because they came from the same source tab and an
  // older backend payload omits choice_id) can each be picked
  // independently. Without this, clicking either of the two same-keyed
  // cards highlights BOTH (because `isPicked = choice === candKey` is
  // true for both) and the user can't distinguish them.
  const [conflictPickedCards, setConflictPickedCards] = useState({});
  const [conflictsToResolve, setConflictsToResolve] = useState([]);
  const [conflictChoices, setConflictChoices] = useState({});
  const [aggregatedSheets, setAggregatedSheets] = useState([]);
  // Differentiates the two conflict-modal shapes that share the same
  // payload envelope: 'multi_sheet_aggregate' / 'multi_section_aggregate'
  // (cross-source picks → echoed as conflict_choices) vs 'intra_section'
  // (single-section duplicate row picks → echoed as
  // intra_section_choices). The handler reads this on confirm to pick
  // the right field name when re-running preview / run.
  const [conflictKind, setConflictKind] = useState('multi_sheet_aggregate');
  // Resolved intra-section duplicate picks. Sticky for this session so
  // the run-confirm call after the preview replays the same filter the
  // user already approved without needing to re-prompt.
  const [intraSectionChoices, setIntraSectionChoices] = useState({});

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
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    // Defensive: the <input> has multiple={false} so the OS picker
    // shouldn't surface more than one file, but if a future regression
    // (or programmatic manipulation) ever populates more than one slot,
    // refuse the whole batch instead of silently dropping the extras.
    // The dynamic-mapping pipeline is single-workbook end-to-end and
    // there's no good way to disambiguate which file the user meant.
    if (fileList.length > 1) {
      Swal.fire({
        icon: "error",
        title: "One File at a Time",
        text: "Please select a single Excel workbook. The dynamic-mapping process runs on one source file per upload.",
        confirmButtonColor: "#26326e",
        customClass: { popup: "swal-inter-font" },
      });
      if (sourceFileInputRef.current) sourceFileInputRef.current.value = "";
      return;
    }
    const file = fileList[0];
    if (!file) return;

    // Extension-first validation. The MIME type alone is unreliable here:
    //   * Browsers on Windows often report .xlsx as application/zip
    //     (xlsx is a zip container) or application/octet-stream when
    //     the OS hasn't registered the Office MIME mapping.
    //   * Excel saves CSV-as-Excel and reports
    //     application/vnd.ms-excel for both .xls AND .csv on some
    //     platforms, which would let CSV slip past a pure-MIME gate.
    // So the gate is the file EXTENSION (matches the `accept` attribute
    // on the <input>), with a permissive MIME allowlist as a secondary
    // signal — never as the sole authority. PDF / CSV are deliberately
    // excluded because the dynamic-mapping pipeline expects an
    // Office-Open-XML workbook (or a legacy .xls binary), not a flat
    // text or document file.
    const allowedExtensions = ['.xlsx', '.xlsm', '.xls'];
    const fileName = (file.name || '').toLowerCase();
    const hasAllowedExtension = allowedExtensions.some(
      (ext) => fileName.endsWith(ext)
    );

    if (!hasAllowedExtension) {
      Swal.fire({
        icon: "error",
        title: "Invalid File Type",
        text: "Only Excel files (.xlsx, .xlsm, .xls) are accepted. PDF and CSV are not supported here — please export your data to an Excel workbook first.",
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

      // Read bytes ONCE here so subsequent Preview/Run requests don't
      // re-read from disk. Chrome flags re-uploads of the same File
      // handle with `net::ERR_UPLOAD_FILE_CHANGED` if the underlying
      // disk file is touched (Excel auto-save, antivirus scan, OS mtime
      // tick) between selection and upload. Buffering the ArrayBuffer
      // in JS state means every later upload constructs a fresh File
      // from in-memory bytes — the browser never re-checks the disk.
      const arrayBuffer = await file.arrayBuffer();

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
                bufferedBytes: arrayBuffer,
                mimeType: file.type,
                originalName: file.name,
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
          bufferedBytes: arrayBuffer,
          mimeType: file.type,
          originalName: file.name,
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
          bufferedBytes: arrayBuffer,
          mimeType: file.type,
          originalName: file.name,
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

  // Build a fresh File backed by buffered in-memory bytes so every
  // Preview/Run request carries an immutable, synchronous Blob to
  // FormData instead of a pointer to the on-disk File handle. Without
  // this, the second Preview after the user resolves a conflict modal
  // can fire `net::ERR_UPLOAD_FILE_CHANGED` because Chrome re-stat'd
  // the disk file between the two uploads. Falls back to the original
  // File object only if buffering somehow failed (older state).
  const buildUploadableFile = (uploadedFile) => {
    if (!uploadedFile) return null;
    if (uploadedFile.bufferedBytes) {
      const name = uploadedFile.originalName || uploadedFile.name;
      const mime = uploadedFile.mimeType
        || (uploadedFile.rawFile && uploadedFile.rawFile.type)
        || 'application/octet-stream';
      return new File([uploadedFile.bufferedBytes], name, { type: mime });
    }
    return uploadedFile.rawFile || null;
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
    setChosenSourceSheetName(null);
    setChosenTargetTab(null);
    await runPreview({ sectionIndex: null, sheetName: null, targetTab: null });
  };

  const handleConfirmTargetTab = async () => {
    if (targetTabsToPick.length === 0) return;
    const picked = targetTabsToPick[selectedTargetTabIndex];
    const name = picked && picked.name;
    if (!name) return;
    setChosenTargetTab(name);
    setShowTargetTabPicker(false);
    await runPreview({ targetTab: name });
  };

  // Submit the user's per-conflict picks back to preview. Every conflict
  // must have a choice (winner sheet name OR "skip"). The button in the
  // modal is disabled until that's true so this guard is defensive only.
  // Two payload shapes share this handler — cross-sheet conflicts (legacy
  // multi_sheet_aggregate, payload echoed back via conflictChoices) and
  // intra-section duplicates (new, payload echoed back via
  // intraSectionChoices). conflictKind tracks which is in flight so
  // runPreview routes the picks to the correct field.
  const handleConfirmConflicts = async () => {
    if (conflictsToResolve.length === 0) return;
    const allResolved = conflictsToResolve.every(
      (c) => conflictChoices[c.anchor_value] !== undefined
    );
    if (!allResolved) return;
    setShowConflictModal(false);
    if (conflictKind === 'intra_section') {
      // For intra-section dups, store the picks as intra_section_choices
      // and clear conflictChoices so subsequent preview re-runs in this
      // session don't accidentally inherit cross-section picks. The
      // current cross-tab aggregate flow uses conflictChoices and lives
      // on a different conflict_kind so the two never collide.
      //
      // Wire shape: when ANY conflict carries a source_sheet (the
      // multi-sheet column-merge path), we MUST send choices nested by
      // source_sheet so per-sheet picks don't bleed across sheets. The
      // backend's _apply_intra_section_choices applies a flat dict to
      // EVERY sheet, which means picking "Row 11 wins" for `2025-01-19`
      // in Operational Cost would also wrongly delete row 19 (idx
      // mismatch) from PROPER FUCKING TABLE. Nested form scopes the
      // pick to its sheet via {sheet_name: {anchor: choice}}.
      // Single-sheet flows (no source_sheet field) keep the legacy
      // flat shape so the single-sheet preview path stays unchanged.
      //
      // CRITICAL: MERGE the new picks INTO `intraSectionChoices`,
      // don't replace. When two source sheets each have intra-section
      // dupes, the user resolves Sheet A in modal 1, Sheet B in modal
      // 2. Modal 2's conflictsToResolve only carries Sheet B's
      // anchors, so a naive rebuild would clobber Sheet A's picks
      // — which made the backend re-detect Sheet A's dupes on the
      // next preview, surfacing modal 1 again, leading to an
      // infinite loop between sheets (CloudWatch evidence at
      // 2026-05-10T15:36-15:38 ping-ponged between PROPER TABLE and
      // Operational Cost across 5 previews).
      const anyHasSourceSheet = conflictsToResolve.some((c) => c.source_sheet);
      const baseIntra = intraSectionChoices || {};
      let nextIntra;
      if (anyHasSourceSheet) {
        nextIntra = {};
        // Carry forward every previously-resolved sheet so its picks
        // don't get re-detected on the next preview.
        if (baseIntra && typeof baseIntra === 'object') {
          for (const [sheet, picks] of Object.entries(baseIntra)) {
            if (picks && typeof picks === 'object' && !Array.isArray(picks)) {
              nextIntra[sheet] = { ...picks };
            }
          }
        }
        // Merge the modal's new picks on top.
        for (const c of conflictsToResolve) {
          const sheet = c.source_sheet || '';
          const choice = conflictChoices[c.anchor_value];
          if (choice === undefined) continue;
          if (!nextIntra[sheet]) nextIntra[sheet] = {};
          nextIntra[sheet][c.anchor_value] = choice;
        }
      } else {
        // Flat-form merge for single-sheet flows.
        nextIntra = { ...(baseIntra || {}), ...conflictChoices };
      }
      setIntraSectionChoices(nextIntra);
      setConflictChoices({});
      setConflictPickedCards({});
      await runPreview({ intraSectionChoices: nextIntra });
    } else {
      await runPreview({ conflictChoices });
    }
  };

  // Run (or re-run) the preview. Shared by the first attempt and the
  // section-picker resubmit flow. When the backend returns
  // requires_section_selection, we surface the card picker instead of the
  // diff modal and wait for the user to pick a section before resubmitting.
  const runPreview = async ({
    sectionIndex,
    sheetName,
    targetTab,
    conflictChoices: choicesArg,
    intraSectionChoices: intraChoicesArg,
  } = {}) => {
    const fileToProcess = uploadedFiles[0];
    if (!fileToProcess) return;

    setIsProcessing(true);
    startSmartProgress();

    // Prefer an explicit arg, fall back to whatever sheet the user picked
    // earlier in this session. chosenSourceSheetName persists across the
    // section picker re-run so the second preview hits the same sheet.
    const effectiveSheetName =
      sheetName !== undefined ? sheetName : chosenSourceSheetName;
    // Target-tab pick is sticky like the source-sheet pick: once the user
    // chooses a target tab from the multi-tab picker, every later preview
    // and the confirm call must hit the same tab.
    const effectiveTargetTab =
      targetTab !== undefined ? targetTab : chosenTargetTab;
    // Conflict choices are sticky too — once resolved they stay in scope
    // for any subsequent preview re-runs in this session (e.g. if the
    // user opens a new picker after resolving conflicts).
    const effectiveConflictChoices =
      choicesArg !== undefined ? choicesArg : conflictChoices;
    const effectiveIntraSectionChoices =
      intraChoicesArg !== undefined ? intraChoicesArg : intraSectionChoices;

    try {
      const preview = await previewDynamicMapping(
        buildUploadableFile(fileToProcess),
        targetFileUrl,
        {
          targetSheetName: effectiveTargetTab || selectedTab,
          sectionIndex,
          sheetName: effectiveSheetName || undefined,
          targetTabChosen: effectiveTargetTab || undefined,
          conflictChoices: (effectiveConflictChoices && Object.keys(effectiveConflictChoices).length > 0)
            ? effectiveConflictChoices
            : undefined,
          intraSectionChoices: (effectiveIntraSectionChoices
              && Object.keys(effectiveIntraSectionChoices).length > 0)
            ? effectiveIntraSectionChoices
            : undefined,
        },
      );

      if (preview && preview.requires_conflict_resolution) {
        // Two flavors share the same modal:
        //   - 'intra_section' (single-section duplicate row picks). Echo
        //     back to backend as intra_section_choices so the cached
        //     confirm filters source rows correctly.
        //   - everything else (cross-tab / cross-section aggregate).
        //     Echo back as conflict_choices to drive the merged anchor
        //     map on the second preview pass.
        finishSmartProgress({ success: false });
        setConflictsToResolve(preview.conflicts_to_resolve || []);
        setAggregatedSheets(preview.aggregated_sheets || []);
        setConflictKind(preview.conflict_kind || 'multi_sheet_aggregate');
        setConflictChoices({});
        setConflictPickedCards({});
        setShowConflictModal(true);
        return;
      }

      if (preview && preview.requires_sheet_selection) {
        finishSmartProgress({ success: false });
        setSheetsToPick(preview.sheets || []);
        setSelectedSheetIndex(0);
        setSheetSearch("");
        setShowSheetPicker(true);
        return;
      }

      if (preview && preview.requires_section_selection) {
        finishSmartProgress({ success: false });
        // Remember any sheet the backend auto-picked so the subsequent
        // section-pick preview and the final confirm call read from the
        // same sheet rather than silently defaulting to sheet 0.
        if (preview.auto_selected_sheet || preview.sheet_name) {
          setChosenSourceSheetName(preview.auto_selected_sheet || preview.sheet_name);
        }
        setSectionsToPick(preview.sections || []);
        setSelectedSectionIndex(0);
        setSectionSearch("");
        setShowSectionPicker(true);
        return;
      }

      if (preview && preview.requires_target_tab_selection) {
        finishSmartProgress({ success: false });
        const tabs = preview.target_tabs || [];
        setTargetTabsToPick(tabs);
        // Pre-select whichever tab is the user's current choice (or the
        // first one with the highest overlap when none is flagged).
        const currentIdx = tabs.findIndex((t) => t.is_current_choice);
        setSelectedTargetTabIndex(currentIdx >= 0 ? currentIdx : 0);
        setTargetTabAnchorCol(preview.anchor_column || "");
        setTargetTabSearch("");
        setShowTargetTabPicker(true);
        return;
      }

      // Capture the sheet the backend actually used so confirm echoes it.
      if (preview && (preview.auto_selected_sheet || preview.sheet_name)) {
        setChosenSourceSheetName(preview.auto_selected_sheet || preview.sheet_name);
      }

      finishSmartProgress({ success: true });
      setPreviewData(preview);
      setDiffShowAll(false);
      setAppendedExpanded(false);
      // Default-select every row in the new preview so the existing "click
      // Confirm and write everything" UX is unchanged. The user only needs
      // to touch the checkboxes when they want to skip rows. No-op cells
      // (source value already matches target) are also pre-checked because
      // the writer treats them as legitimate writes (they'll just be
      // no-op API calls); the user can uncheck them if they want to skip
      // the redundant writes for performance.
      const conflicts   = preview.conflicts || [];
      const emptyCells  = preview.empty_cells || [];
      const noOpCells   = preview.no_op_cells || [];
      const appendedRow = preview.appended_rows_preview || [];
      setSelectedDiffIds(new Set([
        ...conflicts.map((c)  => `diff|overwrite|${c.anchor_value}|${c.column}`),
        ...emptyCells.map((c) => `diff|fill|${c.anchor_value}|${c.column}`),
        ...noOpCells.map((c)  => `diff|noop|${c.anchor_value}|${c.column}`),
      ]));
      setSelectedAppendIds(new Set(
        appendedRow.map((_, i) => `append|${i}`)
      ));
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

  const handleConfirmSheet = async () => {
    if (sheetsToPick.length === 0) return;
    const picked = sheetsToPick[selectedSheetIndex];
    const name = picked && picked.name;
    if (!name) return;
    setChosenSourceSheetName(name);
    setShowSheetPicker(false);
    // Re-run preview with the explicit sheet_name. Section detection will
    // now operate on the correct sheet, so the section picker may still
    // appear next if that sheet has multiple stacked sections.
    await runPreview({ sheetName: name });
  };

  const handleConfirmMapping = async () => {
    if (!previewData) return;

    // Build the per-row write filter from the user's checkbox state. Only
    // emitted for strategies whose run-path ACTUALLY honors writeOnly.
    // Other strategies that emit row-based diff data still get a checkbox
    // UI (so the user can preview what would be written) but the backend
    // ignores the filter — sending it anyway is harmless because each
    // run path explicitly opts in. Set MUST stay in sync with the
    // diff-rendering set below; only add a strategy here once you've
    // verified its `_run_*` function reads `inputs['write_only']`.
    //
    // Confirmed honored at:
    //   - run_dynamic_mapping:735 (row_per_date, row_per_entity,
    //     composite_key, append)
    //   - _run_multi_sheet_aggregate:6103 (multi_sheet_aggregate,
    //     multi_section_aggregate)
    //   - _run_multi_sheet_column_merge (multi_sheet_column_merge)
    //   - _run_cross_tab_section_aggregate:7268
    //     (cross_tab_section_aggregate, with section-aware cell-level
    //     filtering)
    // Not honored (yet): multi_sheet_section, multi_section.
    const rowBased = [
      "row_per_date", "row_per_entity", "composite_key", "append",
      "cross_tab_section_aggregate",
      "multi_sheet_aggregate", "multi_section_aggregate",
      "multi_sheet_column_merge",
    ].includes(previewData.write_strategy);
    let writeOnly = null;
    if (rowBased) {
      const conflicts   = previewData.conflicts || [];
      const emptyCells  = previewData.empty_cells || [];
      // No-op cells are written to the sheet (the agent passes them
      // through to update_rows_by_date / update_rows_by_anchor as normal
      // values) so they belong in the writeOnly allow-list when checked
      // and must be omitted when unchecked. Otherwise unchecking a no-op
      // would have no effect.
      const noOpCells   = previewData.no_op_cells || [];
      const appendedRow = previewData.appended_rows_preview || [];
      const totalDiff   = conflicts.length + emptyCells.length + noOpCells.length;
      const totalAppend = appendedRow.length;
      const allDiff     = totalDiff > 0
        && conflicts.every((c)  => selectedDiffIds.has(`diff|overwrite|${c.anchor_value}|${c.column}`))
        && emptyCells.every((c) => selectedDiffIds.has(`diff|fill|${c.anchor_value}|${c.column}`))
        && noOpCells.every((c)  => selectedDiffIds.has(`diff|noop|${c.anchor_value}|${c.column}`));
      const allAppend   = totalAppend > 0
        && appendedRow.every((_, i) => selectedAppendIds.has(`append|${i}`));
      writeOnly = (allDiff || totalDiff === 0) && (allAppend || totalAppend === 0)
        ? null
        : {
            // `target_section_title` is included for cross_tab_section_aggregate
            // so the backend's allow-set can distinguish two cells that share
            // (anchor, column) but live in different target sections (e.g.
            // both Inbound and Outbound have a "2025-03-01" / "Trucks" cell).
            // Legacy row-based strategies emit it as undefined; the backend's
            // legacy filter ignores it and matches anchor-only as before.
            allowed_diff_cells: [
              ...conflicts
                .filter((c) => selectedDiffIds.has(`diff|overwrite|${c.anchor_value}|${c.column}`))
                .map((c) => ({
                  kind: "overwrite",
                  anchor: c.anchor_value,
                  column: c.column,
                  target_section_title: c.target_section_title,
                })),
              ...emptyCells
                .filter((c) => selectedDiffIds.has(`diff|fill|${c.anchor_value}|${c.column}`))
                .map((c) => ({
                  kind: "fill",
                  anchor: c.anchor_value,
                  column: c.column,
                  target_section_title: c.target_section_title,
                })),
              ...noOpCells
                .filter((c) => selectedDiffIds.has(`diff|noop|${c.anchor_value}|${c.column}`))
                .map((c) => ({
                  kind: "noop",
                  anchor: c.anchor_value,
                  column: c.column,
                  target_section_title: c.target_section_title,
                })),
            ],
            allowed_append_anchors: appendedRow
              .map((row, i) => (selectedAppendIds.has(`append|${i}`) ? row.anchor_value : null))
              .filter((v) => v !== null && v !== undefined),
          };

      if (writeOnly
          && writeOnly.allowed_diff_cells.length === 0
          && writeOnly.allowed_append_anchors.length === 0) {
        // Pure deselect-all is almost certainly an accident; loud-fail in
        // the UI instead of silently no-op-ing on the backend.
        Swal.fire({
          icon: "info",
          title: "Nothing to write",
          text: "All rows are deselected. Pick at least one row before confirming.",
          confirmButtonColor: "#26326e",
          customClass: { popup: "swal-inter-font" },
        });
        return;
      }
    }

    setIsConfirming(true);

    try {
      const fileToProcess = uploadedFiles[0];

      const result = await runDynamicMapping(
        buildUploadableFile(fileToProcess),
        targetFileUrl,
        {
          // Honor the multi-tab picker's choice — when the user picked a
          // different target tab in Step 0c we must write to that tab,
          // not to whatever was selected in the dropdown originally.
          targetSheetName: chosenTargetTab || selectedTab,
          previewCache: previewData,
          sectionIndex: chosenSectionIndex,
          // Echo the source sheet used at preview time so the write targets
          // the same sheet (esp. for multi-sheet xlsx like TC-E02 where the
          // default sheet-0 fallback would hit the wrong tab).
          sheetName:
            chosenSourceSheetName ||
            previewData.sheet_name ||
            previewData.auto_selected_sheet ||
            undefined,
          targetTabChosen: chosenTargetTab || undefined,
          // Multi-sheet aggregate: forward the resolved conflict picks
          // so the backend can replay the merge identically when writing.
          // Omitted entirely on non-aggregate flows (object is empty).
          conflictChoices: (conflictChoices && Object.keys(conflictChoices).length > 0)
            ? conflictChoices
            : undefined,
          // Same-section duplicate row picks. Sticky for this session so
          // the cached confirm filters source rows identically to how
          // preview built the diff the user just approved. Omitted on
          // flows that never hit the intra-section modal.
          intraSectionChoices: (intraSectionChoices && Object.keys(intraSectionChoices).length > 0)
            ? intraSectionChoices
            : undefined,
          writeOnly,
        },
      );

      setShowPreviewModal(false);

      if (result.success) {
        const wr = result.write_result || {};
        const appendMode = result.append_mode || wr.append_mode;
        const overflowReason = result.overflow_reason || wr.overflow_reason;
        const fellBackToSheetBottom =
          appendMode === "sheet-bottom" && (wr.rows_appended ?? 0) > 0;

        const lines = [
          `<strong>Strategy:</strong> ${result.write_strategy?.replace(/_/g, " ")}`,
          `<strong>Rows updated:</strong> ${wr.rows_updated ?? 0}`,
          `<strong>Rows appended:</strong> ${wr.rows_appended ?? 0}`,
        ];
        if (wr.cells_updated) lines.push(`<strong>Cells updated:</strong> ${wr.cells_updated}`);
        // Surface what the writeOnly filter dropped so the user can confirm
        // their unchecks were honored. Only present when the FE actually
        // sent a writeOnly payload (cross_tab_section_aggregate or row-based).
        if (wr.cells_skipped_unselected) {
          lines.push(
            `<strong>Cells skipped (unchecked):</strong> ${wr.cells_skipped_unselected}`,
          );
        }
        if (wr.rows_skipped_unselected) {
          lines.push(
            `<strong>Rows skipped (fully unchecked):</strong> ${wr.rows_skipped_unselected}`,
          );
        }
        if (wr.section) lines.push(`<strong>Section:</strong> ${wr.section}`);
        if (appendMode) lines.push(`<strong>Append mode:</strong> ${appendMode}`);
        if (result.anchor_column) lines.push(`<strong>Anchor column:</strong> ${Array.isArray(result.anchor_column) ? result.anchor_column.join(", ") : result.anchor_column}`);
        if (fellBackToSheetBottom) {
          lines.push(
            `<br><em>Note: new rows were appended at the bottom of the sheet because ` +
              `they did not fit inside the target section` +
              (overflowReason ? ` (${overflowReason})` : "") +
              `. Review the sheet to confirm placement.</em>`,
          );
        }
        Swal.fire({
          icon: fellBackToSheetBottom ? "warning" : "success",
          title: fellBackToSheetBottom ? "Done (with fallback)" : "Done!",
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
                  // Explicitly single-file. The dynamic-mapping Lambda
                  // is invoked once per source file (`file_content` is
                  // a single workbook), so a multi-pick would either
                  // silently drop the extras or fan out into N
                  // independent runs — both surprising. Keeping
                  // `multiple={false}` here (the HTML default, but
                  // documented for posterity) means the OS picker
                  // won't even let the user select more than one.
                  multiple={false}
                  accept=".xlsx,.xlsm,.xls"
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
                    <FileIcon size={48} className="kb-empty-icon" />
                    <p>No files uploaded yet</p>
                    <span className="kb-file-formats">XLSX, XLSM, or XLS</span>
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
            // Overlay click intentionally does NOT dismiss — the user
            // would lose their picker selection and have to re-run
            // preview to get this modal back. Use X / Cancel / Escape.
            <div
              className="duplicate-modal-overlay"
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
                              {section.preview_rows.map((row, ri) => {
                                const lastNonEmpty = row.reduce(
                                  (acc, c, idx) => (c !== "" && c != null ? idx : acc),
                                  -1
                                );
                                const trimmed = row.slice(0, lastNonEmpty + 1);
                                return (
                                  <div key={ri} style={{ whiteSpace: "nowrap" }}>
                                    {trimmed.length === 0 ? (
                                      <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty row)</span>
                                    ) : (
                                      trimmed.map((c, ci) => (
                                        <span key={ci} style={{ marginRight: "12px" }}>
                                          {c !== "" && c != null ? c : <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty)</span>}
                                        </span>
                                      ))
                                    )}
                                  </div>
                                );
                              })}
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

        {/* Sheet Picker Modal (multi-sheet source xlsx files) */}
        {showSheetPicker && sheetsToPick.length >= 2 && (() => {
          const filtered = sheetsToPick
            .map((s, i) => ({ ...s, originalIndex: i }))
            .filter((s) => {
              if (!sheetSearch.trim()) return true;
              const q = sheetSearch.trim().toLowerCase();
              return (
                (s.name || "").toLowerCase().includes(q) ||
                (s.headers || []).some((h) => String(h).toLowerCase().includes(q))
              );
            });
          const showSearch = sheetsToPick.length >= 5;
          return (
            // Overlay click intentionally does NOT dismiss — the user
            // would lose their picker selection and have to re-run
            // preview to get this modal back. Use X / Cancel / Escape.
            <div
              className="duplicate-modal-overlay"
              onKeyDown={(e) => {
                const currentFilteredIdx = filtered.findIndex((s) => s.originalIndex === selectedSheetIndex);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  const next = filtered[(currentFilteredIdx + 1) % filtered.length];
                  if (next) setSelectedSheetIndex(next.originalIndex);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  const prev = filtered[(currentFilteredIdx - 1 + filtered.length) % filtered.length];
                  if (prev) setSelectedSheetIndex(prev.originalIndex);
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  handleConfirmSheet();
                } else if (e.key === "Escape") {
                  setShowSheetPicker(false);
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
                  <h2>Multiple Sheets Detected</h2>
                  <button className="duplicate-modal-close" onClick={() => setShowSheetPicker(false)}><X size={20} /></button>
                </div>

                <div className="duplicate-modal-body">
                  <p style={{ color: "#374151", fontSize: "0.95rem", marginBottom: "12px" }}>
                    Your file contains <strong>{sheetsToPick.length} sheets</strong> and no single one clearly matches the target's columns. Pick the sheet that holds the data you want to map.
                  </p>

                  {showSearch && (
                    <input
                      type="text"
                      placeholder="Search by sheet name or column..."
                      value={sheetSearch}
                      onChange={(e) => setSheetSearch(e.target.value)}
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
                        No sheets match your search.
                      </div>
                    )}
                    {filtered.map((sheet) => {
                      const isSelected = sheet.originalIndex === selectedSheetIndex;
                      return (
                        <div
                          key={sheet.originalIndex}
                          onClick={() => setSelectedSheetIndex(sheet.originalIndex)}
                          onDoubleClick={handleConfirmSheet}
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
                              {sheet.name || `Sheet ${sheet.originalIndex + 1}`}
                            </div>
                            <span style={{
                              background: "#dcfce7", color: "#166534",
                              padding: "3px 10px", borderRadius: "12px",
                              fontSize: "0.75rem", fontWeight: 700,
                            }}>
                              {sheet.data_rows} {sheet.data_rows === 1 ? "row" : "rows"}
                            </span>
                          </div>

                          {typeof sheet.score === "number" && sheet.score > 0 && (
                            <div style={{ fontSize: "0.78rem", color: "#166534", marginBottom: "6px" }}>
                              {sheet.score} column{sheet.score === 1 ? "" : "s"} match the target
                            </div>
                          )}

                          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "10px" }}>
                            {(sheet.headers || []).filter(Boolean).map((h, hi) => (
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

                          {Array.isArray(sheet.preview_rows) && sheet.preview_rows.length > 0 && (
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
                              {sheet.preview_rows.map((row, ri) => {
                                const lastNonEmpty = row.reduce(
                                  (acc, c, idx) => (c !== "" && c != null ? idx : acc),
                                  -1
                                );
                                const trimmed = row.slice(0, lastNonEmpty + 1);
                                return (
                                  <div key={ri} style={{ whiteSpace: "nowrap" }}>
                                    {trimmed.length === 0 ? (
                                      <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty row)</span>
                                    ) : (
                                      trimmed.map((c, ci) => (
                                        <span key={ci} style={{ marginRight: "12px" }}>
                                          {c !== "" && c != null ? c : <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty)</span>}
                                        </span>
                                      ))
                                    )}
                                  </div>
                                );
                              })}
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
                  <button className="duplicate-action-btn cancel" onClick={() => setShowSheetPicker(false)}>
                    <X size={18} /> Cancel
                  </button>
                  <button
                    className="duplicate-action-btn compare"
                    onClick={handleConfirmSheet}
                    disabled={filtered.length === 0}
                    style={{ opacity: filtered.length === 0 ? 0.5 : 1 }}
                  >
                    <CheckCircle2 size={18} /> Use this sheet
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Target-Tab Picker Modal (anchor-overlap detected across multiple
            target tabs). Mirrors the source-section picker — each card shows
            the tab name, the "N matching rows" badge against the source
            anchor column, and a sample of the overlapping anchor values so
            the user can identify the right tab at a glance. */}
        {showTargetTabPicker && targetTabsToPick.length >= 2 && (() => {
          const filtered = targetTabsToPick
            .map((t, i) => ({ ...t, originalIndex: i }))
            .filter((t) => {
              if (!targetTabSearch.trim()) return true;
              const q = targetTabSearch.trim().toLowerCase();
              return (t.name || "").toLowerCase().includes(q);
            });
          const showSearch = targetTabsToPick.length >= 5;
          return (
            // Overlay click intentionally does NOT dismiss — the user
            // would lose their picker selection and have to re-run
            // preview to get this modal back. Use X / Cancel / Escape.
            <div
              className="duplicate-modal-overlay"
              onKeyDown={(e) => {
                const currentFilteredIdx = filtered.findIndex((t) => t.originalIndex === selectedTargetTabIndex);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  const next = filtered[(currentFilteredIdx + 1) % filtered.length];
                  if (next) setSelectedTargetTabIndex(next.originalIndex);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  const prev = filtered[(currentFilteredIdx - 1 + filtered.length) % filtered.length];
                  if (prev) setSelectedTargetTabIndex(prev.originalIndex);
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  handleConfirmTargetTab();
                } else if (e.key === "Escape") {
                  setShowTargetTabPicker(false);
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
                  <h2>Multiple Target Tabs Match</h2>
                  <button className="duplicate-modal-close" onClick={() => setShowTargetTabPicker(false)}><X size={20} /></button>
                </div>

                <div className="duplicate-modal-body">
                  <p style={{ color: "#374151", fontSize: "0.95rem", marginBottom: "12px" }}>
                    Found <strong>{targetTabsToPick.length} target tabs</strong> with rows that match
                    your source's <strong>{targetTabAnchorCol || "anchor"}</strong> values. Pick which tab to write to.
                  </p>

                  {showSearch && (
                    <input
                      type="text"
                      placeholder="Search tabs..."
                      value={targetTabSearch}
                      onChange={(e) => setTargetTabSearch(e.target.value)}
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
                        No tabs match your search.
                      </div>
                    )}
                    {filtered.map((tab) => {
                      const isSelected = tab.originalIndex === selectedTargetTabIndex;
                      const samples = (tab.sample_overlap_values || []).slice(0, 5);
                      return (
                        <div
                          key={tab.originalIndex}
                          onClick={() => setSelectedTargetTabIndex(tab.originalIndex)}
                          onDoubleClick={handleConfirmTargetTab}
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
                              {tab.name}
                              {tab.is_current_choice && (
                                <span style={{
                                  marginLeft: "8px",
                                  background: "#dbeafe", color: "#1e40af",
                                  padding: "2px 8px", borderRadius: "10px",
                                  fontSize: "0.7rem", fontWeight: 700,
                                }}>
                                  current
                                </span>
                              )}
                            </div>
                            <span style={{
                              background: "#fde68a", color: "#92400e",
                              padding: "3px 10px", borderRadius: "12px",
                              fontSize: "0.75rem", fontWeight: 700,
                            }}>
                              {tab.overlap_count} matching {tab.overlap_count === 1 ? "row" : "rows"}
                            </span>
                          </div>

                          {samples.length > 0 && (
                            <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>
                              Sample overlap values:&nbsp;
                              {samples.map((v, vi) => (
                                <span key={vi} style={{
                                  background: "#dcfce7", color: "#166534",
                                  padding: "2px 8px", borderRadius: "10px",
                                  fontSize: "0.75rem", fontWeight: 600,
                                  marginRight: "6px",
                                }}>
                                  {v}
                                </span>
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
                  <button className="duplicate-action-btn cancel" onClick={() => setShowTargetTabPicker(false)}>
                    <X size={18} /> Cancel
                  </button>
                  <button
                    className="duplicate-action-btn compare"
                    onClick={handleConfirmTargetTab}
                    disabled={filtered.length === 0}
                    style={{ opacity: filtered.length === 0 ? 0.5 : 1 }}
                  >
                    <CheckCircle2 size={18} /> Use this tab
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Conflict Resolution Modal (multi-sheet aggregate path).
            Fires when 2+ source sheets contain rows with the same
            identifier value (e.g. 2025-03-01 in both march_data and
            april_data). For each conflict the user picks a winning sheet
            or skips the identifier entirely. The resolved choices are
            echoed back through preview AND confirm so the backend builds
            the same merged anchor map both times. */}
        {showConflictModal && conflictsToResolve.length > 0 && (() => {
          const totalChoices = Object.keys(conflictChoices).length;
          const allResolved = totalChoices === conflictsToResolve.length;
          // Modal adapts to two shapes:
          //   - cross-tab/cross-section aggregate: candidates carry
          //     sheet_name; copy reads "multiple sheets".
          //   - intra_section single-section dups: candidates carry
          //     choice_id ("row_<N>") + label ("Row N"); copy reads
          //     "multiple rows in section X".
          const isIntraSection = conflictKind === 'intra_section';
          const sheetCountLabel = isIntraSection ? "row" : "sheet";
          return (
            // Overlay click intentionally does NOT dismiss the modal — the
            // user has unsaved picks and accidentally clicking outside
            // would force them to re-run preview from scratch (the
            // modal-state isn't persisted server-side; it only lives in
            // this component's transient `conflictChoices` /
            // `conflictsToResolve` state). Use the X button or the
            // Cancel action to leave deliberately.
            <div className="duplicate-modal-overlay">
              <div
                className="duplicate-modal"
                style={{ maxWidth: "1100px", width: "92%" }}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="duplicate-modal-header">
                  <FileText size={32} color="#26326e" />
                  <h2>
                    {isIntraSection
                      ? "Resolve Duplicate Rows"
                      : "Resolve Cross-Sheet Conflicts"}
                  </h2>
                  <button className="duplicate-modal-close" onClick={() => setShowConflictModal(false)}><X size={20} /></button>
                </div>

                <div className="duplicate-modal-body">
                  {isIntraSection ? (
                    <p style={{ color: "#374151", fontSize: "0.95rem", marginBottom: "8px" }}>
                      Found <strong>{conflictsToResolve.length} identifier
                      {conflictsToResolve.length === 1 ? "" : "s"}</strong> appearing on
                      multiple rows{aggregatedSheets && aggregatedSheets.length > 0 ? (
                        <>{" "}within{" "}
                          <strong>{aggregatedSheets.join(", ")}</strong></>
                      ) : null}, with differing values in mapped columns. For each one
                      below, pick which row should win, or choose <em>Skip</em> to drop
                      the identifier entirely.
                    </p>
                  ) : (
                    <p style={{ color: "#374151", fontSize: "0.95rem", marginBottom: "8px" }}>
                      Found <strong>{conflictsToResolve.length} identifier
                      {conflictsToResolve.length === 1 ? "" : "s"}</strong> appearing in
                      multiple source sheets across{" "}
                      <strong>
                        {(aggregatedSheets || []).join(", ") || "your selected sheets"}
                      </strong>. For each one below, pick which sheet&apos;s row should
                      win, or choose <em>Skip</em> to drop it entirely.
                    </p>
                  )}
                  <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: "16px" }}>
                    {isIntraSection
                      ? "Non-conflicting rows are written automatically. Rows whose identifier doesn’t exist in the target tab will be listed in the next step but never written."
                      : "Non-conflicting rows from every sheet will be merged automatically. Rows whose identifier doesn't exist in the target tab will be listed in the next step but never written."}
                  </p>

                  <div style={{ marginBottom: "12px", fontSize: "0.85rem", color: allResolved ? "#166534" : "#92400e", fontWeight: 600 }}>
                    Resolved {totalChoices} of {conflictsToResolve.length}
                  </div>

                  <div style={{
                    maxHeight: "60vh", overflowY: "auto",
                    display: "flex", flexDirection: "column", gap: "16px",
                  }}>
                    {conflictsToResolve.map((conflict) => {
                      const choice = conflictChoices[conflict.anchor_value];
                      const candidateCount = (conflict.candidates || []).length;
                      // Compute the union of mapped target columns across
                      // all candidates so the side-by-side comparison
                      // tables share a column order. Preserves first-seen
                      // order for visual stability.
                      const colOrder = [];
                      const seen = new Set();
                      (conflict.candidates || []).forEach((cand) => {
                        Object.keys(cand.row_data || {}).forEach((col) => {
                          if (!seen.has(col)) {
                            seen.add(col);
                            colOrder.push(col);
                          }
                        });
                      });
                      return (
                        <div key={conflict.anchor_value} style={{
                          border: "1px solid #e5e7eb", borderRadius: "10px",
                          padding: "14px 16px", background: "#fafafa",
                        }}>
                          <div style={{
                            display: "flex", justifyContent: "space-between",
                            alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "8px",
                          }}>
                            <div style={{ fontWeight: 800, color: "#26326e", fontSize: "1rem" }}>
                              Identifier: <span style={{
                                fontFamily: "ui-monospace, Menlo, Consolas, monospace",
                                background: "#fef3c7", color: "#92400e",
                                padding: "2px 10px", borderRadius: "8px",
                                marginLeft: "6px",
                              }}>
                                {conflict.anchor_value}
                              </span>
                            </div>
                            <span style={{
                              background: "#fee2e2", color: "#991b1b",
                              padding: "3px 10px", borderRadius: "12px",
                              fontSize: "0.75rem", fontWeight: 700,
                            }}>
                              {candidateCount} {sheetCountLabel}{candidateCount === 1 ? "" : "s"} contain this
                            </span>
                          </div>

                          {/* Pre-compute candKey -> count map so the
                              "(card N of M)" disambiguator below knows
                              when to fire. Computed once per conflict
                              card group; small N so an extra walk is
                              fine. */}
                          {(() => {
                            const baseKeyCounts = {};
                            (conflict.candidates || []).forEach((c) => {
                              const k = c.choice_id || c.sheet_name;
                              baseKeyCounts[k] = (baseKeyCounts[k] || 0) + 1;
                            });
                            // Bound to a closure variable on the conflict
                            // object so the inner .map() can read it
                            // without recomputing per row. Mutation here
                            // is local to render — conflict objects are
                            // not part of any React state graph.
                            conflict.__baseKeyCounts = baseKeyCounts;
                            return null;
                          })()}
                          {/* Horizontal scroll wrapper. Modal is up to
                              1100px wide; candidate grid uses 220px min
                              per column. With 4+ candidates + Skip the
                              grid (5+ cols × 220px = 1100px+) overflows
                              the modal body, so the wrapper provides a
                              clean horizontal scrollbar instead of
                              page-level overflow. Common since the
                              column-merge planner removed its 25%
                              overlap cap (column_merge_unbounded). */}
                          <div style={{ overflowX: "auto", paddingBottom: "4px" }}>
                          <div style={{
                            display: "grid",
                            gridTemplateColumns: `repeat(${candidateCount + 1}, minmax(220px, 1fr))`,
                            gap: "10px",
                          }}>
                            {(conflict.candidates || []).map((cand, idx) => {
                              // Tolerant of three payload shapes:
                              //   - aggregate: cand.sheet_name is both the
                              //     display label and the picker key.
                              //   - intra_section: cand.choice_id is the
                              //     picker key (e.g. "row_2"), cand.label
                              //     is the display string (e.g. "Row 3").
                              //   - cross-tab: cand.choice_id is the
                              //     unique key (sheet||section||row_N),
                              //     cand.label is the long form
                              //     "Sheet > Section > Row N".
                              const candKey = cand.choice_id || cand.sheet_name;
                              // Disambiguator: if more than one card
                              // shares candKey (e.g. legacy backend
                              // without choice_id for intra-tab dups),
                              // suffix the label so the user can tell
                              // them apart visually. Selection state
                              // already tracks by index so the radio
                              // buttons work correctly even without this
                              // visual hint, but the hint helps the
                              // user know WHICH duplicate they're
                              // picking.
                              const collisionCount = conflict.__baseKeyCounts?.[candKey] || 1;
                              const baseLabel = cand.label || cand.sheet_name || candKey;
                              const candLabel = collisionCount > 1
                                ? `${baseLabel} (card ${idx + 1} of ${candidateCount})`
                                : baseLabel;
                              // Selection by INDEX, not by candKey, so two
                              // cards with the same candKey can each be
                              // picked independently. The backend payload
                              // (conflictChoices[anchor]) still uses
                              // candKey for round-trip compat.
                              const pickedIdx = conflictPickedCards[conflict.anchor_value];
                              const isPicked = pickedIdx === idx;
                              return (
                                <label
                                  key={`${idx}__${candKey}`}
                                  style={{
                                    cursor: "pointer",
                                    border: isPicked ? "2px solid #26326e" : "1px solid #e5e7eb",
                                    background: isPicked ? "#eef2ff" : "white",
                                    borderRadius: "8px",
                                    padding: "10px 12px",
                                    display: "flex", flexDirection: "column",
                                    gap: "8px",
                                    transition: "all 0.12s",
                                  }}
                                >
                                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                    <input
                                      type="radio"
                                      name={`conflict-${conflict.anchor_value}`}
                                      checked={isPicked}
                                      onChange={() => {
                                        // Atomic update of BOTH the index
                                        // (UI state) and the backend value
                                        // (conflictChoices) so they never
                                        // get out of sync between renders.
                                        setConflictPickedCards((prev) => ({
                                          ...prev, [conflict.anchor_value]: idx,
                                        }));
                                        setConflictChoices((prev) => ({
                                          ...prev, [conflict.anchor_value]: candKey,
                                        }));
                                      }}
                                      style={{ cursor: "pointer", width: "16px", height: "16px" }}
                                    />
                                    <strong style={{ color: "#26326e", fontSize: "0.95rem" }}>
                                      {candLabel}
                                    </strong>
                                  </div>
                                  <div style={{
                                    display: "grid",
                                    gridTemplateColumns: "minmax(120px, 1fr) 1fr",
                                    rowGap: "3px", columnGap: "10px",
                                    fontSize: "0.78rem",
                                    background: "#f9fafb",
                                    padding: "8px", borderRadius: "6px",
                                  }}>
                                    {colOrder.length === 0 && (
                                      <div style={{ gridColumn: "1 / span 2", color: "#9ca3af", fontStyle: "italic" }}>
                                        (no mapped columns)
                                      </div>
                                    )}
                                    {colOrder.map((col) => {
                                      const v = cand.row_data?.[col];
                                      return (
                                        <React.Fragment key={col}>
                                          <div style={{ color: "#6b7280" }} title={col}>{col}</div>
                                          <div style={{
                                            color: "#26326e", fontWeight: 600,
                                            fontFamily: "ui-monospace, Menlo, Consolas, monospace",
                                            wordBreak: "break-word",
                                          }}>
                                            {v === null || v === undefined || v === ""
                                              ? <em style={{ color: "#9ca3af" }}>(empty)</em>
                                              : String(v)}
                                          </div>
                                        </React.Fragment>
                                      );
                                    })}
                                  </div>
                                </label>
                              );
                            })}

                            {/* Skip option — drops this identifier from
                                the merged map entirely. The user sees it
                                listed in the Skipped panel of the
                                Mapping Preview modal so the drop is never
                                silent. Selection state mirrors the card
                                pattern: a sentinel "-1" picked-card index
                                represents Skip. */}
                            {(() => {
                              const pickedIdx = conflictPickedCards[conflict.anchor_value];
                              const isSkipped = pickedIdx === -1 || choice === "skip";
                              return (
                            <label
                              style={{
                                cursor: "pointer",
                                border: isSkipped ? "2px solid #6b7280" : "1px dashed #d1d5db",
                                background: isSkipped ? "#f3f4f6" : "white",
                                borderRadius: "8px",
                                padding: "10px 12px",
                                display: "flex", flexDirection: "column",
                                gap: "8px",
                                transition: "all 0.12s",
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <input
                                  type="radio"
                                  name={`conflict-${conflict.anchor_value}`}
                                  checked={isSkipped}
                                  onChange={() => {
                                    setConflictPickedCards((prev) => ({
                                      ...prev, [conflict.anchor_value]: -1,
                                    }));
                                    setConflictChoices((prev) => ({
                                      ...prev, [conflict.anchor_value]: "skip",
                                    }));
                                  }}
                                  style={{ cursor: "pointer", width: "16px", height: "16px" }}
                                />
                                <strong style={{ color: "#374151", fontSize: "0.95rem" }}>
                                  Skip this identifier
                                </strong>
                              </div>
                              <div style={{ fontSize: "0.78rem", color: "#6b7280", lineHeight: 1.4 }}>
                                Drop this row from the write entirely. It will appear in the
                                Skipped panel for review.
                              </div>
                            </label>
                              );
                            })()}
                          </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="duplicate-modal-actions">
                  <button className="duplicate-action-btn cancel" onClick={() => setShowConflictModal(false)}>
                    <X size={18} /> Cancel
                  </button>
                  <button
                    className="duplicate-action-btn override"
                    onClick={handleConfirmConflicts}
                    disabled={!allResolved}
                    style={{ opacity: allResolved ? 1 : 0.5 }}
                  >
                    <CheckCircle2 size={18} /> Continue to Review
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Preview Modal — overlay click intentionally does NOT dismiss.
            The preview holds expensive backend work (resolved conflicts,
            cached identifications, write_only checkbox state); a stray
            click outside used to throw all of that away and force the
            user to re-run preview from scratch. Use X or Cancel. */}
        {showPreviewModal && previewData && (
          <div className="duplicate-modal-overlay">
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
                <div style={{ marginBottom: "16px", display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
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
                      fontWeight: "700", fontSize: "0.85rem",
                    }}>
                      Anchor: {Array.isArray(previewData.anchor_column)
                        ? previewData.anchor_column.join(" + ")
                        : previewData.anchor_column}
                    </span>
                  )}
                  {/* Aggregate badge — shown when the multi-sheet
                      aggregate path was chosen, listing the source tabs
                      that were merged into this preview. */}
                  {previewData.aggregate_mode && (
                    <span
                      title={(previewData.aggregated_sheets || []).join(", ")}
                      style={{
                        background: "#ede9fe", color: "#5b21b6",
                        padding: "4px 12px", borderRadius: "20px",
                        fontWeight: "700", fontSize: "0.85rem",
                      }}
                    >
                      Aggregated {(previewData.aggregated_sheets || []).length} sheet
                      {(previewData.aggregated_sheets || []).length === 1 ? "" : "s"}
                      {(previewData.aggregated_sheets || []).length > 0 && (
                        <>: {(previewData.aggregated_sheets || []).join(", ")}</>
                      )}
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
                    {previewData.unmapped_source.length} column(s) could not be mapped and will be skipped.
                  </div>
                )}

                {/* Skipped (no match in target) panel — populated by the
                    multi-sheet aggregate path. Lists rows with a valid
                    identifier but no matching row in the target tab, plus
                    rows the user explicitly chose to skip in the conflict
                    modal. Read-only by design: aggregate mode is
                    update-only, so these rows never reach the write step. */}
                {Array.isArray(previewData.skipped_no_match) && previewData.skipped_no_match.length > 0 && (() => {
                  const groups = previewData.skipped_no_match.reduce((acc, r) => {
                    const key = r.reason === "user_skipped_conflict" ? "user_skipped" : "no_match";
                    (acc[key] = acc[key] || []).push(r);
                    return acc;
                  }, {});
                  const renderRow = (r, i, key) => {
                    const cells = Object.entries(r.row_data || {}).slice(0, 4);
                    return (
                      <tr key={`${key}-${i}`} style={{ borderTop: "1px solid #e5e7eb" }}>
                        <td style={{ padding: "6px 10px", color: "#6b7280", fontWeight: 600 }}>
                          {r.sheet_name}
                        </td>
                        <td style={{
                          padding: "6px 10px", color: "#26326e", fontWeight: 700,
                          fontFamily: "ui-monospace, Menlo, Consolas, monospace",
                        }}>
                          {r.anchor_value}
                        </td>
                        <td style={{ padding: "6px 10px", color: "#374151" }}>
                          {cells.length === 0 && (
                            <em style={{ color: "#9ca3af" }}>(no mapped columns)</em>
                          )}
                          {cells.map(([col, val], ci) => (
                            <span key={ci} style={{ marginRight: "10px" }}>
                              <span style={{ color: "#6b7280" }}>{col}:</span>{" "}
                              <span style={{ color: "#26326e", fontWeight: 600 }}>
                                {val === null || val === undefined || val === ""
                                  ? "(empty)" : String(val)}
                              </span>
                            </span>
                          ))}
                          {Object.keys(r.row_data || {}).length > cells.length && (
                            <span style={{ color: "#9ca3af", fontSize: "0.78rem" }}>
                              +{Object.keys(r.row_data).length - cells.length} more
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  };
                  return (
                    <div style={{
                      marginTop: "16px", border: "1px solid #fed7aa",
                      borderRadius: "10px", background: "#fff7ed",
                      padding: "12px 14px",
                    }}>
                      <div style={{
                        display: "flex", alignItems: "center", gap: "10px",
                        marginBottom: "8px", flexWrap: "wrap",
                      }}>
                        <strong style={{ color: "#9a3412", fontSize: "0.95rem" }}>
                          Skipped ({previewData.skipped_no_match.length})
                        </strong>
                        <span style={{ color: "#9a3412", fontSize: "0.82rem" }}>
                          These rows will NOT be written.
                        </span>
                      </div>

                      {(groups.no_match || []).length > 0 && (
                        <div style={{ marginBottom: groups.user_skipped?.length ? "10px" : 0 }}>
                          <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "#9a3412", marginBottom: "4px" }}>
                            No match in target ({(groups.no_match || []).length})
                          </div>
                          <div style={{ maxHeight: "180px", overflowY: "auto", border: "1px solid #fed7aa", borderRadius: "6px", background: "white" }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                              <thead>
                                <tr style={{ background: "#ffedd5" }}>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Source sheet</th>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Identifier</th>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Row preview</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(groups.no_match || []).map((r, i) => renderRow(r, i, "nm"))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {(groups.user_skipped || []).length > 0 && (
                        <div>
                          <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "#9a3412", marginBottom: "4px" }}>
                            Dropped via conflict resolution ({(groups.user_skipped || []).length})
                          </div>
                          <div style={{ maxHeight: "180px", overflowY: "auto", border: "1px solid #fed7aa", borderRadius: "6px", background: "white" }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                              <thead>
                                <tr style={{ background: "#ffedd5" }}>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Source sheet</th>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Identifier</th>
                                  <th style={{ padding: "6px 10px", textAlign: "left", fontWeight: 700, color: "#9a3412" }}>Row preview</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(groups.user_skipped || []).map((r, i) => renderRow(r, i, "us"))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Changes preview: current -> new diff for every cell that will change */}
                {(() => {
                  const conflicts = previewData.conflicts || [];
                  const emptyCells = previewData.empty_cells || [];
                  const appendedRows = previewData.appended_rows_preview || [];
                  // No-op cells = source value byte-equals target. Surfaced
                  // by _preview_cross_tab_section_aggregate so the user can
                  // SEE every cell the writer would touch (including
                  // unchanged ones) and uncheck any they don't want sent.
                  // Other strategies emit `[]` (or omit the field) so the
                  // defensive `|| []` keeps the table behavior identical
                  // for legacy paths until they grow no-op support too.
                  const noOpCells = previewData.no_op_cells || [];

                  if (
                    conflicts.length === 0 &&
                    emptyCells.length === 0 &&
                    appendedRows.length === 0 &&
                    noOpCells.length === 0
                  ) {
                    return null;
                  }

                  // Per-row checkbox selection: enabled for strategies
                  // whose run path actually honors `inputs['write_only']`.
                  // Showing a checkbox here without backend support would
                  // mislead the user into thinking their selection
                  // controls the write — see handleConfirmMapping above
                  // for the matching set + backend line citations.
                  // Strategies covered:
                  //   - row_per_date / row_per_entity / composite_key
                  //     (single-sheet anchor-based writes)
                  //   - append (new-row writes)
                  //   - cross_tab_section_aggregate (unified cross-tab ×
                  //     per-section path with cell-level filtering)
                  //   - multi_sheet_aggregate / multi_section_aggregate
                  //     (legacy aggregate path with anchor-level filtering)
                  // Strategies that DO render diff rows but DON'T support
                  // selection (yet): multi_sheet_section, multi_section.
                  // Pure matrix layouts (cross_tab, key_value, horizontal)
                  // never reach this branch — they emit no diff arrays
                  // so the early null-return guard short-circuits them.
                  const rowBasedStrategies = new Set([
                    "row_per_date", "row_per_entity", "composite_key", "append",
                    "cross_tab_section_aggregate",
                    "multi_sheet_aggregate", "multi_section_aggregate",
                    "multi_sheet_column_merge",
                  ]);
                  const allowSelection = rowBasedStrategies.has(previewData.write_strategy);

                  const DIFF_CAP = 200;
                  // ``source_sheet`` is only present on the multi-sheet
                  // aggregate path — single-sheet previews omit the field.
                  // When ANY diff row has it, we show the "Source" column
                  // so the user can tell which source sheet contributed
                  // each cell. This replaces the old "[sheet_name] anchor"
                  // prefix hack which broke the writeOnly filter.
                  // (noOpCells already declared above next to the other
                  // diff arrays — reused here as a row class so the user
                  // can SEE every cell the writer would touch including
                  // unchanged ones, and uncheck any they don't want sent.)
                  const diffRows = [
                    ...conflicts.map((c) => ({
                      id: `diff|overwrite|${c.anchor_value}|${c.column}`,
                      type: "overwrite",
                      anchor: c.anchor_value,
                      column: c.column,
                      current: c.existing_value,
                      next: c.new_value,
                      sourceSheet: c.source_sheet,
                      // `source_section` is populated only by the cross-tab
                      // × per-section preview path. When the section title
                      // differs from the sheet name (i.e. the source sheet
                      // contains MULTIPLE sections, one of which is the
                      // donor for this row), the badge renders as
                      // "Sheet > Section" so the user can disambiguate
                      // between e.g. "Outbound Metrics tab > Outbound
                      // top-section" and "Outbound Metrics tab > Inbound
                      // Metrics inner-section". For legacy multi-sheet
                      // aggregate (one section per sheet) it stays absent
                      // so the badge keeps the existing one-line shape.
                      sourceSection: c.source_section,
                      targetSectionTitle: c.target_section_title,
                    })),
                    ...emptyCells.map((c) => ({
                      id: `diff|fill|${c.anchor_value}|${c.column}`,
                      type: "fill",
                      anchor: c.anchor_value,
                      column: c.column,
                      current: "",
                      next: c.new_value,
                      sourceSheet: c.source_sheet,
                      sourceSection: c.source_section,
                      targetSectionTitle: c.target_section_title,
                    })),
                    ...noOpCells.map((c) => ({
                      id: `diff|noop|${c.anchor_value}|${c.column}`,
                      type: "noop",
                      anchor: c.anchor_value,
                      column: c.column,
                      current: c.existing_value,
                      next: c.new_value,
                      sourceSheet: c.source_sheet,
                      sourceSection: c.source_section,
                      targetSectionTitle: c.target_section_title,
                    })),
                  ];
                  const showSourceCol = diffRows.some((d) => !!d.sourceSheet);
                  const appendedItems = appendedRows.map((r, i) => ({
                    ...r,
                    id: `append|${i}`,
                    index: i,
                  }));
                  // Selection-aware counts for the totals strip + confirm
                  // button. When ``allowSelection`` is false (cross_tab et al.)
                  // we report the raw totals so the legacy "everything will
                  // be written" copy still matches what the backend does.
                  const selectedOverwriteCount = allowSelection
                    ? diffRows.filter((d) => d.type === "overwrite" && selectedDiffIds.has(d.id)).length
                    : diffRows.filter((d) => d.type === "overwrite").length;
                  const selectedFillCount = allowSelection
                    ? diffRows.filter((d) => d.type === "fill" && selectedDiffIds.has(d.id)).length
                    : diffRows.filter((d) => d.type === "fill").length;
                  const selectedNoopCount = allowSelection
                    ? diffRows.filter((d) => d.type === "noop" && selectedDiffIds.has(d.id)).length
                    : diffRows.filter((d) => d.type === "noop").length;
                  const selectedAppendCount = allowSelection
                    ? appendedItems.filter((r) => selectedAppendIds.has(r.id)).length
                    : appendedItems.length;
                  const selectedAppendedCellCount = allowSelection
                    ? appendedItems.filter((r) => selectedAppendIds.has(r.id))
                        .reduce((sum, r) => sum + (r.cells?.length || 0), 0)
                    : appendedItems.reduce((sum, r) => sum + (r.cells?.length || 0), 0);
                  const overwriteCount = selectedOverwriteCount;
                  const fillCount = selectedFillCount;
                  const noopCount = selectedNoopCount;
                  const newRowCount = selectedAppendCount;
                  const appendedCellCount = selectedAppendedCellCount;

                  // Three-state checkbox helper for "select all" headers.
                  const setIndeterminate = (ref, isInd) => {
                    if (ref) ref.indeterminate = isInd;
                  };
                  const allDiffSelected =
                    diffRows.length > 0 && diffRows.every((d) => selectedDiffIds.has(d.id));
                  const noDiffSelected = diffRows.every((d) => !selectedDiffIds.has(d.id));
                  const allAppendSelected =
                    appendedItems.length > 0
                    && appendedItems.every((r) => selectedAppendIds.has(r.id));
                  const noAppendSelected = appendedItems.every((r) => !selectedAppendIds.has(r.id));

                  const toggleDiffRow = (id) => {
                    setSelectedDiffIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    });
                  };
                  const toggleAllDiff = () => {
                    setSelectedDiffIds(allDiffSelected ? new Set() : new Set(diffRows.map((d) => d.id)));
                  };
                  const toggleAppendRow = (id) => {
                    setSelectedAppendIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return next;
                    });
                  };
                  const toggleAllAppend = () => {
                    setSelectedAppendIds(allAppendSelected ? new Set() : new Set(appendedItems.map((r) => r.id)));
                  };

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

                  // Cross-tab × section preview surfaces extra "no-op"
                  // counters so a user who picked an aggregate plan whose
                  // source rows happen to match target byte-for-byte can
                  // see that those rows WERE processed (just produced no
                  // visible change) instead of concluding entire buckets
                  // were silently dropped. The fields are populated only
                  // by `_preview_cross_tab_section_aggregate`; on legacy
                  // multi-sheet aggregate / single-section flows they are
                  // undefined, in which case the counter is hidden so the
                  // existing UX stays intact.
                  // No-op counter for the totals strip is selection-aware so
                  // it matches the overwrite/fill/append counters' behavior:
                  // unchecking a no-op cell in the diff table immediately
                  // drops it from this counter. The total (incl. unchecked)
                  // is rendered as the "X of N" subtitle so the user can
                  // still see how many no-ops the backend detected.
                  const noOpTotalAvailable = (previewData.no_op_cells || []).length;
                  const cellsAlreadyMatched = noopCount;
                  const rowsAlreadyMatching = previewData.rows_already_matching || 0;
                  const showAlreadyMatchedCounter = noOpTotalAvailable > 0 || rowsAlreadyMatching > 0;
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
                        {showAlreadyMatchedCounter && (
                          <div style={{
                            background: "#f1f5f9", border: "1px solid #cbd5e1",
                            padding: "10px 14px", borderRadius: "8px", flex: 1, textAlign: "center",
                          }} title={`${cellsAlreadyMatched} of ${noOpTotalAvailable} no-op cell(s) selected. These cells will be sent to Sheets API even though their target value already matches source — uncheck them in the table below to skip the redundant writes.`}>
                            <div style={{ fontSize: "1.2rem", fontWeight: "800", color: "#475569" }}>
                              {cellsAlreadyMatched}
                              {allowSelection && noOpTotalAvailable !== cellsAlreadyMatched && (
                                <span style={{ fontSize: "0.85rem", color: "#94a3b8", fontWeight: 600 }}>
                                  {" "}/ {noOpTotalAvailable}
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: "0.78rem", color: "#64748b", fontWeight: 600 }}>
                              unchanged cells
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Per-target-section breakdown — only emitted by the
                          cross-tab × per-section preview path. Shows the user
                          that EACH target section in the plan was processed,
                          with a per-bucket cell-change vs cells-already-matched
                          split. Critical for the case where a bucket's source
                          rows happened to all match target byte-for-byte (the
                          headline counters would otherwise show 0 for that
                          bucket and look like the bucket was dropped). */}
                      {Array.isArray(previewData.per_bucket_summary)
                        && previewData.per_bucket_summary.length > 0 && (
                        <div style={{
                          marginBottom: "12px",
                          background: "#f8fafc", border: "1px solid #e2e8f0",
                          borderRadius: "8px", padding: "10px 14px",
                          fontSize: "0.82rem", color: "#334155",
                        }}>
                          <div style={{
                            fontWeight: 700, color: "#26326e", marginBottom: "6px",
                            fontSize: "0.85rem",
                          }}>
                            By target section
                          </div>
                          {previewData.per_bucket_summary.map((b) => {
                            const sourceLabel = (b.sources || [])
                              .map((s) => {
                                const showCompound = s.source_section_title
                                  && s.source_section_title !== s.sheet_name;
                                return showCompound
                                  ? `${s.sheet_name} > ${s.source_section_title}`
                                  : s.sheet_name;
                              })
                              .join(", ");
                            const parts = [];
                            if (b.cells_to_overwrite > 0)
                              parts.push(`${b.cells_to_overwrite} cell(s) to overwrite`);
                            if (b.cells_already_matched > 0)
                              parts.push(`${b.cells_already_matched} already match`);
                            if (b.rows_skipped_no_match > 0)
                              parts.push(`${b.rows_skipped_no_match} row(s) skipped (no target match)`);
                            const summaryText = parts.length > 0
                              ? parts.join(" - ")
                              : "no changes needed";
                            return (
                              <div key={b.target_section_index}
                                style={{ marginBottom: "4px", lineHeight: 1.5 }}>
                                <strong style={{ color: "#1e293b" }}>{b.target_section_title}</strong>
                                {sourceLabel && (
                                  <span style={{ color: "#64748b" }}>
                                    {" "}from {sourceLabel}
                                  </span>
                                )}
                                <span style={{ color: "#475569" }}>: {summaryText}</span>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Truncation banner from backend cap */}
                      {previewData.diff_truncated && (
                        <div style={{
                          marginBottom: "12px", padding: "10px 14px",
                          background: "#fef3c7", borderRadius: "8px",
                          fontSize: "0.85rem", color: "#92400e",
                        }}>
                          <strong>Preview truncated.</strong> Showing the first{" "}
                          {diffRows.length + appendedItems.length} of{" "}
                          {(previewData.diff_total_cells || 0)
                            + (previewData.cells_already_matched || 0)
                            + appendedItems.length} cells.
                          The confirm action will still write every matched cell
                          {allowSelection ? " you have checked." : "."}
                        </div>
                      )}

                      {/* Changes preview table */}
                      {diffRows.length > 0 && (
                        <>
                          <div style={{
                            display: "flex", justifyContent: "space-between", alignItems: "center",
                            marginBottom: "8px",
                          }}>
                            <div style={{
                              fontSize: "0.95rem", fontWeight: 700, color: "#26326e",
                            }}>
                              Changes preview
                            </div>
                            {allowSelection && (
                              <div style={{ fontSize: "0.78rem", color: "#6b7280" }}>
                                {selectedDiffIds.size} of {diffRows.length} cell change(s) selected
                              </div>
                            )}
                          </div>
                          <div style={{
                            maxHeight: "320px", overflowY: "auto",
                            border: "1px solid #e5e7eb", borderRadius: "8px",
                          }}>
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                              <thead>
                                <tr style={{ background: "#f3f4f6", position: "sticky", top: 0 }}>
                                  {allowSelection && (
                                    <th style={{
                                      padding: "8px 12px", textAlign: "center", fontWeight: "700",
                                      color: "#374151", width: "44px",
                                    }}>
                                      <input
                                        type="checkbox"
                                        title={allDiffSelected ? "Deselect all" : "Select all"}
                                        ref={(el) => setIndeterminate(el, !allDiffSelected && !noDiffSelected)}
                                        checked={allDiffSelected}
                                        onChange={toggleAllDiff}
                                        style={{ cursor: "pointer", width: "16px", height: "16px" }}
                                      />
                                    </th>
                                  )}
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Row</th>
                                  {showSourceCol && (
                                    <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Source</th>
                                  )}
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Column</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Current</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>New</th>
                                  <th style={{ padding: "8px 12px", textAlign: "left", fontWeight: "700", color: "#374151" }}>Type</th>
                                </tr>
                              </thead>
                              <tbody>
                                {diffsVisible.map((d, i) => {
                                  const isOverwrite = d.type === "overwrite";
                                  const isFill      = d.type === "fill";
                                  const isNoop      = d.type === "noop";
                                  const isChecked = !allowSelection || selectedDiffIds.has(d.id);
                                  // Three-tone row backgrounds when checked:
                                  //   overwrite -> red tint (destructive change)
                                  //   fill      -> green tint (additive value)
                                  //   noop      -> neutral gray tint (will write
                                  //                same value already in the cell)
                                  // Unchecked rows always use the deselected
                                  // gray (#f9fafb) regardless of type.
                                  const rowBg = !isChecked
                                    ? "#f9fafb"
                                    : isOverwrite ? "#fef2f2"
                                    : isFill      ? "#f0fdf4"
                                    : "#f3f4f6";
                                  const leftBorder = isOverwrite
                                    ? "4px solid #ef4444"
                                    : isFill
                                      ? "4px solid #22c55e"
                                      : "4px solid #9ca3af";
                                  const dimmed = !isChecked;
                                  return (
                                    <tr key={d.id} style={{
                                      borderTop: "1px solid #e5e7eb",
                                      background: rowBg,
                                      borderLeft: leftBorder,
                                      opacity: dimmed ? 0.5 : 1,
                                    }}>
                                      {allowSelection && (
                                        <td style={{ padding: "8px 12px", textAlign: "center" }}>
                                          <input
                                            type="checkbox"
                                            checked={isChecked}
                                            onChange={() => toggleDiffRow(d.id)}
                                            style={{ cursor: "pointer", width: "16px", height: "16px" }}
                                          />
                                        </td>
                                      )}
                                      <td style={{ padding: "8px 12px", color: "#1f2937", fontWeight: 600 }}>
                                        {formatAnchor(d.anchor)}
                                      </td>
                                      {showSourceCol && (
                                        <td style={{ padding: "8px 12px" }}>
                                          {d.sourceSheet ? (() => {
                                            // When the section title is
                                            // present AND distinct from
                                            // the sheet name, render
                                            // "Sheet > Section" so cross-tab
                                            // × multi-section flows
                                            // disambiguate which inner
                                            // section donated the row. For
                                            // headerless sections the
                                            // backend falls back to the
                                            // sheet name as section title
                                            // so they collapse to just the
                                            // sheet name (no redundant
                                            // "Sheet > Sheet" badge).
                                            const showCompound = d.sourceSection
                                              && d.sourceSection !== d.sourceSheet;
                                            const badgeText = showCompound
                                              ? `${d.sourceSheet} > ${d.sourceSection}`
                                              : d.sourceSheet;
                                            const titleText = showCompound
                                              ? `From source sheet "${d.sourceSheet}", section "${d.sourceSection}"`
                                              : `From source sheet "${d.sourceSheet}"`;
                                            return (
                                              <span
                                                title={titleText}
                                                style={{
                                                  background: "#ede9fe", color: "#5b21b6",
                                                  padding: "2px 8px", borderRadius: "10px",
                                                  fontSize: "0.72rem", fontWeight: 700,
                                                  whiteSpace: "nowrap",
                                                }}
                                              >
                                                {badgeText}
                                              </span>
                                            );
                                          })() : (
                                            <span style={{ color: "#9ca3af" }}>—</span>
                                          )}
                                        </td>
                                      )}
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
                                        <span
                                          title={
                                            isOverwrite
                                              ? "Source value differs from current target value — checking will overwrite."
                                              : isFill
                                                ? "Target cell is empty — checking will fill it with the source value."
                                                : "Source value already matches target value — checking will still send a no-op write to Sheets API. Uncheck to skip."
                                          }
                                          style={{
                                          background: isOverwrite
                                            ? "#fee2e2"
                                            : isFill
                                              ? "#dcfce7"
                                              : "#e5e7eb",
                                          color: isOverwrite
                                            ? "#991b1b"
                                            : isFill
                                              ? "#166534"
                                              : "#4b5563",
                                          padding: "4px 12px", borderRadius: "20px",
                                          fontWeight: 700, fontSize: "0.7rem",
                                          textTransform: "uppercase", letterSpacing: "0.5px",
                                          whiteSpace: "nowrap",
                                        }}>
                                          {isOverwrite ? "Overwrite" : isFill ? "Fill" : "Unchanged"}
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
                      {appendedItems.length > 0 && (
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
                            <span>
                              {allowSelection
                                ? `New rows to append (${selectedAppendCount} of ${appendedItems.length} selected)`
                                : `New rows to append (${appendedItems.length})`}
                            </span>
                            <span style={{ fontSize: "0.85rem" }}>
                              {appendedExpanded ? "Hide" : "Show"}
                            </span>
                          </button>
                          {appendedExpanded && (
                            <div style={{
                              maxHeight: "320px", overflowY: "auto",
                              background: "white", padding: "12px 16px",
                            }}>
                              {allowSelection && (
                                <div style={{
                                  display: "flex", alignItems: "center", gap: "8px",
                                  paddingBottom: "10px", marginBottom: "10px",
                                  borderBottom: "1px solid #e5e7eb",
                                }}>
                                  <input
                                    type="checkbox"
                                    ref={(el) => setIndeterminate(el, !allAppendSelected && !noAppendSelected)}
                                    checked={allAppendSelected}
                                    onChange={toggleAllAppend}
                                    style={{ cursor: "pointer", width: "16px", height: "16px" }}
                                  />
                                  <span style={{ fontSize: "0.8rem", color: "#6b7280", fontWeight: 600 }}>
                                    {allAppendSelected ? "Deselect all" : "Select all"}
                                  </span>
                                </div>
                              )}

                              {appendedItems.map((row, i) => {
                                const isChecked = !allowSelection || selectedAppendIds.has(row.id);
                                return (
                                  <div key={row.id} style={{
                                    display: "grid",
                                    gridTemplateColumns: allowSelection ? "auto 1fr" : "1fr",
                                    columnGap: "12px",
                                    marginBottom: i === appendedItems.length - 1 ? 0 : "12px",
                                    paddingBottom: i === appendedItems.length - 1 ? 0 : "12px",
                                    borderBottom: i === appendedItems.length - 1 ? "none" : "1px solid #e5e7eb",
                                    opacity: isChecked ? 1 : 0.5,
                                  }}>
                                    {allowSelection && (
                                      <input
                                        type="checkbox"
                                        checked={isChecked}
                                        onChange={() => toggleAppendRow(row.id)}
                                        style={{
                                          cursor: "pointer", width: "16px", height: "16px",
                                          marginTop: "4px",
                                        }}
                                      />
                                    )}
                                    <div>
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
                                  </div>
                                );
                              })}
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