
function Header({ onNewChat, searchQuery, onSearchChange }) {
  return (
    <div className="Header">
      <button
        className="new-chat-btn btn"
        style={{ display: 'flex', flexDirection: 'row', justifyContent: "space-between", marginLeft: '3px', marginTop: '6px' }}
        onClick={onNewChat}
      >
        <span>New Chat</span>
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="new-chat-icon"
          style={{ marginLeft: '8px' }}
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <div className="search-container">
        <input
          type="text"
          placeholder="Search..."
          className="search-input"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        <svg className="search-icon" viewBox="0 0 24 24">
          <path d="M10.5 3a7.5 7.5 0 105.01 13.07l4.21 4.21 1.28-1.28-4.21-4.21A7.5 7.5 0 0010.5 3zm0 2a5.5 5.5 0 110 11 5.5 5.5 0 010-11z" />
        </svg>
      </div>
    </div>
  )
}

export default Header;