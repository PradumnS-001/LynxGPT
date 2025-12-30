import { useState, useEffect, useCallback, useRef } from "react";
import HistorySection from "./history/history_section";
import ConversationSection from "./conversation/conversation_section";
import BottomBanner from "./bottom_banner";

const API_URL = "http://localhost:8000";
const MAX_NORMAL_CONVERSATIONS = 64;
const MAX_STARRED_CONVERSATIONS = 32;

function App() {
  const [conversations, setConversations] = useState([]);
  const [errorMessage, setErrorMessage] = useState(null);
  const initializedRef = useRef(false);

  // 1. Initialize state from localStorage so it persists on refresh
  const [selectedId, setSelectedId] = useState(() => {
    return localStorage.getItem("currentConversationId") || null;
  });

  const purgeEmptyConversations = useCallback(async () => {
    try {
      await fetch(`${API_URL}/conversations/purge-empty`, { method: "POST" });
    } catch (error) {
      console.error("Failed to purge empty conversations", error);
    }
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/conversations`);
      const data = await res.json();
      setConversations(data);
      return data;
    } catch (error) {
      console.error("Failed to load conversations", error);
      return [];
    }
  }, []);

  const createNewChat = useCallback(async (skipPurge = false) => {
    try {
      if (!skipPurge) {
        await purgeEmptyConversations();
      }

      // Check memory constraints after purge
      const currentConversations = await loadConversations();
      const normalCount = currentConversations.filter(c => !c.isStarred).length;

      // Check normal conversation limit (new chats are always normal by default)
      if (normalCount >= MAX_NORMAL_CONVERSATIONS) {
        setErrorMessage("Maximum conversations limit reached (64 normal conversations)");
        setTimeout(() => setErrorMessage(null), 5000);
        return null;
      }

      const res = await fetch(`${API_URL}/conversations`, { method: "POST" });
      const newConv = await res.json();

      await loadConversations();

      setSelectedId(newConv.id);

      setTimeout(() => {
        const area = document.querySelector(".messages-area");
        if (area) area.scrollTop = area.scrollHeight;
      }, 100);

      return newConv;
    } catch (error) {
      console.error("Failed to create chat", error);
      return null;
    }
  }, [loadConversations, purgeEmptyConversations]);

  // 2. Load the history list on mount and handle initial state
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    const initializeConversations = async () => {
      // Purge empty conversations BEFORE checking if DB is empty
      await purgeEmptyConversations();
      
      const loadedConversations = await loadConversations();
      
      // If no conversations exist, create one (skip purge since we just purged)
      if (loadedConversations.length === 0) {
        const newConv = await createNewChat(true);
        if (newConv) {
          setSelectedId(newConv.id);
        }
      } else {
        // Use the last selected conversation from localStorage, or the first one
        const savedId = localStorage.getItem("currentConversationId");
        if (savedId && loadedConversations.some(c => c.id === savedId)) {
          setSelectedId(savedId);
        } else if (loadedConversations.length > 0) {
          // Use the first conversation if saved one doesn't exist
          setSelectedId(loadedConversations[0].id);
        }
      }
    };
    
    initializeConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount

  // 3. Whenever selectedId changes, save it to localStorage
  useEffect(() => {
    if (selectedId) {
      localStorage.setItem("currentConversationId", selectedId);
    } else {
      localStorage.removeItem("currentConversationId");
    }
  }, [selectedId]);

  const handleNewChat = async () => {
    // Purge empty conversations before creating new chat
    await purgeEmptyConversations();
    await createNewChat(true); // Skip purge since we just purged
  };

  const handleRenameChat = async (id, newTitle) => {
    try {
      const res = await fetch(`${API_URL}/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle })
      });
      const updated = await res.json();

      setConversations(prev =>
        prev.map(c => (c.id === id ? updated : c))
      );
    } catch (error) {
      console.error("Failed to rename chat", error);
    }
  };

  const handleSelectChat = (id) => setSelectedId(id);

  const handleStarToggle = async (id) => {
    try {
      const currentConv = conversations.find(c => c.id === id);
      const willBeStarred = !currentConv?.isStarred;

      // Check memory constraints before starring
      if (willBeStarred) {
        const starredCount = conversations.filter(c => c.isStarred).length;
        if (starredCount >= MAX_STARRED_CONVERSATIONS) {
          setErrorMessage("Maximum starred conversations limit reached (32 starred conversations)");
          setTimeout(() => setErrorMessage(null), 5000);
          return;
        }
      }

      const res = await fetch(`${API_URL}/conversations/${id}/star`, {
        method: "PATCH"
      });
      const updated = await res.json();

      setConversations(prev =>
        prev.map(c => (c.id === id ? updated : c))
      );
    } catch (error) {
      console.error("Failed to toggle star", error);
    }
  };

  const handleDeleteChat = async (id) => {
    try {
      await fetch(`${API_URL}/conversations/${id}`, {
        method: "DELETE"
      });

      // Purge any newly empty conversations after deletion
      await purgeEmptyConversations();

      // Reload conversations to get fresh state
      const updated = await loadConversations();

      if (updated.length === 0) {
        // If nothing remains, create a new chat (skip purge since we just purged)
        const newConv = await createNewChat(true);
        if (newConv) {
          setSelectedId(newConv.id);
        } else {
          setSelectedId(null);
        }
        return;
      }

      // If the deleted conversation was selected, pick the first available
      if (selectedId === id) {
        setSelectedId(updated[0].id);
      }
    } catch (error) {
      console.error("Failed to delete chat", error);
    }
  };

  return (
    <>
      {errorMessage && (
        <div style={{
          position: "fixed",
          top: "20px",
          right: "20px",
          backgroundColor: "#ff4444",
          color: "white",
          padding: "12px 20px",
          borderRadius: "8px",
          boxShadow: "0 4px 6px rgba(0,0,0,0.1)",
          zIndex: 10000,
          maxWidth: "300px",
          fontSize: "14px"
        }}>
          {errorMessage}
        </div>
      )}
      <HistorySection
        conversations={conversations}
        selectedId={selectedId}
        onNewChat={handleNewChat}
        onRenameChat={handleRenameChat}
        onSelectChat={handleSelectChat}
        onStarToggle={handleStarToggle}
        onDeleteChat={handleDeleteChat}
      />
      <ConversationSection conversationId={selectedId} />
      <BottomBanner />
    </>
  );
}

export default App;