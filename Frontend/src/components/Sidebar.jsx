import React, { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { User } from "lucide-react";
import {
  LayoutDashboard,
  Users,
  Bot,
  CheckSquare,
  BarChart3,
  FileScan,
  LogOut,
  BookOpen,
  Activity,
  Zap,
} from "lucide-react";
import { isAdmin as checkIsAdmin, getUserRole, hasAccess, getUserFromToken } from "../utils/tokenManager";
import QuotaWidget from "./QuotaWidget";
import safexpressLogo from "../assets/sfxLogo.png";
import "../css/Sidebar.css";

/**
 * Navigation items with role-based access control
 * 
 * allowedRoles determines which roles can see each nav item:
 * - Admin: Full access to everything
 * - Manager: Cannot access Accounts, Token Quota, Logs & Analytics, KB Analytics
 * - User: Can ONLY access SFXBot, Dynamic Mapping, Analysis Reports
 */
const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard", allowedRoles: ["admin", "manager"] },
  { label: "Accounts", icon: Users, path: "/accounts", allowedRoles: ["admin"] },
  { label: "AI Assistant", icon: Bot, path: "/ai-chat-new", allowedRoles: ["admin", "manager"] },
  { label: "SFX Bot", icon: Bot, path: "/sfx-bot", allowedRoles: ["admin", "manager", "user"] },
  {
    // KB management is admin-only as of 2026-05-01. Managers retain
    // read-only KB query access via the chat surfaces (AI Assistant,
    // SFX Bot) which call /api/kb/query, but the upload / version /
    // delete operations exposed by /document-extraction are now
    // restricted to admins. Server-side enforcement lives in the
    // Lambda authorizer (see authorizer/lambda_authorizer.py); this
    // sidebar entry is just the UX hint.
    label: "Manage KB",
    icon: FileScan,
    path: "/document-extraction",
    allowedRoles: ["admin"]
  },
  { label: "KB Analytics", icon: BarChart3, path: "/kb-analytics", allowedRoles: ["admin"] },
  { label: "Dynamic Mapping", icon: BookOpen, path: "/dynamic-mapping", allowedRoles: ["admin", "manager", "user"] },
  { label: "Analysis Report", icon: BarChart3, path: "/analysis-report", allowedRoles: ["admin", "manager", "user"] },
  { label: "Logs & Analytics", icon: Activity, path: "/logs", allowedRoles: ["admin"] },
  { label: "Token Management", icon: Zap, path: "/quota", allowedRoles: ["admin"]},
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
  const [isAdmin, setIsAdmin] = useState(false);
  const [userInfo, setUserInfo] = useState({
    name: "Admin User",
    email: "admin@example.com",
    picture: null
  });

  const handleProfileClick = () => {
    navigate('/profile');
  };

  // Load user info from JWT token (secure) and localStorage (for display only)
  useEffect(() => {
    const loadUserInfo = () => {
      try {
        // Get admin status from JWT token (cryptographically signed, secure)
        const adminStatus = checkIsAdmin();
        setIsAdmin(adminStatus);
        
        // Get user info from both JWT token and localStorage
        const tokenUser = getUserFromToken();
        const storedUser = localStorage.getItem("user");
        const localStorageUser = storedUser ? JSON.parse(storedUser) : null;
        
        // Merge both sources - JWT for secure data, localStorage for additional display data
        const userData = { ...tokenUser, ...localStorageUser };
        
        if (userData && Object.keys(userData).length > 0) {
          // Build full name from available fields - prioritize fullname from our CustomUser model
          let displayName = "User";
          if (userData.fullname) {
            displayName = userData.fullname;
          } else if (userData.name) {
            displayName = userData.name;
          } else if (userData.first_name || userData.last_name) {
            displayName = `${userData.first_name || ''} ${userData.last_name || ''}`.trim();
          }
          
          // Use gmail from our model, fall back to email
          const userEmail = userData.gmail || userData.email || "user@example.com";
          
          // Get picture - localStorage has the fresh picture from login response
          const userPicture = localStorageUser?.picture || tokenUser?.picture || userData.google_picture || null;
          
          setUserInfo({
            name: displayName,
            email: userEmail,
            picture: userPicture
          });
        }
      } catch (error) {
        console.error("Error loading user info:", error);
      }
    };

    loadUserInfo();

    // Listen for storage changes (in case token is updated)
    window.addEventListener("storage", loadUserInfo);
    return () => window.removeEventListener("storage", loadUserInfo);
  }, []);

  // Filter nav items based on user role
  // Each nav item has allowedRoles array that specifies which roles can access it
  const filteredNavItems = navItems.filter(item => {
    if (!item.allowedRoles) return true; // If no roles specified, allow all
    return hasAccess(item.allowedRoles);
  });

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

      {/* Compact Quota Widget - clickable, expands on click, no redirect */}
      <div className="sidebar-quota-widget">
        <QuotaWidget compact={true} />
      </div>

      <ul className="nav-list">
        {filteredNavItems.map((item) => (
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
