import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useActivate, useUnactivate } from "react-activation";
import { 
  Send, 
  Square,
  Edit2,
  Check,
  XCircle,
  Trash2,
  Menu,
  MoreVertical,
  Sparkles
} from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Swal from 'sweetalert2';
import { ACCESS_TOKEN } from "../token";
import { kbApi } from '../api';
import { dispatchQuotaRefresh } from '../hooks/useWebSocketQuota';
import LLMErrorModal from "./LLMErrorModal";
import QuotaExceededModal from "./QuotaExceededModal";
import "../css/SFXChat.css";

// Storage keys for persisting UI state across refreshes
const SFX_SESSION_KEY = 'sfxbot_active_session';
const SFX_SHOW_THREADS_KEY = 'sfxbot_show_threads';
const DEFAULT_SFX_PROMPTS = [
  "Summarize the SOP for delayed shipment handling",
  "List the required steps to process a customer escalation",
  "Create a quick checklist for daily branch operations",
  "Show the escalation matrix for shipment exceptions",
];

function SFXBot() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [threads, setThreads] = useState([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(true);
  const [activeThreadId, setActiveThreadId] = useState(() => {
    // Restore active thread from sessionStorage on refresh
    return sessionStorage.getItem(SFX_SESSION_KEY) || null;
  });
  const [editingThreadId, setEditingThreadId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [showThreads, setShowThreads] = useState(() => {
    // Persist sidebar visibility across reloads
    return localStorage.getItem(SFX_SHOW_THREADS_KEY) === 'true';
  });
  // Dropdown menu state (rendered via portal so it escapes overflow/stacking contexts)
  const [openDropdownId, setOpenDropdownId] = useState(null);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 });
  // LLM Error state
  const [llmError, setLlmError] = useState(null);
  const [llmErrorModalOpen, setLlmErrorModalOpen] = useState(false);
  const [lastUserMessage, setLastUserMessage] = useState("");
  const [preferredPrompts, setPreferredPrompts] = useState(DEFAULT_SFX_PROMPTS);
  // Quota modal state
  const [showQuotaModal, setShowQuotaModal] = useState(false);
  const [quotaInfo, setQuotaInfo] = useState(null);
  
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null); // For smart auto-scroll
  const wasAtBottomRef = useRef(true);       // Tracks if user was at bottom of chat
  const textareaRef = useRef(null);
  const lastFetchRef = useRef(0);
  const fetchTimeoutRef = useRef(null);
  const activeWsRef = useRef(null);          // Track active WebSocket for cleanup

  // KeepAlive activation: reset stale streaming state when user navigates back
  useActivate(() => {
    if (isStreaming) {
      // If we were streaming when user left, the WS is now dead — reset
      console.warn('⚠️ Resetting stale isStreaming state from KeepAlive restore');
      setIsStreaming(false);
    }
    if (activeWsRef.current) {
      try { activeWsRef.current.close(); } catch (_) {}
      activeWsRef.current = null;
    }
  });

  // KeepAlive deactivation: close any active WebSocket when user navigates away
  useUnactivate(() => {
    console.log('💤 SFXBot deactivated (KeepAlive). Cleaning up WebSocket.');
    if (activeWsRef.current) {
      try { activeWsRef.current.close(); } catch (_) {}
      activeWsRef.current = null;
    }
    setIsStreaming(false);
  });

  const updatePreferredPromptsFromPayload = useCallback((payload) => {
    if (!payload || typeof payload !== "object") return;

    const candidateLists = [
      payload.suggested_prompts,
      payload.suggestedPrompts,
      payload.prompt_suggestions,
      payload.promptSuggestions,
      payload.possible_prompts,
      payload.possiblePrompts,
      payload.recommended_prompts,
      payload.recommendedPrompts,
      payload.suggestions,
      payload.metadata?.suggested_prompts,
      payload.metadata?.prompt_suggestions,
      payload.data?.suggested_prompts,
      payload.data?.prompt_suggestions,
      payload.data?.suggestions,
    ];

    const firstValidList = candidateLists.find(
      (list) => Array.isArray(list) && list.some((item) => typeof item === "string" && item.trim())
    );

    if (!firstValidList) return;

    const normalized = [...new Set(
      firstValidList
        .filter((item) => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean)
    )].slice(0, 4);

    if (normalized.length > 0) {
      setPreferredPrompts(normalized);
    }
  }, []);

  const visibleSuggestions = useMemo(() => {
    const cleanedPreferred = preferredPrompts
      .filter((item) => typeof item === "string")
      .map((item) => item.trim())
      .filter(Boolean);

    const merged = [...new Set([...cleanedPreferred, ...DEFAULT_SFX_PROMPTS])];
    return merged.slice(0, 4);
  }, [preferredPrompts]);

  // Persist active thread ID to sessionStorage whenever it changes
  useEffect(() => {
    if (activeThreadId) {
      sessionStorage.setItem(SFX_SESSION_KEY, activeThreadId);
    } else {
      sessionStorage.removeItem(SFX_SESSION_KEY);
    }
  }, [activeThreadId]);

  // Persist sidebar visibility to localStorage
  useEffect(() => {
    localStorage.setItem(SFX_SHOW_THREADS_KEY, String(showThreads));
  }, [showThreads]);

  // Fetch user sessions on mount, and restore the active thread if saved
  useEffect(() => {
    const restoreSession = async () => {
      try {
        await fetchUserSessions();
        const savedSessionId = sessionStorage.getItem(SFX_SESSION_KEY);
        if (savedSessionId) {
          try {
            const response = await kbApi.get(`/api/chat/session/${savedSessionId}/history`);
            const data = response.data;
            if (data.success || data.messages || data.session_id) {
              setActiveThreadId(savedSessionId);
              setMessages(data.messages || []);
            }
          } catch (error) {
            console.warn('Could not restore session, clearing:', error.message);
            sessionStorage.removeItem(SFX_SESSION_KEY);
            setActiveThreadId(null);
          }
        }
      } finally {
        // Always clear the skeleton loading state once the initial fetch settles
        setIsLoadingThreads(false);
      }
    };
    restoreSession();
  }, []);

  const fetchUserSessions = async () => {
    // Debounce: Don't fetch if called within last 2 seconds
    const now = Date.now();
    if (now - lastFetchRef.current < 2000) {
      return;
    }
    lastFetchRef.current = now;
    
    try {
      const response = await kbApi.get('/api/chat/sessions');
      const data = response.data;
      
      // Accept both: { success: true, sessions: [...] } or { sessions: [...] }
      const sessions = data.sessions || [];
      if (data.success || sessions.length > 0 || Array.isArray(data.sessions)) {
        setThreads(sessions);
      }
    } catch (error) {
      if (error.response?.status === 429) {
        console.warn("Too many requests. Please wait before retrying.");
        return;
      }
      console.error("Error fetching sessions:", error);
    }
  };

  const createNewThread = async () => {
    try {
      const response = await kbApi.post('/api/chat/session/new', {});
      const data = response.data;

      // Accept both formats:
      //  - New: { session_id, title, created_at, ... }  (no success field)
      //  - Old: { success: true, session_id, ... }
      const sessionId = data.session_id;
      if (sessionId) {
        const newThread = {
          session_id: sessionId,
          title: data.title || data.session?.title || `Chat ${threads.length + 1}`,
          created_at: data.created_at || data.session?.created_at || new Date().toISOString(),
          message_count: 0
        };
        setThreads(prev => [newThread, ...prev]);
        setActiveThreadId(sessionId);
        setMessages([]);
        return sessionId;
      }
      console.error('No session_id in response:', data);
      return null;
    } catch (error) {
      if (error.response?.status === 403) {
        // User is deactivated or quota exceeded
        const errorMsg = error.response?.data?.detail || error.response?.data?.error || '';
        if (errorMsg.toLowerCase().includes('deactivated') || errorMsg.toLowerCase().includes('inactive')) {
          setQuotaInfo({ 
            reason: 'account_deactivated',
            message: 'Your account has been deactivated. Please contact an administrator.'
          });
        } else {
          setQuotaInfo({ 
            reason: 'quota_exceeded',
            message: errorMsg
          });
        }
        setShowQuotaModal(true);
        return null;
      }
      console.error("Error creating thread:", error.message, error.response?.status, error.response?.data);
      // Show user-visible feedback so they know something went wrong
      Swal.fire({
        icon: 'error',
        title: 'Connection Error',
        text: 'Unable to start a chat session. Please check your connection and try again.',
        confirmButtonColor: '#26326e'
      });
      return null;
    }
  };

  const switchThread = async (sessionId) => {
    try {
      const response = await kbApi.get(`/api/chat/session/${sessionId}/history`);
      const data = response.data;

      // Accept both: { success: true, messages: [...] } or { messages: [...] }
      if (data.success || data.messages || data.session_id) {
        setActiveThreadId(sessionId);
        setMessages(data.messages || []);
      }
    } catch (error) {
      if (error.response?.status === 429) {
        console.warn("Too many requests when switching threads. Please wait a moment.");
        return;
      }
      console.error("Error switching thread:", error);
    }
  };

  const deleteThreadWithAlert = async (sessionId) => {
    try {
      const response = await kbApi.delete(`/api/chat/session/${sessionId}`);
      const data = response.data;

      // Accept both: { success: true } or just a 200 status
      if (data.success || response.status === 200) {
        setThreads(prev => prev.filter(t => t.session_id !== sessionId));
        if (activeThreadId === sessionId) {
          setActiveThreadId(null);
          setMessages([]);
        }
        
        await Swal.fire({
          icon: 'success',
          title: 'Deleted!',
          text: 'Chat thread has been deleted successfully.',
          confirmButtonColor: '#26326e'
        });
      } else {
        console.error("Failed to delete thread:", response.status);
        await Swal.fire({
          icon: 'error',
          title: 'Error!',
          text: 'Failed to delete chat thread. Please try again.',
          confirmButtonColor: '#26326e'
        });
      }
    } catch (error) {
      console.error("Error deleting thread:", error);
      await Swal.fire({
        icon: 'error',
        title: 'Error!',
        text: 'An error occurred while deleting the chat thread.',
        confirmButtonColor: '#26326e'
      });
    }
  };

  const handleDeleteClick = async (e, thread) => {
    e.stopPropagation();
    
    const result = await Swal.fire({
      icon: 'warning',
      title: 'Delete Chat Thread?',
      html: `Are you sure you want to delete the chat thread:<br><br><strong>"${thread.title}"</strong><br><br>This action cannot be undone.`,
      showCancelButton: true,
      confirmButtonText: 'Yes, Delete',
      cancelButtonText: 'Cancel',
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#26326e',
      reverseButtons: true,
      iconColor: '#fcb117'
    });
    
    if (result.isConfirmed) {
      await deleteThreadWithAlert(thread.session_id);
    }
  };

  const handleEditClick = (e, thread) => {
    e.stopPropagation();
    setEditingThreadId(thread.session_id);
    setEditingTitle(thread.title);
  };

  // Stop an in-flight streaming response by closing the WebSocket. The
  // ws.onclose handler will reset isStreaming via its existing logic.
  const handleStopStreaming = () => {
    if (activeWsRef.current) {
      try { activeWsRef.current.close(); } catch (_) {}
      activeWsRef.current = null;
    }
    setIsStreaming(false);
  };

  // Toggle the per-row dropdown. Position is computed from the button's
  // bounding rect so the menu (rendered via portal) appears anchored to it.
  const handleMenuClick = (e, threadId) => {
    e.stopPropagation();
    if (openDropdownId === threadId) {
      setOpenDropdownId(null);
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    const MENU_WIDTH = 140;
    const MENU_HEIGHT = 84;
    const GAP = 6;

    let top = rect.bottom + GAP;
    let left = rect.right - MENU_WIDTH;

    // Flip above the button when there's not enough room below
    if (top + MENU_HEIGHT > window.innerHeight - 8) {
      top = rect.top - MENU_HEIGHT - GAP;
    }
    // Keep menu fully on-screen horizontally
    if (left < 8) left = rect.left;
    if (left + MENU_WIDTH > window.innerWidth - 8) {
      left = window.innerWidth - MENU_WIDTH - 8;
    }

    setDropdownPos({ top, left });
    setOpenDropdownId(threadId);
  };

  // Close the dropdown on outside click, ESC, scroll, or window resize.
  useEffect(() => {
    if (!openDropdownId) return;

    const close = () => setOpenDropdownId(null);
    const onClickOutside = (e) => {
      if (!e.target.closest?.('.thread-dropdown-menu') &&
          !e.target.closest?.('.thread-menu-btn')) {
        close();
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') close();
    };

    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onKey);
    // Capture phase so we catch scrolls in any nested container
    document.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);

    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [openDropdownId]);

  const handleCancelEdit = (e) => {
    e?.stopPropagation();
    setEditingThreadId(null);
    setEditingTitle("");
  };

  const handleSaveTitle = async (e, sessionId) => {
    e?.stopPropagation();
    
    if (!editingTitle.trim()) {
      handleCancelEdit();
      return;
    }

    try {
      const response = await kbApi.patch(`/api/chat/session/${sessionId}/title`, { title: editingTitle.trim() });
      const data = response.data;

      if (data.success || data.title || response.status === 200) {
        // Update thread in local state
        setThreads(prev => prev.map(t => 
          t.session_id === sessionId ? { ...t, title: data.title || editingTitle.trim() } : t
        ));
        setEditingThreadId(null);
        setEditingTitle("");
      }
    } catch (error) {
      console.error('Error updating title:', error);
      handleCancelEdit();
    }
  };

  const handleTitleKeyDown = (e, sessionId) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSaveTitle(e, sessionId);
    } else if (e.key === 'Escape') {
      handleCancelEdit();
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Track whether the user is near the bottom of the chat. Used to decide
  // whether streaming tokens should auto-scroll, so we don't yank the user
  // away while they're scrolled up reading earlier messages.
  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      wasAtBottomRef.current = distance < 100; // px threshold
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Auto-scroll only if the user is already near the bottom.
  useEffect(() => {
    if (wasAtBottomRef.current) {
      scrollToBottom();
    }
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  const handleSuggestionClick = (suggestion) => {
    setInput(suggestion);
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) {
      return;
    }

    // Resolve the session ID — use existing or create a new one
    let currentSessionId = activeThreadId;
    if (!currentSessionId) {
      const newId = await createNewThread();
      if (!newId) {
        // Thread creation failed (likely 403 quota/deactivation)
        return;
      }
      currentSessionId = newId;
    }

    if (!currentSessionId) {
      console.error("No active session — this should not happen");
      return;
    }

    const userMessage = {
      message_id: Date.now().toString(),
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString()
    };

    // The user just submitted — they expect to see their own message at the
    // bottom, so override any "scrolled up" state for the next render cycle.
    wasAtBottomRef.current = true;

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsStreaming(true);

    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage = {
      message_id: assistantMessageId,
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString()
    };
    setMessages((prev) => [...prev, assistantMessage]);

    try {
      // Store message for potential retry
      setLastUserMessage(userMessage.content);
      
      // Connect to WebSocket for streaming (AWS API Gateway WebSocket)
      const token = localStorage.getItem(ACCESS_TOKEN);
      const wsBaseUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:9009/ws';
      const wsUrl = `${wsBaseUrl}?token=${encodeURIComponent(token)}`;
      
      console.log('🔌 Connecting to WebSocket:', wsBaseUrl);
      
      const ws = new WebSocket(wsUrl);
      activeWsRef.current = ws;           // Track for KeepAlive cleanup
      let fullContent = "";
      let tokenCount = 0;
      
      // BUG 5 FIX: Safety timeout — if no response after 90s, reset streaming state
      const safetyTimeout = setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          console.warn('⏱️ WebSocket safety timeout — no completion received in 90s');
          ws.close();
        }
      }, 90_000);
      
      ws.onopen = () => {
        console.log('✅ WebSocket connected — sending message to session:', currentSessionId);
        // Send the message with action (AWS WebSocket route selection)
        ws.send(JSON.stringify({
          action: 'sendMessage',
          message: userMessage.content,
          session_id: currentSessionId,
          options: {
            include_context: true,
            temperature: 0.7,
            max_tokens: 2000
          }
        }));
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('📨 WS message:', data.type, data.type === 'token' ? '(token)' : data);
          
          if (data.type === 'token') {
            // Stream token to UI
            fullContent += data.content;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.message_id === assistantMessageId
                  ? { ...msg, content: fullContent }
                  : msg
              )
            );
          } else if (data.type === 'done' || data.type === 'complete') {
            // Complete response received
            // Backend sends: type='complete', full_response, tokens_used
            // Handle both field naming conventions for resilience
            tokenCount = data.tokens_used || data.tokens || 0;
            const finalContent = data.full_response || data.content || fullContent;
            fullContent = finalContent;
            updatePreferredPromptsFromPayload(data);

            // ── Quota / deactivation pre-flight block (kb-lambda) ──────
            // kb-lambda's ws_chat_stream sends quota / deactivation
            // blocks as a normal `complete` event with `was_blocked: true`
            // and `block_reason: 'quota_exhausted' | 'account_deactivated'`,
            // not as a `type: error` event. Without this branch the
            // friendly long-form text just renders inline as an
            // assistant bubble (the screenshot the user sent). Mirror
            // AIChatNew's pattern: replace the bubble with a short
            // notice and trigger the shared QuotaExceededModal so the
            // SFXBot UX matches the AI Assistant flow exactly.
            if (data.was_blocked === true) {
              const reason = data.block_reason === 'account_deactivated'
                ? 'account_deactivated'
                : 'quota_exceeded';
              const shortText = reason === 'account_deactivated'
                ? '⚠️ Your account has been deactivated. Please contact an administrator.'
                : '⚠️ Your token quota has been exceeded. Please wait for your quota to reset or contact an administrator.';
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.message_id === assistantMessageId
                    ? { ...msg, content: shortText, error: true, metadata: { tokens_used: 0 } }
                    : msg
                )
              );
              setQuotaInfo({ reason, message: finalContent });
              setShowQuotaModal(true);
              dispatchQuotaRefresh('sfxbot-quota-blocked');
              clearTimeout(safetyTimeout);
              ws.close();
              return;
            }

            setMessages((prev) =>
              prev.map((msg) =>
                msg.message_id === assistantMessageId
                  ? {
                      ...msg,
                      content: fullContent,
                      metadata: { tokens_used: tokenCount }
                    }
                  : msg
              )
            );
            console.log('✅ Streaming complete. Tokens:', tokenCount);
            
            // Auto-update thread title if the backend generated one
            if (data.generated_title) {
              setThreads(prev => prev.map(t => 
                t.session_id === currentSessionId 
                  ? { ...t, title: data.generated_title } 
                  : t
              ));
            }
            
            // Notify quota widget that tokens were consumed
            dispatchQuotaRefresh('sfxbot-chat-complete', tokenCount);
            
            // Update thread list
            if (fetchTimeoutRef.current) {
              clearTimeout(fetchTimeoutRef.current);
            }
            fetchTimeoutRef.current = setTimeout(() => {
              fetchUserSessions().catch(err => {
                console.error('Error reloading data:', err);
              });
            }, 1000);
            
            clearTimeout(safetyTimeout);
            ws.close();
          } else if (data.type === 'error') {
            // Error during streaming
            // Backend sends: { type: 'error', message: '...' }
            const errorMsg = data.message || data.content || 'Unknown streaming error';
            console.error('❌ Stream error:', errorMsg);
            setLlmError({
              is_llm_error: true,
              message: errorMsg,
              error_type: 'stream_error'
            });
            setLlmErrorModalOpen(true);
            setMessages((prev) => prev.filter(msg => msg.message_id !== assistantMessageId));
            clearTimeout(safetyTimeout);
            ws.close();
          } else if (data.type === 'status') {
            // Status updates (processing, generating) — log for debugging
            console.log('📋 Status:', data.message || data.status);
          } else if (data.type === 'connection_established') {
            console.log('🤝 Connection confirmed, id:', data.connection_id);
          }
        } catch (parseError) {
          console.error('Error parsing WebSocket message:', parseError, event.data);
        }
      };
      
      ws.onerror = (error) => {
        console.error('❌ WebSocket error:', error);
        clearTimeout(safetyTimeout);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.message_id === assistantMessageId
              ? {
                  ...msg,
                  content: "Sorry, I encountered a connection error. Please try again.",
                  error: true,
                }
              : msg
          )
        );
      };
      
      ws.onclose = (event) => {
        console.log(`🔌 WebSocket disconnected (code=${event.code}, reason="${event.reason || 'none'}")`);
        clearTimeout(safetyTimeout);
        activeWsRef.current = null;        // Clear ref so KeepAlive knows WS is gone
        setIsStreaming(false);
      };
      
    } catch (error) {
      console.error("Error sending message:", error);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.message_id === assistantMessageId
            ? {
                ...msg,
                content: "Sorry, I encountered an error. Please try again.",
                error: true,
              }
            : msg
        )
      );
      setIsStreaming(false);
    }
  };

  // Retry handler for LLM errors
  const handleRetryMessage = () => {
    if (lastUserMessage) {
      setInput(lastUserMessage);
      // Auto-submit after a short delay
      setTimeout(() => {
        const submitBtn = document.querySelector('.chat-send-btn');
        if (submitBtn) submitBtn.click();
      }, 100);
    }
  };

  return (
    <div className="dm-chat-page">
      {/* LLM Error Modal */}
      <LLMErrorModal
        isOpen={llmErrorModalOpen}
        onClose={() => setLlmErrorModalOpen(false)}
        error={llmError}
        onRetry={handleRetryMessage}
      />

      {/* Quota Exceeded Modal */}
      <QuotaExceededModal
        isOpen={showQuotaModal}
        onClose={() => setShowQuotaModal(false)}
        quotaInfo={quotaInfo}
      />
      
      <div className="dm-chat-container">
        <div className={`dm-chat-content ${showThreads ? 'show-threads' : ''}`}>
          {/* Mobile-only backdrop: tap to dismiss the threads drawer */}
          {showThreads && (
            <div
              className="chat-threads-backdrop"
              onClick={() => setShowThreads(false)}
              aria-hidden="true"
            />
          )}

          {/* Chat Threads Sidebar */}
          <div className={`chat-threads-sidebar ${showThreads ? 'show' : ''}`}>
            <div className="threads-header">
              <h3>Chat Threads</h3>
              <button
                className="new-chat-btn"
                onClick={createNewThread}
                aria-label="New chat thread"
                title="New chat"
              >
                +
              </button>
            </div>
            <div className="threads-list">
              {isLoadingThreads ? (
                <>
                  <div className="thread-skeleton" />
                  <div className="thread-skeleton" />
                  <div className="thread-skeleton" />
                  <div className="thread-skeleton" />
                </>
              ) : threads.length === 0 ? (
                <div className="threads-empty">
                  No chat threads yet
                </div>
              ) : (
                threads.map((thread) => (
                  <div
                    key={thread.session_id}
                    className={`thread-item ${activeThreadId === thread.session_id ? 'active' : ''}`}
                    onClick={() => editingThreadId !== thread.session_id && switchThread(thread.session_id)}
                  >
                    <div className="thread-info">
                      {editingThreadId === thread.session_id ? (
                        <div className="thread-title-edit">
                          <input
                            type="text"
                            value={editingTitle}
                            onChange={(e) => setEditingTitle(e.target.value)}
                            onKeyDown={(e) => handleTitleKeyDown(e, thread.session_id)}
                            onClick={(e) => e.stopPropagation()}
                            autoFocus
                            maxLength={200}
                            className="thread-title-input"
                          />
                          <div className="thread-edit-actions">
                            <button
                              className="thread-edit-save"
                              onClick={(e) => handleSaveTitle(e, thread.session_id)}
                              title="Save"
                            >
                              <Check size={14} />
                            </button>
                            <button
                              className="thread-edit-cancel"
                              onClick={(e) => handleCancelEdit(e)}
                              title="Cancel"
                            >
                              <XCircle size={14} />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="thread-title" title={thread.title}>{thread.title}</div>
                      )}
                    </div>
                    {editingThreadId !== thread.session_id && (
                      <div className="thread-actions">
                        <div className="thread-actions-dropdown">
                          <button
                            className="thread-menu-btn"
                            onClick={(e) => handleMenuClick(e, thread.session_id)}
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={openDropdownId === thread.session_id}
                            aria-label="Thread options"
                          >
                            <MoreVertical size={16} />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Chat Area */}
          <main className="chat-main">
            <header className="chat-main-header">
              <button
                onClick={() => setShowThreads(!showThreads)}
                className="toggle-threads-btn"
                title={showThreads ? "Hide Threads" : "Show Threads"}
                aria-label={showThreads ? "Hide threads sidebar" : "Show threads sidebar"}
              >
                <Menu size={20} />
              </button>
            </header>

            <div className="chat-messages" ref={messagesContainerRef}>
              {messages.length === 0 ? (
                <div className="chat-welcome">
                  <h2>What should SFX Bot help you with?</h2>
                  <p>Ask for SOP guidance, process checklists, policy clarifications, or escalation flow.</p>

                  <div className="chat-suggestions">
                    {visibleSuggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="chat-suggestion"
                      >
                        <span>{suggestion}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {messages.map((msg) => {
                    const isEmptyAssistantWhileStreaming =
                      msg.role === 'assistant' && isStreaming && !msg.content;
                    return (
                      <div
                        key={msg.message_id}
                        className={`message ${msg.role === "user" ? "user" : "assistant"}`}
                      >
                        {msg.role === "assistant" && (
                          <div className="message-glyph" aria-hidden="true">
                            <Sparkles size={18} strokeWidth={1.75} />
                          </div>
                        )}
                        <div className="message-content">
                          <div className="message-text">
                            {isEmptyAssistantWhileStreaming ? (
                              <span className="typing-indicator" aria-label="Assistant is typing">
                                <span></span>
                                <span></span>
                                <span></span>
                              </span>
                            ) : (
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {msg.content}
                              </ReactMarkdown>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            <div className="chat-input-container">
              <form onSubmit={handleSubmit} className="chat-form">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                  placeholder={isStreaming ? "Generating response..." : "Ask a question..."}
                  className="chat-textarea"
                  rows={1}
                  disabled={isStreaming}
                />
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={handleStopStreaming}
                    className="chat-send-btn chat-stop-btn"
                    title="Stop generating"
                    aria-label="Stop generating"
                  >
                    <Square size={14} fill="currentColor" strokeWidth={0} />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className="chat-send-btn"
                    title="Send message"
                    aria-label="Send message"
                  >
                    <Send size={18} />
                  </button>
                )}
              </form>
            </div>
          </main>
        </div>
      </div>

      {/* Thread actions dropdown rendered via portal so it escapes the
          sidebar's overflow-clip and any transformed ancestor stacking
          contexts. Positioned with fixed coordinates from the menu button. */}
      {openDropdownId && createPortal(
        (() => {
          const thread = threads.find(t => t.session_id === openDropdownId);
          if (!thread) return null;
          return (
            <div
              className="thread-dropdown-menu show"
              role="menu"
              style={{
                position: 'fixed',
                top: dropdownPos.top,
                left: dropdownPos.left,
                right: 'auto',
                marginTop: 0
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                className="thread-dropdown-item"
                role="menuitem"
                type="button"
                onClick={(e) => {
                  setOpenDropdownId(null);
                  handleEditClick(e, thread);
                }}
              >
                <Edit2 size={14} />
                <span>Edit</span>
              </button>
              <button
                className="thread-dropdown-item thread-dropdown-delete"
                role="menuitem"
                type="button"
                onClick={(e) => {
                  setOpenDropdownId(null);
                  handleDeleteClick(e, thread);
                }}
              >
                <Trash2 size={14} />
                <span>Delete</span>
              </button>
            </div>
          );
        })(),
        document.body
      )}
    </div>
  );
}

export default SFXBot;
