import ListItems from "./list_items";
function Content({ starred, notStarred, handleStarToggle, handleSelectToggle, onRenameChat, onDeleteChat, searchQuery }) {
  return (
    <div className="Content">
      <div className="Starred">
        <h2 className="h2">Starred Conversations</h2>
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
              onDeleteChat={onDeleteChat}
              searchQuery={searchQuery}
            />
          ))}
        </ul>
      </div>
      <div className="Not_Starred">
        <h2 className="h2">Conversations</h2>
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
              onDeleteChat={onDeleteChat}
              searchQuery={searchQuery}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}
export default Content;
