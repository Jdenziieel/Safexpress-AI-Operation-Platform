import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { User, Mail, Shield, IdCard, Save, X, ArrowLeft } from 'lucide-react';
import Swal from 'sweetalert2';
import api from '../api';
import '../css/EditAccount.css';

function EditAccount() {
  const navigate = useNavigate();
  const location = useLocation();
  const accountData = location.state?.account;

  const [formData, setFormData] = useState({
    fullname: '',
    gmail: '',
    role: 'user',
    is_active: true
  });

  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [isSaving, setIsSaving] = useState(false);

  // Validation rules
  const VALIDATION_RULES = {
    fullname: {
      minLength: 2,
      maxLength: 100,
      pattern: /^[a-zA-Z\s\-'.]+$/,
      patternMessage: "Name can only contain letters, spaces, hyphens, apostrophes, and periods"
    }
  };

  const VALID_ROLES = ['user', 'manager', 'admin'];

  useEffect(() => {
    if (accountData) {
      setFormData({
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

  const validateField = (field, value) => {
    switch (field) {
      case 'fullname': {
        const trimmed = value.trim();
        if (!trimmed) {
          return 'Full name is required';
        }
        if (trimmed.length < VALIDATION_RULES.fullname.minLength) {
          return `Name must be at least ${VALIDATION_RULES.fullname.minLength} characters`;
        }
        if (trimmed.length > VALIDATION_RULES.fullname.maxLength) {
          return `Name cannot exceed ${VALIDATION_RULES.fullname.maxLength} characters`;
        }
        if (!VALIDATION_RULES.fullname.pattern.test(trimmed)) {
          return VALIDATION_RULES.fullname.patternMessage;
        }
        return '';
      }
      case 'role': {
        if (!VALID_ROLES.includes(value.toLowerCase())) {
          return 'Please select a valid role';
        }
        return '';
      }
      default:
        return '';
    }
  };

  const validateForm = () => {
    const newErrors = {};

    // Validate fullname
    const fullnameError = validateField('fullname', formData.fullname);
    if (fullnameError) {
      newErrors.fullname = fullnameError;
    }

    // Validate role
    const roleError = validateField('role', formData.role);
    if (roleError) {
      newErrors.role = roleError;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (field, value) => {
    setFormData({
      ...formData,
      [field]: value
    });
    
    // Real-time validation if field has been touched
    if (touched[field]) {
      const error = validateField(field, value);
      setErrors(prev => ({
        ...prev,
        [field]: error
      }));
    }
  };

  const handleBlur = (field) => {
    setTouched(prev => ({
      ...prev,
      [field]: true
    }));
    
    // Validate on blur
    const error = validateField(field, formData[field]);
    setErrors(prev => ({
      ...prev,
      [field]: error
    }));
  };

  const handleSave = async () => {
    if (!validateForm()) {
      return;
    }

    setIsSaving(true);

    try {
      // Call the AWS Lambda API to update the user (use gmail, no trailing slash)
      const response = await api.patch(`/api/users/${formData.gmail}`, {
        fullname: formData.fullname,
        role: formData.role.toLowerCase(),
        is_active: formData.is_active
      });

      // Show success modal
      await Swal.fire({
        icon: 'success',
        title: 'Success!',
        text: 'Account updated successfully!',
        confirmButtonText: 'OK',
        confirmButtonColor: '#26326e',
        timer: 3000,
        timerProgressBar: true
      });

      // Navigate back to accounts page with updated data
      navigate('/accounts', { 
        state: { 
          updatedAccount: response.data.user || formData
        } 
      });
    } catch (error) {
      console.error('Error saving account:', error);
      
      // Show error modal
      await Swal.fire({
        icon: 'error',
        title: 'Error!',
        text: error.response?.data?.error || 'Failed to save account. Please try again.',
        confirmButtonText: 'OK',
        confirmButtonColor: '#26326e'
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = async () => {
    const result = await Swal.fire({
      icon: 'warning',
      title: 'Cancel Changes?',
      text: 'Are you sure you want to cancel? Any unsaved changes will be lost.',
      showCancelButton: true,
      confirmButtonText: 'Yes, Cancel',
      cancelButtonText: 'No, Stay',
      confirmButtonColor: '#dc3545',
      cancelButtonColor: '#26326e',
      reverseButtons: true
    });

    if (result.isConfirmed) {
      navigate('/accounts');
    }
  };

  return (
    <div className="edit-account-page">
      <div className="edit-account-container">
        {/* Back Button */}
        <div style={{ marginBottom: '16px' }}>
          <button 
            onClick={() => navigate(-1)}
            style={{ 
              background: '#26326e', 
              color: 'white', 
              border: 'none', 
              borderRadius: '8px', 
              padding: '10px', 
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
            title="Back"
          >
            <ArrowLeft size={20} />
          </button>
        </div>

        {/* Header */}
        <div className="edit-account-header">
          <div className="header-left">
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
                    onBlur={() => handleBlur('fullname')}
                    placeholder="Enter full name"
                    maxLength={VALIDATION_RULES.fullname.maxLength}
                  />
                  <div className="field-footer">
                    {errors.fullname ? (
                      <span className="error-message">{errors.fullname}</span>
                    ) : (
                      <span className="helper-text">Letters, spaces, hyphens allowed</span>
                    )}
                    <span className="char-count">
                      {formData.fullname.length}/{VALIDATION_RULES.fullname.maxLength}
                    </span>
                  </div>
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
                    className={`form-select ${errors.role ? 'error' : ''}`}
                    value={formData.role}
                    onChange={(e) => handleInputChange('role', e.target.value)}
                    onBlur={() => handleBlur('role')}
                  >
                    <option value="user">User</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                  {errors.role && <span className="error-message">{errors.role}</span>}
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
