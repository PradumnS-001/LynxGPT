import ListItems from "./list_items";

function Content({starred, notStarred, handleStarToggle, handleSelectToggle, onRenameChat}) {
  return (
    <div className="Content">
      <div className="Starred">
        <h2 className="h2" style={{
              background: "linear-gradient(135deg, #338819ff, #9f2f2fff)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent"
            }}>Starred Conversations</h2>
        <ul>
          {starred.map(item => (
            <ListItems
              key={item.id}
              id={item.id}
              title={item.title}
              isStarred={item.isStarred}
              isSelected={item.isSelected}
              onStarToggle={handleStarToggle}
              onSelectToggle={handleSelectToggle}
              onRenameChat={onRenameChat}
            />
          ))}
        </ul>
      </div>
      <div className="Not_Starred">
        <h2 className="h2" style={{ paddingTop:'20px',background: "linear-gradient(135deg, #338819ff, #9f2f2fff)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent" }}>Conversations</h2>
        <ul>
          {notStarred.map(item => (
            <ListItems
              key={item.id}
              id={item.id}
              title={item.title}
              isStarred={item.isStarred}
              isSelected={item.isSelected}
              onStarToggle={handleStarToggle}
              onSelectToggle={handleSelectToggle}
              onRenameChat={onRenameChat}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}
export default Content;
