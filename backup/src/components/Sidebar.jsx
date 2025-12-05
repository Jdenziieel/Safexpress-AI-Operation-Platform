import React, { useState, useEffect } from "react";
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
  BookOpen,
  Activity,
} from "lucide-react";
import safexpressLogo from "../assets/sfxLogo.png";
import "../css/Sidebar.css";

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard" },
  { label: "Audit Logs", icon: ScrollText, path: "/audit-logs" },
  { label: "Accounts", icon: Users, path: "/accounts" },
  { label: "AI Assistant", icon: Bot, path: "/ai-chat-new" },
  { label: "SFX Bot", icon: Bot, path: "/sfx-bot" },
  {
    label: "Manage Knowledge Base",
    icon: FileScan,
    path: "/document-extraction",
  },
  { label: "Dynamic Mapping", icon: BookOpen, path: "/dynamic-mapping" },
  { label: "Analysis Report", icon: BarChart3, path: "/analysis-report" },
  { label: "Logs & Analytics", icon: Activity, path: "/logs" },
];

const NavItem = React.memo(({ item, isActive, isCollapsed }) => (
  <li>
    <Link to={item.path} className={`nav-item ${isActive ? "active" : ""}`}>
      <item.icon className="nav-icon" size={20} strokeWidth={2} />
      {!isCollapsed && <span className="nav-label">{item.label}</span>}
    </Link>
  </li>
));

const Sidebar = React.memo(({ isOpen, toggleSidebar, onLogout }) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [userInfo, setUserInfo] = useState({
    name: "Admin User",
    email: "admin@example.com",
    picture: null
  });

  const handleProfileClick = () => {
    navigate('/profile');
  };

  // Load user info from localStorage
  useEffect(() => {
    const loadUserInfo = () => {
      try {
        const storedUser = localStorage.getItem("user");
        if (storedUser) {
          const userData = JSON.parse(storedUser);
          
          // Build full name from first_name and last_name, or fall back to username
          let displayName = "User";
          if (userData.first_name || userData.last_name) {
            displayName = `${userData.first_name || ''} ${userData.last_name || ''}`.trim();
          } else if (userData.name) {
            displayName = userData.name;
          } else if (userData.username) {
            displayName = userData.username;
          }
          
          setUserInfo({
            name: displayName,
            email: userData.email || "user@example.com",
            picture: userData.picture || null
          });
          
          console.log("Loaded user info:", { name: displayName, email: userData.email, picture: userData.picture });
        }
      } catch (error) {
        console.error("Error loading user info:", error);
      }
    };

    loadUserInfo();

    // Listen for storage changes (in case user info is updated)
    window.addEventListener("storage", loadUserInfo);
    return () => window.removeEventListener("storage", loadUserInfo);
  }, []);

  const handleLogout = React.useCallback(() => {
    if (onLogout) onLogout();
    navigate("/login");
  }, [onLogout, navigate]);

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
      <div className="user-profile-section" onClick={handleProfileClick}>
        <div className="user-info">
          <div className="user-avatar">
            {userInfo.picture ? (
              <img 
                src={userInfo.picture} 
                alt={userInfo.name}
                className="user-avatar-img"
                onError={(e) => {
                  // Fallback to icon if image fails to load
                  e.target.style.display = 'none';
                  e.target.nextSibling.style.display = 'flex';
                }}
              />
            ) : null}
            <User 
              size={20} 
              strokeWidth={1.5} 
              style={{ display: userInfo.picture ? 'none' : 'block' }}
            />
          </div>
          <div className="user-text">
            <div className="user-name">{userInfo.name}</div>
            <div className="user-email">{userInfo.email}</div>
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
});

export default Sidebar;
