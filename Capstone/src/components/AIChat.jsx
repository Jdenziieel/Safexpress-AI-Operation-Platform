import React, { useState, useEffect, useRef } from "react";
import { Send, Sparkles } from "lucide-react";
import "../css/AIChat3.css";
import { ACCESS_TOKEN } from "../token";

const API_BASE_URL = "https://d1r565u2m90baj.cloudfront.net";

function AIChat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [threadId, setThreadId] = useState(null);
  const [isLoadingThread, setIsLoadingThread] = useState(true);
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
      textareaRef.current.style.height =
        textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  // Load or create thread on mount
  useEffect(() => {
    loadOrCreateThread();
  }, []);

  const loadOrCreateThread = async () => {
    try {
      const token = localStorage.getItem(ACCESS_TOKEN);
      
      // Try to get existing threads
      const threadsResponse = await fetch(
        `${API_BASE_URL}/api/chat/threads`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (threadsResponse.ok) {
        const threadsData = await threadsResponse.json();
        
        // Use the most recent thread if it exists
        if (threadsData.threads && threadsData.threads.length > 0) {
          const latestThread = threadsData.threads[0];
          setThreadId(latestThread.thread_id);
          
          // Load messages from this thread
          await loadThreadMessages(latestThread.thread_id, token);
          setIsLoadingThread(false);
          return;
        }
      }

      // No threads exist, create a new one
      await createNewThread();
      
    } catch (error) {
      console.error("Error loading thread:", error);
      // Create new thread as fallback
      await createNewThread();
    }
  };

  const createNewThread = async () => {
    try {
      const token = localStorage.getItem(ACCESS_TOKEN);
      
      const response = await fetch(
        `${API_BASE_URL}/api/chat/threads/create`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            title: "New Conversation",
          }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        setThreadId(data.thread_id);
        console.log("✅ Created new thread:", data.thread_id);
      }
    } catch (error) {
      console.error("Error creating thread:", error);
    } finally {
      setIsLoadingThread(false);
    }
  };

  const loadThreadMessages = async (thread_id, token) => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/chat/threads/${thread_id}/messages`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (response.ok) {
        const data = await response.json();
        
        // Convert messages to UI format
        const formattedMessages = data.messages.map((msg) => ({
          id: msg.message_id,
          role: msg.sender, // 'user' or 'assistant'
          content: msg.content,
          timestamp: new Date(msg.created_at),
        }));
        
        setMessages(formattedMessages);
        console.log(`✅ Loaded ${formattedMessages.length} messages`);
      }
    } catch (error) {
      console.error("Error loading messages:", error);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isStreaming || !threadId) return;

    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const userInput = input.trim();
    setInput("");
    setIsStreaming(true);

    // Add empty assistant message for streaming
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
      const token = localStorage.getItem(ACCESS_TOKEN);

      // ✅ Updated: Send to correct endpoint with thread_id
      const response = await fetch(
        `${API_BASE_URL}/api/chat/messages/send`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            thread_id: threadId,
            message: userInput,
            // ❌ DON'T send history - Django gets it from DynamoDB!
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      // ✅ Get response from Supervisor Lambda
      const fullResponse = data.response || "No response received.";
      
      // Log tool calls if any
      if (data.tool_calls && data.tool_calls.length > 0) {
        console.log("🔧 Tool calls executed:", data.tool_calls);
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

        // Small delay for streaming effect
        await new Promise((resolve) => setTimeout(resolve, 30));
      }
      
      // Update the assistant message with actual message_id from backend
      if (data.assistant_message_id) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, id: data.assistant_message_id }
              : msg
          )
        );
      }

    } catch (error) {
      console.error("Error:", error);

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

  const handleNewChat = async () => {
    // Create a new thread
    setMessages([]);
    await createNewThread();
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
          <button 
            onClick={handleNewChat} 
            className="new-chat-button"
            disabled={isStreaming}
          >
            + New Chat
          </button>
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
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`message-wrapper ${message.role}`}
                  >
                    <div
                      className={`message-bubble ${message.role} ${
                        message.error ? "error" : ""
                      }`}
                    >
                      <div className="message-content">
                        {message.content}
                        {message.role === "assistant" &&
                          isStreaming &&
                          message.content && (
                            <span className="cursor-blink">|</span>
                          )}
                      </div>
                    </div>
                  </div>
                ))}
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
                disabled={isStreaming || !threadId}
                className="message-textarea"
                rows={1}
              />
              <button
                type="submit"
                disabled={isStreaming || !input.trim() || !threadId}
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
    </div>
  );
}

export default AIChat;