import React from 'react';
import '../css/StatCard.css';

function StatCard({ icon, title, value, description }) {
    return (
        <div className="card stat-card">
            <div className="stat-card-content">
                <div className="stat-card-header">
                    {icon}
                    <h3 className="stat-card-title">{title}</h3>
                </div>
                <p className="stat-card-value">{value}</p>
                <p className="stat-card-description">{description}</p>
            </div>
        </div>
    );
}

export default StatCard;