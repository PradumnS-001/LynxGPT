import { useState } from "react";

function ListItems({title = "idk wat to put here", id, isStarred, isSelected, onStarToggle, onSelectToggle, onRenameChat}) {

  const [hovered, setHovered] = useState(false);
  const [editing, setEditing] = useState(false);
  const [localTitle, setLocalTitle] = useState(title);

  let displayTitle = localTitle;
  if (displayTitle.length > 25) displayTitle = displayTitle.slice(0,25) + "...";

  const back = isSelected ? {color:"black", backgroundColor:"rgba(var(--accent-rgb), 0.5)"} : {};

  const handleDoubleClick = () => setEditing(true);

  const handleBlurOrEnter = () => {
    setEditing(false);
    if (onRenameChat && localTitle.trim() !== "") {
      onRenameChat(id, localTitle.trim());
    }
  };

  return (
    <li
      key={id}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={(e) => {
        if (!e.target.closest(".star") && !editing){onSelectToggle(id);}
      }}
      style={back}
    >
      {editing ? (
        <input
          value={localTitle}
          onChange={e => setLocalTitle(e.target.value)}
          onBlur={handleBlurOrEnter}
          onKeyDown={e => e.key === "Enter" && handleBlurOrEnter()}
          autoFocus
          style={{ background:"transparent", border:"none", color:"inherit", outline:"none", width:"80%" }}
        />
      ) : (
        <span onDoubleClick={handleDoubleClick}>{displayTitle}</span>
      )}

      <div>

                <svg xmlns="http://www.w3.org/2000/svg" 
                width="16" 
                height="16" 
                fill="currentColor" 
                className="bi bi-star-fill star" 
                viewBox="0 0 18 18" 

                style={{ 
                    fill: isStarred ? "#e8c35d" : "none", 
                    stroke: "#e8c35d", 
                    cursor: 'pointer' }} 
                    onClick={() => onStarToggle(id)}>

                <path d="M3.612 15.443c-.386.198-.824-.149-.746-.592l.83-4.73L.173 6.765c-.329-.314-.158-.888.283-.95l4.898-.696L7.538.792c.197-.39.73-.39.927 0l2.184 4.327 4.898.696c.441.062.612.636.282.95l-3.522 3.356.83 4.73c.078.443-.36.79-.746.592L8 13.187l-4.389 2.256z"/>
                </svg>
                

                <svg 
                width="16" 
                height="16" 
                viewBox="0 0 24 24" 
                fill="none" 
                xmlns="http://www.w3.org/2000/svg" 

                style={{
                    marginLeft: '1rem', 
                    marginRight: '-1rem', 
                    cursor: 'pointer', 
                    display: hovered ? 'inline' : 'none'
                }} 
                className="a3dots">

                    <circle cx="12" cy="4" r="2" fill="currentColor"/>
                    <circle cx="12" cy="12" r="2" fill="currentColor"/>
                    <circle cx="12" cy="20" r="2" fill="currentColor"/>
                </svg>
            </div>
    </li>
  );
}

export default ListItems;
