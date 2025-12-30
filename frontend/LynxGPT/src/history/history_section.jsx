import { useState } from "react";
import Content from "./Content";
import Header from "./Header";
import Footer from "./Footer";

function HistorySection({ conversations, selectedId, onNewChat, onRenameChat, onSelectChat, onStarToggle, onDeleteChat }) {
  const [searchQuery, setSearchQuery] = useState("");

  const itemsData = conversations.map(c => ({
    id: c.id,
    title: c.title,
    isStarred: c.isStarred,
    isSelected: c.id === selectedId
  }));

  // Filter items based on search query
  const filteredItems = searchQuery.trim() === ""
    ? itemsData
    : itemsData.filter(item =>
      item.title.toLowerCase().includes(searchQuery.toLowerCase())
    );

  const handleStarToggle = (id) => {
    onStarToggle && onStarToggle(id);
  };

  const handleSelectToggle = (id) => {
    onSelectChat && onSelectChat(id);
  };

  const handleDeleteChat = (id) => {
    onDeleteChat && onDeleteChat(id);
  };

  return (
    <div className="history-section">
      <Header
        onNewChat={onNewChat}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
      />
      <Content
        starred={filteredItems.filter(i => i.isStarred)}
        notStarred={filteredItems.filter(i => !i.isStarred)}
        handleStarToggle={handleStarToggle}
        handleSelectToggle={handleSelectToggle}
        onRenameChat={onRenameChat}
        onDeleteChat={handleDeleteChat}
        searchQuery={searchQuery}
      />
      <Footer />
    </div>
  );
}

export default HistorySection;
