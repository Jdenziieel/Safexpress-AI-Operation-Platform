import React from 'react';
import '../css/WelcomeCard.css';

function WelcomeCard({ userName, handImage }) {
    return (
        <div className="card welcome-card">
            <div className="welcome-left">
                <h2 className="welcome-title">
                    👋 Welcome back, <span className="highlight">{userName}</span>
                </h2>
                <p className="welcome-description">
                    This is your personal dashboard — manage projects, keep track of tasks, 
                    and stay on top of your goals. Let’s make progress today!
                </p>
                <button className="get-started-btn">Get Started</button>
            </div>

            
        </div>
    );
}

export default WelcomeCard;
