import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { User } from "lucide-react";
import {
  LayoutDashboard,
  ScrollText,
  Users,
  Bot,
  CheckSquare,
  BarChart3,
  FileScan,
  LogOut,
} from "lucide-react";
import safexpressLogo from "../assets/sfxLogo.png";
import "../css/Sidebar.css";

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard" },
  { label: "Audit Logs", icon: ScrollText, path: "/audit-logs" },
  { label: "Accounts", icon: Users, path: "/accounts" },
  { label: "AI Chat", icon: Bot, path: "/ai-chat" },
  { label: "Task Approval", icon: CheckSquare, path: "/task-approval" },
  { label: "Report & Analysis", icon: BarChart3, path: "/report-analysis" },
  {
    label: "Document Extraction",
    icon: FileScan,
    path: "/document-extraction",
  },
  { label: "Admin Onboarding", icon: Users, path: "/admin-onboarding" },
];

const NavItem = ({ item, isActive }) => (
  <li>
    <Link to={item.path} className={`nav-item ${isActive ? "active" : ""}`}>
      <item.icon className="nav-icon" size={20} strokeWidth={2} />
      <span className="nav-label">{item.label}</span>
    </Link>
  </li>
);

function Sidebar({ isOpen, toggleSidebar, onLogout }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const handleLogout = () => {
    if (onLogout) onLogout();
    navigate("/login");
  };

  // Sidebar.jsx — Updated return block
  return (
    <nav className="sidebar-container">
      <div className="sidebar-header">
        <img
          src={safexpressLogo}
          alt="Safexpress Logo"
          className="sidebar-logo"
        />
      </div>

      <ul className="nav-list">
        {navItems.map((item) => (
          <NavItem
            key={item.label}
            item={item}
            isActive={pathname === item.path}
          />
        ))}
      </ul>

      {/* 👇 Updated User Profile Section with Avatar */}
      <div className="user-profile-section">
        <div className="user-info">
          <div className="user-avatar">
            <User size={20} strokeWidth={1.5} />
          </div>
          <div className="user-text">
            <div className="user-name">Admin User</div>
            <div className="user-email">admin@example.com</div>
          </div>
        </div>
      </div>

      <div className="logout-section">
        <button onClick={handleLogout} className="logout-btn">
          <LogOut size={20} strokeWidth={2} />
          <span className="nav-label">Logout</span>
        </button>
      </div>
    </nav>
  );
}

export default Sidebar;
