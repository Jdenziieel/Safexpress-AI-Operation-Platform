/**
 * Workload Analysis page.
 *
 * Two tabs (Inbound / Outbound) that share the same data shape:
 * each holds a list of "pallet cards" (1 uploaded PDF = 1 pallet) with
 * editable items inside. A Per-Pallet / Per-Piece basis toggle decides
 * which driver feeds the math.
 *
 * Compute model:
 *   - Inbound  phases : Inbound Checking + Put-Away
 *   - Outbound phases : Picking + Outbound Checking
 *   - Per-pallet basis: driver = number of pallet cards
 *   - Per-piece  basis: driver = sum of all item.qty across all cards
 *
 * Persistence: full state survives page refresh via localStorage
 * (`workload-analysis:v1:state`, see Frontend/src/token.js).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import {
  ArrowLeft, Plus, Minus, Trash2, Calculator, Calendar, Download, RefreshCw,
  Package, Save, Upload, FileText, AlertCircle, CheckCircle2,
  Clock, Users, X, ChevronDown, ChevronUp,
} from 'lucide-react';
import {
  WORKLOAD_API_BASE,
  checkAPIHealth,
  workloadCalculationAPI,
  workloadConfigAPI,
  workloadPdfAPI,
  workloadUomAPI,
} from '../utils/workloadAPI';
import {
  clearWorkloadState,
  loadWorkloadState,
  saveWorkloadState,
} from '../token';
import '../css/WorkloadAnalysis.css';

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

const TABS = {
  inbound:  { label: 'Inbound Workload',  defaultBasis: 'per_pallet',
              phases: ['Inbound Checking', 'Put-Away'] },
  outbound: { label: 'Outbound Workload', defaultBasis: 'per_piece',
              phases: ['Picking', 'Outbound Checking'] },
};

// Rate keys per (mode, basis). Matches handlers/calculate.py:_PHASE_SETS.
const RATE_KEYS = {
  inbound: {
    per_pallet: ['inboundCheckingSecPerPallet', 'putAwaySecPerPallet'],
    per_piece:  ['inboundCheckingSecPerPiece',  'putAwaySecPerPiece'],
  },
  outbound: {
    per_pallet: ['pickingSecPerPallet', 'outboundCheckingSecPerPallet'],
    per_piece:  ['pickingSecPerPiece',  'outboundCheckingSecPerPiece'],
  },
};

const RATE_LABELS = {
  inboundCheckingSecPerPallet:  ['Inbound Checking',  'sec/pallet'],
  inboundCheckingSecPerPiece:   ['Inbound Checking',  'sec/piece'],
  putAwaySecPerPallet:          ['Put-Away',          'sec/pallet'],
  putAwaySecPerPiece:           ['Put-Away',          'sec/piece'],
  pickingSecPerPallet:          ['Picking',           'sec/pallet'],
  pickingSecPerPiece:           ['Picking',           'sec/piece'],
  outboundCheckingSecPerPallet: ['Outbound Checking', 'sec/pallet'],
  outboundCheckingSecPerPiece:  ['Outbound Checking', 'sec/piece'],
};

// Used as a last-resort fallback when /api/uom hasn't loaded yet. Same list
// as DEFAULT_UOMS in the Lambda's storage.py so the dropdown is never empty.
const FALLBACK_UOMS = [
  'Pack', 'Case', 'Can', 'Bottle', 'Jar', 'Pouch', 'Block', 'Container',
  'Gal', 'Tetra', 'Box', 'Roll', 'Canister', 'Bar', 'Pcs', 'Pallet',
];

const PERSIST_DEBOUNCE_MS = 300;

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

const createEmptyTabState = (basis) => ({
  basis,
  workers: '',
  palletCards: [],     // [{ palletId, sourceFilename, items: [...], addedAt }]
  rateOverrides: {},   // map: rateKey -> override number (only set when user edits the panel)
  lastResults: null,   // last calculate() response (so refresh keeps showing results)
  lastPayload: null,   // exact payload that produced lastResults — used by Save Calculation
  lastSavedAt: null,   // ISO timestamp of when current result was last saved to history (null = unsaved)
});

const _makeManualPalletId = () => {
  const ts = Date.now().toString(36).toUpperCase();
  return `MANUAL-${ts}`;
};

const _coerceNumeric = (v, fallback = 0) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
};

const _fmtSeconds = (totalSeconds) => {
  const minutes = totalSeconds / 60;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
};

/** Relative-time formatter for history rows ("2 minutes ago"). Pure helper,
 *  good enough for capstone scale — switch to date-fns if we ever need it. */
const _fmtRelative = (iso) => {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const diffSec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (diffSec < 60) return 'just now';
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
  return new Date(iso).toLocaleDateString();
};

// ---------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------

const WorkloadAnalysis = () => {
  const navigate = useNavigate();
  const fileInputRefs = useRef({});      // tabId -> <input ref>
  const persistTimer = useRef(null);

  // Tab state
  const [activeTab, setActiveTab] = useState('inbound');
  const [tabs, setTabs] = useState({
    inbound:  createEmptyTabState(TABS.inbound.defaultBasis),
    outbound: createEmptyTabState(TABS.outbound.defaultBasis),
  });

  // Backend state
  const [config, setConfig]               = useState(null); // 8-rate config
  const [uomList, setUomList]             = useState(FALLBACK_UOMS);
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [isLoadingConfig, setIsLoadingConfig]       = useState(true);
  const [isUploading, setIsUploading]               = useState(false);
  const [uploadErrors, setUploadErrors]             = useState([]);
  const [isCalculating, setIsCalculating]           = useState(false);
  const [calcError, setCalcError]                   = useState('');
  const [showRateSettings, setShowRateSettings]     = useState(false);
  const [hasHydratedFromStorage, setHasHydratedFromStorage] = useState(false);

  // History modal (centered popup over the form, was a right-column drawer
  // before — the form stays visible underneath now).
  const [showHistory, setShowHistory]               = useState(false);
  const [historyItems, setHistoryItems]             = useState([]);
  const [isLoadingHistory, setIsLoadingHistory]     = useState(false);
  const [historyError, setHistoryError]             = useState('');
  const [historyExpanded, setHistoryExpanded]       = useState(null); // id
  const [historyCount, setHistoryCount]             = useState(0);    // for header badge
  // Tracks duplicate filenames per active tab so we can surface a friendly
  // "already added" notice instead of silently swapping the pallet.
  const [duplicateUploads, setDuplicateUploads]     = useState([]);
  // Save-Calculation state — replaces the implicit "save every Calculate"
  // behaviour. The user explicitly opts in once they're happy with the
  // result. PDF export also auto-saves (strong signal of intent).
  const [isSaving, setIsSaving]                     = useState(false);
  const [saveError, setSaveError]                   = useState('');
  // Generic confirm-dialog state. We push a {title, message, variant,
  // confirmLabel, onConfirm} object onto it and the <ConfirmModal> renders.
  const [confirmDialog, setConfirmDialog]           = useState(null);
  const askConfirm = useCallback((opts) => {
    setConfirmDialog({
      variant:      'default',
      confirmLabel: 'Confirm',
      cancelLabel:  'Cancel',
      ...opts,
    });
  }, []);

  // ----- Initial mount: hydrate from localStorage, then talk to backend ---

  useEffect(() => {
    const saved = loadWorkloadState();
    if (saved) {
      if (saved.activeTab && TABS[saved.activeTab]) setActiveTab(saved.activeTab);
      const next = { ...tabs };
      for (const tabId of Object.keys(TABS)) {
        if (saved[tabId]) {
          next[tabId] = {
            ...createEmptyTabState(TABS[tabId].defaultBasis),
            ...saved[tabId],
            // Always re-validate the shape so a malformed blob can't break us.
            palletCards: Array.isArray(saved[tabId].palletCards) ? saved[tabId].palletCards : [],
            rateOverrides: saved[tabId].rateOverrides || {},
          };
        }
      }
      setTabs(next);
    }
    setHasHydratedFromStorage(true);

    (async () => {
      const connected = await checkAPIHealth();
      setIsBackendConnected(connected);
      if (connected) {
        try {
          const cfg = await workloadConfigAPI.getConfig();
          setConfig(cfg);
        } catch (e) {
          console.warn('Failed to load config:', e);
        }
        try {
          const uoms = await workloadUomAPI.listUoms();
          if (uoms && uoms.length) setUomList(uoms);
        } catch (e) {
          console.warn('Failed to load UOM list:', e);
        }
      } else {
        console.warn('Workload backend is offline. Running in offline mode.');
      }
      setIsLoadingConfig(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ----- Persistence: debounced save on any state change ---------------

  useEffect(() => {
    if (!hasHydratedFromStorage) return;
    if (persistTimer.current) clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      saveWorkloadState({ activeTab, ...tabs });
    }, PERSIST_DEBOUNCE_MS);
    return () => {
      if (persistTimer.current) clearTimeout(persistTimer.current);
    };
  }, [activeTab, tabs, hasHydratedFromStorage]);

  // ----- Derived state for the active tab -----------------------------

  const tab = tabs[activeTab];
  const phaseNames = TABS[activeTab].phases;
  const activeRateKeys = RATE_KEYS[activeTab][tab.basis];

  const effectiveRates = useMemo(() => {
    const base = config || {};
    return {
      ...base,
      ...(tab.rateOverrides || {}),
    };
  }, [config, tab.rateOverrides]);

  const driverSummary = useMemo(() => {
    const palletCount = tab.palletCards.length;
    let totalQty = 0;
    for (const card of tab.palletCards) {
      for (const item of card.items || []) {
        totalQty += _coerceNumeric(item.qty, 0);
      }
    }
    return { palletCount, totalQty };
  }, [tab.palletCards]);

  // ----- Generic tab-state setters ------------------------------------

  const updateTab = useCallback((tabId, updater) => {
    setTabs((prev) => ({
      ...prev,
      [tabId]: typeof updater === 'function' ? updater(prev[tabId]) : { ...prev[tabId], ...updater },
    }));
  }, []);

  const updateActiveTab = useCallback((updater) => {
    updateTab(activeTab, updater);
  }, [activeTab, updateTab]);

  // ----- Pallet card operations ---------------------------------------

  const upsertPalletCard = useCallback((card) => {
    updateActiveTab((s) => {
      const others = s.palletCards.filter((c) => c.palletId !== card.palletId);
      return { ...s, palletCards: [...others, card] };
    });
  }, [updateActiveTab]);

  const removePalletCard = useCallback((palletId) => {
    updateActiveTab((s) => ({
      ...s,
      palletCards: s.palletCards.filter((c) => c.palletId !== palletId),
    }));
  }, [updateActiveTab]);

  const addManualPallet = useCallback(() => {
    const palletId = _makeManualPalletId();
    upsertPalletCard({
      palletId,
      sourceFilename: '(manual entry)',
      items: [{ itemCode: '', description: '', qty: '', uom: uomList[0] || 'Pcs' }],
      addedAt: new Date().toISOString(),
      manual: true,
    });
  }, [upsertPalletCard, uomList]);

  const addItemToCard = useCallback((palletId) => {
    updateActiveTab((s) => ({
      ...s,
      palletCards: s.palletCards.map((c) =>
        c.palletId === palletId
          ? { ...c, items: [...c.items, { itemCode: '', description: '', qty: '', uom: uomList[0] || 'Pcs' }] }
          : c
      ),
    }));
  }, [updateActiveTab, uomList]);

  const updateItem = useCallback((palletId, idx, field, value) => {
    updateActiveTab((s) => ({
      ...s,
      palletCards: s.palletCards.map((c) =>
        c.palletId === palletId
          ? {
              ...c,
              items: c.items.map((it, i) => (i === idx ? { ...it, [field]: value } : it)),
            }
          : c
      ),
    }));
  }, [updateActiveTab]);

  const removeItem = useCallback((palletId, idx) => {
    updateActiveTab((s) => ({
      ...s,
      palletCards: s.palletCards.map((c) =>
        c.palletId === palletId
          ? { ...c, items: c.items.filter((_, i) => i !== idx) }
          : c
      ),
    }));
  }, [updateActiveTab]);

  // ----- PDF upload ---------------------------------------------------

  const handleFiles = useCallback(async (files) => {
    const list = Array.from(files || []);
    if (!list.length) return;
    if (!isBackendConnected) {
      setUploadErrors([{ filename: 'all', message: 'Backend is offline; PDF parsing requires the workload API.' }]);
      return;
    }
    setIsUploading(true);
    setUploadErrors([]);
    setDuplicateUploads([]);

    // Pre-flight check: any incoming filename that matches an already-staged
    // pallet's sourceFilename or palletId becomes a "duplicate" — we still
    // parse (the backend's the source of truth for the pallet ID) but we
    // surface a friendly notice instead of silently swapping the row.
    const existingByFilename = new Set(
      tab.palletCards.map((c) => (c.sourceFilename || '').toLowerCase()).filter(Boolean)
    );
    const preflightDuplicates = list
      .map((f) => f.name)
      .filter((name) => existingByFilename.has(name.toLowerCase()));

    const results = await Promise.allSettled(list.map((f) => workloadPdfAPI.parsePdf(f)));
    const errors = [];
    const replacedPalletIds = [];

    setTabs((prev) => {
      const s = prev[activeTab];
      let palletCards = [...s.palletCards];

      results.forEach((r, i) => {
        const file = list[i];
        if (r.status === 'fulfilled' && r.value?.success) {
          const palletId =
            r.value.palletId || `${file.name.replace(/\.[^.]+$/, '')}-${i}`;
          // Replace any existing card with the same palletId. If we did
          // replace one, record it for the dup notice.
          if (palletCards.some((c) => c.palletId === palletId)) {
            replacedPalletIds.push({ palletId, filename: file.name });
          }
          palletCards = palletCards.filter((c) => c.palletId !== palletId);
          palletCards.push({
            palletId,
            sourceFilename: file.name,
            items: r.value.items || [],
            warnings: r.value.warnings || [],
            pages: r.value.pages,
            addedAt: new Date().toISOString(),
            // Audit-trail handle written by the parse Lambda. Both may be
            // empty strings when S3 is disabled (local dev / missing creds)
            // and the calc still works fine in that case.
            s3Bucket: r.value.s3Bucket || '',
            s3Key:    r.value.s3Key    || '',
          });
        } else {
          const message = r.status === 'rejected' ? r.reason?.message : (r.value?.message || 'Unknown error');
          errors.push({ filename: file.name, message });
        }
      });

      return { ...prev, [activeTab]: { ...s, palletCards } };
    });

    // Combine the two duplicate-detection paths into one user-facing list.
    const dupSet = new Set();
    preflightDuplicates.forEach((n) => dupSet.add(`filename:${n}`));
    replacedPalletIds.forEach((d) => dupSet.add(`pallet:${d.palletId}:${d.filename}`));
    setDuplicateUploads(Array.from(dupSet).map((k) => {
      const [kind, ...rest] = k.split(':');
      if (kind === 'filename') return { kind, filename: rest.join(':') };
      const [palletId, filename] = [rest[0], rest.slice(1).join(':')];
      return { kind, palletId, filename };
    }));

    setUploadErrors(errors);
    setIsUploading(false);
  }, [activeTab, isBackendConnected, tab.palletCards]);

  const triggerFilePicker = () => {
    const ref = fileInputRefs.current[activeTab];
    if (ref) ref.click();
  };

  // ----- Rates panel --------------------------------------------------

  const setRateOverride = useCallback((rateKey, value) => {
    updateActiveTab((s) => ({
      ...s,
      rateOverrides: { ...s.rateOverrides, [rateKey]: _coerceNumeric(value, 0) },
    }));
  }, [updateActiveTab]);

  const clearRateOverrides = useCallback(() => {
    updateActiveTab((s) => ({ ...s, rateOverrides: {} }));
  }, [updateActiveTab]);

  const saveCurrentRatesToBackend = useCallback(async () => {
    if (!isBackendConnected) {
      alert('Backend not connected. Cannot save rates.');
      return;
    }
    try {
      // Save all 8 rates, blending overrides on top of the current config.
      // NOTE: This writes to the CURRENT USER'S personal config row only.
      // Other users keep their own rates / the organization default.
      const payload = { ...config, ...tab.rateOverrides, updatedBy: 'user' };
      // Strip non-rate fields the backend doesn't accept.
      const allowed = new Set(Object.keys(RATE_LABELS));
      const cleaned = Object.fromEntries(
        Object.entries(payload).filter(([k]) => allowed.has(k) || k === 'updatedBy')
      );
      const next = await workloadConfigAPI.updateConfig(cleaned);
      setConfig(next);
      clearRateOverrides();
      alert('Your personal rates have been saved.');
    } catch (e) {
      console.error('Save rates failed:', e);
      alert(`Failed to save rates: ${e.message}`);
    }
  }, [config, tab.rateOverrides, isBackendConnected, clearRateOverrides]);

  const resetRatesToOrgDefault = useCallback(() => {
    if (!isBackendConnected) {
      setCalcError('Backend not connected. Cannot reset rates.');
      return;
    }
    askConfirm({
      variant:      'danger',
      title:        'Reset to system defaults?',
      message:      'This drops your saved rates and goes back to the warehouse standard values from Workload.xlsx. Your in-progress overrides will also be cleared.',
      confirmLabel: 'Reset rates',
      onConfirm: async () => {
        try {
          const next = await workloadConfigAPI.resetToDefault();
          setConfig(next);
          clearRateOverrides();
          setConfirmDialog(null);
        } catch (e) {
          console.error('Reset rates failed:', e);
          setCalcError(`Failed to reset rates: ${e.message}`);
          setConfirmDialog(null);
        }
      },
    });
  }, [isBackendConnected, clearRateOverrides, askConfirm]);

  // ----- History (centered modal) ------------------------------------

  const loadHistory = useCallback(async () => {
    if (!isBackendConnected) return;
    setIsLoadingHistory(true);
    setHistoryError('');
    try {
      const resp = await workloadCalculationAPI.getHistory({ limit: 100, offset: 0 });
      setHistoryItems(resp.data || []);
      setHistoryCount((resp.data || []).length);
    } catch (e) {
      console.error('Load history failed:', e);
      setHistoryError(e.message || 'Failed to load history');
    } finally {
      setIsLoadingHistory(false);
    }
  }, [isBackendConnected]);

  // Auto-load when the modal opens, and once on mount so the header badge
  // is accurate without needing the user to open the modal first.
  useEffect(() => {
    if (showHistory) {
      loadHistory();
      setHistoryExpanded(null);
    }
  }, [showHistory, loadHistory]);
  useEffect(() => {
    if (isBackendConnected) loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBackendConnected]);

  const deleteHistoryItem = useCallback((id) => {
    askConfirm({
      variant:      'danger',
      title:        'Delete this saved calculation?',
      message:      'This cannot be undone. The row will be removed from your history immediately.',
      confirmLabel: 'Delete',
      onConfirm: async () => {
        try {
          await workloadCalculationAPI.deleteCalculation(id);
          setHistoryItems((items) => items.filter((it) => it.id !== id));
          setHistoryCount((c) => Math.max(0, c - 1));
          if (historyExpanded === id) setHistoryExpanded(null);
          setConfirmDialog(null);
        } catch (e) {
          console.error('Delete history failed:', e);
          setHistoryError(`Failed to delete: ${e.message}`);
          setConfirmDialog(null);
        }
      },
    });
  }, [historyExpanded, askConfirm]);

  // ----- Basis / workers ----------------------------------------------

  const setBasis = useCallback((basis) => {
    updateActiveTab({ basis });
  }, [updateActiveTab]);

  const setWorkers = useCallback((workers) => {
    updateActiveTab({ workers });
  }, [updateActiveTab]);

  // ----- Calculate ----------------------------------------------------

  /** Build the API payload from the current tab state. Pulled out so the
   *  Save Calculation button can reuse the exact same shape. */
  const buildCalculatePayload = useCallback((options = {}) => {
    const workers = parseInt(tab.workers || '0', 10);
    const palletsForApi = tab.palletCards.map((c) => ({
      palletId:       c.palletId,
      sourceFilename: c.sourceFilename,
      s3Bucket:       c.s3Bucket || '',
      s3Key:          c.s3Key    || '',
      items: (c.items || [])
        .filter((it) => _coerceNumeric(it.qty, 0) > 0)
        .map((it) => ({
          itemCode:    it.itemCode || '',
          description: it.description || '',
          qty:         _coerceNumeric(it.qty, 0),
          uom:         it.uom || '',
        })),
    }));
    return {
      mode:      activeTab,
      basis:     tab.basis,
      workers,
      pallets:   palletsForApi,
      rates:     tab.rateOverrides,
      notes:     '',
      createdBy: 'user',
      save:      false,   // explicit save now — overridden by callers that want it
      ...options,
    };
  }, [activeTab, tab]);

  const runCalculate = useCallback(async () => {
    setCalcError('');
    setSaveError('');
    if (!tab.palletCards.length) {
      setCalcError('Upload at least one PDF or add a manual pallet first.');
      return;
    }
    const workers = parseInt(tab.workers || '0', 10);
    if (!Number.isFinite(workers) || workers < 1) {
      setCalcError('Enter the number of workers (must be at least 1).');
      return;
    }

    // We deliberately pass `save: false` here. The user now has to press
    // "Save Calculation" (or "Export PDF", which implies save) to commit
    // the row to history — avoids polluting the history every time someone
    // tweaks an input.
    const payload = buildCalculatePayload({ save: false });

    setIsCalculating(true);
    try {
      if (isBackendConnected) {
        const result = await workloadCalculationAPI.calculate(payload);
        // result will NOT contain `id` because we didn't save. Set
        // lastSavedAt to null so the UI knows to show the Save button.
        // Capture the payload so Save Calculation can re-send the EXACT
        // same inputs — avoids the "user edited inputs after Calculate, then
        // clicked Save and got a different result" footgun.
        updateActiveTab({
          lastResults: result,
          lastPayload: payload,
          lastSavedAt: null,
        });
      } else {
        const result = clientSideCalculate(payload, effectiveRates);
        updateActiveTab({
          lastResults: result,
          lastPayload: payload,
          lastSavedAt: null,
        });
      }
    } catch (e) {
      console.error('Calculate failed:', e);
      setCalcError(e.message || 'Calculation failed');
    } finally {
      setIsCalculating(false);
    }
  }, [tab, isBackendConnected, effectiveRates, buildCalculatePayload, updateActiveTab]);

  /** Persist the currently-displayed calculation to the user's history.
   *  Re-runs the calc on the server with `save: true` using the EXACT same
   *  payload that produced lastResults, so the saved row matches what's
   *  on screen even if the user has since edited the form. Returns the
   *  saved record's id, or null on failure. */
  const saveCurrentCalculation = useCallback(async () => {
    setSaveError('');
    if (!tab.lastResults) return null;
    if (!isBackendConnected) {
      setSaveError('Backend offline — cannot save right now.');
      return null;
    }
    // Prefer the captured payload (matches the displayed result). Fall back
    // to building a fresh one only if we somehow lost it (e.g. an old
    // localStorage entry from before this code shipped).
    const basePayload = tab.lastPayload || buildCalculatePayload();
    const payload     = { ...basePayload, save: true };
    setIsSaving(true);
    try {
      const result = await workloadCalculationAPI.calculate(payload);
      updateActiveTab({
        lastResults: result,
        lastPayload: basePayload,
        lastSavedAt: new Date().toISOString(),
      });
      setHistoryCount((c) => c + 1);
      return result.id || null;
    } catch (e) {
      console.error('Save failed:', e);
      setSaveError(e.message || 'Save failed');
      return null;
    } finally {
      setIsSaving(false);
    }
  }, [tab.lastResults, tab.lastPayload, isBackendConnected, buildCalculatePayload, updateActiveTab]);

  // Offline / client-side mirror of handlers/calculate.py. Kept in sync via
  // the same RATE_KEYS table and phase names so results match what the
  // backend would return.
  const clientSideCalculate = (payload, rates) => {
    const total = payload.pallets.reduce(
      (acc, p) => acc + (p.items || []).reduce((a, it) => a + _coerceNumeric(it.qty, 0), 0),
      0,
    );
    const driverValue = payload.basis === 'per_pallet'
      ? payload.pallets.length
      : total;
    const phaseRateKeys = RATE_KEYS[payload.mode][payload.basis];
    const phaseBreakdown = phaseRateKeys.map((key, idx) => {
      const rate = _coerceNumeric(rates[key], 0);
      const timeSeconds = (driverValue * rate) / payload.workers;
      return {
        name:         TABS[payload.mode].phases[idx],
        driver:       payload.basis === 'per_pallet' ? 'pallet' : 'piece',
        driverValue,
        ratePerUnit:  rate,
        rateKey:      key,
        timeSeconds,
        timeMinutes:  timeSeconds / 60,
      };
    });
    const totalSeconds = phaseBreakdown.reduce((a, p) => a + p.timeSeconds, 0);
    return {
      mode:            payload.mode,
      basis:           payload.basis,
      numberOfWorkers: payload.workers,
      palletCount:     payload.pallets.length,
      totalQty:        total,
      totalSeconds,
      totalMinutes:    totalSeconds / 60,
      totalHours:      totalSeconds / 3600,
      displayHours:    Math.floor((totalSeconds / 60) / 60),
      displayMinutes:  Math.round((totalSeconds / 60) % 60),
      phaseBreakdown,
      pallets:         payload.pallets.map((p) => ({
        palletId: p.palletId, sourceFilename: p.sourceFilename,
        itemCount: (p.items || []).length,
        totalQty:  (p.items || []).reduce((a, it) => a + _coerceNumeric(it.qty, 0), 0),
      })),
      items: payload.pallets.flatMap((p) =>
        (p.items || []).map((it) => ({ ...it, palletId: p.palletId }))
      ),
    };
  };

  // ----- Reset (uses ConfirmModal, not window.confirm) ----------------

  const resetActiveTab = useCallback(() => {
    askConfirm({
      variant:      'danger',
      title:        `Clear the ${TABS[activeTab].label} tab?`,
      message:      `This removes all uploaded pallets, any in-progress rate overrides and the current result from the ${TABS[activeTab].label} tab. Your saved history is not affected.`,
      confirmLabel: 'Clear tab',
      onConfirm: () => {
        updateActiveTab(createEmptyTabState(TABS[activeTab].defaultBasis));
        setConfirmDialog(null);
      },
    });
  }, [activeTab, askConfirm, updateActiveTab]);

  const resetAll = useCallback(() => {
    askConfirm({
      variant:      'danger',
      title:        'Clear ALL workload data?',
      message:      'This removes every uploaded pallet on both Inbound and Outbound tabs, plus any in-progress overrides. Your saved history is not affected — open it from the calendar icon to manage saved rows.',
      confirmLabel: 'Clear everything',
      onConfirm: () => {
        clearWorkloadState();
        setTabs({
          inbound:  createEmptyTabState(TABS.inbound.defaultBasis),
          outbound: createEmptyTabState(TABS.outbound.defaultBasis),
        });
        setActiveTab('inbound');
        setUploadErrors([]);
        setCalcError('');
        setSaveError('');
        setConfirmDialog(null);
      },
    });
  }, [askConfirm]);

  // ----- Export PDF ---------------------------------------------------

  const exportToPDF = async () => {
    const results = tab.lastResults;
    if (!results) {
      setCalcError('Press Calculate before exporting.');
      return;
    }
    // Auto-save on export — exporting a PDF is a strong signal that this
    // calculation matters, so we tuck a copy into history (only if not
    // already saved in this session) before generating the document.
    if (isBackendConnected && !tab.lastSavedAt && !results.id) {
      const savedId = await saveCurrentCalculation();
      if (savedId) {
        // saveCurrentCalculation updates tab.lastResults with the id; use
        // the latest state via the local variable for the PDF stamp.
        results.id = savedId;
      }
    }
    const doc = new jsPDF();
    const now = new Date();
    const date = now.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    const driverLabel = tab.basis === 'per_pallet' ? 'Per Pallet' : 'Per Piece';

    doc.setFontSize(18);
    doc.setFont('helvetica', 'bold');
    doc.text('Workload Analysis Report', 14, 18);

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`Mode: ${TABS[activeTab].label}    Basis: ${driverLabel}`, 14, 26);
    doc.text(`Generated: ${date} ${time}`, 14, 32);

    doc.setFontSize(11);
    doc.setFont('helvetica', 'bold');
    doc.text('Summary', 14, 42);
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    const workers      = Math.max(1, results.numberOfWorkers || 1);
    const perWorkerSec = results.totalSeconds;
    const baselineSec  = perWorkerSec * workers;
    doc.text(`Pallets:           ${results.palletCount}`, 14, 49);
    doc.text(`Total Qty:         ${results.totalQty.toLocaleString()}`, 14, 55);
    doc.text(`Workers Assigned:  ${workers}`, 14, 61);
    doc.text(`Total Time:        ${results.displayHours}h ${results.displayMinutes}m`, 14, 67);

    // Workforce-impact block — the value of adding people, in concrete terms.
    doc.setFont('helvetica', 'bold');
    doc.text('Workforce Impact', 14, 79);
    doc.setFont('helvetica', 'normal');
    if (workers === 1) {
      doc.text('1 worker = baseline. Add more workers to see time savings.', 14, 86);
    } else {
      doc.text(`Solo baseline (1 worker):  ${_fmtSeconds(baselineSec)}`, 14, 86);
      doc.text(`With ${workers} workers:           ${_fmtSeconds(perWorkerSec)}`, 14, 92);
      doc.text(`Time saved:                ${_fmtSeconds(baselineSec - perWorkerSec)} (${Math.round((1 - 1 / workers) * 100)}%)`, 14, 98);
    }

    const phasesStartY = workers === 1 ? 96 : 110;
    autoTable(doc, {
      head: [['Warehouse Phase', 'Driver', 'Rate', 'Time']],
      body: [
        ...results.phaseBreakdown.map((p) => [
          p.name,
          `${p.driverValue.toLocaleString()} ${p.driver}${p.driverValue === 1 ? '' : 's'}`,
          `${p.ratePerUnit.toFixed(3)} sec/${p.driver}`,
          _fmtSeconds(p.timeSeconds),
        ]),
        ['Total Time', '', '', _fmtSeconds(results.totalSeconds)],
      ],
      startY: phasesStartY,
      theme: 'grid',
      headStyles: { fillColor: [38, 50, 110], textColor: [255, 255, 255], fontStyle: 'bold' },
      bodyStyles: { fontSize: 9 },
      alternateRowStyles: { fillColor: [245, 247, 250] },
    });

    // --- All Items, split per pallet, one pallet per page -----------
    // The user explicitly asked for: "ALL Items table section start with a
    // new page then divide the table per pallet. So display pallet 1 first,
    // then for the 2nd, start at the paper again."
    // We page-break before the section, group items by pallet, then
    // page-break between pallets.
    const itemsByPallet = (results.pallets || []).map((p) => ({
      palletId:       p.palletId,
      sourceFilename: p.sourceFilename,
      itemCount:      p.itemCount,
      totalQty:       p.totalQty,
      items:          (results.items || []).filter((it) => it.palletId === p.palletId),
    }));
    // Catch any orphan items that have a palletId not on results.pallets
    // (shouldn't happen in practice, but stay safe).
    const knownIds = new Set(itemsByPallet.map((g) => g.palletId));
    const orphan   = (results.items || []).filter((it) => !knownIds.has(it.palletId));
    if (orphan.length) {
      itemsByPallet.push({
        palletId: '(unassigned)',
        sourceFilename: '',
        itemCount: orphan.length,
        totalQty: orphan.reduce((s, it) => s + Number(it.qty || 0), 0),
        items: orphan,
      });
    }

    itemsByPallet.forEach((group, idx) => {
      doc.addPage(); // each pallet starts on a fresh page

      // Page header band
      doc.setFillColor(38, 50, 110);
      doc.rect(0, 0, doc.internal.pageSize.getWidth(), 26, 'F');
      doc.setTextColor(255, 255, 255);
      doc.setFontSize(11);
      doc.setFont('helvetica', 'bold');
      doc.text('All Items', 14, 12);
      doc.setFontSize(9);
      doc.setFont('helvetica', 'normal');
      doc.text(`Pallet ${idx + 1} of ${itemsByPallet.length}`, 14, 20);

      // Pallet title (large) — pallet ID prominent + meta line below
      doc.setTextColor(15, 23, 42);
      doc.setFontSize(16);
      doc.setFont('helvetica', 'bold');
      doc.text(group.palletId, 14, 40);

      doc.setFontSize(10);
      doc.setFont('helvetica', 'normal');
      doc.setTextColor(71, 85, 105);
      const metaLine = [
        group.sourceFilename ? `File: ${group.sourceFilename}` : null,
        `${group.items.length} item${group.items.length === 1 ? '' : 's'}`,
        `Total qty: ${(group.totalQty || 0).toLocaleString()}`,
      ].filter(Boolean).join('    ');
      doc.text(metaLine, 14, 47);

      // Item table for this pallet only
      autoTable(doc, {
        head: [['Item Code', 'Description', 'Qty', 'UOM']],
        body: group.items.map((it) => [
          it.itemCode || '',
          it.description || '',
          String(it.qty ?? ''),
          it.uom || '',
        ]),
        startY: 54,
        theme: 'grid',
        headStyles: {
          fillColor: [241, 245, 249],
          textColor: [15, 23, 42],
          fontStyle: 'bold',
          fontSize: 9,
          lineColor: [203, 213, 225],
        },
        bodyStyles: {
          fontSize: 9,
          textColor: [30, 41, 59],
          lineColor: [229, 231, 235],
        },
        alternateRowStyles: { fillColor: [248, 250, 252] },
        columnStyles: {
          0: { cellWidth: 40 },
          1: { cellWidth: 'auto' },
          2: { cellWidth: 22, halign: 'right' },
          3: { cellWidth: 22 },
        },
        margin: { left: 14, right: 14, top: 34 },
        didDrawPage: (data) => {
          // When the table itself spills to a continuation page, draw a
          // lighter "(continued)" band so the reader doesn't lose context.
          if (data.pageNumber === 1) return;
          doc.setFillColor(241, 245, 249);
          doc.rect(0, 0, doc.internal.pageSize.getWidth(), 18, 'F');
          doc.setTextColor(71, 85, 105);
          doc.setFontSize(9);
          doc.setFont('helvetica', 'italic');
          doc.text(`${group.palletId} (continued)`, 14, 12);
          doc.setFont('helvetica', 'normal');
          doc.setTextColor(15, 23, 42);
        },
      });
    });

    const fileDate = now.toISOString().split('T')[0];
    doc.save(`workload-${activeTab}-${tab.basis}-${fileDate}.pdf`);
  };

  // ----- Render --------------------------------------------------------

  const dropzoneClasses = `pdf-dropzone${isUploading ? ' pdf-dropzone-uploading' : ''}`;

  return (
    <div className="workload-main">
      <div className="workload-container">
        {/* Header */}
        <div className="workload-header">
          <div className="header-left1">
            <button
              className="main-card-btn action-button-export"
              style={{ padding: 10, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
              onClick={() => navigate('/analysis-report')}
              title="Back"
            >
              <ArrowLeft size={18} />
            </button>
            <h1 className="workload-title">Workload Analysis</h1>
            <p className="header-subtitle">
              Upload PMRL PDFs (one per pallet) to estimate inbound or outbound processing time.
            </p>
            {!isBackendConnected && (
              <div className="header-offline-banner" title={
                WORKLOAD_API_BASE.startsWith('http://localhost')
                  ? `Build is targeting ${WORKLOAD_API_BASE}. Set VITE_WORKLOAD_API_BASE before npm run build.`
                  : `Cannot reach ${WORKLOAD_API_BASE}. Sign in again or check that the API is up.`
              }>
                <AlertCircle size={14} />
                <span>Working in offline mode &mdash; results are computed locally and not saved.</span>
              </div>
            )}
          </div>
          <div className="header-actions">
            <button
              className="main-card-btn action-button-export header-history-btn"
              onClick={() => setShowHistory(true)}
              title="View your saved calculations"
              style={{ padding: 10 }}
              disabled={!isBackendConnected}
            >
              <Calendar size={18} />
              {historyCount > 0 && (
                <span className="header-history-count" aria-label={`${historyCount} saved calculations`}>
                  {historyCount > 99 ? '99+' : historyCount}
                </span>
              )}
            </button>
            <button
              className="main-card-btn action-button-export"
              onClick={exportToPDF}
              disabled={!tab.lastResults}
              title="Export current results to PDF"
              style={{ padding: 10 }}
            >
              <Download size={18} />
            </button>
            <button
              className="main-card-btn action-button-export"
              onClick={resetActiveTab}
              title={`Clear the ${TABS[activeTab].label} tab`}
              style={{ padding: 10 }}
            >
              <RefreshCw size={18} />
            </button>
            <button
              className="main-card-btn action-button-export"
              onClick={resetAll}
              title="Clear ALL tabs and saved state"
              style={{ padding: 10, background: '#b91c1c' }}
            >
              <Trash2 size={18} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="workload-tabs">
          {Object.entries(TABS).map(([tabId, meta]) => (
            <button
              key={tabId}
              className={`workload-tab${activeTab === tabId ? ' is-active' : ''}`}
              onClick={() => setActiveTab(tabId)}
            >
              {meta.label}
              {tabs[tabId].palletCards.length > 0 && (
                <span className="tab-pill">{tabs[tabId].palletCards.length}</span>
              )}
            </button>
          ))}
        </div>

        {/* Tab body */}
        <div className="workload-grid">
          {/* Left column: input form */}
          <div className="form-section">

            {/* 1. PDF dropzone + pallet cards (top: this is the primary action) */}
            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Pallet PDFs</h2>
              </div>
              <p className="section-description">
                Drop one or more PMRL PDFs here. Each PDF is treated as one pallet,
                identified by its <code>VRMSD</code> code. Multi-page tables are merged
                automatically.
              </p>

              <div
                className={dropzoneClasses}
                onClick={triggerFilePicker}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleFiles(e.dataTransfer.files);
                }}
                role="button"
                tabIndex={0}
              >
                <Upload size={28} />
                <div className="pdf-dropzone-text">
                  <strong>Click to choose PDFs</strong> or drag-and-drop multiple files
                </div>
                {isUploading && <div className="pdf-dropzone-status">Parsing…</div>}
                <input
                  ref={(r) => { fileInputRefs.current[activeTab] = r; }}
                  type="file"
                  accept="application/pdf"
                  multiple
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    handleFiles(e.target.files);
                    e.target.value = '';
                  }}
                />
              </div>

              {duplicateUploads.length > 0 && (
                <div className="upload-duplicates">
                  {duplicateUploads.map((d, i) => (
                    <div key={i} className="upload-duplicate">
                      <AlertCircle size={14} />
                      {d.kind === 'pallet' ? (
                        <span>
                          Pallet <strong>{d.palletId}</strong> was already on this tab &mdash;
                          replaced with the new upload from <em>{d.filename}</em>.
                        </span>
                      ) : (
                        <span>
                          <strong>{d.filename}</strong> matches a file you already uploaded.
                          The newer parse has replaced the existing pallet.
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {uploadErrors.length > 0 && (
                <div className="upload-errors">
                  {uploadErrors.map((err) => (
                    <div key={err.filename} className="upload-error">
                      <AlertCircle size={14} /> <strong>{err.filename}:</strong> {err.message}
                    </div>
                  ))}
                </div>
              )}

              {/* Pallet cards */}
              {tab.palletCards.length === 0 ? (
                <div className="empty-state" style={{ marginTop: 16 }}>
                  <Package size={40} className="empty-icon" />
                  <h3>No pallets staged</h3>
                  <p>Upload PDFs above, or add a pallet manually.</p>
                </div>
              ) : (
                <div className="pallet-list">
                  {tab.palletCards.map((card) => (
                    <PalletCard
                      key={card.palletId}
                      card={card}
                      uomList={uomList}
                      onUpdateItem={updateItem}
                      onRemoveItem={removeItem}
                      onAddItem={addItemToCard}
                      onRemoveCard={removePalletCard}
                    />
                  ))}
                </div>
              )}

              <button className="add-item-btn" onClick={addManualPallet}>
                <Plus size={16} /> Add Pallet Manually
              </button>
            </div>

            {/* 2. Calculation Method (Per Pallet / Per Piece) */}
            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Calculation Method</h2>
              </div>
              <p className="section-description">
                How is the workload measured? Inbound put-aways are usually
                <strong> Per Pallet</strong>; order picking is usually <strong>Per Piece</strong>.
                The choice changes which standard times are used below.
              </p>
              <div className="basis-toggle">
                {['per_pallet', 'per_piece'].map((b) => (
                  <button
                    key={b}
                    className={`basis-btn${tab.basis === b ? ' is-active' : ''}`}
                    onClick={() => setBasis(b)}
                  >
                    {b === 'per_pallet' ? 'Per Pallet' : 'Per Piece'}
                  </button>
                ))}
              </div>
            </div>

            {/* 3. Standard Times (was "Phase Rates"). Sits right under the
                  Calculation Method so the user sees them together. */}
            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Standard Times</h2>
              </div>
              <p className="section-description">
                Time per {tab.basis === 'per_pallet' ? 'pallet' : 'piece'} for the
                {' '}<strong>two {TABS[activeTab].label.toLowerCase().replace(' workload', '')}
                {' '}phases</strong>. {TABS[activeTab].label.replace(' Workload', '')} processing has
                exactly two phases in the time-and-motion study
                {' '}({TABS[activeTab].phases.join(' \u2192 ')}); the
                {' '}{activeTab === 'inbound' ? 'outbound' : 'inbound'} side has its own two
                phases on the other tab. Edit a value to override just this calculation,
                or save it as your default.
              </p>
              <button
                className="toggle-rates-btn"
                onClick={() => setShowRateSettings(!showRateSettings)}
              >
                {showRateSettings ? '\u2212 Hide times' : '+ Show times'}
                {config && !config.inheritedFromDefault && !config.isDefault && (
                  <span className="toggle-rates-status">&nbsp;&middot; using your saved values</span>
                )}
              </button>
              {showRateSettings && (
                <>
                  <div className="rates-grid">
                    {activeRateKeys.map((key) => {
                      const [phase, unit] = RATE_LABELS[key];
                      const current = tab.rateOverrides[key] ?? effectiveRates[key] ?? '';
                      const overridden = key in tab.rateOverrides;
                      return (
                        <div className={`rate-input-group${overridden ? ' is-overridden' : ''}`} key={key}>
                          <div className="rate-header">
                            <label className="rate-label">{phase}</label>
                            <span className="rate-description">{unit}</span>
                          </div>
                          <div className="rate-input-wrapper">
                            <input
                              type="number"
                              className="rate-input"
                              value={current}
                              min="0"
                              step="0.01"
                              onChange={(e) => setRateOverride(key, e.target.value)}
                            />
                            <span className="rate-suffix">{unit}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="rate-actions">
                    <button
                      className="rate-action-btn rate-action-btn--primary"
                      onClick={saveCurrentRatesToBackend}
                      disabled={!isBackendConnected || Object.keys(tab.rateOverrides).length === 0}
                      title="Saves these times to YOUR account only. Other users keep their own."
                    >
                      <Save size={14} /> Save my times
                    </button>
                    <button
                      className="rate-action-btn rate-action-btn--ghost"
                      onClick={clearRateOverrides}
                      disabled={Object.keys(tab.rateOverrides).length === 0}
                      title="Discards the edits above and goes back to your saved times."
                    >
                      Clear edits
                    </button>
                    <button
                      className="rate-action-btn rate-action-btn--danger"
                      onClick={resetRatesToOrgDefault}
                      disabled={!isBackendConnected || (config?.inheritedFromDefault ?? true)}
                      title="Deletes your saved times so this account goes back to the system defaults."
                    >
                      Reset to system defaults
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* 4. Workforce + calculate */}
            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Workforce</h2>
              </div>
              <p className="section-description">
                How many workers are sharing this job? Total time is divided across them
                evenly, so doubling the workers roughly halves the duration.
              </p>
              <WorkforceInput
                value={tab.workers}
                onChange={setWorkers}
                palletCount={tab.palletCards.length}
                totalQty={tab.palletCards.reduce(
                  (sum, c) => sum + (c.items || [])
                    .reduce((a, it) => a + _coerceNumeric(it.qty, 0), 0),
                  0,
                )}
                basis={tab.basis}
              />
              {calcError && (
                <div className="upload-error" style={{ marginBottom: 8 }}>
                  <AlertCircle size={14} /> {calcError}
                </div>
              )}
              <button
                className="calculate-btn"
                onClick={runCalculate}
                disabled={isCalculating || isLoadingConfig}
              >
                {isCalculating ? 'Calculating…' : 'Calculate Workload'}
              </button>
            </div>
          </div>

          {/* Right column: results (history is now a modal popup) */}
          <div className="results-section">
            {!tab.lastResults ? (
              <div className="empty-state">
                <Calculator size={48} className="empty-icon" />
                <h3>No Results Yet</h3>
                <p>Upload a PDF or add a manual pallet, set workers, then click <strong>Calculate Workload</strong>.</p>
              </div>
            ) : (
              <ResultsCard
                results={tab.lastResults}
                mode={activeTab}
                basis={tab.basis}
                isSaving={isSaving}
                isSaved={Boolean(tab.lastSavedAt || tab.lastResults?.id)}
                saveError={saveError}
                onSave={saveCurrentCalculation}
                onOpenHistory={() => setShowHistory(true)}
                isBackendConnected={isBackendConnected}
              />
            )}
          </div>
        </div>
      </div>

      {/* History popup (floats over the form). */}
      {showHistory && (
        <HistoryModal
          items={historyItems}
          loading={isLoadingHistory}
          error={historyError}
          expandedId={historyExpanded}
          onToggleExpand={(id) =>
            setHistoryExpanded((prev) => (prev === id ? null : id))
          }
          onRefresh={loadHistory}
          onDelete={deleteHistoryItem}
          onClose={() => setShowHistory(false)}
        />
      )}

      {/* Generic destructive-action confirm. */}
      <ConfirmModal
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Are you sure?'}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel}
        cancelLabel={confirmDialog?.cancelLabel}
        variant={confirmDialog?.variant}
        onConfirm={confirmDialog?.onConfirm}
        onCancel={() => setConfirmDialog(null)}
      />
    </div>
  );
};

// ---------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------

const PalletCard = ({ card, uomList, onUpdateItem, onRemoveItem, onAddItem, onRemoveCard }) => {
  const [expanded, setExpanded] = useState(true);
  const totalQty = (card.items || []).reduce((a, it) => a + _coerceNumeric(it.qty, 0), 0);

  return (
    <div className="pallet-card">
      <div className="pallet-card-head">
        <div className="pallet-card-meta">
          <span className="pallet-id-chip" title="VRMSD pallet ID">{card.palletId}</span>
          <span className="pallet-card-filename">
            <FileText size={12} /> {card.sourceFilename || '(no file)'}
          </span>
          <span className="pallet-card-counts">
            {(card.items || []).length} item{card.items?.length === 1 ? '' : 's'}
            {' '} &middot; {' '}
            <strong>{totalQty.toLocaleString()}</strong> qty
            {card.pages ? <> &middot; {card.pages} pages</> : null}
          </span>
        </div>
        <div className="pallet-card-actions">
          <button
            className="pallet-card-toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          <button
            className="pallet-card-remove"
            onClick={() => onRemoveCard(card.palletId)}
            title="Remove this pallet"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {card.warnings?.length > 0 && (
        <div className="pallet-card-warnings">
          {card.warnings.map((w, i) => (
            <div className="upload-error" key={i}>
              <AlertCircle size={12} /> {w}
            </div>
          ))}
        </div>
      )}

      {expanded && (
        <>
          <table className="pallet-items-table">
            <thead>
              <tr>
                <th style={{ width: '22%' }}>Item Code</th>
                <th>Description</th>
                <th style={{ width: '12%' }}>Qty</th>
                <th style={{ width: '14%' }}>UOM</th>
                <th style={{ width: '40px' }}></th>
              </tr>
            </thead>
            <tbody>
              {(card.items || []).map((it, idx) => (
                <tr key={idx}>
                  <td>
                    <input
                      className="cell-input"
                      type="text"
                      value={it.itemCode || ''}
                      onChange={(e) => onUpdateItem(card.palletId, idx, 'itemCode', e.target.value)}
                      placeholder="e.g., RMFD0081..."
                    />
                  </td>
                  <td>
                    <input
                      className="cell-input"
                      type="text"
                      value={it.description || ''}
                      onChange={(e) => onUpdateItem(card.palletId, idx, 'description', e.target.value)}
                      placeholder="Description"
                    />
                  </td>
                  <td>
                    <input
                      className="cell-input"
                      type="number"
                      min="0"
                      step="any"
                      value={it.qty ?? ''}
                      onChange={(e) => onUpdateItem(card.palletId, idx, 'qty', e.target.value)}
                    />
                  </td>
                  <td>
                    <select
                      className="cell-input"
                      value={it.uom || ''}
                      onChange={(e) => onUpdateItem(card.palletId, idx, 'uom', e.target.value)}
                    >
                      <option value="">(none)</option>
                      {(uomList.includes(it.uom) ? uomList : [...uomList, it.uom].filter(Boolean))
                        .map((u) => (
                          <option key={u} value={u}>{u}</option>
                        ))}
                    </select>
                  </td>
                  <td>
                    <button
                      className="remove-item-btn"
                      title="Remove row"
                      onClick={() => onRemoveItem(card.palletId, idx)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="add-item-btn add-item-inline" onClick={() => onAddItem(card.palletId)}>
            <Plus size={14} /> Add row
          </button>
        </>
      )}
    </div>
  );
};

const ResultsCard = ({ results, mode, basis,
                       isSaving, isSaved, saveError,
                       onSave, onOpenHistory, isBackendConnected }) => {
  // Per-worker share preview. Time is already divided by workers in
  // results.totalSeconds, so each worker's share equals the total when
  // workforce >= 1. We surface that explicitly because users keep asking
  // "what does changing the worker count actually do?"
  const workers      = Math.max(1, results.numberOfWorkers || 1);
  const perWorkerSec = results.totalSeconds; // already worker-adjusted (ideal even split)
  const baselineSec  = perWorkerSec * workers; // if it were a single worker
  return (
    <div className="results-content">
      <div className="section-card results-card">
        <div className="section-header">
          <h2 className="section-title">
            {TABS[mode].label} &middot; {basis === 'per_pallet' ? 'Per Pallet' : 'Per Piece'}
          </h2>
        </div>

        <div className="metrics-grid">
          <div className="metric-card primary">
            <div className="metric-content">
              <div className="metric-value">{results.displayHours}h {results.displayMinutes}m</div>
              <div className="metric-label">Total Time ({workers} {workers === 1 ? 'worker' : 'workers'})</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-content">
              <div className="metric-value">{results.palletCount}</div>
              <div className="metric-label">Pallets</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-content">
              <div className="metric-value">{results.totalQty.toLocaleString()}</div>
              <div className="metric-label">Total Qty</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-content">
              <div className="metric-value">{workers}</div>
              <div className="metric-label">Workers</div>
            </div>
          </div>
        </div>

        {workers > 1 && (
          <div className="results-staff-impact">
            <Users size={14} />
            <span>
              Solo, this job would take <strong>{_fmtSeconds(baselineSec)}</strong>.
              With {workers} workers it drops to <strong>{_fmtSeconds(perWorkerSec)}</strong>
              {' '}&mdash; a saving of <strong>{_fmtSeconds(baselineSec - perWorkerSec)}</strong>.
            </span>
          </div>
        )}

        <div className="breakdown-section">
          <h3 className="breakdown-title">Time by Phase</h3>
          <div className="breakdown-grid">
            {results.phaseBreakdown.map((p, i) => (
              <div key={i} className="breakdown-item">
                <span className="breakdown-label">
                  {p.name} <small>({p.driverValue.toLocaleString()} {p.driver}{p.driverValue === 1 ? '' : 's'} &times; {p.ratePerUnit.toFixed(3)} s/{p.driver})</small>
                </span>
                <span className="breakdown-value">{_fmtSeconds(p.timeSeconds)}</span>
              </div>
            ))}
            <div className="breakdown-item total">
              <span className="breakdown-label">Total</span>
              <span className="breakdown-value">{_fmtSeconds(results.totalSeconds)}</span>
            </div>
          </div>
        </div>

        {results.pallets?.length > 0 && (
          <div className="breakdown-section">
            <h3 className="breakdown-title">Pallets Included</h3>
            <div className="breakdown-grid">
              {results.pallets.map((p) => (
                <div key={p.palletId} className="breakdown-item-detailed">
                  <div className="item-detail-header">
                    <span className="breakdown-label">{p.palletId}</span>
                    <span className="breakdown-value">{p.itemCount} items</span>
                  </div>
                  <div className="item-detail-meta">
                    <span className="detail-rate">{p.sourceFilename}</span>
                    <span className="detail-hours">Total: {p.totalQty.toLocaleString()} qty</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="results-save-bar">
          {isSaved ? (
            <div className="results-footer">
              <CheckCircle2 size={14} />
              <span>Saved to your history</span>
              <button
                type="button"
                className="results-footer-link"
                onClick={onOpenHistory}
              >
                View history
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                className="results-save-btn"
                onClick={onSave}
                disabled={isSaving || !isBackendConnected}
                title={
                  isBackendConnected
                    ? 'Save this calculation to your history. You can find it again under the calendar icon.'
                    : 'Connect to the backend to save calculations.'
                }
              >
                <Save size={14} /> {isSaving ? 'Saving…' : 'Save Calculation'}
              </button>
              <span className="results-save-hint">
                {isBackendConnected
                  ? 'Not saved yet. Export PDF also auto-saves.'
                  : 'Backend offline — saving is disabled.'}
              </span>
            </>
          )}
        </div>
        {saveError && (
          <div className="upload-error" style={{ marginTop: 8 }}>
            <AlertCircle size={14} /> {saveError}
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------
// Workforce input — stepper + impact preview
// ---------------------------------------------------------------------

const WorkforceInput = ({ value, onChange, palletCount, totalQty, basis }) => {
  const n = parseInt(value || '0', 10) || 0;
  const set = (next) => onChange(String(Math.max(0, Math.min(999, next))));
  const driverLabel = basis === 'per_pallet' ? 'pallets' : 'pieces';
  const driverValue = basis === 'per_pallet' ? palletCount : totalQty;
  // When the user picks N workers, an equal split would mean each one handles
  // roughly driver/N units. We show that as a soft "expected per worker"
  // preview so they can sanity-check the team size.
  const perWorker = n > 0 ? Math.ceil(driverValue / n) : 0;

  return (
    <div className="workforce-input">
      <div className="workforce-stepper">
        <button
          type="button"
          className="workforce-step-btn"
          onClick={() => set(n - 1)}
          disabled={n <= 1}
          aria-label="Decrease workers"
        >
          <Minus size={16} />
        </button>
        <input
          type="number"
          className="workforce-stepper-value"
          min="1"
          step="1"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="—"
          aria-label="Workers"
        />
        <button
          type="button"
          className="workforce-step-btn"
          onClick={() => set(n + 1)}
          aria-label="Increase workers"
        >
          <Plus size={16} />
        </button>
        <span className="workforce-stepper-suffix">
          {n === 1 ? 'worker' : 'workers'}
        </span>
      </div>
      {n > 0 && driverValue > 0 && (
        <div className="workforce-hint">
          <Users size={13} />
          <span>
            ~<strong>{perWorker.toLocaleString()}</strong> {driverLabel} per worker
            {' '}if {driverValue.toLocaleString()} {driverLabel} are shared evenly
            across {n} {n === 1 ? 'person' : 'people'}.
          </span>
        </div>
      )}
    </div>
  );
};


// ---------------------------------------------------------------------
// ConfirmModal — replaces window.confirm() with a styled dialog.
// Controlled component: caller manages open/close state.
// ---------------------------------------------------------------------

const ConfirmModal = ({
  open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  variant = 'default', onConfirm, onCancel,
}) => {
  // Close on Escape; trap focus is intentionally light-weight (we don't
  // have a tonne of dialogs and this isn't an a11y-critical capstone path).
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape' && onCancel) onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget && onCancel) onCancel();
    }}>
      <div className="modal modal--confirm" role="dialog" aria-modal="true">
        <div className={`modal-icon modal-icon--${variant}`}>
          {variant === 'danger' ? <AlertCircle size={22} /> : <CheckCircle2 size={22} />}
        </div>
        <h3 className="modal-title">{title}</h3>
        <p className="modal-message">{message}</p>
        <div className="modal-actions">
          <button
            type="button"
            className="rate-action-btn rate-action-btn--ghost"
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={
              variant === 'danger'
                ? 'rate-action-btn rate-action-btn--danger-solid'
                : 'rate-action-btn rate-action-btn--primary'
            }
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------
// HistoryModal — centered popup that floats above the form (was the
// right-column drawer; users wanted to keep their form visible).
// ---------------------------------------------------------------------

const HistoryModal = ({ items, loading, error, expandedId,
                       onToggleExpand, onRefresh, onDelete, onClose }) => {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="modal modal--history" role="dialog" aria-modal="true">
        <div className="modal-head">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Calendar size={18} />
            <h3 className="modal-title" style={{ margin: 0 }}>Saved Calculations</h3>
            {items.length > 0 && (
              <span className="modal-head-count">
                {items.length}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="rate-action-btn rate-action-btn--ghost"
              onClick={onRefresh}
              disabled={loading}
              title="Reload from server"
            >
              <RefreshCw size={14} /> {loading ? 'Loading…' : 'Refresh'}
            </button>
            <button
              type="button"
              className="modal-close"
              onClick={onClose}
              title="Close"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <p className="section-description" style={{ margin: '0 0 12px 0' }}>
          Every <strong>Save Calculation</strong> click (or PDF export) lands
          here under your account. Only you can see or delete these rows.
        </p>

        <div className="modal-body">
          {error && (
            <div className="upload-error" style={{ marginBottom: 8 }}>
              <AlertCircle size={14} /> {error}
            </div>
          )}

          {loading && items.length === 0 ? (
            <div className="empty-state"><Clock size={36} className="empty-icon" /><p>Loading…</p></div>
          ) : items.length === 0 ? (
            <div className="empty-state">
              <Calendar size={36} className="empty-icon" />
              <h3>Nothing saved yet</h3>
              <p>
                Run <strong>Calculate Workload</strong>, review the results, then
                click <strong>Save Calculation</strong> to keep a copy here.
              </p>
            </div>
          ) : (
            <div className="history-list">
              {items.map((row) => {
                const expanded = expandedId === row.id;
                const modeLabel = row.mode === 'inbound' ? 'Inbound' : 'Outbound';
                const basisLabel = row.basis === 'per_pallet' ? 'Per Pallet' : 'Per Piece';
                return (
                  <div key={row.id} className={`history-row${expanded ? ' is-expanded' : ''}`}>
                    <button
                      type="button"
                      className="history-row-head"
                      onClick={() => onToggleExpand(row.id)}
                    >
                      <div className="history-row-main">
                        <span className="history-row-title">
                          {modeLabel} &middot; {basisLabel}
                        </span>
                        <span className="history-row-meta">
                          {_fmtSeconds(row.totalSeconds)} &middot;
                          {' '}{row.palletCount} pallet{row.palletCount === 1 ? '' : 's'} &middot;
                          {' '}{row.totalQty.toLocaleString()} qty &middot;
                          {' '}{row.numberOfWorkers} worker{row.numberOfWorkers === 1 ? '' : 's'}
                        </span>
                        <span className="history-row-when">{_fmtRelative(row.createdAt)}</span>
                      </div>
                      {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </button>
                    {expanded && (
                      <div className="history-row-body">
                        <div className="breakdown-grid">
                          {(row.phaseBreakdown || []).map((p, i) => (
                            <div key={i} className="breakdown-item">
                              <span className="breakdown-label">
                                {p.name} <small>({p.driverValue?.toLocaleString?.() ?? p.driverValue} {p.driver}{p.driverValue === 1 ? '' : 's'})</small>
                              </span>
                              <span className="breakdown-value">{_fmtSeconds(p.timeSeconds)}</span>
                            </div>
                          ))}
                        </div>
                        {(row.pallets || []).length > 0 && (
                          <div className="history-pallets">
                            <strong>Pallets:</strong>{' '}
                            {(row.pallets || []).map((p, i) => (
                              <span key={p.palletId || i} className="pallet-id-chip">{p.palletId}</span>
                            ))}
                          </div>
                        )}
                        <div className="history-row-actions">
                          <button
                            type="button"
                            className="rate-action-btn rate-action-btn--danger"
                            onClick={() => onDelete(row.id)}
                          >
                            <Trash2 size={14} /> Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WorkloadAnalysis;
