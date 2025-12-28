import Content from "./Content";
import Header from "./Header";
import Footer from "./Footer";

function HistorySection({ conversations, selectedId, onNewChat, onRenameChat, onSelectChat }) {
  const itemsData = conversations.map(c => ({
    id: c.id,
    title: c.title,
    isStarred: c.isStarred,
    isSelected: c.id === selectedId
  }));

  const handleStarToggle = () => {}; // You will hook backend later

  const handleSelectToggle = (id) => {
    onSelectChat && onSelectChat(id);
  };

  return (
    <div className="history-section">
      <Header onNewChat={onNewChat} />
      <Content
        starred={itemsData.filter(i => i.isStarred)}
        notStarred={itemsData.filter(i => !i.isStarred)}
        handleStarToggle={handleStarToggle}
        handleSelectToggle={handleSelectToggle}
        onRenameChat={onRenameChat}
      />
      <Footer />
    </div>
  );
}

export default HistorySection;
