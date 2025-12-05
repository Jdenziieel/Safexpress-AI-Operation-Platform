import mysql.connector
from mysql.connector import Error
from datetime import datetime
import uuid
from typing import Dict, List, Optional
from contextlib import contextmanager


class SafexpressMySQLDB:
    def __init__(
        self,
        host="localhost",
        database="safexpressops_local",
        user="root",
        password="",
    ):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.connection = None

    @contextmanager
    def get_cursor(self, dictionary=True):
        """Context manager for database cursor"""
        connection = mysql.connector.connect(
            host=self.host,
            database=self.database,
            user=self.user,
            password=self.password,
        )
        cursor = connection.cursor(dictionary=dictionary)
        try:
            yield cursor, connection
            connection.commit()
        except Exception as e:
            connection.rollback()
            raise e
        finally:
            cursor.close()
            connection.close()

    # ==========================================
    # USER MANAGEMENT METHODS
    # ==========================================

    def create_user(
        self,
        email: str,
        name: str,
        role: str,
        department: str,
        warehouse: str,
        position: str,
        created_by: str = None,
    ) -> Dict:
        """Create new user account"""
        user_id = str(uuid.uuid4())

        query = """
        INSERT INTO users 
        (user_id, email, name, role, department, warehouse, position, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        with self.get_cursor() as (cursor, conn):
            cursor.execute(
                query,
                (
                    user_id,
                    email,
                    name,
                    role,
                    department,
                    warehouse,
                    position,
                    created_by,
                ),
            )

        return {"user_id": user_id, "email": email, "name": name, "role": role}

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        query = "SELECT * FROM users WHERE email = %s AND is_active = TRUE"

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, (email,))
            return cursor.fetchone()

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by ID"""
        query = "SELECT * FROM users WHERE user_id = %s AND is_active = TRUE"

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, (user_id,))
            return cursor.fetchone()

    def update_user_google_tokens(
        self,
        user_id: str,
        google_id: str,
        access_token: str,
        refresh_token: str,
        token_expiry: datetime,
    ):
        """Update user's Google OAuth tokens"""
        query = """
        UPDATE users 
        SET google_id = %s,
            google_access_token = %s, 
            google_refresh_token = %s, 
            token_expiry = %s
        WHERE user_id = %s
        """

        with self.get_cursor() as (cursor, conn):
            cursor.execute(
                query, (google_id, access_token, refresh_token, token_expiry, user_id)
            )

    def get_all_users(self, role: str = None) -> List[Dict]:
        """Get all users, optionally filtered by role"""
        if role:
            query = "SELECT * FROM users WHERE role = %s AND is_active = TRUE ORDER BY created_at DESC"
            params = (role,)
        else:
            query = (
                "SELECT * FROM users WHERE is_active = TRUE ORDER BY created_at DESC"
            )
            params = ()

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, params)
            return cursor.fetchall()

    def deactivate_user(self, user_id: str):
        """Soft delete - deactivate user"""
        query = "UPDATE users SET is_active = FALSE WHERE user_id = %s"

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, (user_id,))

    # ==========================================
    # ACTIVITY LOG METHODS
    # ==========================================

    def log_activity(
        self,
        user_id: str,
        user_email: str,
        user_name: str,
        user_role: str,
        action: str,
        details: str,
        resource_type: str = None,
        resource_id: str = None,
        ip_address: str = None,
        user_agent: str = None,
    ) -> str:
        """Log user activity"""
        log_id = str(uuid.uuid4())

        query = """
        INSERT INTO activity_logs 
        (log_id, user_id, user_email, user_name, user_role, action, details, 
         resource_type, resource_id, ip_address, user_agent, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """

        with self.get_cursor() as (cursor, conn):
            cursor.execute(
                query,
                (
                    log_id,
                    user_id,
                    user_email,
                    user_name,
                    user_role,
                    action,
                    details,
                    resource_type,
                    resource_id,
                    ip_address,
                    user_agent,
                ),
            )

        return log_id

    def get_user_activity(self, user_id: str, limit: int = 50) -> List[Dict]:
        """Get user's activity logs"""
        query = """
        SELECT * FROM activity_logs 
        WHERE user_id = %s 
        ORDER BY timestamp DESC 
        LIMIT %s
        """

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, (user_id, limit))
            return cursor.fetchall()

    def get_all_activity(self, limit: int = 100) -> List[Dict]:
        """Get all activity logs (admin only)"""
        query = """
        SELECT * FROM activity_logs 
        ORDER BY timestamp DESC 
        LIMIT %s
        """

        with self.get_cursor() as (cursor, conn):
            cursor.execute(query, (limit,))
            return cursor.fetchall()
