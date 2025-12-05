import React, { useState, useEffect } from 'react';
import { User, Mail, Calendar, Shield } from 'lucide-react';
import '../css/ProfilePage.css';

function ProfilePage() {
  const [userInfo, setUserInfo] = useState({
    fullName: '',
    email: '',
    username: '',
    picture: null,
    dateJoined: '',
    role: 'User'
  });

  useEffect(() => {
    const loadUserInfo = () => {
      try {
        const storedUser = localStorage.getItem('user');
        if (storedUser) {
          const userData = JSON.parse(storedUser);
          
          // Format the date from created_at
          let formattedDate = 'Unknown';
          if (userData.created_at) {
            formattedDate = new Date(userData.created_at).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'long',
              day: 'numeric'
            });
          }
          
          setUserInfo({
            fullName: userData.fullname || userData.name || `${userData.first_name || ''} ${userData.last_name || ''}`.trim() || 'User',
            email: userData.gmail || userData.email || '',
            username: userData.gmail?.split('@')[0] || userData.username || '',
            picture: userData.picture || null,
            dateJoined: formattedDate,
            role: userData.role || (userData.is_staff ? 'Admin' : 'User')
          });
        }
      } catch (error) {
        console.error('Error loading user info:', error);
      }
    };

    loadUserInfo();
  }, []);

  return (
    <div className="profile-page">
      <div className="profile-container">
        <div className="profile-header">
          <h1 className="profile-title">My Profile</h1>
          <p className="profile-subtitle">Manage your account information</p>
        </div>

        <div className="profile-content">
          {/* Profile Card */}
          <div className="profile-card">
            <div className="profile-card-header">
              <div className="profile-avatar-section">
                <div className="profile-avatar-large">
                  {userInfo.picture ? (
                    <img 
                      src={userInfo.picture} 
                      alt={userInfo.fullName}
                      className="profile-avatar-img"
                      onError={(e) => {
                        e.target.style.display = 'none';
                        e.target.nextSibling.style.display = 'flex';
                      }}
                    />
                  ) : null}
                  <div 
                    className="profile-avatar-icon"
                    style={{ display: userInfo.picture ? 'none' : 'flex' }}
                  >
                    <User size={48} strokeWidth={1.5} />
                  </div>
                </div>
                <div className="profile-name-section">
                  <h2 className="profile-name">
                    {userInfo.fullName}
                  </h2>
                  <p className="profile-username">@{userInfo.username}</p>
                </div>
              </div>
            </div>

            <div className="profile-card-body">
              <div className="profile-info-grid">
                {/* Full Name */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <User size={18} />
                    <span>Full Name</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.fullName}
                  </div>
                </div>

                {/* Username */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <User size={18} />
                    <span>Username</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.username}
                  </div>
                </div>

                {/* Email */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Mail size={18} />
                    <span>Email</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.email}
                  </div>
                </div>

                {/* Role */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Shield size={18} />
                    <span>Role</span>
                  </div>
                  <div className="profile-info-value">
                    <span className="profile-role-badge">{userInfo.role}</span>
                  </div>
                </div>

                {/* Date Joined */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Calendar size={18} />
                    <span>Member Since</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.dateJoined}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Additional Info Card */}
          <div className="profile-card">
            <div className="profile-card-header">
              <h3 className="profile-card-title">Account Information</h3>
            </div>
            <div className="profile-card-body">
              <div className="profile-info-notice">
                <Shield size={24} className="notice-icon" />
                <div>
                  <h4>Google Account</h4>
                  <p>Your profile information is managed through your Google account. To update your name, email, or profile picture, please visit your Google Account settings.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProfilePage;
