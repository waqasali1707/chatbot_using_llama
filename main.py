import os
import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict
from fastapi.middleware.cors import CORSMiddleware
import httpx
import json
from datetime import datetime
import sqlite3
from contextlib import contextmanager
import asyncio
from threading import Lock

class QueryRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = "default"
    max_tokens: Optional[int] = 100
    temperature: Optional[float] = 0.1

class QueryResponse(BaseModel):
    query: str
    answer: str
    conversation_id: str
    timestamp: datetime

class ConversationListResponse(BaseModel):
    conversation_id: str
    last_message: str
    last_updated: datetime
    message_count: int

class DatabaseManager:
    def __init__(self, db_path: str = "chat_history.db"):
        self.db_path = db_path
        self.lock = Lock()
        self.init_database()

    def init_database(self):
        """Initialize the database and create tables if they don't exist"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    user_query TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_id 
                ON conversations(conversation_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON conversations(timestamp)
            """)
            
            conn.commit()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            with self.lock:
                yield conn
        finally:
            conn.close()

    def add_interaction(self, conversation_id: str, user_query: str, assistant_response: str):
        """Add a new interaction to the database"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (conversation_id, user_query, assistant_response, timestamp)
                VALUES (?, ?, ?, ?)
            """, (conversation_id, user_query, assistant_response, datetime.now()))
            conn.commit()

    def get_conversation_history(self, conversation_id: str, limit: int = 50) -> List[Dict[str, str]]:
        """Get conversation history for a specific conversation ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_query, assistant_response, timestamp
                FROM conversations
                WHERE conversation_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (conversation_id, limit))
            
            rows = cursor.fetchall()
            return [
                {
                    "query": row["user_query"],
                    "response": row["assistant_response"],
                    "timestamp": row["timestamp"]
                }
                for row in rows
            ]

    def get_all_conversations(self) -> List[Dict]:
        """Get list of all conversations with summary info"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    conversation_id,
                    user_query as last_message,
                    timestamp as last_updated,
                    COUNT(*) as message_count
                FROM conversations
                WHERE id IN (
                    SELECT MAX(id)
                    FROM conversations
                    GROUP BY conversation_id
                )
                GROUP BY conversation_id
                ORDER BY timestamp DESC
            """)
            
            rows = cursor.fetchall()
            return [
                {
                    "conversation_id": row["conversation_id"],
                    "last_message": row["last_message"][:100] + "..." if len(row["last_message"]) > 100 else row["last_message"],
                    "last_updated": row["last_updated"],
                    "message_count": row["message_count"]
                }
                for row in rows
            ]

    def clear_conversation(self, conversation_id: str):
        """Clear all messages for a specific conversation"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM conversations
                WHERE conversation_id = ?
            """, (conversation_id,))
            conn.commit()
            return cursor.rowcount

    def delete_conversation(self, conversation_id: str):
        """Completely delete a conversation"""
        return self.clear_conversation(conversation_id)

    def get_conversation_stats(self):
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Total conversations
            cursor.execute("SELECT COUNT(DISTINCT conversation_id) as total_conversations FROM conversations")
            total_conversations = cursor.fetchone()["total_conversations"]
            
            # Total messages
            cursor.execute("SELECT COUNT(*) as total_messages FROM conversations")
            total_messages = cursor.fetchone()["total_messages"]
            
            # Most recent activity
            cursor.execute("SELECT MAX(timestamp) as last_activity FROM conversations")
            last_activity = cursor.fetchone()["last_activity"]
            
            return {
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "last_activity": last_activity
            }

app = FastAPI(
    title="Simple Chatbot API with Groq & SQL Storage",
    description="A simple chatbot using Groq API with persistent SQL-based conversation storage",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database manager
db_manager = DatabaseManager()

# Groq API configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "your_Groq_api")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# System prompt to control chatbot behavior
SYSTEM_PROMPT = """You are an AI Bot. Your job is to explore the user's childhood stories in a warm, curious way.

INSTRUCTIONS:
Be a good listner. 
Do not bore the user asking long questions.
Change the topic if the current topic becomes boring and too long (Your goal is to fetch as much memories as possible. Do not stick to one topic for too long).
"""

async def call_groq_api(messages: List[Dict], max_tokens: int = 100, temperature: float = 0.1):
    """Call Groq API with the provided messages"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",  # You can change this to other Groq models
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(GROQ_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Groq API error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error calling Groq API: {str(e)}")

def build_messages(query: str, conversation_history: List[Dict[str, str]]) -> List[Dict]:
    """Build messages array for Groq API including system prompt and conversation history"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history
    for interaction in conversation_history:
        messages.append({"role": "user", "content": interaction["query"]})
        messages.append({"role": "assistant", "content": interaction["response"]})
    
    # Add current query
    messages.append({"role": "user", "content": query})
    
    return messages

@app.post("/chat/query", response_model=QueryResponse)
async def chat_query(request: QueryRequest):
    """Main chat endpoint"""
    
    # Use default conversation_id if not provided
    if not request.conversation_id:
        request.conversation_id = "default"
    
    # Handle special reset command
    if request.query == "----":
        db_manager.clear_conversation(request.conversation_id)
        return QueryResponse(
            query=request.query,
            answer="Hello! I'm your AI assistant. How can I help you today?",
            conversation_id=request.conversation_id,
            timestamp=datetime.now()
        )
    
    try:
        # Get conversation history from database
        conversation_history = db_manager.get_conversation_history(request.conversation_id)
        
        # Build messages for Groq API
        messages = build_messages(request.query, conversation_history)
        
        # Call Groq API
        answer = await call_groq_api(
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        # Store interaction in database
        db_manager.add_interaction(request.conversation_id, request.query, answer)
        
        return QueryResponse(
            query=request.query,
            answer=answer,
            conversation_id=request.conversation_id,
            timestamp=datetime.now()
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/conversations", response_model=List[ConversationListResponse])
def get_all_conversations():
    """Get list of all conversations"""
    try:
        conversations = db_manager.get_all_conversations()
        return [
            ConversationListResponse(
                conversation_id=conv["conversation_id"],
                last_message=conv["last_message"],
                last_updated=datetime.fromisoformat(conv["last_updated"]) if isinstance(conv["last_updated"], str) else conv["last_updated"],
                message_count=conv["message_count"]
            )
            for conv in conversations
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/conversation/{conversation_id}")
def get_conversation_history(conversation_id: str, limit: int = 50):
    """Get conversation history for a specific conversation ID"""
    try:
        history = db_manager.get_conversation_history(conversation_id, limit)
        return {
            "conversation_id": conversation_id,
            "history": history,
            "total_messages": len(history)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/chat/conversation/{conversation_id}")
def delete_conversation(conversation_id: str):
    """Delete conversation history for a specific conversation ID"""
    try:
        deleted_count = db_manager.delete_conversation(conversation_id)
        return {
            "message": f"Conversation {conversation_id} deleted successfully",
            "deleted_messages": deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/system-prompt")
async def update_system_prompt(new_prompt: dict):
    """Update the system prompt"""
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = new_prompt.get("prompt", SYSTEM_PROMPT)
    return {"message": "System prompt updated successfully", "new_prompt": SYSTEM_PROMPT}

@app.get("/chat/system-prompt")
def get_system_prompt():
    """Get current system prompt"""
    return {"system_prompt": SYSTEM_PROMPT}

@app.get("/chat/stats")
def get_chat_stats():
    """Get database statistics"""
    try:
        stats = db_manager.get_conversation_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    """Health check endpoint"""
    try:
        stats = db_manager.get_conversation_stats()
        return {
            "status": "healthy",
            "api_configured": GROQ_API_KEY != "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",
            "database_connected": True,
            "stats": stats
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "api_configured": GROQ_API_KEY != "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",
            "database_connected": False,
            "error": str(e)
        }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1
    )
