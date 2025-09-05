#!/usr/bin/env python3
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class ChatAnalytics:
    """Analytics and management for chat database"""
    
    def __init__(self, db_path: str = "chat_history.db"):
        self.db_path = db_path
    
    def get_usage_stats(self, days: int = 7) -> Dict:
        """Get usage statistics"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Total messages
            cursor.execute('''
                SELECT COUNT(*) FROM messages 
                WHERE created_at > ?
            ''', (cutoff_date,))
            total_messages = cursor.fetchone()[0]
            
            # Unique users
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) FROM chat_sessions 
                WHERE created_at > ?
            ''', (cutoff_date,))
            unique_users = cursor.fetchone()[0]
            
            # Tool usage
            cursor.execute('''
                SELECT tool_name, COUNT(*) as count 
                FROM tool_calls 
                WHERE created_at > ?
                GROUP BY tool_name 
                ORDER BY count DESC
            ''', (cutoff_date,))
            tool_usage = cursor.fetchall()
            
            return {
                "period_days": days,
                "total_messages": total_messages,
                "unique_users": unique_users,
                "tool_usage": [{"tool": t[0], "count": t[1]} for t in tool_usage]
            }
    
    def export_session(self, session_id: str) -> Dict:
        """Export a complete session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get session info
            cursor.execute('''
                SELECT * FROM chat_sessions WHERE session_id = ?
            ''', (session_id,))
            session = cursor.fetchone()
            
            if not session:
                return None
            
            # Get messages
            cursor.execute('''
                SELECT * FROM messages 
                WHERE session_id = ? 
                ORDER BY created_at
            ''', (session_id,))
            messages = cursor.fetchall()
            
            # Get tool calls
            cursor.execute('''
                SELECT * FROM tool_calls 
                WHERE session_id = ? 
                ORDER BY created_at
            ''', (session_id,))
            tool_calls = cursor.fetchall()
            
            return {
                "session": {
                    "id": session[0],
                    "channel_id": session[1],
                    "user_id": session[2],
                    "thread_ts": session[3],
                    "created_at": session[4],
                    "updated_at": session[5]
                },
                "messages": [
                    {
                        "role": msg[2],
                        "content": msg[3],
                        "metadata": json.loads(msg[4]) if msg[4] else None,
                        "created_at": msg[5]
                    }
                    for msg in messages
                ],
                "tool_calls": [
                    {
                        "tool_name": tc[2],
                        "input": json.loads(tc[3]) if tc[3] else None,
                        "output": tc[4],
                        "status": tc[5],
                        "created_at": tc[6]
                    }
                    for tc in tool_calls
                ]
            }
    
    def cleanup_old_sessions(self, days: int = 30):
        """Remove old sessions"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get old session IDs
            cursor.execute('''
                SELECT session_id FROM chat_sessions 
                WHERE updated_at < ?
            ''', (cutoff_date,))
            old_sessions = [row[0] for row in cursor.fetchall()]
            
            # Delete related data
            for session_id in old_sessions:
                cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
                cursor.execute('DELETE FROM tool_calls WHERE session_id = ?', (session_id,))
                cursor.execute('DELETE FROM chat_sessions WHERE session_id = ?', (session_id,))
            
            conn.commit()
            
            return len(old_sessions)

if __name__ == "__main__":
    # CLI for database management
    import sys
    
    analytics = ChatAnalytics()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "stats":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            stats = analytics.get_usage_stats(days)
            print(json.dumps(stats, indent=2))
        
        elif command == "export" and len(sys.argv) > 2:
            session_id = sys.argv[2]
            data = analytics.export_session(session_id)
            if data:
                print(json.dumps(data, indent=2, default=str))
            else:
                print(f"Session {session_id} not found")
        
        elif command == "cleanup":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            count = analytics.cleanup_old_sessions(days)
            print(f"Cleaned up {count} old sessions")
        
        else:
            print("Usage:")
            print("  python db_utils.py stats [days]")
            print("  python db_utils.py export <session_id>")
            print("  python db_utils.py cleanup [days]")
    else:
        # Show basic stats
        stats = analytics.get_usage_stats()
        print("Chat Database Statistics (Last 7 days):")
        print(json.dumps(stats, indent=2))