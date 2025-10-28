// AdminOnboardingForm.jsx
import React, { useState } from "react";
import api from "../api";
import "../css/AdminOnboardingForm.css";

const AdminOnboardingForm = () => {
  const [formData, setFormData] = useState({
    gmail: "",
    employeeId: "",
    fullName: "",
    department: "Operations",
    warehouse: "VFP Warehouse",
    position: "Staff",
    role: "User",
  });

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage({ type: "", text: "" });

    try {
      console.log("Creating user with data:", formData);

      const response = await api.post("/api/auth/dynamodb/create-user/", {
        email: formData.gmail,
        name: formData.fullName,
        role: formData.role,
        department: formData.department,
        warehouse: formData.warehouse,
        position: formData.position,
      });

      console.log("User created:", response.data);
      setMessage({
        type: "success",
        text: `✅ User ${formData.fullName} created successfully! They can now log in with ${formData.gmail}`,
      });

      // Reset form
      setFormData({
        gmail: "",
        employeeId: "",
        fullName: "",
        department: "Operations",
        warehouse: "VFP Warehouse",
        position: "Staff",
        role: "User",
      });
    } catch (error) {
      console.error("Error creating user:", error);
      setMessage({
        type: "error",
        text:
          error.response?.data?.error ||
          "Failed to create user. Please try again.",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="adminonboarding-page">
      <div className="adminonboarding-container">
        <div className="adminonboarding-header">
          <div>
            <h2 className="adminonboarding-header-title">
              Admin Account Onboarding
            </h2>
            <p className="adminonboarding-header-subtitle">
              Create and manage admin accounts for organizational oversight.
            </p>
          </div>
        </div>

        {message.text && (
          <div
            className={`alert ${
              message.type === "success" ? "alert-success" : "alert-error"
            }`}
          >
            {message.text}
          </div>
        )}

        <div className="admin-form-card">
          <form onSubmit={handleSubmit} className="admin-form">
            <div className="form-group">
              <label className="form-group-label">Gmail Address *</label>
              <input
                type="email"
                id="gmail"
                name="gmail"
                value={formData.gmail}
                onChange={handleChange}
                required
                placeholder="admin@company.com"
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="fullName">Full Name *</label>
              <input
                type="text"
                id="fullName"
                name="fullName"
                value={formData.fullName}
                onChange={handleChange}
                required
                placeholder="Juan Dela Cruz"
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="department">Department *</label>
              <select
                id="department"
                name="department"
                value={formData.department}
                onChange={handleChange}
                required
                disabled={loading}
              >
                <option value="Operations">Operations</option>
                <option value="Warehouse">Warehouse</option>
                <option value="Finance">Finance</option>
                <option value="HR">HR</option>
                <option value="IT">IT</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="warehouse">Warehouse *</label>
              <select
                id="warehouse"
                name="warehouse"
                value={formData.warehouse}
                onChange={handleChange}
                required
                disabled={loading}
              >
                <option value="VFP Warehouse">VFP Warehouse</option>
                <option value="Main Warehouse">Main Warehouse</option>
                <option value="Branch A">Branch A</option>
                <option value="Branch B">Branch B</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="position">Position *</label>
              <input
                type="text"
                id="position"
                name="position"
                value={formData.position}
                onChange={handleChange}
                required
                placeholder="Staff, Manager, etc."
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="role">Role *</label>
              <select
                id="role"
                name="role"
                value={formData.role}
                onChange={handleChange}
                required
                disabled={loading}
              >
                <option value="User">User</option>
                <option value="Admin">Admin</option>
              </select>
            </div>

            <button
              type="submit"
              className="new-upload-button"
              disabled={loading}
            >
              {loading ? "Creating..." : "Create User Account"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AdminOnboardingForm;
