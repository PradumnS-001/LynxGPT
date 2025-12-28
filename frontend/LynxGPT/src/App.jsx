import { useState, useEffect, useCallback } from "react";
import HistorySection from "./history/history_section";
import ConversationSection from "./conversation/conversation_section";

const API_URL = "http://localhost:8000";

function App() {
  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState(null);

  const loadConversations = useCallback(async () => {
    const res = await fetch(`${API_URL}/conversations`);
    const data = await res.json();
    setConversations(data);
  }, []);

  const createNewChat = useCallback(async () => {
    const res = await fetch(`${API_URL}/conversations`, { method: "POST" });
    const newConv = await res.json();

    await loadConversations();

    setSelectedId(newConv.id);

    setTimeout(() => {
      const area = document.querySelector(".messages-area");
      if (area) area.scrollTop = area.scrollHeight;
    }, 100);

    return newConv;
  }, [loadConversations]);

  // 🔥 Always create a fresh new chat each reload
  useEffect(() => {
    async function init() {
      await createNewChat();
    }
    init();
  }, [createNewChat]);

  const handleNewChat = async () => {
    await createNewChat();
  };

  const handleRenameChat = async (id, newTitle) => {
    const res = await fetch(`${API_URL}/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle })
    });
    const updated = await res.json();

    setConversations(prev =>
      prev.map(c => (c.id === id ? updated : c))
    );
  };

  const handleSelectChat = (id) => setSelectedId(id);

  return (
    <>
      <HistorySection
        conversations={conversations}
        selectedId={selectedId}
        onNewChat={handleNewChat}
        onRenameChat={handleRenameChat}
        onSelectChat={handleSelectChat}
      />
      <ConversationSection conversationId={selectedId} />
    </>
  );
}

export default App;
