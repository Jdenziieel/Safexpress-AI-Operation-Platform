/**
 * Workload Analysis API Client
 * Handles all communication with the backend API
 */

const WORKLOAD_API_BASE = 'http://localhost:5003/api';

/**
 * Time Configuration API
 */
export const workloadConfigAPI = {
  /**
   * Get current time configuration
   */
  async getConfig() {
    const response = await fetch(`${WORKLOAD_API_BASE}/config`);
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data.data;
  },

  /**
   * Update time configuration
   */
  async updateConfig(config) {
    const response = await fetch(`${WORKLOAD_API_BASE}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data;
  },
};

/**
 * Workload Calculation API
 */
export const workloadCalculationAPI = {
  /**
   * Save calculation to history
   */
  async saveCalculation(calculationData) {
    const response = await fetch(`${WORKLOAD_API_BASE}/workload/calculate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(calculationData),
    });
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data;
  },

  /**
   * Get calculation history
   */
  async getHistory(limit = 50, offset = 0) {
    const response = await fetch(
      `${WORKLOAD_API_BASE}/workload/history?limit=${limit}&offset=${offset}`
    );
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data;
  },

  /**
   * Get specific calculation by ID
   */
  async getCalculationById(id) {
    const response = await fetch(`${WORKLOAD_API_BASE}/workload/history/${id}`);
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data.data;
  },

  /**
   * Delete calculation from history
   */
  async deleteCalculation(id) {
    const response = await fetch(`${WORKLOAD_API_BASE}/workload/history/${id}`, {
      method: 'DELETE',
    });
    const data = await response.json();
    if (!data.success) throw new Error(data.message);
    return data;
  },
};

/**
 * Health check
 */
export const checkAPIHealth = async () => {
  try {
    const response = await fetch(`${WORKLOAD_API_BASE}/health`);
    const data = await response.json();
    return data.success;
  } catch (error) {
    return false;
  }
};
