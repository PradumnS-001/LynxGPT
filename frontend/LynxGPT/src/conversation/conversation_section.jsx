import ChatBotUI from "./ChatBotUI";

function ConversationSection({ conversationId }) {
  return (
    <div className="conversation-section">
      <ChatBotUI conversationId={conversationId} />
    </div>
  );
}

export default ConversationSection;
