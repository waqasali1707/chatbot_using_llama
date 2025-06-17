document.addEventListener('DOMContentLoaded', () => {
    const queryInput = document.getElementById('query-input');
    const submitBtn = document.getElementById('submit-btn');
    const chatMessages = document.getElementById('chat-messages');
    const typingIndicator = document.getElementById('typing-indicator');
    const chatHistory = document.getElementById('chat-history');
    const BACKEND_URL = 'http://192.168.0.177:8000';

    // Chat management
    let conversations = [];
    let currentChatId = localStorage.getItem('currentChatId') || null;

    // Initialize
    initializeApp();

    async function initializeApp() {
        try {
            // Load all conversations from backend
            await loadConversationsFromBackend();
            
            // If no current chat or it doesn't exist, create new one
            if (!currentChatId || !conversations.find(c => c.conversation_id === currentChatId)) {
                await createNewChat();
            } else {
                await loadChat(currentChatId);
            }
        } catch (error) {
            console.error('Failed to initialize app:', error);
            // Fallback: create new chat
            await createNewChat();
        }
    }

    async function loadConversationsFromBackend() {
        try {
            const response = await fetch(`${BACKEND_URL}/chat/conversations`);
            if (response.ok) {
                conversations = await response.json();
                updateChatHistory();
            } else {
                console.warn('Failed to load conversations from backend');
                conversations = [];
            }
        } catch (error) {
            console.error('Error loading conversations:', error);
            conversations = [];
        }
    }

    function formatMessage(text) {
        // Handle bold text
        text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Handle italic text
        text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');

        // Handle numbered lists
        text = text.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
        text = text.replace(/(<li>.*?<\/li>(\n|$))+/g, '<ol>$&</ol>');

        // Handle bullet points
        text = text.replace(/^[\*\-]\s+(.+)$/gm, '<li>$1</li>');
        text = text.replace(/(<li>.*?<\/li>(\n|$))+/g, '<ul>$&</ul>');

        // Handle headers
        text = text.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
        text = text.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
        text = text.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');

        // Handle paragraphs
        text = text.replace(/\n\n/g, '</p><p>');
        text = '<p>' + text + '</p>';

        return text;
    }

    function addMessage(content, isUser, timestamp = null, skipSave = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user-message' : 'ai-message'}`;

        // Format the message content if it's from AI
        if (!isUser) {
            messageDiv.innerHTML = formatMessage(content);
        } else {
            messageDiv.textContent = content;
        }

        const timestampDiv = document.createElement('div');
        timestampDiv.className = 'timestamp';
        timestampDiv.textContent = getFormattedTime(timestamp);
        messageDiv.appendChild(timestampDiv);

        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    async function createNewChat() {
        // Generate new conversation ID
        currentChatId = 'conv_' + Date.now().toString();
        localStorage.setItem('currentChatId', currentChatId);
        
        // Clear chat messages
        chatMessages.innerHTML = '';
        
        // Add welcome message
        addMessage("Hey there! I'm here to listen — do you feel like sharing a memory or telling me a story?", false, new Date().toISOString(), true);
        
        // Reload conversations to update sidebar
        await loadConversationsFromBackend();
        
        return currentChatId;
    }

    async function deleteChat(chatId, event) {
        event.stopPropagation();

        try {
            // Delete from backend
            const response = await fetch(`${BACKEND_URL}/chat/conversation/${chatId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                // Remove from local conversations array
                conversations = conversations.filter(c => c.conversation_id !== chatId);
                
                // If we deleted the current chat, create a new one
                if (chatId === currentChatId) {
                    await createNewChat();
                }
                
                updateChatHistory();
            } else {
                console.error('Failed to delete conversation');
            }
        } catch (error) {
            console.error('Error deleting conversation:', error);
        }
    }

    function updateChatHistory() {
        chatHistory.innerHTML = '';

        if (conversations.length === 0) {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'empty-history';
            emptyDiv.textContent = 'No conversations yet';
            emptyDiv.style.color = '#888';
            emptyDiv.style.textAlign = 'center';
            emptyDiv.style.padding = '20px';
            chatHistory.appendChild(emptyDiv);
            return;
        }

        // Group conversations by time periods
        const timeGroups = {
            today: [],
            yesterday: [],
            lastWeek: [],
            lastMonth: [],
            older: []
        };

        const now = new Date();
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const lastWeek = new Date(now);
        lastWeek.setDate(lastWeek.getDate() - 7);
        const lastMonth = new Date(now);
        lastMonth.setMonth(lastMonth.getMonth() - 1);

        conversations.forEach(conv => {
            const chatDate = new Date(conv.last_updated);

            if (isSameDay(chatDate, now)) {
                timeGroups.today.push(conv);
            } else if (isSameDay(chatDate, yesterday)) {
                timeGroups.yesterday.push(conv);
            } else if (chatDate >= lastWeek) {
                timeGroups.lastWeek.push(conv);
            } else if (chatDate >= lastMonth) {
                timeGroups.lastMonth.push(conv);
            } else {
                timeGroups.older.push(conv);
            }
        });

        // Helper function to check if two dates are the same day
        function isSameDay(date1, date2) {
            return date1.getDate() === date2.getDate() &&
                date1.getMonth() === date2.getMonth() &&
                date1.getFullYear() === date2.getFullYear();
        }

        // Create time group headers and add chats
        const timeLabels = {
            today: 'Today',
            yesterday: 'Yesterday',
            lastWeek: 'Last 7 Days',
            lastMonth: 'Last Month',
            older: 'Older'
        };

        Object.entries(timeGroups).forEach(([group, groupChats]) => {
            if (groupChats.length > 0) {
                // Add group header
                const headerDiv = document.createElement('div');
                headerDiv.className = 'time-group-header';
                headerDiv.textContent = timeLabels[group];
                chatHistory.appendChild(headerDiv);

                // Add chats in reverse chronological order
                groupChats.sort((a, b) => new Date(b.last_updated) - new Date(a.last_updated)).forEach(conv => {
                    const historyItem = document.createElement('div');
                    historyItem.className = `history-item ${conv.conversation_id === currentChatId ? 'active' : ''}`;
                    historyItem.innerHTML = `
                        <span>💬</span>
                        <span class="history-item-title">${conv.last_message}</span>
                        <button class="delete-chat" title="Delete chat">🗑️</button>
                    `;

                    historyItem.addEventListener('click', () => loadChat(conv.conversation_id));
                    const deleteBtn = historyItem.querySelector('.delete-chat');
                    deleteBtn.addEventListener('click', (e) => deleteChat(conv.conversation_id, e));

                    chatHistory.appendChild(historyItem);
                });
            }
        });
    }

    async function loadChat(chatId) {
        try {
            currentChatId = chatId;
            localStorage.setItem('currentChatId', currentChatId);
            
            // Clear current messages
            chatMessages.innerHTML = '';
            
            // Load conversation history from backend
            const response = await fetch(`${BACKEND_URL}/chat/conversation/${chatId}`);
            
            if (response.ok) {
                const data = await response.json();
                
                // Display messages
                if (data.history && data.history.length > 0) {
                    data.history.forEach(msg => {
                        // Add user message
                        addMessage(msg.query, true, msg.timestamp, true);
                        // Add AI response
                        addMessage(msg.response, false, msg.timestamp, true);
                    });
                } else {
                    // If no history, show welcome message
                    addMessage("Hello! I'm your AI assistant. How can I help you today?", false, new Date().toISOString(), true);
                }
            } else {
                console.error('Failed to load conversation history');
                // Show welcome message as fallback
                addMessage("Hello! I'm your AI assistant. How can I help you today?", false, new Date().toISOString(), true);
            }
            
            updateChatHistory();
            
        } catch (error) {
            console.error('Error loading chat:', error);
            // Show welcome message as fallback
            chatMessages.innerHTML = '';
            addMessage("Hello! I'm your AI assistant. How can I help you today?", false, new Date().toISOString(), true);
        }
    }

    function getFormattedTime(timestamp = null) {
        const date = timestamp ? new Date(timestamp) : new Date();
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${hours}:${minutes}`;
    }

    submitBtn.addEventListener('click', async () => {
        const query = queryInput.value.trim();

        if (!query) {
            return;
        }

        // Add user message to UI
        addMessage(query, true, null, true);
        queryInput.value = '';

        // Show typing indicator
        typingIndicator.style.display = 'block';
        chatMessages.scrollTop = chatMessages.scrollHeight;

        try {
            const response = await fetch(`${BACKEND_URL}/chat/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query,
                    conversation_id: currentChatId,
                    max_tokens: 512,
                    temperature: 0.1
                })
            });

            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            const data = await response.json();
            typingIndicator.style.display = 'none';
            
            // Add AI response to UI
            addMessage(data.answer, false, data.timestamp, true);
            
            // Refresh conversations list to update last message and timestamp
            await loadConversationsFromBackend();

        } catch (error) {
            console.error('Error:', error);
            typingIndicator.style.display = 'none';
            addMessage('I apologize, but I encountered an error. Please try again.', false, null, true);
        }
    });

    queryInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            submitBtn.click();
        }
    });

    document.querySelector('.new-chat-btn').addEventListener('click', async () => {
        await createNewChat();
        queryInput.focus();
    });
});