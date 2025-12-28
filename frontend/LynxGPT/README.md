# LynxGPT Frontend 🐆

> React-based chat interface for the LynxGPT AI assistant

## 🛠️ Tech Stack

- **React 19** + Vite 7
- **Vanilla CSS** (no frameworks)
- **Nginx** for production serving

## 📁 Structure

```
src/
├── App.jsx              # Main app with routing
├── main.jsx             # Entry point + API calls
├── conversation/        # Chat message components
├── history/             # Sidebar & history components
└── assets/              # Static assets
```

## 🚀 Development

```bash
# Install dependencies
npm install

# Start dev server (hot reload)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## 🐳 Docker

The frontend uses a **multi-stage Docker build**:

1. **Build Stage**: Node 18 compiles React to static files
2. **Production Stage**: Nginx Alpine serves the built assets

```bash
docker build -t lynxgpt-frontend .
docker run -p 80:80 lynxgpt-frontend
```

## 🔗 API Integration

The frontend connects to the backend API at `/api/*` (proxied via Nginx in production).

| Endpoint | Purpose |
|----------|---------|
| `GET /api/conversations` | Fetch conversation list |
| `POST /api/conversations` | Create new chat |
| `POST /api/conversations/:id/messages` | Send message |
| `POST /api/conversations/:id/upload_pdf/:type` | Upload PDF |
