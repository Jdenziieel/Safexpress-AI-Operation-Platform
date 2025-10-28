import React from 'react';
import { FiCheck } from 'react-icons/fi';
import '../css/ActionCard.css';

function ActionCard({ icon, title, subtitle, description, tasks, buttonText, onButtonClick }) {
    return (
        <div className="card action-card">
            <div className="action-card-header">
                <div className="action-card-title-group">
                    <p className="action-card-subtitle">{subtitle}</p>
                    <h3 className="action-card-title">{title}</h3>
                </div>
                <div className="action-card-icon">{icon}</div>
            </div>
            <p className="action-card-description">{description}</p>
            <hr className="action-card-divider" />
            <ul className="action-card-list">
                {tasks.map((task, index) => (
                    <li key={index} className="action-card-list-item">
                        <FiCheck size={18} className="action-card-list-icon" />
                        <span>{task}</span>
                    </li>
                ))}
            </ul>
            <div className="action-card-footer">
                <button onClick={onButtonClick} className="primary-button">
                    {buttonText}
                </button>
            </div>
        </div>
    );
}

export default ActionCard;