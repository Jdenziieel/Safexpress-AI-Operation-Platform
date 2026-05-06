import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { 
  Send, 
  Sparkles, 
  MessageSquare, 
  Trash2,
  Pencil,
  Check,
  Loader2,
  Clock,
  CheckCircle,
  XCircle,
  Menu,
  ListTodo,
  Paperclip,
  Activity,
  Zap,
  DollarSign,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Search,
  ClipboardList,
  Play,
  PenTool,
  Brain,
  FileText,
  Image as ImageIcon,
  MoreVertical,
  X,
  Cpu,
  BarChart3,
  AlertCircle,
  Square
} from "lucide-react";
import { getUserFromToken, getUserUUID } from "../utils/tokenManager";
import "../css/AIChatNew.css";
import { supervisorApi } from "../api";
import QuotaWidget from "./QuotaWidget";
import QuotaExceededModal from "./QuotaExceededModal";
import LLMErrorModal from "./LLMErrorModal";
import useWebSocketAgent from "../hooks/useWebSocketAgent";
import { dispatchQuotaRefresh } from "../hooks/useWebSocketQuota";
import Swal from "sweetalert2";

// Progress Step Component
function ProgressStep({ step, isActive, isCompleted }) {
  return (
    <div className={`progress-step ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''}`}>
      <div className="progress-step-indicator">
        {isCompleted ? (
          <CheckCircle size={16} className="step-icon completed" />
        ) : isActive ? (
          <Loader2 size={16} className="step-icon spinning" />
        ) : (
          <div className="step-dot" />
        )}
      </div>
      <div className="progress-step-content">
        <span className="step-name">{step.step_name || step.operation || 'Processing'}</span>
        {step.agent && <span className="step-agent">{step.agent}</span>}
      </div>
    </div>
  );
}

// Token Usage Badge Component
function TokenUsageBadge({ usage }) {
  if (!usage || usage.total_tokens === 0) return null;
  
  return (
    <div className="token-usage-badge">
      <Zap size={14} className="token-icon" />
      <span className="token-count">{usage.total_tokens?.toLocaleString() || 0}</span>
      <span className="token-label">tokens</span>
      {usage.total_cost_usd > 0 && (
        <span className="token-cost">
          <DollarSign size={12} />
          {usage.total_cost_usd.toFixed(4)}
        </span>
      )}
    </div>
  );
}

// Attachment Badge Component - shows file info on messages
function AttachmentBadge({ fileName, fileType, fileSize }) {
  if (!fileName) return null;

  const isImage = fileType && fileType.startsWith('image/');
  const Icon = isImage ? ImageIcon : FileText;

  const formatSize = (bytes) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="message-attachment-badge">
      <Icon size={14} className="attachment-badge-icon" />
      <span className="attachment-badge-name">{fileName}</span>
      {fileSize > 0 && (
        <span className="attachment-badge-size">{formatSize(fileSize)}</span>
      )}
    </div>
  );
}

// Stage configuration: maps backend status codes to display props
const STAGE_CONFIG = {
  analyzing:        { icon: Search,        label: 'Analyzing',       percent: 5  },
  understanding:    { icon: Brain,         label: 'Understanding',   percent: 15 },
  classifying:      { icon: ListTodo,      label: 'Classifying',     percent: 25 },
  planning:         { icon: ClipboardList, label: 'Planning',        percent: 35 },
  executing:        { icon: Play,          label: 'Executing',       percent: 55 },
  composing:        { icon: PenTool,       label: 'Composing',       percent: 90 },
};

const STAGE_ORDER = ['analyzing', 'understanding', 'classifying', 'planning', 'executing', 'composing'];

function InlineChatProgress({ progress, startTime }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startTime) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 500);
    return () => clearInterval(id);
  }, [startTime]);

  if (!progress) return null;
  
  const { current_step, total_steps, step_name, status } = progress;
  const stageCfg = STAGE_CONFIG[status] || STAGE_CONFIG.analyzing;
  const StageIcon = stageCfg.icon;

  // For executing steps, interpolate between 35% and 90%
  let barPercent = stageCfg.percent;
  if (status === 'executing' && total_steps > 0 && current_step > 0) {
    barPercent = 35 + ((current_step / total_steps) * 55);
  }

  const currentIdx = STAGE_ORDER.indexOf(status);

  return (
    <div className="inline-chat-progress">
      {/* Stage timeline */}
      <div className="stage-timeline">
        {STAGE_ORDER.map((stageKey, idx) => {
          const cfg = STAGE_CONFIG[stageKey];
          const Icon = cfg.icon;
          const isPast = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          return (
            <div key={stageKey} className={`stage-dot ${isPast ? 'past' : ''} ${isCurrent ? 'current' : ''}`}>
              <Icon size={14} />
            </div>
          );
        })}
      </div>

      {/* Main content */}
      <div className="inline-progress-header">
        <div className="inline-progress-icon">
          {status === 'executing' ? <StageIcon size={18} /> : <Loader2 size={18} className="spinner" />}
        </div>
        <div className="inline-progress-label">
          <span className="inline-progress-title">{step_name || stageCfg.label}</span>
          {status === 'executing' && total_steps > 0 && (
            <span className="inline-step-counter">Step {current_step}/{total_steps}</span>
          )}
        </div>
        {elapsed > 0 && (
          <div className="inline-elapsed">
            <Clock size={12} />
            <span>{elapsed}s</span>
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="inline-progress-bar-container">
        <div
          className="inline-progress-bar"
          style={{ width: `${Math.min(barPercent, 100)}%` }}
        />
      </div>
    </div>
  );
}

// Execution Progress Panel Component (collapsible panel version - kept for reference)
function ExecutionProgress({ progress, isVisible, onToggle }) {
  if (!progress || !progress.steps || progress.steps.length === 0) return null;

  const { current_step, total_steps, steps, status } = progress;
  const isExecuting = status === 'executing';

  return (
    <div className={`execution-progress-panel ${isVisible ? 'expanded' : 'collapsed'}`}>
      <button className="progress-toggle" onClick={onToggle}>
        <Activity size={16} />
        <span>Execution Progress</span>
        <span className="progress-summary">
          {current_step}/{total_steps} steps
        </span>
        {isVisible ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      
      {isVisible && (
        <div className="progress-steps-list">
          {steps.map((step, idx) => (
            <ProgressStep
              key={idx}
              step={step}
              isActive={idx + 1 === current_step && isExecuting}
              isCompleted={idx + 1 < current_step || status === 'completed'}
            />
          ))}
        </div>
      )}

      {isExecuting && (
        <div className="progress-status">
          <Loader2 size={14} className="spinner" />
          <span>Executing step {current_step} of {total_steps}...</span>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// THREAD TOKEN HISTORY MODAL
// =============================================================================
//
// Per-thread "Token consumption history" panel reachable from the chat
// header's Activity icon. Mirrors the SFXBot/QuotaPage UserHistoryModal
// pattern: KPI tiles up top, then a recent-activity table that defaults
// to "1 row per chat turn" (grouped by request_id) and expands to raw
// LLM-call rows when "Show details" is checked.
//
// Backend: GET /logs/stats?thread_id=<X>&period=<P>&include_calls=true
// (added in supervisor-logs-stats Lambda — returns token_summary +
// llm_calls[]). Threads with no LLM activity (e.g. pure Tier-0 greeting
// threads) render an explicit "No LLM calls yet" empty state rather than
// silently showing zeros.
// =============================================================================
const TIER_LABELS = {
  '0.5': 'Quick Check',
  '1': 'Full Analysis',
  'classifier': 'Agent Classifier',
  'planner': 'Plan Generation',
  'supervisor': 'Plan Generation',
  'formatter': 'Confirmation Fmt',
  'memory': 'Memory',
  'post': 'Post-Processing',
  'enrichment': 'Enrichment',
  'orchestrator': 'LLM Transform',
  'transform': 'LLM Transform',
  'summarization': 'Summarization',
};

const formatTokensShort = (t) => {
  const n = Number(t || 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
};

const formatCostShort = (c) => {
  const n = Number(c || 0);
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(6)}`;
};

const formatTimeShort = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: true,
    });
  } catch {
    return iso;
  }
};

function ThreadTokenHistoryModal({ threadId, threadTitle, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showDetails, setShowDetails] = useState(false);
  const [periodDays, setPeriodDays] = useState(30);

  const fetchData = useCallback(async () => {
    if (!threadId) return;
    setLoading(true);
    setError(null);
    try {
      const period = periodDays === 1 ? '24h' : `${periodDays}d`;
      const res = await supervisorApi.get('/logs/stats', {
        params: {
          thread_id: threadId,
          period,
          include_calls: 'true',
        },
      });
      setData(res.data);
    } catch (err) {
      console.error('Error fetching thread token stats:', err);
      setError(err.response?.data?.error || err.message || 'Failed to load token history');
    } finally {
      setLoading(false);
    }
  }, [threadId, periodDays]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totals = data?.token_summary?.totals || {};
  const byTier = data?.token_summary?.by_tier || [];
  const llmCalls = data?.llm_calls || [];

  // Group raw rows by request_id when "Show details" is OFF — collapses
  // a single chat turn (planner + classifier + formatter + Tier 1 + …)
  // into one summary line, mirroring the SFXBot Chat groupHistoryChatTurns
  // behavior. The ungrouped rows are kept on the cluster row so we can
  // surface the child count badge.
  const groupedRows = useMemo(() => {
    if (showDetails) return null;
    const groups = new Map();
    for (const row of llmCalls) {
      const key = row.request_id || row.id || row.timestamp || Math.random();
      if (!groups.has(key)) {
        groups.set(key, {
          request_id: row.request_id,
          earliest: row.timestamp,
          latest: row.timestamp,
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0,
          cost_usd: 0,
          duration_ms: 0,
          children: [],
          models: new Set(),
          tiers: new Set(),
        });
      }
      const g = groups.get(key);
      g.input_tokens += Number(row.input_tokens || 0);
      g.output_tokens += Number(row.output_tokens || 0);
      g.total_tokens += Number(row.total_tokens || 0);
      g.cost_usd += Number(row.estimated_cost_usd || row.cost_usd || 0);
      g.duration_ms += Number(row.duration_ms || 0);
      if (row.model) g.models.add(row.model);
      if (row.tier) g.tiers.add(row.tier);
      g.children.push(row);
      if ((row.timestamp || '') > (g.latest || '')) g.latest = row.timestamp;
      if ((row.timestamp || '') < (g.earliest || '') || !g.earliest) g.earliest = row.timestamp;
    }
    return Array.from(groups.values()).sort((a, b) =>
      (b.latest || '').localeCompare(a.latest || '')
    );
  }, [llmCalls, showDetails]);

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 9999, padding: 20,
      }}
    >
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Token consumption history for ${threadTitle || threadId}`}
        style={{
          background: '#fff', borderRadius: 12,
          width: '100%', maxWidth: 920, maxHeight: '85vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 20px 50px rgba(0,0,0,0.3)',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '20px 24px', borderBottom: '1px solid #e5e7eb',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16,
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600, letterSpacing: 0.5 }}>
              <Activity size={14} /> Token consumption history
            </div>
            <h2 style={{ margin: '6px 0 0 0', fontSize: 18, color: '#111827' }} title={`Thread ID: ${threadId}`}>
              {threadTitle || 'This conversation'}
            </h2>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <select
              value={periodDays}
              onChange={(e) => setPeriodDays(Number(e.target.value))}
              disabled={loading}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13 }}
            >
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button
              onClick={fetchData}
              disabled={loading}
              title="Refresh"
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 12px', background: '#3b82f6', color: '#fff',
                border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer',
              }}
            >
              <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
            </button>
            <button
              onClick={onClose}
              title="Close"
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 12px', background: '#6b7280', color: '#fff',
                border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer',
              }}
            >
              <X size={14} /> Close
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ padding: 24, overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 14px', background: '#fef2f2', color: '#991b1b',
              borderRadius: 8, marginBottom: 16, fontSize: 13,
            }}>
              <AlertCircle size={16} /> <span>{error}</span>
            </div>
          )}

          {loading && !data && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 24, color: '#6b7280' }}>
              <RefreshCw size={18} className="spin" /> <span>Loading history…</span>
            </div>
          )}

          {/* KPI tiles */}
          {data && (
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: 12, marginBottom: 20,
            }}>
              <div style={{ padding: 14, background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>
                  <Cpu size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> LLM Calls
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginTop: 4 }}>
                  {(totals.total_calls || 0).toLocaleString()}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                  {totals.successful_calls || 0} ok · {totals.failed_calls || 0} failed
                </div>
              </div>
              <div style={{ padding: 14, background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>
                  <Zap size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Tokens
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginTop: 4 }}>
                  {formatTokensShort(totals.total_tokens)}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                  In: {formatTokensShort(totals.total_input_tokens)} · Out: {formatTokensShort(totals.total_output_tokens)}
                </div>
              </div>
              <div style={{ padding: 14, background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>
                  <DollarSign size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Cost
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginTop: 4 }}>
                  {formatCostShort(totals.total_cost_usd)}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
                  this thread
                </div>
              </div>
              <div style={{ padding: 14, background: '#f9fafb', borderRadius: 10, border: '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600 }}>
                  <Clock size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Avg Latency
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginTop: 4 }}>
                  {totals.avg_duration_ms ? `${(totals.avg_duration_ms / 1000).toFixed(1)}s` : 'N/A'}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>per call</div>
              </div>
            </div>
          )}

          {/* By-tier breakdown */}
          {data && byTier.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                <BarChart3 size={14} style={{ verticalAlign: 'middle', marginRight: 4 }} /> By tier
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {byTier.map((row) => {
                  const pct = totals.total_tokens
                    ? ((row.tokens || 0) / totals.total_tokens) * 100
                    : 0;
                  return (
                    <div key={row.tier || 'none'} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '6px 10px', background: '#fafbfc', borderRadius: 6,
                    }}>
                      <span style={{ flex: '0 0 140px', fontSize: 12, color: '#374151' }}>
                        {TIER_LABELS[row.tier] || row.tier || 'Other'}
                      </span>
                      <span style={{ flex: '0 0 90px', fontSize: 11, color: '#6b7280' }}>
                        {row.calls} calls
                      </span>
                      <span style={{ flex: '0 0 80px', fontSize: 11, color: '#6b7280' }}>
                        {formatTokensShort(row.tokens)}
                      </span>
                      <div style={{ flex: 1, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{
                          width: `${pct}%`, height: '100%',
                          background: 'linear-gradient(90deg, #3b82f6, #6366f1)',
                        }} />
                      </div>
                      <span style={{ flex: '0 0 50px', fontSize: 11, color: '#6b7280', textAlign: 'right' }}>
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Recent activity table */}
          {data && (
            <div>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                gap: 12, marginBottom: 8,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#374151' }}>
                  Recent activity
                  <span style={{ fontSize: 11, color: '#9ca3af', fontWeight: 400, marginLeft: 8 }}>
                    {showDetails
                      ? '· raw events (every LLM call shown separately)'
                      : '· 1 row per chat turn (sub-calls merged in)'}
                  </span>
                </div>
                <label style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  fontSize: 12, color: '#374151', cursor: 'pointer',
                }}>
                  <input
                    type="checkbox"
                    checked={showDetails}
                    onChange={(e) => setShowDetails(e.target.checked)}
                    disabled={loading}
                  />
                  <span>Show details</span>
                </label>
              </div>

              {llmCalls.length === 0 ? (
                <div style={{
                  textAlign: 'center', padding: 32, color: '#6b7280', fontSize: 13,
                  background: '#f9fafb', borderRadius: 8, border: '1px dashed #e5e7eb',
                }}>
                  <Activity size={28} style={{ opacity: 0.4, marginBottom: 8 }} />
                  <div>No LLM calls recorded for this conversation yet.</div>
                  <div style={{ fontSize: 11, marginTop: 4, opacity: 0.7 }}>
                    Greetings and short replies are answered by Tier 0 without an LLM call, so they don't appear here.
                  </div>
                </div>
              ) : (
                <div style={{ overflowX: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead style={{ background: '#f9fafb' }}>
                      <tr>
                        <th style={{ padding: '8px 10px', textAlign: 'left', color: '#6b7280', fontWeight: 600 }}>When</th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', color: '#6b7280', fontWeight: 600 }}>Tier / Operation</th>
                        <th style={{ padding: '8px 10px', textAlign: 'right', color: '#6b7280', fontWeight: 600 }}>Input</th>
                        <th style={{ padding: '8px 10px', textAlign: 'right', color: '#6b7280', fontWeight: 600 }}>Output</th>
                        <th style={{ padding: '8px 10px', textAlign: 'right', color: '#6b7280', fontWeight: 600 }}>Total</th>
                        <th style={{ padding: '8px 10px', textAlign: 'right', color: '#6b7280', fontWeight: 600 }}>Cost</th>
                        <th style={{ padding: '8px 10px', textAlign: 'left', color: '#6b7280', fontWeight: 600 }}>Model</th>
                      </tr>
                    </thead>
                    <tbody>
                      {showDetails
                        ? llmCalls.map((row, idx) => (
                            <tr key={row.id || idx} style={{ borderTop: '1px solid #f3f4f6' }}>
                              <td style={{ padding: '8px 10px', color: '#374151' }}>{formatTimeShort(row.timestamp)}</td>
                              <td style={{ padding: '8px 10px', color: '#111827' }}>
                                <div style={{ fontWeight: 500 }}>{TIER_LABELS[row.tier] || row.tier || '—'}</div>
                                <div style={{ fontSize: 10, color: '#9ca3af' }}>{row.operation || ''}</div>
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', color: '#374151' }}>
                                {(row.input_tokens || 0).toLocaleString()}
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', color: '#374151' }}>
                                {(row.output_tokens || 0).toLocaleString()}
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: '#111827' }}>
                                {formatTokensShort(row.total_tokens)}
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', color: '#059669' }}>
                                {formatCostShort(row.estimated_cost_usd || row.cost_usd)}
                              </td>
                              <td style={{ padding: '8px 10px', color: '#6b7280', fontFamily: 'monospace', fontSize: 11 }}>
                                {row.model || '—'}
                              </td>
                            </tr>
                          ))
                        : (groupedRows || []).map((g, idx) => {
                            const tiersList = Array.from(g.tiers);
                            const modelsList = Array.from(g.models);
                            const childCount = g.children.length;
                            return (
                              <tr key={g.request_id || idx} style={{ borderTop: '1px solid #f3f4f6' }}>
                                <td style={{ padding: '8px 10px', color: '#374151' }}>{formatTimeShort(g.latest)}</td>
                                <td style={{ padding: '8px 10px', color: '#111827' }}>
                                  <div style={{ fontWeight: 500 }}>Chat turn</div>
                                  <div style={{ fontSize: 10, color: '#9ca3af' }}>
                                    {tiersList.length > 0 ? tiersList.map(t => TIER_LABELS[t] || t).join(' + ') : '—'}
                                    {childCount > 1 && (
                                      <span style={{
                                        marginLeft: 6, padding: '1px 6px', background: '#eef2ff',
                                        color: '#4338ca', borderRadius: 4, fontSize: 10, fontWeight: 600,
                                      }}
                                      title={`This row already includes ${childCount} sub-calls (planner / classifier / formatter / etc.). Toggle "Show details" to see them as separate rows.`}>
                                        {childCount} sub-calls
                                      </span>
                                    )}
                                  </div>
                                </td>
                                <td style={{ padding: '8px 10px', textAlign: 'right', color: '#374151' }}>
                                  {g.input_tokens.toLocaleString()}
                                </td>
                                <td style={{ padding: '8px 10px', textAlign: 'right', color: '#374151' }}>
                                  {g.output_tokens.toLocaleString()}
                                </td>
                                <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: '#111827' }}>
                                  {formatTokensShort(g.total_tokens)}
                                </td>
                                <td style={{ padding: '8px 10px', textAlign: 'right', color: '#059669' }}>
                                  {formatCostShort(g.cost_usd)}
                                </td>
                                <td style={{ padding: '8px 10px', color: '#6b7280', fontFamily: 'monospace', fontSize: 11 }}>
                                  {modelsList.length > 1 ? `${modelsList.length} models` : (modelsList[0] || '—')}
                                </td>
                              </tr>
                            );
                          })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AIChatNew() {
  // Helper to get user ID from JWT token (secure, not from localStorage)
  const getUserId = () => {
    return getUserUUID() || "default_user";
  };

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [threadId, setThreadId] = useState(null);
  const [isLoadingThread, setIsLoadingThread] = useState(false);
  const [threads, setThreads] = useState([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(false);
  const [pendingActions, setPendingActions] = useState([]);
  const [isFetchingPending, setIsFetchingPending] = useState(false);
  const [showThreads, setShowThreads] = useState(false);
  const [showActions, setShowActions] = useState(false);
  // Token-history modal — opens from the chat header's Activity icon.
  // Scoped to the current thread; useless when threadId is null
  // (so the button is hidden in that case).
  const [showTokenHistory, setShowTokenHistory] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [executionProgress, setExecutionProgress] = useState(null);
  const [showProgress, setShowProgress] = useState(true);
  const [tokenUsage, setTokenUsage] = useState({ total_tokens: 0, total_cost_usd: 0 });
  const [currentRequestId, setCurrentRequestId] = useState(null);
  // Inline progress state - shows current execution status in chat area
  const [inlineProgress, setInlineProgress] = useState(null);
  const [progressStartTime, setProgressStartTime] = useState(null);
  // Quota exceeded modal state
  const [showQuotaModal, setShowQuotaModal] = useState(false);
  const [quotaInfo, setQuotaInfo] = useState(null);
  // LLM Error modal state
  const [llmError, setLlmError] = useState(null);
  const [showLlmErrorModal, setShowLlmErrorModal] = useState(false);
  const [lastUserMessage, setLastUserMessage] = useState("");
  const [editingThreadId, setEditingThreadId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [openThreadMenuId, setOpenThreadMenuId] = useState(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const progressPollingRef = useRef(null);
  // Tracks the in-flight assistant message id between sendAgentMessage and
  // the matching `complete` / `error` / `paused` frame. Refs (not state)
  // because the WS callbacks are registered once and need a stable handle.
  const pendingAssistantIdRef = useRef(null);

  // AI Assistant WebSocket — speaks `sendAgentMessage` against the same
  // kb-lambda WebSocket API as KB chat. The supervisor lambda streams
  // status/progress/complete frames back over this socket so we no longer
  // need the legacy `ws://localhost:8010/ws/threads/.../progress` channel.
  // See websocket.md §5 for the protocol.
  const agentWs = useWebSocketAgent();
  // Production deployments set VITE_WS_URL to the kb-lambda WebSocket API
  // (e.g. wss://3lt9ozkq6k.execute-api.<region>.amazonaws.com/prod). When
  // it's unset (typical local dev), we fall through to the HTTP path
  // against the localhost supervisor.
  const isAgentWsConfigured = Boolean(import.meta.env.VITE_WS_URL);

  /**
   * Translate a supervisor `progress` frame into the shape InlineChatProgress
   * already understands. The wire schema differs slightly between the
   * legacy `/ws/threads/{id}/progress` channel and the new `sendAgentMessage`
   * stream — this normalises both into one local representation.
   */
  const applyAgentProgress = (data = {}) => {
    setInlineProgress({
      current_step: data.current_step ?? data.step ?? 0,
      total_steps:  data.total_steps ?? 0,
      step_name:    data.step_name || data.tool || data.message || 'Processing...',
      agent:        data.agent || null,
      status:       data.status || 'executing',
      message:      data.message || data.step_name || 'Working on your request...',
    });
  };

  /**
   * Wire the WS hook callbacks once. They read latest props/state via the
   * pendingAssistantIdRef + setMessages closure-free updater pattern.
   */
  useEffect(() => {
    agentWs.onStatus((data) => {
      // `status` is informational ("received", "analyzing", "planning", ...).
      // We surface it on the inline progress card while we wait for the
      // first `progress` frame with concrete step counts. Functional
      // setters are required here because this callback is bound once
      // on mount and would otherwise read stale state via closure.
      setProgressStartTime((prev) => prev || Date.now());
      setInlineProgress((prev) => ({
        current_step: prev?.current_step || 0,
        total_steps:  prev?.total_steps || 0,
        step_name:    data.message || data.status || 'Working...',
        agent:        prev?.agent || null,
        status:       data.status || 'analyzing',
        message:      data.message || data.status || 'Working...',
      }));
    });

    agentWs.onProgress((payload) => {
      applyAgentProgress(payload);
    });

    // Live-update the sidebar when supervisor-ws-chat auto-titles the
    // thread on its first real message. The supervisor sends
    // `generated_title` on the FIRST `complete` / `paused` after the
    // backfill (subsequent turns omit the field). Mirrors SFXBot's
    // pattern — without this, AIChatNew's sidebar shows
    // "New Conversation" until the next page refresh even though the
    // DDB row was correctly updated. We key off `data.thread_id`
    // (not the `threadId` closure) so a user who switched threads
    // while the WS reply was in flight still sees the right thread
    // get retitled.
    const applyGeneratedTitle = (data) => {
      const newTitle = data?.generated_title;
      const targetThreadId = data?.thread_id;
      if (!newTitle || !targetThreadId) return;
      setThreads((prev) => prev.map((t) =>
        t.thread_id === targetThreadId ? { ...t, title: newTitle } : t
      ));
    };

    agentWs.onPaused((data) => {
      // Workflow paused for HITL approval. The assistant message becomes
      // an explanatory placeholder; the actual approval prompt is fetched
      // separately via `fetchPendingActions()`.
      const assistantId = pendingAssistantIdRef.current;
      const text = data.response || 'Awaiting your approval to continue.';
      if (assistantId) {
        setMessages((prev) => prev.map((msg) =>
          msg.id === assistantId ? { ...msg, content: text } : msg
        ));
      }
      setInlineProgress(null);
      setIsStreaming(false);
      applyGeneratedTitle(data);
      // Pull the pending action so the existing approval UI picks it up.
      fetchPendingActions();
      // Pause still consumes tokens for Tier 0/0.5/1 + planner before the
      // pause point. The quota widget is on a SEPARATE WebSocket connection
      // (useWebSocketQuota) so the supervisor's per-connection `paused`
      // push only reaches the chat hook here — not the quota hook. Bridge
      // the two via the shared `quota:refresh` CustomEvent so the sidebar
      // KPI updates the moment the assistant pauses (mirrors SFXBot.jsx).
      dispatchQuotaRefresh('ai-assistant-paused');
    });

    agentWs.onComplete((data) => {
      const assistantId = pendingAssistantIdRef.current;
      const fullResponse = data.response || 'No response received from the assistant.';
      if (assistantId) {
        setMessages((prev) => prev.map((msg) =>
          msg.id === assistantId ? { ...msg, content: fullResponse } : msg
        ));
      }
      pendingAssistantIdRef.current = null;
      setInlineProgress(null);
      setIsStreaming(false);
      applyGeneratedTitle(data);
      // Same cross-hook bridge as the paused branch above. Without this
      // the Token Usage widget stays stale until the next 2-minute
      // fallback poll fires (or the user refreshes the page). Reported
      // by user "Why is token quota widget not updating real time too?".
      dispatchQuotaRefresh('ai-assistant-complete');
    });

    agentWs.onError((data) => {
      const assistantId = pendingAssistantIdRef.current;
      const reason = data.reason || 'UNKNOWN';
      const message = data.message || 'Something went wrong.';

      // Map structured error reasons to the existing modal flows so the
      // user gets the same UX as the HTTP path's error responses.
      if (reason === 'QUOTA_EXCEEDED') {
        setShowQuotaModal(true);
        if (assistantId) {
          setMessages((prev) => prev.map((msg) =>
            msg.id === assistantId
              ? {
                  ...msg,
                  content: '⚠️ Your token quota has been exceeded. Please wait for your quota to reset or contact an administrator.',
                  error: true,
                }
              : msg
          ));
        }
        pendingAssistantIdRef.current = null;
        setInlineProgress(null);
        setIsStreaming(false);
        return;
      }

      if (
        reason === 'BRAIN_IMPORT_FAILED' ||
        message.toLowerCase().includes('rate limit') ||
        message.toLowerCase().includes('billing')
      ) {
        setLlmError({
          error_type: reason.toLowerCase(),
          title: 'AI Service Error',
          user_message: message,
          message,
        });
        setShowLlmErrorModal(true);
        if (assistantId) {
          setMessages((prev) => prev.filter((msg) => msg.id !== assistantId));
        }
        pendingAssistantIdRef.current = null;
        setInlineProgress(null);
        setIsStreaming(false);
        return;
      }

      if (assistantId) {
        setMessages((prev) => prev.map((msg) =>
          msg.id === assistantId
            ? { ...msg, content: `Sorry, I encountered an error: ${message}. Please try again.`, error: true }
            : msg
        ));
      }
      pendingAssistantIdRef.current = null;
      setInlineProgress(null);
      setIsStreaming(false);
    });
    // We intentionally bind these callbacks once on mount. The hook stores
    // them in a ref internally so re-binding on every render isn't useful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Safety net: if the agent socket drops while we're mid-stream (no
  // terminal frame received) the in-flight assistant message would
  // otherwise stay stuck on "..." forever and the textarea would stay
  // disabled. When connectionStatus flips to 'disconnected' AND we have
  // a pending assistant id, we surface a retry prompt and reset the
  // streaming flag so the user can try again. The hook's auto-reconnect
  // will rebuild the socket; the message itself isn't replayed (we'd
  // need the supervisor to support resume tokens for that).
  useEffect(() => {
    if (agentWs.connectionStatus === 'disconnected' && pendingAssistantIdRef.current) {
      const assistantId = pendingAssistantIdRef.current;
      setMessages((prev) => prev.map((msg) =>
        msg.id === assistantId
          ? {
              ...msg,
              content: 'Connection dropped before the response completed. Please try again.',
              error: true,
            }
          : msg
      ));
      pendingAssistantIdRef.current = null;
      setInlineProgress(null);
      setIsStreaming(false);
    }
  }, [agentWs.connectionStatus]);

  // Disconnect WebSocket and cancel any in-flight progress polling.
  const disconnectProgressWebSocket = () => {
    pendingAssistantIdRef.current = null;
    stopProgressPolling();
  };

  // Fallback: Poll progress from backend during execution
  const pollProgress = async (targetThreadId) => {
    try {
      const response = await supervisorApi.get(`/threads/${targetThreadId}/progress`);
      return response.data;
    } catch (error) {
      console.warn('Progress polling error:', error);
      return null;
    }
  };

  // Start polling progress for a thread (fallback when WebSocket fails)
  const startProgressPolling = (targetThreadId) => {
    // Clear any existing polling
    stopProgressPolling();
    
    console.log('📊 Starting progress polling (fallback) for thread:', targetThreadId);
    
    setProgressStartTime(Date.now());
    setInlineProgress({
      current_step: 0,
      total_steps: 0,
      step_name: 'Analyzing your message...',
      agent: null,
      status: 'analyzing',
      message: 'Analyzing your message...'
    });
    
    // Poll immediately, then every 1.5 seconds
    const poll = async () => {
      const progressData = await pollProgress(targetThreadId);
      
      if (progressData) {
        // Update inline progress with real backend data
        setInlineProgress({
          current_step: progressData.current_step || 0,
          total_steps: progressData.total_steps || 0,
          step_name: progressData.step_name || 'Processing...',
          agent: progressData.agent || null,
          status: progressData.status || 'executing',
          message: progressData.step_name || 'Working on your request...'
        });
        
        // Update token usage if available
        if (progressData.token_usage) {
          setTokenUsage(prev => ({
            total_tokens: progressData.token_usage.total_tokens || prev.total_tokens,
            total_cost_usd: progressData.token_usage.total_cost_usd || prev.total_cost_usd,
            llm_calls: progressData.token_usage.llm_calls || prev.llm_calls
          }));
        }
        
        // Stop polling if execution is complete (not executing or processing)
        if (progressData.status !== 'executing' && progressData.status !== 'processing') {
          console.log('📊 Execution status changed to:', progressData.status, '- stopping polling');
          stopProgressPolling();
        }
      }
    };
    
    // First poll immediately
    poll();
    
    // Then poll every 1.5 seconds
    progressPollingRef.current = setInterval(poll, 1500);
  };

  // Stop polling progress
  const stopProgressPolling = () => {
    if (progressPollingRef.current) {
      console.log('📊 Stopping progress polling');
      clearInterval(progressPollingRef.current);
      progressPollingRef.current = null;
    }
  };

  // Cleanup WebSocket and polling on unmount
  useEffect(() => {
    return () => {
      disconnectProgressWebSocket();
      stopProgressPolling();
    };
  }, []);

  // Open the agent WebSocket eagerly when configured. Connecting on mount
  // (instead of lazily on send) gives the API Gateway handshake time to
  // settle before the user types their first message, so the WS path is
  // taken on the very first send instead of falling back to HTTP.
  useEffect(() => {
    if (!isAgentWsConfigured) return undefined;
    agentWs.connect();
    return () => {
      // Hook owns its own teardown on unmount, but we explicitly call
      // disconnect here to also cancel any pending reconnect timer.
      agentWs.disconnect();
    };
    // agentWs.connect / .disconnect are stable (useCallback []), so this
    // effect only fires once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAgentWsConfigured]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  useEffect(() => {
    loadOrCreateThread();
  }, []);

  // Note: No polling - threads/messages are fetched on mount and after user actions
  // (send message, create thread, delete thread, switch thread)

  const fetchThreads = async () => {
    setIsLoadingThreads(true);
    try {
      const userId = getUserId();
      const response = await supervisorApi.get(`/threads?user_id=${userId}`);
      console.log("Fetched threads:", response.data);
      setThreads(response.data.threads || []);
    } catch (error) {
      console.error("Error fetching threads:", error);
    } finally {
      setIsLoadingThreads(false);
    }
  };

  const handleThreadSelect = async (thread_id) => {
    if (thread_id === threadId) return;
    
    setIsLoadingThread(true);
    try {
      await loadThreadMessages(thread_id);
      setThreadId(thread_id);
    } catch (error) {
      console.error("Error switching threads:", error);
    } finally {
      setIsLoadingThread(false);
    }
  };

  const handleDeleteThread = async (thread_id, e) => {
    e.stopPropagation();

    // Mirror SFXBot's `handleDeleteClick` styling so both surfaces feel
    // consistent — same warning icon, same brand-navy cancel, same
    // alarming-red confirm, same reverseButtons layout (cancel on the
    // LEFT, destructive on the RIGHT). The native `confirm()` we used
    // before was visually jarring against the rest of the app and
    // failed accessibility heuristics on touch devices.
    const thread = threads.find((t) => t.thread_id === thread_id);
    const titleSnippet = thread?.title || `${thread_id.substring(0, 12)}…`;

    const result = await Swal.fire({
      icon: "warning",
      title: "Delete Conversation?",
      html: `Are you sure you want to delete the conversation:<br><br><strong>"${titleSnippet}"</strong><br><br>This action cannot be undone.`,
      showCancelButton: true,
      confirmButtonText: "Yes, Delete",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#ef4444",
      cancelButtonColor: "#26326e",
      reverseButtons: true,
      iconColor: "#fcb117",
    });

    if (!result.isConfirmed) return;

    try {
      await supervisorApi.delete(`/threads/${thread_id}`);
      await fetchThreads();

      if (thread_id === threadId) {
        await createNewThread();
      }

      // Toast-style success that auto-dismisses — matches the
      // post-delete confirmation in SFXBot but uses a less-intrusive
      // toast variant since the sidebar already reflects the deletion
      // visually (the row is gone). Heavier modal would feel redundant.
      await Swal.fire({
        toast: true,
        position: "top-end",
        icon: "success",
        title: "Conversation deleted",
        showConfirmButton: false,
        timer: 2200,
        timerProgressBar: true,
      });
    } catch (error) {
      console.error("Error deleting thread:", error);
      await Swal.fire({
        icon: "error",
        title: "Delete failed",
        text:
          error?.response?.data?.detail ||
          error?.message ||
          "An error occurred while deleting the conversation.",
        confirmButtonColor: "#26326e",
      });
    }
  };

  const startEditingTitle = (thread_id, currentTitle, e) => {
    e.stopPropagation();
    setEditingThreadId(thread_id);
    setEditingTitle(currentTitle || "");
  };

  // Set true while a PUT /threads/:id is in flight. Two distinct call
  // sites can fire `handleRenameThread` for the SAME edit — the
  // input's onKeyDown=Enter AND its onBlur (Enter blurs the input,
  // which triggers blur, which would fire a second PUT). Without this
  // guard you get duplicate API calls and a duplicate `await
  // fetchThreads()`. The guard lets the first call own the save and
  // the second one no-op, while still cleaning up the editing state
  // exactly once.
  const renamingRef = useRef(false);

  const handleRenameThread = useCallback(async (thread_id) => {
    if (renamingRef.current) return;
    renamingRef.current = true;

    const trimmed = editingTitle.trim();
    const original = threads.find((t) => t.thread_id === thread_id)?.title || "";

    // Empty input or unchanged title → silent no-op (no PUT, no toast).
    if (!trimmed || trimmed === original) {
      setEditingThreadId(null);
      setEditingTitle("");
      renamingRef.current = false;
      return;
    }

    try {
      await supervisorApi.put(`/threads/${thread_id}`, { title: trimmed });
      // Optimistic update — flip the local title immediately so the
      // sidebar re-renders before the threads-fetch round-trip lands.
      // Mirrors SFXBot's `handleSaveTitle` which does the same.
      setThreads((prev) => prev.map((t) =>
        t.thread_id === thread_id ? { ...t, title: trimmed } : t
      ));
      // Background refetch reconciles in case the backend normalized
      // the title (trimmed whitespace, length cap, etc).
      fetchThreads().catch(() => {});
    } catch (error) {
      console.error("Error renaming thread:", error);
      Swal.fire({
        icon: "error",
        title: "Rename failed",
        text:
          error?.response?.data?.detail ||
          error?.message ||
          "Could not rename the conversation. Please try again.",
        confirmButtonColor: "#26326e",
      });
    } finally {
      setEditingThreadId(null);
      setEditingTitle("");
      renamingRef.current = false;
    }
  }, [editingTitle, threads]);

  // Enter saves, Escape cancels — mirrors SFXBot's
  // `handleTitleKeyDown`. preventDefault on Enter is important: some
  // ancestor key handlers (e.g. textarea event delegation) would
  // otherwise also see the keystroke.
  const handleTitleKeyDown = useCallback((e, thread_id) => {
    if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      handleRenameThread(thread_id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setEditingThreadId(null);
      setEditingTitle("");
    }
  }, [handleRenameThread]);

  const loadOrCreateThread = async () => {
    setIsLoadingThread(true);
    try {
      const userId = getUserId();
      const response = await supervisorApi.get(`/threads?user_id=${userId}`);
      const threadsData = response.data;
      console.log("Fetched conversations:", threadsData);

      if (threadsData.threads && threadsData.threads.length > 0) {
        const latestThread = threadsData.threads[0];
        setThreadId(latestThread.thread_id);
        await loadThreadMessages(latestThread.thread_id);
        setIsLoadingThread(false);
        console.log("Loaded existing thread:", latestThread.thread_id);
        await fetchThreads();
        return;
      }
      
      setMessages([]);
      setThreadId(null);
      setIsLoadingThread(false);
      await fetchThreads();
      
    } catch (error) {
      console.error("Error loading or creating thread:", error);
      setMessages([]);
      setThreadId(null);
      setIsLoadingThread(false);
    }
  };

  const createNewThread = async () => {
    try {
      setMessages([]);
      setThreadId(null);
      setPendingActions([]);
      setExecutionProgress(null);
      setTokenUsage({ total_tokens: 0, total_cost_usd: 0 });
      setCurrentRequestId(null);
      
      console.log("✅ Ready for new thread (will be created on first message)");
      await fetchThreads();
      
    } catch (error) {
      console.error("Error preparing new thread:", error);
      setMessages(prev => [...prev, {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: `Failed to start a new conversation: ${error.message}`,
        timestamp: new Date(),
        error: true,
      }]);
    } finally {
      setIsLoadingThread(false);
    }
  };

  // Fetch logs for a specific request to show progress
  const fetchRequestProgress = async (requestId) => {
    if (!requestId) return;
    
    try {
      const response = await supervisorApi.get(`/logs/requests/${requestId}`);
      const data = response.data;
      
      // Extract execution steps from logs
      const progressLogs = data.logs.filter(log => 
        log.level === 'PROGRESS' || 
        (log.component === 'orchestrator' && log.operation === 'agent_call')
      );
      
      // Build progress state from logs
      const steps = progressLogs.map(log => ({
        step_name: log.data?.step_name || log.data?.tool || log.operation,
        agent: log.data?.agent,
        current_step: log.data?.current_step || log.data?.step,
        total_steps: log.data?.total_steps,
        success: log.data?.success,
        duration_ms: log.data?.duration_ms
      }));
      
      // Update token usage from summary
      if (data.summary) {
        setTokenUsage({
          total_tokens: data.summary.total_tokens || 0,
          total_cost_usd: data.summary.total_cost_usd || 0,
          llm_calls: data.summary.llm_calls || 0
        });
      }
      
      // Get the latest progress info
      const latestProgress = progressLogs[progressLogs.length - 1]?.data || {};
      
      setExecutionProgress({
        current_step: latestProgress.current_step || steps.length,
        total_steps: latestProgress.total_steps || steps.length,
        steps: steps,
        status: 'executing'
      });
      
    } catch (error) {
      console.error("Error fetching request progress:", error);
    }
  };

  // Fetch overall token stats
  const fetchTokenStats = async () => {
    try {
      const response = await supervisorApi.get('/logs/stats');
      const data = response.data;
      if (data.token_summary?.totals) {
        // Store for potential display in a stats panel
        console.log("Token stats:", data.token_summary.totals);
      }
    } catch (error) {
      console.error("Error fetching token stats:", error);
    }
  };

  const loadThreadMessages = async (thread_id) => {
    try {
      const response = await supervisorApi.get(`/threads/${thread_id}/messages`);
      const data = response.data;
      console.log("Loaded thread messages:", data);

      const formattedMessages = (data.messages || []).map((msg, idx) => {
        const m = {
          id: msg.message_id || `msg-${thread_id}-${idx}`,
          role: msg.role || "assistant",
          content: msg.content || "No content",
          timestamp: msg.created_at ? new Date(msg.created_at) : new Date(),
        };
        if (msg.file_name) {
          m.file_name = msg.file_name;
          m.file_type = msg.file_type;
          m.file_size = msg.file_size;
        }
        return m;
      });
      setMessages(formattedMessages);
      console.log(`✅ Loaded ${formattedMessages.length} messages for thread ${thread_id}`);
    } catch (error) {
      console.error("Error loading messages:", error);
      setMessages(prev => [...prev, {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: `Failed to load messages: ${error.message}`,
        timestamp: new Date(),
        error: true,
      }]);
    }
  };

  const fetchPendingActions = async () => {
    if (isFetchingPending) return;
    setIsFetchingPending(true);
    try {
      const response = await supervisorApi.get('/actions/pending');
      console.log("Fetched pending actions:", response.data);
      setPendingActions(response.data.pending_actions || []);
    } catch (error) {
      console.error("Error fetching pending actions:", error);
    } finally {
      setIsFetchingPending(false);
    }
  };

  const cleanupExpiredActions = async () => {
    try {
      const response = await supervisorApi.post('/actions/cleanup');
      console.log(`🧹 Cleaned up ${response.data.cleaned_count} expired actions`);
    } catch (error) {
      console.error("Error cleaning up actions:", error);
    }
  };

  const handleNewChat = async () => {
    console.log("🆕 Starting new chat...");
    setMessages([]);
    setPendingActions([]);
    setThreadId(null);
    await cleanupExpiredActions();
    await createNewThread();
    textareaRef.current?.focus();
  };

  const handleApproveAction = async (actionId) => {
    try {
      const response = await supervisorApi.post(`/action/approve/${actionId}`, { decision: 'approve' });
      const result = response.data;
      console.log("Action approved:", result);
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      setMessages(prev => [...prev, {
        id: `approval-${actionId}`,
        role: "assistant",
        content: `Action "${result.step_info?.description || 'Unknown Action'}" approved and executed.`,
        timestamp: new Date(),
        info: true,
      }]);
    } catch (error) {
      console.error("Error approving action:", error);
      setMessages(prev => [...prev, {
        id: `approval-error-${actionId}`,
        role: "assistant",
        content: `Failed to approve action ${actionId}: ${error.message}`,
        timestamp: new Date(),
        error: true,
      }]);
    }
  };

  const handleRejectAction = async (actionId) => {
    try {
      const response = await supervisorApi.post(`/action/approve/${actionId}`, { decision: 'reject' });
      const result = response.data;
      console.log("Action rejected:", result);
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      setMessages(prev => [...prev, {
        id: `rejection-${actionId}`,
        role: "assistant",
        content: `❌ Action was rejected and will not be executed.`,
        timestamp: new Date(),
        info: true,
      }]);
    } catch (error) {
      console.error("Error rejecting action:", error);
      setMessages(prev => [...prev, {
        id: `rejection-error-${actionId}`,
        role: "assistant",
        content: `Failed to reject action ${actionId}: ${error.message}`,
        timestamp: new Date(),
        error: true,
      }]);
    }
  };

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files);
    setAttachedFiles(prev => [...prev, ...files]);
    // Clear the input value so picking the SAME file again (or re-picking a
    // file the user just removed via the X chip) re-fires onChange. Without
    // this reset, browsers suppress the change event when the new selection
    // equals the previous one — which made the paperclip silently no-op
    // until the user refreshed the page.
    if (e.target) {
      e.target.value = '';
    }
  };

  const handleRemoveFile = (index) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handlePaperclipClick = () => {
    fileInputRef.current?.click();
  };

  // Stop the in-flight supervisor run from the user's POV.
  //
  // The hook's `cancelStreaming()` flips a flag that swallows every
  // post-cancel WS frame for this run; it deliberately does NOT close
  // the socket (the AI Assistant uses one persistent WS across many
  // messages — closing would force a fresh handshake on the next
  // send). We then mirror that into local component state: stop the
  // composer's "AI is thinking..." chrome, drop any in-progress
  // assistant bubble that hasn't streamed any content yet, and stamp
  // a "Stopped by user" marker on a half-streamed bubble so the user
  // has a visual cue that the result they see is incomplete.
  //
  // Caveat documented at the hook: tool actions that already executed
  // (sent emails, doc/calendar writes, drive moves) are NOT undone —
  // there is no server-side cancel endpoint today. DANGEROUS-tier
  // tools require explicit approval before executing so the blast
  // radius is bounded; LLM-thinking and orchestrator-planning phases
  // are the safe ones to stop and the common case for this button.
  const handleStopStreaming = useCallback(() => {
    try { agentWs.cancelStreaming(); } catch (_) { /* hook always defined */ }

    const assistantId = pendingAssistantIdRef.current;
    if (assistantId) {
      setMessages((prev) => {
        const target = prev.find((m) => m.id === assistantId);
        if (!target) return prev;

        const hasContent = (target.content || '').trim().length > 0;
        if (!hasContent) {
          // No streamed content yet — drop the empty placeholder so
          // the user doesn't see a ghost "thinking..." bubble.
          return prev.filter((m) => m.id !== assistantId);
        }
        // Some content already arrived — preserve it but mark as
        // user-stopped so it's distinguishable from a clean finish.
        return prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: `${m.content}\n\n_⏹ Stopped by user._`, stopped: true }
            : m
        );
      });
    }

    pendingAssistantIdRef.current = null;
    setInlineProgress(null);
    setExecutionProgress(null);
    setProgressStartTime(null);
    setIsStreaming(false);
  }, [agentWs]);

  const handleSubmit = async (e) => {
    e.preventDefault();

    const userMessage = input.trim();
    if (!userMessage || isStreaming) return;

    // Store message for potential retry (in case of LLM errors)
    setLastUserMessage(userMessage);

    // Store current threadId - may be null for first message
    const currentThreadId = threadId;

    // Reset progress state for new request
    setExecutionProgress(null);
    setInlineProgress(null);
    setProgressStartTime(null);
    setTokenUsage({ total_tokens: 0, total_cost_usd: 0 });
    setCurrentRequestId(null);

    // Snapshot files before clearing
    const filesToSend = [...attachedFiles];

    // Add user's message immediately (include attachment info for display)
    const userMessageObj = {
      id: `user-${Date.now()}`,
      role: "user",
      content: userMessage,
      timestamp: new Date(),
    };
    if (filesToSend.length > 0) {
      userMessageObj.file_name = filesToSend[0].name;
      userMessageObj.file_type = filesToSend[0].type;
      userMessageObj.file_size = filesToSend[0].size;
    }

    setMessages((prev) => [...prev, userMessageObj]);
    setInput("");
    setAttachedFiles([]);
    setIsStreaming(true);

    // Add empty assistant message for streaming effect
    const assistantMessageId = `assistant-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      },
    ]);

    // ── PATH 1: WebSocket (`sendAgentMessage`) ────────────────────────
    // Preferred path — the supervisor lambda streams progress and the
    // final response back over the same kb-lambda WS the KB chat uses.
    // We only take this path when:
    //   1. VITE_WS_URL is configured (typically AWS in production),
    //   2. there's no file attachment (the WS shape needs a pre-uploaded
    //      `s3_key` and we don't yet have an upload-to-S3 flow), and
    //   3. the socket is already OPEN (avoids racing the handshake).
    // Otherwise we fall through to the HTTP path below — same behaviour
    // as before this migration.
    const useAgentWs = isAgentWsConfigured
                       && filesToSend.length === 0
                       && agentWs.isConnected;

    if (useAgentWs) {
      try {
        // The WS path needs a thread_id up-front — create one if we don't
        // have one yet. The legacy HTTP path conflates thread creation
        // with first-message send; we split them here so the WS frame
        // can carry the thread_id from the first send.
        let threadIdForSend = currentThreadId;
        if (!threadIdForSend) {
          const userId = getUserId();
          const response = await supervisorApi.post('/threads', { user_id: userId });
          threadIdForSend = response.data?.thread_id;
          if (!threadIdForSend) {
            throw new Error('Thread creation returned no thread_id');
          }
          setThreadId(threadIdForSend);
          await fetchThreads();
        }

        // Show an initial progress card while we wait for the first
        // `status` / `progress` frame from the supervisor.
        setProgressStartTime(Date.now());
        setInlineProgress({
          current_step: 0,
          total_steps:  0,
          step_name:    'Sending to AI Assistant...',
          status:       'analyzing',
          agent:        null,
          message:      'Sending to AI Assistant...',
        });

        // Stash the assistant message id so the WS handlers (bound once
        // in the useEffect above) can update the right placeholder when
        // `complete` / `error` / `paused` arrives.
        pendingAssistantIdRef.current = assistantMessageId;

        const ok = agentWs.sendAgentMessage(threadIdForSend, userMessage);
        if (!ok) {
          throw new Error(agentWs.error?.message || 'WebSocket send rejected');
        }

        // Important: do NOT set isStreaming=false here — the WS handler
        // flips it when the terminal frame (`complete` / `error` /
        // `paused`) arrives. Returning early skips the HTTP path's
        // finally block (which would clobber the streaming state).
        return;
      } catch (wsError) {
        // WS path tripped before the supervisor took over — clean up
        // the pending pointer and fall through to the HTTP path so the
        // user still gets a reply.
        console.warn('[AIChat] WS path failed; falling back to HTTP:', wsError);
        pendingAssistantIdRef.current = null;
        setInlineProgress(null);
      }
    }

    // ── PATH 2: HTTP fallback (legacy supervisor on :8010) ────────────
    try {
      console.log("📤 Sending message via HTTP:", userMessage);
      console.log("📍 Thread ID:", currentThreadId || "null (first message)");

      // Show progress polled from the supervisor REST API.
      if (currentThreadId) {
        startProgressPolling(currentThreadId);
      } else {
        // No thread yet — show static progress until POST /threads completes.
        setProgressStartTime(Date.now());
        setInlineProgress({
          current_step: 0, total_steps: 0,
          step_name: 'Analyzing your message...',
          status: 'analyzing', agent: null,
          message: 'Analyzing your message...'
        });
      }

      let responseData;
      
      // If no thread exists, create one with initial message
      if (!currentThreadId) {
        const userId = getUserId();
        try {
          let response;
          if (filesToSend.length > 0) {
            const formData = new FormData();
            formData.append('file', filesToSend[0]);
            formData.append('message', userMessage);
            formData.append('user_id', userId);
            response = await supervisorApi.post('/threads/create-with-upload', formData);
          } else {
            response = await supervisorApi.post('/threads', {
              user_id: userId,
              message: userMessage
            });
          }
          responseData = response.data;
          
          if (responseData.is_llm_error) {
            const error = new Error(responseData.user_message || responseData.message);
            error.responseData = responseData;
            throw error;
          }
          
          console.log("📥 Created thread:", responseData);
          
          setThreadId(responseData.thread_id);
          await fetchThreads();
        } catch (error) {
          if (error.response?.data?.is_llm_error) {
            const llmError = new Error(error.response.data.user_message || error.response.data.message);
            llmError.responseData = error.response.data;
            throw llmError;
          }
          throw error;
        }
      } else {
        // Thread exists, send message to existing thread
        try {
          let response;
          if (filesToSend.length > 0) {
            const formData = new FormData();
            formData.append('file', filesToSend[0]);
            formData.append('message', userMessage);
            response = await supervisorApi.post(`/threads/${currentThreadId}/messages/upload`, formData);
          } else {
            response = await supervisorApi.post(`/threads/${currentThreadId}/messages`, {
              message: userMessage,
            });
          }
          responseData = response.data;
          
          if (responseData.is_llm_error) {
            const error = new Error(responseData.user_message || responseData.message);
            error.responseData = responseData;
            throw error;
          }
          
          console.log("📥 Received response:", responseData);
        } catch (error) {
          if (error.response?.status === 403 || error.response?.data?.detail?.error === 'account_deactivated') {
            const deactivatedError = new Error(error.response?.data?.detail?.user_message || 'Your account has been deactivated. Please contact an administrator.');
            deactivatedError.isDeactivated = true;
            throw deactivatedError;
          }
          
          if (error.response?.status === 429 || error.response?.data?.detail?.error === 'quota_exceeded') {
            const quotaError = new Error(error.response?.data?.detail?.user_message || 'Token quota exceeded. Please wait for your quota to reset.');
            quotaError.isQuotaExceeded = true;
            throw quotaError;
          }
          
          if (error.response?.data?.is_llm_error) {
            const llmError = new Error(error.response.data.user_message || error.response.data.message);
            llmError.responseData = error.response.data;
            throw llmError;
          }
          
          if (error.response?.status === 404 || error.response?.data?.detail?.includes?.('not found')) {
            console.log("⚠️ Thread not found, creating new thread...");
            setThreadId(null);
            
            const userId = getUserId();
            try {
              let newResponse;
              if (filesToSend.length > 0) {
                const formData = new FormData();
                formData.append('file', filesToSend[0]);
                formData.append('message', userMessage);
                formData.append('user_id', userId);
                newResponse = await supervisorApi.post('/threads/create-with-upload', formData);
              } else {
                newResponse = await supervisorApi.post('/threads', {
                  user_id: userId,
                  message: userMessage
                });
              }
              responseData = newResponse.data;
              
              if (responseData.is_llm_error) {
                const llmError = new Error(responseData.user_message || responseData.message);
                llmError.responseData = responseData;
                throw llmError;
              }
              
              setThreadId(responseData.thread_id);
              await fetchThreads();
              console.log("✅ Created new thread:", responseData.thread_id);
            } catch (createError) {
              if (createError.response?.data?.is_llm_error) {
                const llmError = new Error(createError.response.data.user_message || createError.response.data.message);
                llmError.responseData = createError.response.data;
                throw llmError;
              }
              throw createError;
            }
          } else {
            throw error;
          }
        }
      }

      // HTTP response arrived -- clear progress immediately
      disconnectProgressWebSocket();
      setInlineProgress(null);

      if (responseData.request_id) {
        setCurrentRequestId(responseData.request_id);
      }
      
      if (responseData.token_usage) {
        setTokenUsage({
          total_tokens: responseData.token_usage.total_tokens || 0,
          total_cost_usd: responseData.token_usage.total_cost_usd || 0,
          llm_calls: responseData.token_usage.llm_call_count || 0
        });
      }

      // Display the response instantly (execution already happened server-side)
      const fullResponse = responseData.bot_response || "No response received from the assistant.";
      
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, content: fullResponse }
            : msg
        )
      );

    } catch (error) {
      console.error("Error during chat or execution:", error);
      // Disconnect WebSocket and clear inline progress on error
      disconnectProgressWebSocket();
      setInlineProgress(null);
      
      // Check if user account is deactivated
      if (error.isDeactivated) {
        console.log("🔴 Account deactivated");
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: "⚠️ Your account has been deactivated. Please contact an administrator to restore access.",
                  error: true,
                }
              : msg
          )
        );
        setIsStreaming(false);
        return;
      }
      
      // Check if quota exceeded
      if (error.isQuotaExceeded) {
        console.log("🔴 Quota exceeded");
        setShowQuotaModal(true);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: "⚠️ Your token quota has been exceeded. Please wait for your quota to reset or contact an administrator.",
                  error: true,
                }
              : msg
          )
        );
        setIsStreaming(false);
        return;
      }
      
      // Check if this is an LLM error response from the API
      const errorData = error.responseData || {};
      if (errorData.is_llm_error) {
        console.log("🔴 LLM Error detected:", errorData);
        setLlmError(errorData);
        setShowLlmErrorModal(true);
        setLastUserMessage(userMessage);
        // Remove the empty assistant message
        setMessages((prev) => prev.filter(msg => msg.id !== assistantMessageId));
        setIsStreaming(false);
        return;
      }
      
      // Check if error message indicates LLM service issues
      const errorMessage = error.message || '';
      const isLlmError = 
        errorMessage.toLowerCase().includes('rate limit') ||
        errorMessage.toLowerCase().includes('quota exceeded') ||
        errorMessage.toLowerCase().includes('service unavailable') ||
        errorMessage.toLowerCase().includes('billing') ||
        errorMessage.toLowerCase().includes('api key') ||
        errorMessage.toLowerCase().includes('authentication');
      
      if (isLlmError) {
        // Determine error type
        let errorType = 'unknown';
        let title = 'AI Service Error';
        let userMsg = errorMessage;
        
        if (errorMessage.toLowerCase().includes('rate limit')) {
          errorType = 'rate_limit';
          title = 'Too Many Requests';
          userMsg = 'Please wait a moment and try again. The AI service is experiencing high demand.';
        } else if (errorMessage.toLowerCase().includes('quota') || errorMessage.toLowerCase().includes('billing')) {
          errorType = 'quota_exceeded';
          title = 'AI Service Quota Exceeded';
          userMsg = 'The AI service is temporarily unavailable due to quota limits. Please contact your administrator.';
        } else if (errorMessage.toLowerCase().includes('service unavailable') || errorMessage.toLowerCase().includes('502') || errorMessage.toLowerCase().includes('503')) {
          errorType = 'service_unavailable';
          title = 'AI Service Unavailable';
          userMsg = 'The AI service is temporarily unavailable. Please try again in a few minutes.';
        } else if (errorMessage.toLowerCase().includes('api key') || errorMessage.toLowerCase().includes('authentication')) {
          errorType = 'authentication';
          title = 'AI Service Authentication Error';
          userMsg = 'Unable to connect to the AI service. Please contact your administrator.';
        }
        
        setLlmError({
          error_type: errorType,
          title: title,
          user_message: userMsg,
          message: errorMessage
        });
        setShowLlmErrorModal(true);
        setLastUserMessage(userMessage);
        // Remove the empty assistant message
        setMessages((prev) => prev.filter(msg => msg.id !== assistantMessageId));
        setIsStreaming(false);
        return;
      }
      
      // Check if this is a quota exceeded error (legacy check)
      if (errorMessage.toLowerCase().includes('quota exceeded') || 
          errorMessage.toLowerCase().includes('token limit')) {
        // Parse quota info from error if available
        try {
          const quotaMatch = errorMessage.match(/used (\d+).*limit (\d+)/i);
          if (quotaMatch) {
            setQuotaInfo({
              current_usage: parseInt(quotaMatch[1]),
              monthly_limit: parseInt(quotaMatch[2]),
              tier: 'free' // Default, will be updated when modal fetches fresh data
            });
          }
        } catch (e) {
          // Ignore parsing errors
        }
        setShowQuotaModal(true);
      }
      
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `Sorry, I encountered an error: ${error.message}. Please try again.`,
                error: true,
              }
            : msg
        )
      );
    } finally {
      setIsStreaming(false);
      disconnectProgressWebSocket();
      setInlineProgress(null);
    }
  };
  
  // Retry handler for LLM errors
  const handleRetryMessage = () => {
    if (lastUserMessage) {
      setInput(lastUserMessage);
      // Auto-submit after a short delay
      setTimeout(() => {
        const form = document.querySelector('.chat-composer');
        if (form) {
          const event = new Event('submit', { bubbles: true, cancelable: true });
          form.dispatchEvent(event);
        }
      }, 100);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    setInput(suggestion);
    textareaRef.current?.focus();
  };

  const suggestions = [
    "Create a document called Meeting Notes",
    "Send an email to my team about the project update",
    "Read my recent emails",
    "Help me organize my tasks for today",
  ];

  return (
    <div className="aichat-page">
      <div className="aichat-container">
        
        <div className={`aichat-new-page ${showThreads ? 'show-threads' : ''} ${showActions ? 'show-actions' : ''}`}>
          {/* Threads Sidebar */}
          <aside className={`threads-panel ${showThreads ? 'visible' : ''}`}>
          <div className="threads-panel-header">
            <h3>
              Recents
            </h3>
            <button
              onClick={handleNewChat}
              className="new-thread-btn"
              disabled={isStreaming}
              title="New Chat"
            >
              +
            </button>
          </div>
          
          <div className="threads-panel-list">
            {isLoadingThreads ? (
              <div className="threads-panel-loading">
                <Loader2 size={20} className="spinner" />
                <span>Loading...</span>
              </div>
            ) : threads.length === 0 ? (
              <div className="threads-panel-empty">
                <MessageSquare size={32} opacity={0.3} />
                <p>No conversations yet</p>
              </div>
            ) : (
              threads.map((thread) => (
                <div
                  key={thread.thread_id}
                  className={`thread-card ${thread.thread_id === threadId ? 'active' : ''} ${openThreadMenuId === thread.thread_id ? 'menu-open' : ''}`}
                  onClick={() => handleThreadSelect(thread.thread_id)}
                >
                  <div className="thread-card-content">
                    <div className="thread-title-row">
                      {editingThreadId === thread.thread_id ? (
                        <input
                          className="thread-title-input"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => handleTitleKeyDown(e, thread.thread_id)}
                          onBlur={() => handleRenameThread(thread.thread_id)}
                          onClick={(e) => e.stopPropagation()}
                          autoFocus
                          maxLength={200}
                        />
                      ) : (
                        <span className="thread-title-text">
                          {thread.title || thread.thread_id.substring(0, 12) + '...'}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="thread-card-actions">
                    <button
                      className="thread-action-btn thread-menu-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenThreadMenuId((current) => current === thread.thread_id ? null : thread.thread_id);
                      }}
                      title="More actions"
                    >
                      <MoreVertical size={14} />
                    </button>
                    {openThreadMenuId === thread.thread_id && (
                      <div className="thread-action-menu" onClick={(e) => e.stopPropagation()}>
                        {editingThreadId === thread.thread_id ? (
                          <button
                            className="thread-menu-item"
                            onClick={() => {
                              handleRenameThread(thread.thread_id);
                              setOpenThreadMenuId(null);
                            }}
                          >
                            <Check size={14} />
                            <span>Save</span>
                          </button>
                        ) : (
                          <button
                            className="thread-menu-item"
                            onClick={(e) => {
                              startEditingTitle(thread.thread_id, thread.title || thread.thread_id.substring(0, 12), e);
                              setOpenThreadMenuId(null);
                            }}
                          >
                            <Pencil size={14} />
                            <span>Rename</span>
                          </button>
                        )}
                        <button
                          className="thread-menu-item thread-menu-delete"
                          onClick={(e) => {
                            handleDeleteThread(thread.thread_id, e);
                            setOpenThreadMenuId(null);
                          }}
                        >
                          <Trash2 size={14} />
                          <span>Delete</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Main Chat Area */}
        <main className="chat-container">
          <header className="chat-header">
            <div className="chat-header-left">
              <button
                onClick={() => setShowThreads(!showThreads)}
                className="toggle-panel-btn"
                title={showThreads ? "Hide Conversations" : "Show Conversations"}
              >
                <Menu size={20} />
              </button>
            </div>
            
            <div className="chat-header-right">
              {/* Token consumption history — only visible once a thread
                  is bound (otherwise there's no scope to query). The
                  button itself is intentionally minimal so it doesn't
                  steal attention from the chat input; the modal opens
                  on click and renders aggregated + drill-down rows. */}
              {threadId && (
                <button
                  onClick={() => setShowTokenHistory(true)}
                  className="toggle-panel-btn"
                  title="Token consumption history for this conversation"
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <Activity size={18} />
                  <span style={{ fontSize: 12, fontWeight: 500 }}>Token Usage</span>
                </button>
              )}
            </div>
          </header>

          {/* Per-thread token consumption modal */}
          {showTokenHistory && threadId && (
            <ThreadTokenHistoryModal
              threadId={threadId}
              threadTitle={threads.find((t) => t.thread_id === threadId)?.title}
              onClose={() => setShowTokenHistory(false)}
            />
          )}

          {/* Execution Progress Panel */}
          <ExecutionProgress 
            progress={executionProgress}
            isVisible={showProgress}
            onToggle={() => setShowProgress(!showProgress)}
          />

          <div className="chat-thread">
            {isLoadingThread ? (
              <div className="chat-loading-screen">
                <div className="loading-screen">
                  <Sparkles size={48} className="loading-icon" />
                  <p>Loading chat...</p>
                </div>
              </div>
            ) : (
              <>
                <div className="chat-messages">
                  {messages.length === 0 ? (
                <div className="chat-welcome">
                  
                  <h2>Hello! How can I help you today?</h2>
                  <p>I can help you with Gmail, Google Docs, Drive, and more</p>

                  <div className="chat-suggestions">
                    {suggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="chat-suggestion"
                      >
                        <span className="chat-suggestion-icon">💡</span>
                        <span>{suggestion}</span>
                      </button>
                    ))}
                  </div>
                </div>
                  ) : (
                    <>
                      {messages.map((message) => {
                        return (
                          <div
                            key={message.id}
                            className={`chat-message ${message.role} ${message.error ? 'error' : ''} ${message.info ? 'info' : ''}`}
                          >
                            {message.role === "assistant" && (
                              <div className="chat-message-glyph" aria-hidden="true">
                                <Sparkles size={18} strokeWidth={1.75} />
                              </div>
                            )}
                            <div className="chat-message-content1">
                              {message.file_name && (
                                <AttachmentBadge
                                  fileName={message.file_name}
                                  fileType={message.file_type}
                                  fileSize={message.file_size}
                                />
                              )}
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm, remarkBreaks]}
                                components={{
                                  a: ({ node, ...props }) => (
                                    <a {...props} target="_blank" rel="noreferrer noopener" />
                                  ),
                                }}
                              >
                                {message.content}
                              </ReactMarkdown>
                              {message.role === "assistant" &&
                                isStreaming &&
                                message.content && (
                                  <span className="cursor-blink">|</span>
                                )}
                              {/* Show token usage for execution completion messages */}
                              {message.tokenUsage && message.tokenUsage.total_tokens > 0 && (
                                <div className="message-token-usage">
                                  <Zap size={12} />
                                  <span>{message.tokenUsage.total_tokens.toLocaleString()} tokens</span>
                                  {message.tokenUsage.total_cost_usd > 0 && (
                                    <span>• ${message.tokenUsage.total_cost_usd.toFixed(4)}</span>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      
                      {/* Inline Progress Indicator - Shows during execution */}
                      {inlineProgress && (
                        <InlineChatProgress progress={inlineProgress} startTime={progressStartTime} />
                      )}
                      
                      <div ref={messagesEndRef} />
                    </>
                  )}
                </div>

                <form onSubmit={handleSubmit} className="chat-composer">
              {attachedFiles.length > 0 && (
                <div className="attached-files-preview">
                  {attachedFiles.map((file, index) => (
                    <div key={index} className="attached-file-item">
                      <Paperclip size={14} />
                      <span className="attached-file-name">{file.name}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveFile(index)}
                        className="remove-file-btn"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="chat-composer-input">
                <button
                  type="button"
                  onClick={handlePaperclipClick}
                  className="chat-composer-attach"
                  disabled={isStreaming}
                  title="Attach files"
                >
                  <Paperclip size={50} />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFileSelect}
                  style={{ display: 'none' }}
                  accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png"
                />
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask me to create documents, send emails, or help with tasks..."
                  disabled={isStreaming}
                  rows={1}
                />
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={handleStopStreaming}
                    className="chat-composer-send chat-composer-stop"
                    title="Stop generating"
                    aria-label="Stop generating"
                  >
                    <Square size={14} fill="currentColor" strokeWidth={0} />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className="chat-composer-send"
                    title="Send message"
                    aria-label="Send message"
                  >
                    <Send size={18} />
                  </button>
                )}
              </div>
              <div className="chat-composer-footer">
                <span>
                  {isStreaming
                    ? "AI is thinking..."
                    : "Press Enter to send, Shift+Enter for new line"}
                </span>
              </div>
                </form>
              </>
            )}
          </div>
        </main>

        {/* Pending Actions now handled via chat — sidebar removed */}
      </div>
      </div>
      
      {/* Quota Exceeded Modal */}
      <QuotaExceededModal
        isOpen={showQuotaModal}
        onClose={() => setShowQuotaModal(false)}
        quotaInfo={quotaInfo}
      />
      
      {/* LLM Error Modal - Shows when AI service has issues */}
      <LLMErrorModal
        isOpen={showLlmErrorModal}
        onClose={() => setShowLlmErrorModal(false)}
        error={llmError}
        onRetry={handleRetryMessage}
      />
    </div>
  );
}

export default AIChatNew;