import React, { useState, useEffect, useRef } from "react";
import { Sparkles, Send, Clock, CheckCircle, XCircle, Loader2, Mail, Calendar, User, MessageSquare, Trash2 } from "lucide-react";
import "../css/AIChat3.css";

// Assuming you have an api.js file configured, otherwise use a direct fetch or axios
// import api from "../api";
// If not using api.js, define the base URL here:
const API_BASE_URL = "http://localhost:8000"; // Match your FastAPI server port

// Helper function to parse email results from assistant response
function parseEmailResults(content) {
  try {
    // Try to extract JSON from the response
    const jsonMatch = content.match(/\{[\s\S]*"emails"[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed.emails && Array.isArray(parsed.emails)) {
        return parsed.emails;
      }
    }
    
    // Try to find email objects in the text
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
    <div style={{
      background: 'white',
      border: '1px solid #e2e8f0',
      borderRadius: '8px',
      padding: '1rem',
      marginBottom: '0.75rem',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', marginBottom: '0.5rem' }}>
        <Mail size={18} color="#26326E" style={{ flexShrink: 0, marginTop: '2px' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, color: '#1e293b', marginBottom: '0.25rem' }}>
            {email.subject || 'No Subject'}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', fontSize: '0.85rem', color: '#64748b' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <User size={14} />
              <span>{email.from || 'Unknown'}</span>
            </div>
            {email.date && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                <Calendar size={14} />
                <span>{new Date(email.date).toLocaleDateString()}</span>
              </div>
            )}
          </div>
        </div>
      </div>
      {email.body && (
        <div style={{
          fontSize: '0.9rem',
          color: '#475569',
          marginTop: '0.5rem',
          paddingTop: '0.5rem',
          borderTop: '1px solid #f1f5f9',
          maxHeight: '100px',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }}>
          {email.body.substring(0, 200)}{email.body.length > 200 ? '...' : ''}
        </div>
      )}
    </div>
  );
}

function AIChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  // Use 'threadId' to match the backend's terminology
  const [threadId, setThreadId] = useState(null);
  const [isLoadingThread, setIsLoadingThread] = useState(false); // Add this line
  const [threads, setThreads] = useState([]);
  const [isLoadingThreads, setIsLoadingThreads] = useState(false); // Loading state for initial thread setup
  const [pendingActions, setPendingActions] = useState([]);
  const [isFetchingPending, setIsFetchingPending] = useState(false);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  // Load or create thread on mount
  useEffect(() => {
    loadOrCreateThread();
  }, []);

  // FIND the useEffect for polling (around line 135) and REPLACE it:
  useEffect(() => {
    // Only poll if we have an active thread
    if (!threadId) {
      console.log("⏸️ Polling paused - no active thread");
      return;
    }

    const intervalId = setInterval(() => {
      if (!isStreaming) {
        fetchPendingActions();
        fetchThreads();
      }
    }, 100000); // 100 seconds

    return () => clearInterval(intervalId); // Cleanup on unmount
  }, [isStreaming, threadId]); // Add threadId dependency


  // Fetch threads from new thread API
  const fetchThreads = async () => {
    setIsLoadingThreads(true);
    try {
      // Use hardcoded user_id for now - you can make this dynamic later
      const userId = "default_user";
      const response = await fetch(`${API_BASE_URL}/threads?user_id=${userId}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch threads: ${response.status}`);
      }
      const data = await response.json();
      console.log("Fetched threads:", data);
      setThreads(data.threads || []);
    } catch (error) {
      console.error("Error fetching threads:", error);
    } finally {
      setIsLoadingThreads(false);
    }
  };

  // Add this new function after fetchThreads
  const handleThreadSelect = async (thread_id) => {
    if (thread_id === threadId) return; // Already on this thread
    
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

  // Delete thread using new thread API
  const handleDeleteThread = async (thread_id, e) => {
    e.stopPropagation(); // Prevent thread selection when clicking delete
    
    if (!confirm("Are you sure you want to delete this conversation?")) {
      return;
    }
    
    try {
      const response = await fetch(`${API_BASE_URL}/threads/${thread_id}`, {
        method: "DELETE",
      });
      
      if (!response.ok) {
        throw new Error(`Failed to delete thread: ${response.status}`);
      }
      
      // Refresh threads list
      await fetchThreads();
      
      // If deleted thread was active, create new thread
      if (thread_id === threadId) {
        await createNewThread();
      }
    } catch (error) {
      console.error("Error deleting thread:", error);
    }
  };

  // Load or create thread using new thread API
  const loadOrCreateThread = async () => {
    setIsLoadingThread(true);
    try {
      const userId = "default_user";
      const response = await fetch(`${API_BASE_URL}/threads?user_id=${userId}`);
      if (!response.ok) {
        throw new Error(`Failed to list threads: ${response.status} ${response.statusText}`);
      }
      const threadsData = await response.json();
      console.log("Fetched threads:", threadsData);

      if (threadsData.threads && threadsData.threads.length > 0) {
        const latestThread = threadsData.threads[0];
        setThreadId(latestThread.thread_id);
        await loadThreadMessages(latestThread.thread_id);
        setIsLoadingThread(false);
        console.log("Loaded existing thread:", latestThread.thread_id);
        await fetchThreads();
        return;
      }
      
      // No existing threads, start fresh (don't create until user sends first message)
      setMessages([]);
      setThreadId(null);
      setIsLoadingThread(false);
      await fetchThreads();
      
    } catch (error) {
      console.error("Error loading threads:", error);
      setMessages([]);
      setThreadId(null);
      setIsLoadingThread(false);
    }
  };


  const createNewThread = async () => {
    try {
      // Clear current state
      setMessages([]);
      setThreadId(null);
      setPendingActions([]);
      
      // Thread will be created when user sends first message
      console.log("✅ Ready for new thread (will be created on first message)");
      await fetchThreads(); // Refresh threads list
      
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

  const loadThreadMessages = async (thread_id) => {
    try {
      // Fetch thread messages from new API
      const response = await fetch(`${API_BASE_URL}/threads/${thread_id}/messages`);
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log("Loaded thread messages:", data);

      // Convert messages to UI format
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
      // Optionally add an error message to the UI
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
    // Prevent multiple simultaneous fetches
    if (isFetchingPending) return;
    setIsFetchingPending(true);
    try {
      // const response = await api.get("/actions/pending"); // If using api.js
      const response = await fetch(`${API_BASE_URL}/actions/pending`);
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      console.log("Fetched pending actions:", data);
      setPendingActions(data.pending_actions || []);
    } catch (error) {
      console.error("Error fetching pending actions:", error);
      // Optionally clear pending actions or show an error
      // setPendingActions([]); // Or keep the old list if error is temporary
    } finally {
      setIsFetchingPending(false);
    }
  };

  // ADD this new function after fetchPendingActions (around line 315):
  const cleanupExpiredActions = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/actions/cleanup`, {
        method: "POST",
      });
      if (response.ok) {
        const data = await response.json();
        console.log(`🧹 Cleaned up ${data.cleaned_count} expired actions`);
      }
    } catch (error) {
      console.error("Error cleaning up actions:", error);
    }
  };

  // UPDATE handleNewChat to cleanup when starting fresh (around line 490):
  const handleNewChat = async () => {
    console.log("🆕 Starting new chat...");
    
    // Clear the current thread state
    setMessages([]);
    setPendingActions([]); // Clear pending actions UI
    setThreadId(null); // Clear thread ID temporarily
    
    // Cleanup any expired backend actions
    await cleanupExpiredActions();
    
    // Create new thread (without automatic message)
    await createNewThread();
    
    // Focus on input field so user can type
    textareaRef.current?.focus();
  };

  const handleApproveAction = async (actionId) => {
    try {
      // const response = await api.post(`/action/approve/${actionId}`, { decision: 'approve' }); // If using api.js
      const response = await fetch(`${API_BASE_URL}/action/approve/${actionId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ decision: 'approve' }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const result = await response.json();
      console.log("Action approved:", result);
      // Remove the approved action from the local state
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      // Optionally add a message to the chat confirming approval
      setMessages(prev => [...prev, {
          id: `approval-${actionId}`,
          role: "assistant",
          content: `Action "${result.step_info?.description || 'Unknown Action'}" approved and executed.`,
          timestamp: new Date(),
          info: true,
      }]);
    } catch (error) {
      console.error("Error approving action:", error);
      // Optionally add an error message to the chat or update the action status
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
      // const response = await api.post(`/action/approve/${actionId}`, { decision: 'reject' }); // If using api.js
      const response = await fetch(`${API_BASE_URL}/action/approve/${actionId}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ decision: 'reject' }),
      });
      if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: `HTTP error! status: ${response.status}` }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }
      const result = await response.json();
      console.log("Action rejected:", result);
      // Remove the rejected action from the local state
      setPendingActions(prev => prev.filter(action => action.action_id !== actionId));
      // Optionally add a message to the chat confirming rejection
      setMessages(prev => [...prev, {
          id: `rejection-${actionId}`,
          role: "assistant",
          content: `❌ Action was rejected and will not be executed.`,
          timestamp: new Date(),
          info: true,
      }]);
    } catch (error) {
      console.error("Error rejecting action:", error);
      // Optionally add an error message to the chat or update the action status
      setMessages(prev => [...prev, {
          id: `rejection-error-${actionId}`,
          role: "assistant",
          content: `Failed to reject action ${actionId}: ${error.message}`,
          timestamp: new Date(),
          error: true,
      }]);
    }
  };

  // REPLACE your entire handleSubmit function (lines 431-588) with this:
  const handleSubmit = async (e) => {
    e.preventDefault();

    const userMessage = input.trim();
    if (!userMessage || isStreaming) return;

    // Store current threadId - may be null for first message
    const currentThreadId = threadId;

    // Add user's message immediately
    const userMessageObj = {
      id: `user-${Date.now()}`,
      role: "user",
      content: userMessage,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessageObj]);
    setInput("");
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

      let responseData;
      
      // If no thread exists, create one with initial message
      if (!currentThreadId) {
        const response = await fetch(`${API_BASE_URL}/threads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: "default_user",
            message: userMessage,
            tags: []
          }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({
            detail: `HTTP error! status: ${response.status}`,
          }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }

        responseData = await response.json();
        console.log("📥 Created thread:", responseData);
        
        // Set the new thread ID
        setThreadId(responseData.thread_id);
        await fetchThreads(); // Refresh threads list
      } else {
        // Thread exists, send message to existing thread
        const response = await fetch(`${API_BASE_URL}/threads/${currentThreadId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: userMessage,
          }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({
            detail: `HTTP error! status: ${response.status}`,
          }));
          throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }

        responseData = await response.json();
        console.log("📥 Received response:", responseData);
      }

      // Get the bot's response text
      const fullResponse = responseData.bot_response || "No response received from the assistant.";
      
      // Check if the conversation is now ready for execution
      const isReadyForExecution = !!responseData.ready_for_execution;
      
      if (isReadyForExecution) {
        console.log("✅ Workflow ready for execution based on response.");
      }

      // Simulate streaming effect (word by word)
      let currentText = "";
      const words = fullResponse.split(" ");
      for (let i = 0; i < words.length; i++) {
        currentText += (i > 0 ? " " : "") + words[i];
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: currentText }
              : msg
          )
        );
        await new Promise((resolve) => setTimeout(resolve, 30));
      }

      // Auto-execute when ready (requires manual approval if risk level is DANGEROUS)
      if (isReadyForExecution) {
        const execThreadId = responseData.thread_id || currentThreadId;
        console.log("🔄 Auto-executing conversation:", execThreadId);
        
        // Call the execute endpoint
        const execResponse = await fetch(
          `${API_BASE_URL}/chat/${data.conversation_id || currentThreadId}/execute`,
          { method: "POST" }
        );

        if (!execResponse.ok) {
          const execErrorData = await execResponse.json().catch(() => ({
            detail: `HTTP error! status: ${execResponse.status}`,
          }));
          throw new Error(execErrorData.detail || `Execution failed: ${execResponse.status}`);
        }

        const execResult = await execResponse.json();
        console.log("✅ Execution completed or paused for approval:", execResult);

        // Check if execution was paused for approval
        if (execResult.status === "approval_required") {
          console.log("🔄 Execution paused, awaiting approval. Action ID:", execResult.action_id);
          
          // Fetch pending actions to update UI
          await fetchPendingActions();
          
          // Add message indicating approval is needed
          setMessages((prev) => [
            ...prev,
            {
              id: `approval-needed-${Date.now()}`,
              role: "assistant",
              content: `⏸️ Action "${execResult.step_info?.description || "Unknown Action"}" requires your approval.`,
              timestamp: new Date(),
              info: true,
            },
          ]);
        } else if (execResult.status === "completed") {
          // Execution completed successfully
          setMessages((prev) => [
            ...prev,
            {
              id: `exec-summary-${Date.now()}`,
              role: "assistant",
              content: `✅ Execution completed. Summary: ${execResult.execution_summary || "Task finished successfully."}`,
              timestamp: new Date(),
              info: true,
            },
          ]);
        } else if (execResult.status === "failed") {
          // Execution failed
          setMessages((prev) => [
            ...prev,
            {
              id: `exec-error-${Date.now()}`,
              role: "assistant",
              content: `❌ Execution failed: ${execResult.error || "Unknown error occurred."}`,
              timestamp: new Date(),
              error: true,
            },
          ]);
        }
      }

    } catch (error) {
      console.error("Error during chat or execution:", error);
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

  // Show loading state while thread is being created
  if (isLoadingThread) {
    return (
      <div className="ai-chat-page">
        <div className="aichat-container">
          <div className="loading-container">
            <Sparkles size={48} className="loading-icon" />
            <p>Loading chat...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-chat-page">
      <div className="aichat-container">
        {/* Threads Sidebar - NEW */}
        <aside className="threads-sidebar">
          <div className="threads-header">
            <h3 className="threads-title">
              <MessageSquare size={20} />
              Conversations
            </h3>
            <button
              onClick={handleNewChat}
              className="new-thread-button"
              disabled={isStreaming}
              title="New Chat"
            >
              +
            </button>
          </div>
          
          <div className="threads-list">
            {isLoadingThreads ? (
              <div className="threads-loading">
                <Loader2 size={20} className="spinner" />
                <span>Loading...</span>
              </div>
            ) : threads.length === 0 ? (
              <div className="threads-empty">
                <MessageSquare size={32} opacity={0.3} />
                <p>No conversations yet</p>
              </div>
            ) : (
              threads.map((thread) => (
                <div
                  key={thread.thread_id}
                  className={`thread-item ${thread.thread_id === threadId ? 'active' : ''}`}
                  onClick={() => handleThreadSelect(thread.thread_id)}
                >
                  <div className="thread-content">
                    <div className="thread-header">
                      <MessageSquare size={16} />
                      <span className="thread-id">
                        {thread.title || thread.thread_id.substring(0, 12) + '...'}
                      </span>
                    </div>
                    {thread.status && (
                      <span className="thread-status">{thread.status}</span>
                    )}
                    <span className="thread-messages">
                      {thread.message_count || 0} messages
                    </span>
                  </div>
                  <button
                    className="thread-delete"
                    onClick={(e) => handleDeleteThread(thread.thread_id, e)}
                    title="Delete conversation"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>

        {/* Main Chat Area - WRAPPED */}
        <div className="chat-main">
          <div className="chat-main-content">
            <header className="page-header">
              <div>
                <h1 className="aichat-header-title">
                  <Sparkles
                    size={32}
                    style={{ marginRight: "0.5rem", color: "#26326E" }}
                  />
                  AI Chat
                </h1>
                <p className="header-subtitle">
                  Chat with AI assistant powered by your Google Workspace
                </p>
              </div>
            </header>

            <main className="chat-card">
            <div className="messages-area">
              {messages.length === 0 ? (
                <div className="welcome-container">
                  <div className="welcome-icon">
                    <Sparkles size={48} />
                  </div>
                  <h2 className="welcome-title">
                    Hello! How can I help you today?
                  </h2>
                  <p className="welcome-subtitle">
                    I can help you with Gmail, Google Docs, Drive, and more
                  </p>

                  <div className="suggestions-grid">
                    {suggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="suggestion-card"
                      >
                        <span className="suggestion-icon">💡</span>
                        <span className="suggestion-text">{suggestion}</span>
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
                        className={`message-wrapper ${message.role} ${message.error ? 'error' : ''} ${message.info ? 'info' : ''}`}
                      >
                        <div
                          className={`message-bubble ${message.role} ${
                            message.error ? "error" : ""
                          } ${message.info ? "info" : ""}`}
                        >
                          {emails && emails.length > 0 ? (
                            <div className="message-content">
                              <div style={{ marginBottom: '0.75rem', fontWeight: 600, color: '#26326E' }}>
                                📧 Found {emails.length} email{emails.length !== 1 ? 's' : ''}
                              </div>
                              {emails.map((email, idx) => (
                                <EmailCard key={email.message_id || idx} email={email} />
                              ))}
                            </div>
                          ) : (
                            <div className="message-content">
                              {message.content}
                              {message.role === "assistant" &&
                                isStreaming &&
                                message.content && (
                                  <span className="cursor-blink">|</span>
                                )}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            <form onSubmit={handleSubmit} className="input-area">
              <div className="input-wrapper">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask me to create documents, send emails, or help with tasks..."
                  disabled={isStreaming}
                  className="message-textarea"
                  rows={1}
                />
                <button
                  type="submit"
                  disabled={isStreaming || !input.trim()}
                  className="send-button"
                >
                  <Send size={20} />
                </button>
              </div>
              <div className="input-footer">
                <span className="input-hint">
                  {isStreaming
                    ? "AI is thinking..."
                    : "Press Enter to send, Shift+Enter for new line"}
                </span>
              </div>
            </form>
          </main>
          </div>

          {/* Pending Actions Sidebar - RIGHT SIDE */}
          <aside className="pending-actions-sidebar">
            <div className="pending-actions-header">
              <h3 className="pending-actions-title">
                <Clock size={18} className="pending-actions-icon" />
                Pending Actions
              </h3>
            </div>
            
            {pendingActions.length > 0 ? (
              <div className="pending-actions-list">
                {pendingActions.map((action) => (
                  <div key={action.action_id} className="pending-action-item">
                    <div className="pending-action-details">
                      <p className="pending-action-description">{action.description || "Action description unavailable"}</p>
                      <p className="pending-action-agent">Agent: <strong>{action.agent || "Unknown Agent"}</strong></p>
                      <p className="pending-action-tool">Tool: <strong>{action.tool || "Unknown Tool"}</strong></p>
                      {action.inputs && Object.keys(action.inputs).length > 0 && (
                        <details className="pending-action-inputs">
                          <summary>Inputs</summary>
                          <pre>{JSON.stringify(action.inputs, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                    <div className="pending-action-buttons">
                      <button
                        onClick={() => handleApproveAction(action.action_id)}
                        className="approve-button"
                        disabled={isFetchingPending}
                      >
                        <CheckCircle size={16} /> Approve
                      </button>
                      <button
                        onClick={() => handleRejectAction(action.action_id)}
                        className="reject-button"
                        disabled={isFetchingPending}
                      >
                        <XCircle size={16} /> Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : isFetchingPending ? (
              <div className="pending-actions-empty">
                <Loader2 size={20} className="spinner" />
                <span>Checking...</span>
              </div>
            ) : (
              <div className="pending-actions-empty">
                <Clock size={32} opacity={0.3} />
                <p>No pending actions</p>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
export default AIChat;