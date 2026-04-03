import { useState, useEffect, useRef } from "react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  User,
  Mail,
  Calendar,
  Bot,
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
  Brain
} from "lucide-react";
import { getUserFromToken, getUserUUID } from "../utils/tokenManager";
import "../css/AIChatNew.css";
import { supervisorApi } from "../api";
import QuotaWidget from "./QuotaWidget";
import QuotaExceededModal from "./QuotaExceededModal";
import LLMErrorModal from "./LLMErrorModal";

// Helper function to parse email results from assistant response
function parseEmailResults(content) {
  try {
    const jsonMatch = content.match(/\{[\s\S]*"emails"[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed.emails && Array.isArray(parsed.emails)) {
        return parsed.emails;
      }
    }
    
    const emailPattern = /\{\s*"message_id"[\s\S]*?"subject"[\s\S]*?"from"[\s\S]*?\}/g;
    const matches = content.match(emailPattern);
    if (matches) {
      return matches.map(match => {
        try {
          return JSON.parse(match);
        } catch {
          return null;
        }
      }).filter(Boolean);
    }
  } catch (e) {
    console.log("Could not parse emails from response:", e);
  }
  return null;
}

// Email Card Component
function EmailCard({ email }) {
  return (
    <div className="email-card">
      <div className="email-card-header">
        <Mail size={18} className="email-icon" />
        <div className="email-card-content">
          <div className="email-subject">
            {email.subject || 'No Subject'}
          </div>
          <div className="email-meta">
            <div className="email-from">
              <User size={14} />
              <span>{email.from || 'Unknown'}</span>
            </div>
            {email.date && (
              <div className="email-date">
                <Calendar size={14} />
                <span>{new Date(email.date).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>
      </div>
      {email.body && (
        <div className="email-body">
          {email.body.substring(0, 200)}{email.body.length > 200 ? '...' : ''}
        </div>
      )}
    </div>
  );
}

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
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const progressWebSocketRef = useRef(null);
  const progressPollingRef = useRef(null);

  // WebSocket URL (convert http to ws) - supervisor is on port 8010
  const WS_BASE_URL = "ws://localhost:8010";

  // Connect to WebSocket for real-time progress updates
  const connectProgressWebSocket = (targetThreadId) => {
    disconnectProgressWebSocket();
    
    console.log('🔌 Connecting WebSocket for thread:', targetThreadId);
    
    // Show initial progress immediately
    setProgressStartTime(Date.now());
    setInlineProgress({
      current_step: 0,
      total_steps: 0,
      step_name: 'Analyzing your message...',
      agent: null,
      status: 'analyzing',
      message: 'Analyzing your message...'
    });
    
    try {
      const ws = new WebSocket(`${WS_BASE_URL}/ws/threads/${targetThreadId}/progress`);
      progressWebSocketRef.current = ws;
      
      ws.onopen = () => {
        console.log('✅ WebSocket connected for progress');
      };
      
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          
          if (message.type === 'progress') {
            const data = message.data;
            setInlineProgress({
              current_step: data.current_step || 0,
              total_steps: data.total_steps || 0,
              step_name: data.step_name || 'Processing...',
              agent: data.agent || null,
              status: data.status || 'executing',
              message: data.step_name || 'Working on your request...'
            });
          } else if (message.type === 'token_usage') {
            setTokenUsage(prev => ({
              total_tokens: message.data.total_tokens || prev.total_tokens,
              total_cost_usd: message.data.total_cost_usd || prev.total_cost_usd,
              llm_calls: message.data.llm_calls || prev.llm_calls
            }));
          }
        } catch (e) {
          console.warn('Failed to parse WebSocket message:', e);
        }
      };
      
      ws.onerror = (error) => {
        console.warn('WebSocket error:', error);
        startProgressPolling(targetThreadId);
      };
      
      ws.onclose = () => {
        progressWebSocketRef.current = null;
      };
      
    } catch (error) {
      console.warn('Failed to create WebSocket:', error);
      startProgressPolling(targetThreadId);
    }
  };

  // Disconnect WebSocket
  const disconnectProgressWebSocket = () => {
    if (progressWebSocketRef.current) {
      console.log('🔌 Closing WebSocket connection');
      progressWebSocketRef.current.close();
      progressWebSocketRef.current = null;
    }
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
    
    if (!confirm("Are you sure you want to delete this conversation?")) {
      return;
    }
    
    try {
      await supervisorApi.delete(`/threads/${thread_id}`);
      
      await fetchThreads();
      
      if (thread_id === threadId) {
        await createNewThread();
      }
    } catch (error) {
      console.error("Error deleting thread:", error);
    }
  };

  const startEditingTitle = (thread_id, currentTitle, e) => {
    e.stopPropagation();
    setEditingThreadId(thread_id);
    setEditingTitle(currentTitle || "");
  };

  const handleRenameThread = async (thread_id) => {
    const trimmed = editingTitle.trim();
    if (!trimmed) {
      setEditingThreadId(null);
      return;
    }

    try {
      await supervisorApi.put(`/threads/${thread_id}`, { title: trimmed });
      await fetchThreads();
    } catch (error) {
      console.error("Error renaming thread:", error);
    } finally {
      setEditingThreadId(null);
    }
  };

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

      const formattedMessages = (data.messages || []).map((msg, idx) => ({
        id: msg.message_id || `msg-${thread_id}-${idx}`,
        role: msg.role || "assistant",
        content: msg.content || "No content",
        timestamp: msg.created_at ? new Date(msg.created_at) : new Date(),
      }));
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
  };

  const handleRemoveFile = (index) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handlePaperclipClick = () => {
    fileInputRef.current?.click();
  };

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

    // Add user's message immediately
    const userMessageObj = {
      id: `user-${Date.now()}`,
      role: "user",
      content: userMessage,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessageObj]);
    setInput("");
    const filesToSend = [...attachedFiles];
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

    try {
      console.log("📤 Sending message:", userMessage);
      console.log("📍 Thread ID:", currentThreadId || "null (first message)");

      // Connect WebSocket BEFORE the HTTP call so we receive progress during execution
      if (currentThreadId) {
        connectProgressWebSocket(currentThreadId);
      } else {
        // No thread yet -- show static progress (no WS available until thread is created)
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

  if (isLoadingThread) {
    return (
      <div className="aichat-new-wrapper">
        <div className="aichat-new-page">
          <div className="loading-screen">
            <Sparkles size={48} className="loading-icon" />
            <p>Loading chat...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="aichat-page">
      <div className="aichat-container">
        
        <div className={`aichat-new-page ${showThreads ? 'show-threads' : ''} ${showActions ? 'show-actions' : ''}`}>
          {/* Threads Sidebar */}
          <aside className={`threads-panel ${showThreads ? 'visible' : ''}`}>
          <div className="threads-panel-header">
            <h3>
              <MessageSquare size={20} />
              Conversations
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
                  className={`thread-card ${thread.thread_id === threadId ? 'active' : ''}`}
                  onClick={() => handleThreadSelect(thread.thread_id)}
                >
                  <div className="thread-card-content">
                    <div className="thread-card-header">
                      <MessageSquare size={16} />
                      {editingThreadId === thread.thread_id ? (
                        <input
                          className="thread-title-input"
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleRenameThread(thread.thread_id);
                            if (e.key === "Escape") setEditingThreadId(null);
                          }}
                          onBlur={() => handleRenameThread(thread.thread_id)}
                          onClick={(e) => e.stopPropagation()}
                          autoFocus
                        />
                      ) : (
                        <span className="thread-id">
                          {thread.title || thread.thread_id.substring(0, 12) + '...'}
                        </span>
                      )}
                    </div>
                    <span className="thread-messages-count">
                      {thread.message_count || 0} messages
                    </span>
                  </div>
                  <div className="thread-card-actions">
                    {editingThreadId === thread.thread_id ? (
                      <button
                        className="thread-action-btn thread-confirm-btn"
                        onClick={(e) => { e.stopPropagation(); handleRenameThread(thread.thread_id); }}
                        title="Save title"
                      >
                        <Check size={14} />
                      </button>
                    ) : (
                      <button
                        className="thread-action-btn thread-edit-btn"
                        onClick={(e) => startEditingTitle(thread.thread_id, thread.title || thread.thread_id.substring(0, 12), e)}
                        title="Rename conversation"
                      >
                        <Pencil size={14} />
                      </button>
                    )}
                    <button
                      className="thread-action-btn thread-delete-btn"
                      onClick={(e) => handleDeleteThread(thread.thread_id, e)}
                      title="Delete conversation"
                    >
                      <Trash2 size={14} />
                    </button>
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
            
            {/* Token Usage Badge in Header */}
            <div className="chat-header-center">
              <QuotaWidget compact={true} />
              <TokenUsageBadge usage={tokenUsage} />
            </div>
            
            <div className="chat-header-right">
            </div>
          </header>

          {/* Execution Progress Panel */}
          <ExecutionProgress 
            progress={executionProgress}
            isVisible={showProgress}
            onToggle={() => setShowProgress(!showProgress)}
          />

          <div className="chat-thread">
            <div className="chat-messages">
              {messages.length === 0 ? (
                <div className="chat-welcome">
                  <div className="chat-welcome-icon">
                  </div>
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
                    const emails = message.role === "assistant" ? parseEmailResults(message.content) : null;
                    
                    return (
                      <div
                        key={message.id}
                        className={`chat-message ${message.role} ${message.error ? 'error' : ''} ${message.info ? 'info' : ''}`}
                      >
                        <div className="chat-message-avatar">
                          {message.role === "user" ? (
                            <User size={20} />
                          ) : (
                            <Bot size={20} />
                          )}
                        </div>
                        <div className="chat-message-content">
                          {emails && emails.length > 0 ? (
                            <>
                              <div className="email-results-header">
                                📧 Found {emails.length} email{emails.length !== 1 ? 's' : ''}
                              </div>
                              {emails.map((email, idx) => (
                                <EmailCard key={email.message_id || idx} email={email} />
                              ))}
                            </>
                          ) : (
                            <>
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {message.content}
                              </ReactMarkdown>
                              {message.role === "assistant" &&
                                isStreaming &&
                                message.content && (
                                  <span className="cursor-blink">|</span>
                                )}
                            </>
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
                <button
                  type="submit"
                  disabled={isStreaming || !input.trim()}
                  className="chat-composer-send"
                >
                  <Send size={50} />
                </button>
              </div>
              <div className="chat-composer-footer">
                <span>
                  {isStreaming
                    ? "AI is thinking..."
                    : "Press Enter to send, Shift+Enter for new line"}
                </span>
              </div>
            </form>
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