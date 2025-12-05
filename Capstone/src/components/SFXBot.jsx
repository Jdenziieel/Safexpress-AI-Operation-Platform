import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { 
  Send, 
  Sparkles, 
  User,
  Bot,
  X,
  Edit2,
  Check,
  XCircle
} from "lucide-react";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { kbApi } from '../api';
import DeleteConfirmationModal from "./DeleteConfirmationModal";
import LLMErrorModal from "./LLMErrorModal";
import "../css/DynamicMappingChat.css";

function SFXBot() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [threads, setThreads] = useState([]);
  const [activeThreadId, setActiveThreadId] = useState(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [threadToDelete, setThreadToDelete] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [editingThreadId, setEditingThreadId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  // LLM Error state
  const [llmError, setLlmError] = useState(null);
  const [llmErrorModalOpen, setLlmErrorModalOpen] = useState(false);
  const [lastUserMessage, setLastUserMessage] = useState("");
  
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const lastFetchRef = useRef(0);
  const fetchTimeoutRef = useRef(null);

  const suggestions = [
    "What are the company policies on remote work?",
    "How do I submit a leave request?",
    "Explain the expense reimbursement process",
    "What documents do I need for onboarding?"
  ];

  // Fetch user sessions on mount
  useEffect(() => {
    fetchUserSessions();
  }, []);

  const fetchUserSessions = async () => {
    // Debounce: Don't fetch if called within last 2 seconds
    const now = Date.now();
    if (now - lastFetchRef.current < 2000) {
      console.log('Skipping fetchUserSessions - too soon after last fetch');
      return;
    }
    lastFetchRef.current = now;
    
    try {
      const response = await kbApi.get('/chat/sessions');
      
      if (response.data.success) {
        setThreads(response.data.sessions || []);
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
      const response = await kbApi.post('/chat/session/new', {});

      if (response.data.success) {
        const newThread = {
          session_id: response.data.session_id,
          title: response.data.session?.title || `Chat ${threads.length + 1}`,
          created_at: response.data.session?.created_at || new Date().toISOString(),
          message_count: 0
        };
        setThreads(prev => [newThread, ...prev]);
        setActiveThreadId(response.data.session_id);
        setMessages([]);
      }
    } catch (error) {
      console.error("Error creating thread:", error);
    }
  };

  const switchThread = async (sessionId) => {
    try {
      const response = await kbApi.get(`/chat/session/${sessionId}/history`);

      if (response.data.success) {
        setActiveThreadId(sessionId);
        setMessages(response.data.messages || []);
      }
    } catch (error) {
      if (error.response?.status === 429) {
        console.warn("Too many requests when switching threads. Please wait a moment.");
        return;
      }
      console.error("Error switching thread:", error);
    }
  };

  const deleteThread = async (sessionId) => {
    setIsDeleting(true);
    try {
      const response = await kbApi.delete(`/chat/session/${sessionId}`);

      if (response.data.success) {
        setThreads(prev => prev.filter(t => t.session_id !== sessionId));
        if (activeThreadId === sessionId) {
          setActiveThreadId(null);
          setMessages([]);
        }
        setDeleteModalOpen(false);
        setThreadToDelete(null);
      }
    } catch (error) {
      console.error("Error deleting thread:", error);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeleteClick = (e, thread) => {
    e.stopPropagation();
    setThreadToDelete(thread);
    setDeleteModalOpen(true);
  };

  const handleEditClick = (e, thread) => {
    e.stopPropagation();
    setEditingThreadId(thread.session_id);
    setEditingTitle(thread.title);
  };

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
      const response = await kbApi.patch(`/chat/session/${sessionId}/title`, { title: editingTitle.trim() });

      if (response.data.success) {
        // Update thread in local state
        setThreads(prev => prev.map(t => 
          t.session_id === sessionId ? { ...t, title: response.data.title } : t
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

  useEffect(() => {
    scrollToBottom();
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
    if (!input.trim() || isStreaming) return;

    // Create session if needed
    if (!activeThreadId) {
      await createNewThread();
      // Wait for session to be created
      await new Promise(resolve => setTimeout(resolve, 500));
    }

    if (!activeThreadId) {
      console.error("No active session");
      return;
    }

    const userMessage = {
      message_id: Date.now().toString(),
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString()
    };

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
      
      // Connect to WebSocket for streaming
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const kbHost = import.meta.env.VITE_KB_HOST || 'localhost:9009';
      const wsUrl = `${protocol}//${kbHost}/chat/ws/${activeThreadId}/stream`;
      
      console.log('🔌 Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      let fullContent = "";
      let tokenCount = 0;
      
      ws.onopen = () => {
        console.log('✅ WebSocket connected');
        // Send the message after connecting
        ws.send(JSON.stringify({
          message: userMessage.content,
          options: {
            include_context: true
          }
        }));
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
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
          } else if (data.type === 'done') {
            // Complete response received
            tokenCount = data.tokens || 0;
            fullContent = data.content;
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
            
            // Update thread list
            if (fetchTimeoutRef.current) {
              clearTimeout(fetchTimeoutRef.current);
            }
            fetchTimeoutRef.current = setTimeout(() => {
              fetchUserSessions().catch(err => {
                console.error('Error reloading data:', err);
              });
            }, 1000);
            
            ws.close();
          } else if (data.type === 'error') {
            // Error during streaming
            console.error('❌ Stream error:', data.content);
            setLlmError({
              is_llm_error: true,
              message: data.content,
              error_type: 'stream_error'
            });
            setLlmErrorModalOpen(true);
            setMessages((prev) => prev.filter(msg => msg.message_id !== assistantMessageId));
            ws.close();
          }
        } catch (parseError) {
          console.error('Error parsing WebSocket message:', parseError);
        }
      };
      
      ws.onerror = (error) => {
        console.error('❌ WebSocket error:', error);
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
      
      ws.onclose = () => {
        console.log('🔌 WebSocket disconnected');
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
      
      <div className="dm-chat-container">
        <div className="dm-chat-header-row">
          <div>
            <h1 className="dm-chat-header-title">SFX Bot</h1>
            <div className="dm-chat-header-subtitle">
              AI-powered assistant for your queries
            </div>
          </div>
        </div>

        <div className="dm-chat-content">
          {/* Chat Threads Sidebar */}
          <div className="chat-threads-sidebar">
            <div className="threads-header">
              <h3>Chat Threads</h3>
              <button className="new-chat-btn" onClick={createNewThread}>
                <Sparkles size={16} />
                New Chat
              </button>
            </div>
            <div className="threads-list">
              {threads.length === 0 ? (
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
                        <>
                          <div className="thread-title">{thread.title}</div>
                          <div className="thread-date">
                            {new Date(thread.created_at).toLocaleDateString()}
                          </div>
                        </>
                      )}
                    </div>
                    {editingThreadId !== thread.session_id && (
                      <div className="thread-actions">
                        <button
                          className="thread-edit-btn"
                          onClick={(e) => handleEditClick(e, thread)}
                          title="Edit title"
                        >
                          <Edit2 size={14} />
                        </button>
                        <button
                          className="thread-delete-btn"
                          onClick={(e) => handleDeleteClick(e, thread)}
                          title="Delete thread"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Chat Area */}
          <main className="chat-main">
            <div className="chat-messages">
              {messages.length === 0 ? (
                <div className="chat-welcome">
                  <div className="welcome-icon">
                    <Bot size={64} />
                  </div>
                  <h2>How can I help you find information?</h2>
                  <p>Ask me about company policies, procedures, or documentation</p>

                  <div className="chat-suggestions">
                    {suggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="chat-suggestion"
                      >
                        <span className="suggestion-icon">💡</span>
                        <span>{suggestion}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <div
                      key={msg.message_id}
                      className={`message ${msg.role === "user" ? "user" : "assistant"}`}
                    >
                      <div className="message-avatar">
                        {msg.role === "user" ? (
                          <User size={20} />
                        ) : (
                          <Bot size={20} />
                        )}
                      </div>
                      <div className="message-content">
                        <div className="message-text">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  ))}
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
                  placeholder="Ask a question..."
                  className="chat-textarea"
                  rows={1}
                  disabled={isStreaming}
                />
                <button
                  type="submit"
                  disabled={!input.trim() || isStreaming}
                  className="chat-send-btn"
                >
                  <Send size={20} />
                </button>
              </form>
            </div>
          </main>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        isOpen={deleteModalOpen}
        onClose={() => {
          if (!isDeleting) {
            setDeleteModalOpen(false);
            setThreadToDelete(null);
          }
        }}
        onConfirm={() => threadToDelete && deleteThread(threadToDelete.session_id)}
        documentName={threadToDelete ? `"${threadToDelete.title}"` : ''}
        isDeleting={isDeleting}
      />
    </div>
  );
}

export default SFXBot;
