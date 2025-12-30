import { useState, useEffect, useCallback, useRef } from "react";
import "./chatbot.css";
import botPfp from "../assets/pfp2.png";
import userPfp from "../assets/pfp1.png";

const API_URL = "http://localhost:8000";

// Global cache for pending messages (sent but not yet in DB)
const pendingMessages = new Map();

const INTRO_MESSAGES = [
  "What can I help you with today?",
  "What problem are we tackling?",
  "What's on your mind right now?",
  "Need help with something specific?",
  "What are we working on today?",
  "Ask me anything. I'm listening."
];

function ChatBotUI({ conversationId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [showChat, setShowChat] = useState(false);
  const [botTyping, setBotTyping] = useState(false);
  const typingConversationIdRef = useRef(null);
  const conversationsWithMessagesRef = useRef(new Set()); // Track conversations that have messages
  const activeConversationIdRef = useRef(conversationId); // Track current visible conversation

  const [introText, setIntroText] = useState(
    () => INTRO_MESSAGES[Math.floor(Math.random() * INTRO_MESSAGES.length)]
  );
  const [introIndex, setIntroIndex] = useState(0);

  const welcomeText = "Welcome to Lynx Terminal!";
  const [welcomeIndex, setWelcomeIndex] = useState(0);

  const introDisplay = introText.slice(0, introIndex);

  const welcomeDone = welcomeIndex >= welcomeText.length;
  const introTyping = welcomeDone && introIndex < introText.length;

  // Combined typing sequence: welcome (bigger) -> intro (random)
  function playTypingSound() {
    try {
      const audio = new Audio('/sounds/typing.mp3');
      audio.volume = 0.18;
      audio.play().catch(() => { });
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    if (showChat) return; // Only type on intro screen

    // Sequential typing using async/await to guarantee order
    let cancelled = false;

    const delay = (ms) => new Promise(res => setTimeout(res, ms));

    async function typeText(setter, text, charDelay) {
      for (let i = 1; i <= text.length; i++) {
        if (cancelled) break;
        setter(i);
        playTypingSound();
        // wait for next char
        // eslint-disable-next-line no-await-in-loop
        await delay(charDelay);
      }
    }

    (async () => {
      // reset indices
      setWelcomeIndex(0);
      setIntroIndex(0);

      await typeText(setWelcomeIndex, welcomeText, 60);
      if (cancelled) return;
      // short pause before intro
      await delay(300);
      if (cancelled) return;
      await typeText(setIntroIndex, introText, 80);
    })();

    return () => { cancelled = true; };
  }, [introText, showChat, welcomeText]);


  const prevConversationIdRef = useRef(null);


  const loadMessages = useCallback(async () => {
    if (!conversationId) return;

    const res = await fetch(`${API_URL}/conversations/${conversationId}/messages`);
    const data = await res.json();
    const loadedMessages = data.messages || [];

    // Merge pending message if exists
    const pendingText = pendingMessages.get(conversationId);
    if (pendingText) {
      // Check if backend already saved it (deduplication)
      const isSaved = loadedMessages.some(m => m.sender === "gru" && m.text === pendingText);
      if (isSaved) {
        pendingMessages.delete(conversationId);
      } else {
        // Not saved yet, append locally
        loadedMessages.push({ sender: "gru", text: pendingText });
      }
    }

    setMessages(loadedMessages);

    // Track if this conversation has messages
    if (loadedMessages.length > 0) {
      conversationsWithMessagesRef.current.add(conversationId);
      setShowChat(true);
    } else if (!conversationsWithMessagesRef.current.has(conversationId)) {
      // Only show intro if we've never seen messages for this conversation
      setShowChat(false);
    }
  }, [conversationId]);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  useEffect(() => {
    // Poll for updates if bot is typing for a different conversation
    // This ensures messages appear when switching back to a conversation with pending responses
    let pollInterval;
    if (botTyping && typingConversationIdRef.current !== conversationId) {
      pollInterval = setInterval(loadMessages, 500);
    }

    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [conversationId, botTyping, loadMessages]);


  // When conversation changes (new chat), randomize intro text
  useEffect(() => {
    // Check if conversation actually changed (not just a re-render)
    const conversationChanged = prevConversationIdRef.current !== conversationId;
    prevConversationIdRef.current = conversationId;
    activeConversationIdRef.current = conversationId;

    // Only reset intro text if conversation actually changed
    if (conversationChanged) {
      const choice = INTRO_MESSAGES[Math.floor(Math.random() * INTRO_MESSAGES.length)];
      setIntroText(choice);
      setWelcomeIndex(0);
      setIntroIndex(0);
      // Don't set showChat here - let the loadMessages effect handle it
    }
  }, [conversationId]);

  const stripHtmlIfAny = (text) => {
    if (!text) return "";
    return text.replace(/<[^>]+>/g, "");
  };

  const handleSend = async () => {
    if (!input.trim() || !conversationId) return;

    const userText = input;
    setInput("");
    setShowChat(true);

    const sendBtn = document.querySelector(".send-btn");
    sendBtn.disabled = true;
    sendBtn.classList.add("disabled");

    // Mark this conversation as having messages
    conversationsWithMessagesRef.current.add(conversationId);

    // Cache pending message
    pendingMessages.set(conversationId, userText);

    // Add user message immediately to state
    setMessages(prev => [
      ...prev,
      { sender: "gru", text: userText }
    ]);

    setTimeout(() => {
      const area = document.querySelector(".messages-area");
      if (area) area.scrollTop = area.scrollHeight;
    }, 50);

    setBotTyping(true);
    typingConversationIdRef.current = conversationId;
    const currentConvId = conversationId; // Capture for comparison

    try {
      const res = await fetch(
        `${API_URL}/conversations/${conversationId}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sender: "gru", text: userText })
        }
      );
      const data = await res.json();

      // Check if conversation changed while we were waiting for response
      if (typingConversationIdRef.current !== currentConvId) {
        // Conversation changed, don't update messages
        setBotTyping(false);
        typingConversationIdRef.current = null;
        return;
      }

      // Backend always returns [user_msg, ...bot_messages]
      // We already added user_msg to state, so always skip index 0
      const full = data.messages || [];
      const incoming = full.length > 0 ? full.slice(1) : [];

      // We'll append bot messages one-by-one: type non-link messages, queue link-only messages
      const linkQueue = [];

      // Start from existing messages (should already include the user's message)
      setMessages(prev => [...prev]);

      // Helper to type text into a message at position index (mutating state via setter)
      const typeMessage = (targetIndex, text, charDelay = 12) => {
        return new Promise((resolve) => {
          let i = 0;
          const tick = () => {
            // Check if conversation changed during typing
            if (activeConversationIdRef.current !== currentConvId) {
              resolve();
              return;
            }

            i += 1;
            setMessages(prev => {
              const copy = [...prev];
              // safety: ensure targetIndex exists
              if (!copy[targetIndex]) copy[targetIndex] = { sender: "bot", text: "" };
              copy[targetIndex] = { ...copy[targetIndex], text: text.slice(0, i) };
              return copy;
            });
            if (i < text.length) {
              setTimeout(tick, charDelay);
            } else {
              resolve();
            }
          };
          tick();
        });
      };

      // iterate incoming messages sequentially
      for (const msg of incoming) {
        // Check if conversation changed during typing
        if (activeConversationIdRef.current !== currentConvId) {
          setBotTyping(false);
          typingConversationIdRef.current = null;
          return;
        }

        if (!msg) continue;
        // If it's a PDF link or an URL-only message, queue it to append after typing
        const txt = (msg.text || "").trim();
        const isLink = /^https?:\/\//i.test(txt) || txt.toLowerCase().endsWith('.pdf');
        if (isLink) {
          linkQueue.push(msg);
          continue;
        }

        // append an empty bot message and type into it
        let targetIndex;
        setMessages(prev => {
          if (activeConversationIdRef.current !== currentConvId) return prev;
          const copy = [...prev, { sender: "bot", text: "" }];
          targetIndex = copy.length - 1;
          return copy;
        });

        // wait a tiny pause before typing to feel natural
        // eslint-disable-next-line no-await-in-loop
        await new Promise(r => setTimeout(r, 250));

        // Check again before typing
        if (activeConversationIdRef.current !== currentConvId) {
          setBotTyping(false);
          typingConversationIdRef.current = null;
          return;
        }

        // eslint-disable-next-line no-await-in-loop
        await typeMessage(targetIndex, txt, Math.max(8, Math.floor(800 / Math.max(50, txt.length))));
      }

      // append link-only messages now (one per response as required)
      for (const lmsg of linkQueue) {
        setMessages(prev => [...prev, lmsg]);
      }

    } catch (error) {
      console.error(error);
    } finally {
      // Only clear typing state if we're still on the same conversation
      if (typingConversationIdRef.current === currentConvId) {
        setBotTyping(false);
        typingConversationIdRef.current = null;
      }

      const btn = document.querySelector(".send-btn");
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("disabled");
      }

      setTimeout(() => {
        const area = document.querySelector(".messages-area");
        if (area) area.scrollTop = area.scrollHeight;
      }, 100);
    }
  };

  const handlePdfUpload = async (event, pdfType) => {
    const file = event.target.files[0];
    if (!file) return;

    if (file.type !== "application/pdf") {
      setMessages(prev => [...prev, { sender: "bot", text: "Upload a pdf please" }]);
      event.target.value = "";
      return;
    }

    if (!conversationId) {
      event.target.value = "";
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(
      `${API_URL}/conversations/${conversationId}/upload_pdf/${pdfType}`,
      {
        method: "POST",
        body: formData
      }
    );

    const data = await res.json();
    const botText = data.bot_text || `Received ${pdfType}: ${file.name}`;

    setMessages(prev => [
      ...prev,
      { sender: "bot", text: botText }
    ]);
    setShowChat(true);
    event.target.value = "";

    setTimeout(() => {
      const area = document.querySelector(".messages-area");
      if (area) area.scrollTop = area.scrollHeight;
    }, 100);
  };

  // Audio hook placeholder: will be wired to a real audio file later
  function playClickSound() {
    try {
      const audio = new Audio('/sounds/click.mp3');
      audio.volume = 0.18;
      audio.play().catch(() => { });
    } catch {
      // ignore if not available
    }
  }

  function playKeySound() {
    try {
      const k = new Audio('/sounds/keystroke.mp3');
      k.volume = 0.06;
      k.play().catch(() => { });
    } catch {
      // ignore
    }
  }


  // wrap triggerRipple in useCallback and attach global click listener
  const triggerRipple = useCallback((e) => {
    try {
      if (!e || e.button !== undefined && e.button !== 0) return; // left click only

      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent-vibrant') || '#00F2FF';
      const accentColor = accent.trim();

      const maxSide = Math.max(window.innerWidth, window.innerHeight);
      const size = Math.max(0, Math.floor(maxSide * 0.012));

      const ripple = document.createElement('span');
      ripple.className = 'ripple';
      ripple.style.width = `${size}px`;
      ripple.style.height = `${size}px`;
      ripple.style.background = accentColor;
      ripple.style.position = 'fixed';
      ripple.style.left = `${e.clientX - size / 2}px`;
      ripple.style.top = `${e.clientY - size / 2}px`;
      ripple.style.pointerEvents = 'none';
      ripple.style.zIndex = 9999;
      ripple.style.opacity = '0.95';
      ripple.style.transform = 'scale(0)';

      document.body.appendChild(ripple);
      playClickSound();

      // trigger reflow for animation
      void ripple.offsetWidth;
      ripple.style.transform = 'scale(3)';
      ripple.style.opacity = '0';

      setTimeout(() => {
        ripple.remove();
      }, 700);
    } catch {
      // fail silently
    }
  }, []);

  useEffect(() => {
    function globalClick(e) {
      triggerRipple(e);
    }
    document.addEventListener('click', globalClick);
    return () => document.removeEventListener('click', globalClick);
  }, [triggerRipple]);

  const delay = Math.random() * 3;

  return (
    <div className="chat-container">
      {!showChat && (
        <div className="typing-screen">
          <div className="typing-inner">
            <p className="welcome-text animate-text">{welcomeText.slice(0, welcomeIndex)}{!welcomeDone && <span className="cursor"></span>}</p>
            <p
              className="intro-text animate-text"
              style={{
                animationDelay: `${delay}s`
              }}
            >
              {introDisplay}
              {introTyping && <span className="cursor"></span>}
            </p>
          </div>
        </div>
      )}

      {showChat && (
        <div className="messages-area">
          {messages.map((msg, index) => (
            <div
              key={index}
              className={`message-wrapper ${msg.sender === "gru" ? "right" : "left"}`}
              onClick={(e) => triggerRipple(e)}
            >
              <img
                src={msg.sender === "gru" ? userPfp : botPfp}
                alt="pfp"
                className="pfp"
              />
              <div className={`message-bubble ${msg.sender}`}>
                <span className="sender-name">
                  {msg.sender === "gru" ? "Gru" : "Chad-Bot"}
                </span>
                <div className="message-text">
                  {(() => {
                    const clean = stripHtmlIfAny(msg.text);
                    if (clean.toLowerCase().startsWith("error")) {
                      return (
                        <p>The document does not exist...</p>
                      );
                    }
                    if (clean.toLowerCase().endsWith(".pdf")) {
                      return (
                        <a
                          href={`${clean}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="pdf-link"
                        >
                          📄 Open PDF
                        </a>
                      );
                    }
                    return clean.split("\n").map((line, i) => (
                      <span key={i}>
                        {line}
                        <br />
                      </span>
                    ));
                  })()}
                </div>
              </div>
            </div>
          ))}

          {botTyping && typingConversationIdRef.current === conversationId && (
            <div className="message-wrapper left">
              <img src={botPfp} alt="pfp" className="pfp" />
              <div className="message-bubble bot typing-bubble">
                <div className="typing-dots">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="input-area">
        <div className="pdf-upload-buttons">
          <label className="pdf-btn" onClick={(e) => triggerRipple(e)}>
            📄Resume
            <input type="file" accept="application/pdf" hidden
              onChange={(e) => handlePdfUpload(e, "ResumePDF")} />
          </label>

          <label className="pdf-btn" onClick={(e) => triggerRipple(e)}>
            📚 Q-Papers
            <input type="file" accept="application/pdf" hidden
              onChange={(e) => handlePdfUpload(e, "QuestionPapersPDF")} />
          </label>
        </div>

        <input
          type="text"
          placeholder="Why do I exist..."
          className="input-box"
          value={input}
          onChange={(e) => { setInput(e.target.value); playKeySound(); }}
          onKeyDown={(e) => !document.querySelector(".send-btn").disabled && e.key === "Enter" && handleSend()}
        />
        <button onClick={(e) => { triggerRipple(e); handleSend(); }} className="send-btn">Send</button>
      </div>
    </div>
  );
}

export default ChatBotUI;
