import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import '../css/WorkloadAnalysis.css';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import { 
  ArrowLeft,
  Plus, 
  Trash2, 
  Calculator, 
  Users, 
  Clock, 
  Calendar,
  Download,
  RefreshCw,
  Package,
  TrendingUp,
  Settings,
  Save,
  History,
  Database
} from 'lucide-react';
import { workloadConfigAPI, workloadCalculationAPI, checkAPIHealth } from '../utils/workloadAPI';

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button className={`main-card-btn ${className}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.1rem', fontWeight: 700 }} {...props}>
      <Icon size={20} />
    </button>
    <span style={{ 
      position: 'absolute', 
      top: '100%', 
      left: '50%', 
      transform: 'translateX(-50%)', 
      marginTop: '8px',
      padding: '6px 12px', 
      background: '#26326e', 
      color: 'white', 
      borderRadius: '6px', 
      fontSize: '0.85rem', 
      fontWeight: 600,
      whiteSpace: 'nowrap',
      opacity: 0,
      pointerEvents: 'none',
      transition: 'opacity 0.2s',
      zIndex: 1000
    }} className="button-tooltip">{children}</span>
  </div>
);

const WorkloadAnalysis = () => {
  const navigate = useNavigate();

  // Warehouse phase processing rates (seconds per pallet)
  const [phaseRates, setPhaseRates] = useState({
    'inboundChecking': 215.07,
    'putAway': 152.99,
    'picking': 215.07,
    'outboundChecking': 215.07,
  });

  // Form state - Items with pallets and items per pallet
  const [items, setItems] = useState([
    { id: Date.now(), description: '', pallets: '', itemsPerPallet: '' }
  ]);
  const [numberOfPeople, setNumberOfPeople] = useState('');
  const [showRateSettings, setShowRateSettings] = useState(false);
  
  // Results state
  const [results, setResults] = useState(null);
  const [showResults, setShowResults] = useState(false);

  // Backend integration state
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);

  // Load configuration from backend on mount
  useEffect(() => {
    loadConfiguration();
    checkBackendConnection();
  }, []);

  // Check backend connection
  const checkBackendConnection = async () => {
    const isConnected = await checkAPIHealth();
    setIsBackendConnected(isConnected);
    if (!isConnected) {
      console.warn('Backend not connected. Running in offline mode.');
    }
  };

  // Load time configuration from backend
  const loadConfiguration = async () => {
    try {
      const config = await workloadConfigAPI.getConfig();
      setPhaseRates({
        inboundChecking: config.inboundChecking,
        putAway: config.putAway,
        picking: config.picking,
        outboundChecking: config.outboundChecking,
      });
      setConfigLoaded(true);
    } catch (error) {
      console.error('Failed to load configuration:', error);
      // Keep default values if backend is not available
    }
  };

  // Save configuration to backend
  const saveConfiguration = async () => {
    try {
      await workloadConfigAPI.updateConfig({
        inboundChecking: phaseRates.inboundChecking,
        putAway: phaseRates.putAway,
        picking: phaseRates.picking,
        outboundChecking: phaseRates.outboundChecking,
        updatedBy: 'user' // Replace with actual user when auth is implemented
      });
      alert('Configuration saved successfully!');
      setConfigLoaded(true);
    } catch (error) {
      console.error('Failed to save configuration:', error);
      alert('Failed to save configuration. Please try again.');
    }
  };

  // Add new item
  const addItem = () => {
    setItems([...items, { 
      id: Date.now(), 
      description: '', 
      pallets: '', 
      itemsPerPallet: '' 
    }]);
  };

  // Remove item
  const removeItem = (id) => {
    if (items.length > 1) {
      setItems(items.filter(item => item.id !== id));
    }
  };

  // Update item
  const updateItem = (id, field, value) => {
    setItems(items.map(item => 
      item.id === id ? { ...item, [field]: value } : item
    ));
  };

  // Calculate workload based on warehouse phases
  const calculateWorkload = () => {
    // Validation
    const hasValidItems = items.some(item => item.description && item.pallets);
    
    if (!hasValidItems || !numberOfPeople) {
      alert('Please fill in at least one item with pallets and number of people');
      return;
    }

    const people = parseInt(numberOfPeople);
    
    // Calculate total pallets and build items breakdown
    let totalPallets = 0;
    let totalItems = 0;
    const itemsBreakdown = [];
    
    items.forEach(item => {
      if (item.pallets) {
        const pallets = parseFloat(item.pallets);
        const itemsPerPallet = parseFloat(item.itemsPerPallet) || 0;
        const totalItemQty = pallets * itemsPerPallet;
        
        totalPallets += pallets;
        totalItems += totalItemQty;
        
        itemsBreakdown.push({
          description: item.description || 'Unnamed Item',
          pallets: pallets,
          itemsPerPallet: itemsPerPallet,
          totalItems: totalItemQty
        });
      }
    });
    
    // Calculate time for each phase (in seconds)
    // Formula: (Total Pallets / Number of Workers) * Seconds per Pallet
    const phases = [
      {
        name: 'Inbound Checking',
        key: 'inboundChecking',
        timeSeconds: (totalPallets / people) * phaseRates.inboundChecking
      },
      {
        name: 'Put-away',
        key: 'putAway',
        timeSeconds: (totalPallets / people) * phaseRates.putAway
      },
      {
        name: 'Picking',
        key: 'picking',
        timeSeconds: (totalPallets / people) * phaseRates.picking
      },
      {
        name: 'Outbound Checking',
        key: 'outboundChecking',
        timeSeconds: (totalPallets / people) * phaseRates.outboundChecking
      }
    ];
    
    // Calculate totals
    const totalSeconds = phases.reduce((sum, phase) => sum + phase.timeSeconds, 0);
    const totalMinutes = totalSeconds / 60;
    const totalHours = totalMinutes / 60;
    const displayHours = Math.floor(totalMinutes / 60);
    const displayMinutes = Math.round(totalMinutes % 60);

    setResults({
      totalPallets,
      totalItems,
      people,
      phases,
      totalSeconds,
      totalMinutes,
      totalHours,
      displayHours,
      displayMinutes,
      itemsBreakdown
    });

    setShowResults(true);
  };

  // Reset form
  const resetForm = () => {
    setItems([{ id: Date.now(), description: '', pallets: '', itemsPerPallet: '' }]);
    setNumberOfPeople('');
    setResults(null);
    setShowResults(false);
  };

  // Update phase rate
  const updatePhaseRate = (phase, value) => {
    setPhaseRates({
      ...phaseRates,
      [phase]: parseFloat(value) || 0
    });
  };

  // Save calculation to database
  const saveCalculation = async () => {
    if (!results) {
      alert('No calculation to save');
      return;
    }

    if (!isBackendConnected) {
      alert('Backend not connected. Cannot save calculation.');
      return;
    }

    setIsSaving(true);
    setSaveSuccess(false);

    try {
      const calculationData = {
        totalPallets: results.totalPallets,
        totalItems: results.totalItems,
        numberOfWorkers: results.people,
        totalHours: results.totalHours,
        totalMinutes: results.totalMinutes,
        items: results.itemsBreakdown,
        phases: results.phases.map(p => ({
          name: p.name,
          timeSeconds: p.timeSeconds,
          timeMinutes: Math.floor(p.timeSeconds / 60),
          timeRemainderSeconds: Math.round(p.timeSeconds % 60)
        })),
        configUsed: phaseRates,
        notes: '',
        createdBy: 'user' // Replace with actual user when auth is implemented
      };

      await workloadCalculationAPI.saveCalculation(calculationData);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      alert('Calculation saved to database successfully!');
    } catch (error) {
      console.error('Failed to save calculation:', error);
      alert('Failed to save calculation. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  // Export to PDF (placeholder for now)
  const exportToPDF = () => {
    if (!results) {
      alert('Please calculate workload first before exporting.');
      return;
    }

    const doc = new jsPDF();
    const generatedAt = new Date();
    const generatedDate = generatedAt.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
    const generatedTime = generatedAt.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit'
    });

    doc.setFontSize(18);
    doc.setFont('helvetica', 'bold');
    doc.text('Workload Analysis Report', 14, 18);

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`Generated: ${generatedDate} ${generatedTime}`, 14, 26);

    doc.setFontSize(11);
    doc.setFont('helvetica', 'bold');
    doc.text('Summary', 14, 36);

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`Total Processing Time: ${results.displayHours}h ${results.displayMinutes}m`, 14, 43);
    doc.text(`Total Pallets: ${results.totalPallets}`, 14, 49);
    doc.text(`Workers Assigned: ${results.people}`, 14, 55);
    doc.text(`Total Items: ${results.totalItems.toLocaleString()}`, 14, 61);

    autoTable(doc, {
      head: [['Warehouse Phase', 'Time']],
      body: [
        ...results.phases.map((phase) => [
          phase.name,
          `${Math.floor(phase.timeSeconds / 60)} min ${Math.round(phase.timeSeconds % 60)} sec`
        ]),
        ['Total Time', `${results.displayHours}h ${results.displayMinutes}m`]
      ],
      startY: 68,
      theme: 'grid',
      headStyles: {
        fillColor: [38, 50, 110],
        textColor: [255, 255, 255],
        fontStyle: 'bold'
      },
      bodyStyles: {
        fontSize: 9
      },
      alternateRowStyles: {
        fillColor: [245, 247, 250]
      }
    });

    const itemTableStartY = doc.lastAutoTable?.finalY ? doc.lastAutoTable.finalY + 10 : 120;

    autoTable(doc, {
      head: [['Item Description', 'Pallets', 'Items/Pallet', 'Total Items']],
      body: results.itemsBreakdown.map((item) => [
        item.description,
        item.pallets,
        item.itemsPerPallet,
        item.totalItems.toLocaleString()
      ]),
      startY: itemTableStartY,
      theme: 'grid',
      headStyles: {
        fillColor: [38, 50, 110],
        textColor: [255, 255, 255],
        fontStyle: 'bold'
      },
      bodyStyles: {
        fontSize: 9
      },
      alternateRowStyles: {
        fillColor: [245, 247, 250]
      }
    });

    const fileDate = generatedAt.toISOString().split('T')[0];
    doc.save(`workload-analysis-${fileDate}.pdf`);
  };

  return (
    <div className="workload-main">
      <div className="workload-container">
        {/* Header */}
        <div className="workload-header">
          <div className="header-left1">
            <ActionButton
              icon={ArrowLeft}
              className="action-button-export"
              onClick={() => navigate('/analysis-report')}
            >
              Back
            </ActionButton>
            <h1 className="workload-title">Workload Analysis</h1>
            <p className="header-subtitle">
              Calculate warehouse processing time across Inbound, Put-away, Picking, and Outbound phases
            </p>
          </div>
          <div className="header-actions">
            <ActionButton icon={Download} className="action-button-export" onClick={exportToPDF}>Export</ActionButton>
            <ActionButton 
              icon={Save} 
              className="action-button-settings" 
              onClick={saveCalculation}
              disabled={isSaving || !showResults || !isBackendConnected}
            >
              Save to Database
            </ActionButton>
          </div>
        </div>

        {/* Main Content - Two Column Layout */}
        <div className="workload-grid">
          {/* Left Column - Input Form */}
          <div className="form-section">
            {/* Combined Items & Pallets Section */}
            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Items & Pallets</h2>
              </div>
              <p className="section-description">
                Enter items with their pallet quantities and items per pallet
              </p>

              {/* Items List */}
              <div className="items-list">
                {items.map((item, index) => (
                  <div key={item.id} className="item-row">
                    <div className="item-number">{index + 1}</div>
                    <div className="item-inputs">
                      <input
                        type="text"
                        placeholder="Item Description (e.g., X item, Y item)"
                        value={item.description}
                        onChange={(e) => updateItem(item.id, 'description', e.target.value)}
                        className="input-field item-description"
                      />
                      <div className="quantity-unit-group">
                        <div className="quantity-input-wrapper">
                          <input
                            type="number"
                            placeholder="Pallets"
                            value={item.pallets}
                            onChange={(e) => updateItem(item.id, 'pallets', e.target.value)}
                            className="input-field item-quantity"
                            min="0"
                            step="1"
                          />
                          {item.pallets && (
                            <span className="quantity-label">{item.pallets} Pallets</span>
                          )}
                        </div>
                        <div className="quantity-input-wrapper">
                          <input
                            type="number"
                            placeholder="Items/Pallet"
                            value={item.itemsPerPallet}
                            onChange={(e) => updateItem(item.id, 'itemsPerPallet', e.target.value)}
                            className="input-field item-quantity"
                            min="0"
                            step="1"
                          />
                          {item.itemsPerPallet && (
                            <span className="quantity-label">{parseInt(item.itemsPerPallet).toLocaleString()} items</span>
                          )}
                        </div>
                      </div>
                    </div>
                    {items.length > 1 && (
                      <button
                        className="remove-item-btn"
                        onClick={() => removeItem(item.id)}
                        title="Remove item"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                ))}
              </div>

              <button className="add-item-btn" onClick={addItem}>
                <Plus size={16} />
                Add Another Item
              </button>
            </div>

            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Warehouse Phase Rates</h2>
              </div>
              <p className="section-description">
                Configure processing time per pallet for each warehouse operation phase
              </p>

              <button 
                className="toggle-rates-btn" 
                onClick={() => setShowRateSettings(!showRateSettings)}
              >
                {showRateSettings ? '− Hide Rate Settings' : '+ Show Rate Settings'}
              </button>

              {showRateSettings && (
                <>
                  <div className="rates-grid">
                    <div className="rate-input-group">
                      <div className="rate-header">
                        <label className="rate-label">Inbound Checking</label>
                        <span className="rate-description">Verify incoming pallets</span>
                      </div>
                      <div className="rate-input-wrapper">
                        <input
                          type="number"
                          value={phaseRates.inboundChecking}
                          onChange={(e) => updatePhaseRate('inboundChecking', e.target.value)}
                          className="rate-input"
                          min="0"
                          step="0.01"
                        />
                        <span className="rate-suffix">sec/pallet</span>
                      </div>
                    </div>
                    <div className="rate-input-group">
                      <div className="rate-header">
                        <label className="rate-label">Put-away</label>
                        <span className="rate-description">Store pallets in warehouse</span>
                      </div>
                      <div className="rate-input-wrapper">
                        <input
                          type="number"
                          value={phaseRates.putAway}
                          onChange={(e) => updatePhaseRate('putAway', e.target.value)}
                          className="rate-input"
                          min="0"
                          step="0.01"
                        />
                        <span className="rate-suffix">sec/pallet</span>
                      </div>
                    </div>
                    <div className="rate-input-group">
                      <div className="rate-header">
                        <label className="rate-label">Picking</label>
                        <span className="rate-description">Retrieve pallets for orders</span>
                      </div>
                      <div className="rate-input-wrapper">
                        <input
                          type="number"
                          value={phaseRates.picking}
                          onChange={(e) => updatePhaseRate('picking', e.target.value)}
                          className="rate-input"
                          min="0"
                          step="0.01"
                        />
                        <span className="rate-suffix">sec/pallet</span>
                      </div>
                    </div>
                    <div className="rate-input-group">
                      <div className="rate-header">
                        <label className="rate-label">Outbound Checking</label>
                        <span className="rate-description">Final verification before shipment</span>
                      </div>
                      <div className="rate-input-wrapper">
                        <input
                          type="number"
                          value={phaseRates.outboundChecking}
                          onChange={(e) => updatePhaseRate('outboundChecking', e.target.value)}
                          className="rate-input"
                          min="0"
                          step="0.01"
                        />
                        <span className="rate-suffix">sec/pallet</span>
                      </div>
                    </div>
                  </div>
                  {isBackendConnected && (
                    <button 
                      className="calculate-btn" 
                      onClick={saveConfiguration}
                      style={{ marginTop: '12px', background: 'linear-gradient(135deg, #10b981, #059669)' }}
                    >
                      <Save size={18} />
                      Save Configuration to Database
                    </button>
                  )}
                </>
              )}
            </div>

            <div className="section-card">
              <div className="section-header">
                <h2 className="section-title">Workforce</h2>
              </div>
              <p className="section-description">
                Number of workers assigned to process these items
              </p>
              <div className="params-grid">
                <div className="input-group">
                  <input
                    type="number"
                    placeholder="e.g., 2"
                    value={numberOfPeople}
                    onChange={(e) => setNumberOfPeople(e.target.value)}
                    className="input-field"
                    min="1"
                  />
                  <span className="input-hint">Workers assigned to all phases</span>
                </div>
              </div>

              <button className="calculate-btn" onClick={calculateWorkload}>
                Calculate Workload
              </button>
            </div>
          </div>

          {/* Right Column - Results */}
          <div className="results-section">
            {!showResults ? (
              <div className="empty-state">
                <Calculator size={48} className="empty-icon" />
                <h3>No Results Yet</h3>
                <p>Fill in items with pallets and workers, then click "Calculate Workload"</p>
              </div>
            ) : (
              <div className="results-content">
                <div className="section-card results-card">
                  <div className="section-header">
                    <h2 className="section-title">Warehouse Processing Time</h2>
                  </div>

                  {/* Key Metrics */}
                  <div className="metrics-grid">
                    <div className="metric-card primary">
                      <div className="metric-content">
                        <div className="metric-value">{results.displayHours}h {results.displayMinutes}m</div>
                        <div className="metric-label">Total Time</div>
                      </div>
                    </div>

                    <div className="metric-card">
                      <div className="metric-content">
                        <div className="metric-value">{results.totalPallets}</div>
                        <div className="metric-label">Total Pallets</div>
                      </div>
                    </div>

                    <div className="metric-card">
                      <div className="metric-content">
                        <div className="metric-value">{results.people}</div>
                        <div className="metric-label">Workers Assigned</div>
                      </div>
                    </div>

                    <div className="metric-card">
                      <div className="metric-content">
                        <div className="metric-value">{results.totalItems.toLocaleString()}</div>
                        <div className="metric-label">Total Items</div>
                      </div>
                    </div>
                  </div>

                  {/* Phase Breakdown */}
                  <div className="breakdown-section">
                    <h3 className="breakdown-title">Time by Warehouse Phase</h3>
                    <div className="breakdown-grid">
                      {results.phases.map((phase, index) => (
                        <div key={index} className="breakdown-item">
                          <span className="breakdown-label">{phase.name}</span>
                          <span className="breakdown-value">
                            {Math.floor(phase.timeSeconds / 60)} min {Math.round(phase.timeSeconds % 60)} sec
                          </span>
                        </div>
                      ))}
                      <div className="breakdown-item total">
                        <span className="breakdown-label">Total Time</span>
                        <span className="breakdown-value">{results.displayHours}h {results.displayMinutes}m</span>
                      </div>
                    </div>
                  </div>

                  {/* Items Breakdown with Processing Details */}
                  <div className="breakdown-section">
                    <h3 className="breakdown-title">Items Breakdown</h3>
                    <div className="items-breakdown">
                      {results.itemsBreakdown.map((item, index) => (
                        <div key={index} className="breakdown-item-detailed">
                          <div className="item-detail-header">
                            <span className="breakdown-label">{item.description}</span>
                            <span className="breakdown-value">{item.pallets} Pallets</span>
                          </div>
                          <div className="item-detail-meta">
                            <span className="detail-rate">{item.itemsPerPallet} items/pallet</span>
                            <span className="detail-hours">Total: {item.totalItems.toLocaleString()} items</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default WorkloadAnalysis;
