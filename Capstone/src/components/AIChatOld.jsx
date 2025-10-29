import React, { useState } from 'react';
import '../css/AIChatOld.css'; // Using the same CSS file name

function AIChat() {
  const formFields = [
    { id: 'last_node', label: 'Last Node' },
    { id: 'next_node', label: 'Next Node' },
    { id: 'thread', label: 'Thread' },
    { id: 'draft_rev', label: 'Draft Rev' },
    { id: 'count', label: 'Count' },
  ];

  const tabs = ['Agent', 'Plan', 'Research Content', 'Draft', 'Critique', 'StateSnapShots'];
  const [activeTab, setActiveTab] = useState(0);
  const [isAgentManagerOpen, setIsAgentManagerOpen] = useState(true);

  const interruptOptions = [
    { id: 'planner', label: 'Planner' },
    { id: 'research_plan', label: 'Research Plan' },
    { id: 'generate', label: 'Generate' },
    { id: 'reflect', label: 'Reflect' },
    { id: 'research_critique', label: 'Research Critique' },
  ];

  const [interruptState, setInterruptState] = useState({
    planner: false,
    research_plan: false,
    generate: false,
    reflect: false,
    research_critique: false,
  });

  const [chooseThread, setChooseThread] = useState(0);
  const [updateState, setUpdateState] = useState("");
  const [planText, setPlanText] = useState("");
  const [draftText, setDraftText] = useState("");
  const [critiqueText, setCritiqueText] = useState("");
  const [stateSnapShotsText, setStateSnapShotsText] = useState("");
  const [researchContent, setResearchContent] = useState("");


  const handleInterruptChange = (id) => {
    setInterruptState((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 0: // Agent Tab
        return (
          <div className="agent-tab-container">
            <div className="input-group">
              <label htmlFor="essay-topic" className="input-label">
                Essay Topic
              </label>
              <input
                id="essay-topic"
                className="text-input"
                type="text"
                placeholder="Enter the topic for the essay..."
              />
            </div>
            <div className="form-row">
              {formFields.map((field) => (
                <div key={field.id} className="form-field">
                  <label htmlFor={field.id} className="field-label">
                    {field.label}
                  </label>
                  <input id={field.id} className="small-input" placeholder="Value" />
                </div>
              ))}
            </div>

            <div className="manage-agent-card">
              <div
                className="manage-agent-header"
                onClick={() => setIsAgentManagerOpen(!isAgentManagerOpen)}
              >
                <span>Manage Agent</span>
                <span className={`dropdown-arrow ${isAgentManagerOpen ? 'open' : ''}`}>&#9660;</span>
              </div>
              {isAgentManagerOpen && (
                <div className="manage-agent-content">
                  <div className="interrupt-row">
                    <span className="interrupt-label">Interrupt After State</span>
                    <div className="interrupt-checkboxes">
                      {interruptOptions.map((opt) => (
                        <label key={opt.id} className="interrupt-checkbox">
                          <input
                            type="checkbox"
                            checked={interruptState[opt.id]}
                            onChange={() => handleInterruptChange(opt.id)}
                          />
                          {opt.label}
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="manage-agent-row">
                    <label className="choose-thread-label" htmlFor="choose-thread">
                      Choose Thread
                    </label>
                    <select
                      id="choose-thread"
                      className="choose-thread-select"
                      value={chooseThread}
                      onChange={(e) => setChooseThread(Number(e.target.value))}
                    >
                      <option value={0}>0</option>
                      <option value={1}>1</option>
                    </select>
                    <input
                      className="update-state-input"
                      value={updateState}
                      onChange={(e) => setUpdateState(e.target.value)}
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="input-group">
              <label htmlFor="agent-output" className="input-label section-title">
                Live Agent Output
              </label>
              <textarea
                id="agent-output"
                className="output-box"
                placeholder="Live agent output will appear here..."
                rows={10}
              ></textarea>
            </div>
            
            <div className="agent-actions">
                <div className="button-group">
                    <button className="btn btn-secondary">Continue Essay</button>
                    <button className="btn btn-primary">Generate Essay</button>
                </div>
            </div>
          </div>
        );
      case 1: // Plan Tab
        return (
          <div className="plan-tab-container">
            <div className="plan-actions">
              <button className="btn btn-plan">Refresh</button>
              <button className="btn btn-plan">Modify</button>
            </div>
            <div className="plan-content-card">
              <p className="plan-metadata">Plan</p>
              <textarea
                className="plan-editor"
                value={planText}
                onChange={(e) => setPlanText(e.target.value)}
              />
            </div>
          </div>
        );
      case 2: // Research Content Tab
        return (
            <div className="research-content-tab-container">
              <div className="plan-actions">
                <button className="btn btn-plan">Refresh</button>
              </div>
              <div className="plan-content-card">
                <p className="plan-metadata">Research Content</p>
                <textarea
                  className="plan-editor"
                  value={researchContent}
                  onChange={(e) => setResearchContent(e.target.value)}
                />
              </div>
            </div>
          );
      case 3: // Draft Tab
        return (
          <div className="draft-tab-container">
            <div className="plan-actions">
              <button className="btn btn-plan">Refresh</button>
              <button className="btn btn-plan">Modify</button>
            </div>
            <div className="plan-content-card">
              <p className="plan-metadata">Draft</p>
              <textarea
                className="plan-editor"
                value={draftText}
                onChange={(e) => setDraftText(e.target.value)}
              />
            </div>
          </div>
        );
      case 4: // Critique Tab
        return (
          <div className="critique-tab-container">
            <div className="plan-actions">
              <button className="btn btn-plan">Refresh</button>
              <button className="btn btn-plan">Modify</button>
            </div>
            <div className="plan-content-card">
              <p className="plan-metadata">Critique</p>
              <textarea
                className="plan-editor"
                value={critiqueText}
                onChange={(e) => setCritiqueText(e.target.value)}
              />
            </div>
          </div>
        );
      case 5: // State Snapshots Tab
        return (
          <div className="state-snapshots-tab-container">
            <div className="plan-actions">
              <button className="btn btn-plan">Refresh</button>
              <button className="btn btn-plan">Modify</button>
            </div>
            <div className="plan-content-card">
              <p className="plan-metadata">State Snapshots</p>
              <textarea
                className="plan-editor"
                value={stateSnapShotsText}
                onChange={(e) => setStateSnapShotsText(e.target.value)}
              />
            </div>
          </div>
        );
      default:
        return (
          <div className="placeholder-content">
            <h2>{tabs[activeTab]}</h2>
            <p>Content for this section is displayed here.</p>
          </div>
        );
    }
  };

  return (
    <div className="ai-chat-page">
      <div className="aichat-container">
        <header className="page-header">
          <div>
            <h1 className="aichat-header-title">AI Chat</h1>
            <p className="header-subtitle">Use the agent to generate, critique, and refine content.</p>
          </div>
        </header>
        <main className="content-card">
          <div className="ai-chat-tabs">
            {tabs.map((tab, idx) => (
              <button
                key={tab}
                className={`tab${activeTab === idx ? ' active' : ''}`}
                onClick={() => setActiveTab(idx)}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="ai-chat-content">{renderTabContent()}</div>
          <div className="ai-chat-footer">
            <div className="footer-status">
              <span>Status:</span>
              <span className="status-text">Idle</span>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

export default AIChat;