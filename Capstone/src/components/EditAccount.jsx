import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { User, Mail, Shield, IdCard, Save, X, ArrowLeft } from 'lucide-react';
import api from '../api';
import '../css/EditAccount.css';

function EditAccount() {
  const navigate = useNavigate();
  const location = useLocation();
  const accountData = location.state?.account;

  const [formData, setFormData] = useState({
    id: '',
    fullname: '',
    gmail: '',
    role: 'user',
    is_active: true
  });

  const [errors, setErrors] = useState({});
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (accountData) {
      setFormData({
        id: accountData.id,
        fullname: accountData.fullname || '',
        gmail: accountData.gmail || '',
        role: accountData.role || 'user',
        is_active: accountData.is_active ?? true
      });
    } else {
      // If no account data, redirect back to accounts page
      navigate('/accounts');
    }
  }, [accountData, navigate]);

  const validateForm = () => {
    const newErrors = {};

    if (!formData.fullname.trim()) {
      newErrors.fullname = 'Name is required';
    }

    if (!formData.gmail.trim()) {
      newErrors.gmail = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.gmail)) {
      newErrors.gmail = 'Invalid email format';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (field, value) => {
    setFormData({
      ...formData,
      [field]: value
    });
    
    // Clear error for this field when user starts typing
    if (errors[field]) {
      setErrors({
        ...errors,
        [field]: ''
      });
    }
  };

  const handleSave = async () => {
    if (!validateForm()) {
      return;
    }

    setIsSaving(true);

    try {
      // Call the API to update the user
      const response = await api.patch(`/api/users/${formData.id}/`, {
        fullname: formData.fullname,
        role: formData.role.toLowerCase(),
        is_active: formData.is_active
      });

      // Navigate back to accounts page with updated data
      navigate('/accounts', { 
        state: { 
          updatedAccount: response.data.user || formData,
          message: 'Account updated successfully!'
        } 
      });
    } catch (error) {
      console.error('Error saving account:', error);
      alert(error.response?.data?.error || 'Failed to save account. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    if (window.confirm('Are you sure you want to cancel? Any unsaved changes will be lost.')) {
      navigate('/accounts');
    }
  };

  return (
    <div className="edit-account-page">
      <div className="edit-account-container">
        {/* Header */}
        <div className="edit-account-header">
          <div className="header-left">
            <button className="back-button" onClick={() => navigate('/accounts')}>
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="edit-account-title">Edit Account</h1>
              <p className="edit-account-subtitle">Update account information and settings</p>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="edit-account-content">
          {/* Account Information Card */}
          <div className="edit-account-card">
            <div className="edit-account-card-header">
              <h3 className="card-title">Account Information</h3>
              <span className={`status-indicator ${formData.is_active ? 'active' : 'inactive'}`}>
                {formData.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <div className="edit-account-card-body">
              <div className="form-grid">
                {/* Name */}
                <div className="form-group">
                  <label className="form-label">
                    <User size={18} />
                    <span>Full Name</span>
                  </label>
                  <input
                    type="text"
                    className={`form-input ${errors.fullname ? 'error' : ''}`}
                    value={formData.fullname}
                    onChange={(e) => handleInputChange('fullname', e.target.value)}
                    placeholder="Enter full name"
                  />
                  {errors.fullname && <span className="error-message">{errors.fullname}</span>}
                </div>

                {/* Email */}
                <div className="form-group">
                  <label className="form-label">
                    <Mail size={18} />
                    <span>Email Address</span>
                  </label>
                  <input
                    type="email"
                    className="form-input readonly"
                    value={formData.gmail}
                    readOnly
                    disabled
                  />
                  <span className="helper-text">Email cannot be modified</span>
                </div>

                {/* Role */}
                <div className="form-group">
                  <label className="form-label">
                    <Shield size={18} />
                    <span>Role</span>
                  </label>
                  <select
                    className="form-select"
                    value={formData.role}
                    onChange={(e) => handleInputChange('role', e.target.value)}
                  >
                    <option value="user">User</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>

                {/* Status */}
                <div className="form-group">
                  <label className="form-label">
                    <Shield size={18} />
                    <span>Account Status</span>
                  </label>
                  <select
                    className="form-select"
                    value={formData.is_active ? 'true' : 'false'}
                    onChange={(e) => handleInputChange('is_active', e.target.value === 'true')}
                  >
                    <option value="true">Active</option>
                    <option value="false">Inactive</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="action-buttons">
            <button 
              className="cancel-button" 
              onClick={handleCancel}
              disabled={isSaving}
            >
              <X size={20} />
              <span>Cancel</span>
            </button>
            <button 
              className="save-button" 
              onClick={handleSave}
              disabled={isSaving}
            >
              <Save size={20} />
              <span>{isSaving ? 'Saving...' : 'Save Changes'}</span>
            </button>
          </div>

          {/* Information Notice */}
          <div className="info-notice">
            <Shield size={24} className="notice-icon" />
            <div>
              <h4>Important Information</h4>
              <ul>
                <li>Changes to the account role will take effect immediately</li>
                <li>Email address cannot be modified after account creation</li>
                <li>Deactivating an account will prevent the user from logging in</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EditAccount;
