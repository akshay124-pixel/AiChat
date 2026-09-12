# AI Chat — Backend

FastAPI backend for the AI Chat application.

## Architecture

```
Vercel Frontend (React/Vite)
        │
        │ HTTPS
        ▼
VPS — Nginx (host, port 443)         ← you configure this
        │
        │ http://127.0.0.1:8000
        ▼
FastAPI container (Docker)
        │
        │ http://host.docker.internal:11434
        │ (Docker maps this to the host machine)
        ▼
Ollama (running on VPS host — NOT in Docker)
        │
        ▼
Existing Qwen model
```

**Key point:** Ollama runs directly on the VPS host. The Docker container reaches it
via `host.docker.internal`, which Docker automatically maps to the host's gateway IP
through the `extra_hosts: host.docker.internal:host-gateway` entry in
`docker-compose.yml`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health + Ollama connectivity status |
| POST | `/api/chat` | Non-streaming chat |
| POST | `/api/chat/stream` | **Streaming chat (SSE)** |
| GET | `/api/conversations` | List conversations |
| POST | `/api/conversations` | Create conversation |
| GET | `/api/conversations/{id}` | Get conversation + messages |
| DELETE | `/api/conversations/{id}` | Delete conversation |
| PATCH | `/api/conversations/{id}/title` | Rename conversation |
| POST | `/api/conversations/{id}/messages` | Append a message |

> Swagger UI (`/docs`) and ReDoc (`/redoc`) are only available when `DEBUG=true`.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Docker/VPS value | Local dev value | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen3:4b` | `qwen3:4b` | Model name — must match `ollama list` |
| `OLLAMA_TIMEOUT` | `180` | `120` | Request timeout (seconds) |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` | `["http://localhost:5173"]` | Allowed frontend origins (JSON array) |
| `DEBUG` | `false` | `false` | Enables /docs /redoc /openapi.json |
| `ENVIRONMENT` | `production` | `development` | Used in logs |

---

## Local Development (no Docker)

```bash
# 1. Make sure Ollama is running on your machine
ollama serve   # in a separate terminal, or it may already be running as a service

# 2. Set up Python environment
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\Activate.ps1  # Windows PowerShell

pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env: set OLLAMA_BASE_URL=http://localhost:11434

# 4. Start
uvicorn app.main:app --reload --port 8000

# 5. Test
curl http://localhost:8000/api/health
```

---

## VPS Deployment (Docker)

### Prerequisites on the VPS

- Docker + Docker Compose plugin installed
- Ollama installed and running on the **host** (not in Docker)
- Qwen model already pulled (`ollama list` to verify)
- Ollama listening on all interfaces:
  ```bash
  # Check current binding
  ss -tlnp | grep 11434

  # If only bound to 127.0.0.1, configure Ollama to listen on all interfaces
  # Add to /etc/systemd/system/ollama.service (Environment section):
  Environment="OLLAMA_HOST=0.0.0.0"
  # Then:
  sudo systemctl daemon-reload
  sudo systemctl restart ollama
  ```

### Deploy

```bash
# 1. Clone the repository on your VPS
git clone https://github.com/akshay124-pixel/AiChat.git
cd AiChat

# 2. Configure environment
cp .env.example .env
nano .env
# Set:
#   OLLAMA_BASE_URL=http://host.docker.internal:11434
#   OLLAMA_MODEL=qwen3:0.6b   (or whatever model you have — check: ollama list)
#   CORS_ORIGINS=["https://ai-chat-client-tau.vercel.app"]
#   DEBUG=false

# 3. Build and start
docker compose up -d --build

# 4. Verify it started
docker compose ps
docker compose logs backend

# 5. Test health
curl http://127.0.0.1:8000/api/health
```

Expected healthy response:
```json
{
  "status": "ok",
  "services": {
    "api": "ok",
    "ollama": {
      "status": "ok",
      "base_url": "http://host.docker.internal:11434",
      "version": "...",
      "active_model": "qwen3:4b",
      "available_models": ["qwen3:4b"]
    }
  }
}
```

### Test AI request

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, say one word"}'
```

### Test streaming

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Count to 5"}'
```

You should see SSE events flowing in real time.

---

## Nginx Configuration (on the VPS host)

Nginx handles HTTPS and proxies to the Docker container on `127.0.0.1:8000`.

Minimum working config:

```nginx
server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

    # Regular API routes
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # SSE streaming — buffering MUST be off
    location /api/chat/stream {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        proxy_buffering            off;   # ← REQUIRED for SSE
        proxy_cache                off;
        proxy_http_version         1.1;
        proxy_set_header           Connection '';
        chunked_transfer_encoding  on;
        proxy_read_timeout         300s;
    }
}

server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$host$request_uri;
}
```

Get SSL certificate:
```bash
sudo certbot certonly --nginx -d api.yourdomain.com
```

---

## Vercel Frontend Configuration

In Vercel Dashboard → Project → Settings → Environment Variables:

```
VITE_API_BASE_URL = https://api.yourdomain.com
```

No trailing slash. This is the public URL nginx serves.

---

## Troubleshooting

### `Cannot connect to Ollama at http://host.docker.internal:11434`

1. Verify Ollama is running on the host: `systemctl status ollama`
2. Check Ollama is listening on all interfaces (not just 127.0.0.1):
   ```bash
   ss -tlnp | grep 11434
   # Should show: 0.0.0.0:11434 or :::11434
   ```
3. If it shows only `127.0.0.1:11434`, set `OLLAMA_HOST=0.0.0.0` in Ollama's systemd service and restart.
4. Test from inside the container:
   ```bash
   docker compose exec backend python -c \
     "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version').read())"
   ```

### Model not found (404)

```bash
# Check what models are available on the host
ollama list

# Update OLLAMA_MODEL in .env to match exactly, then restart
docker compose restart backend
```

### CORS errors in the browser

Make sure `CORS_ORIGINS` in `.env` contains your exact Vercel URL with no trailing slash:
```
CORS_ORIGINS=["https://ai-chat-client-tau.vercel.app"]
```
Then restart: `docker compose restart backend`

### Streaming not working through nginx

Add to your nginx location for `/api/chat/stream`:
```nginx
proxy_buffering off;
proxy_http_version 1.1;
proxy_set_header Connection '';
```

---

## Docker Operations

```bash
# Start
docker compose up -d --build

# Stop
docker compose down

# View logs (follow)
docker compose logs -f backend

# Restart after .env change
docker compose restart backend

# Full rebuild (after code change)
docker compose up -d --build

# Check health
docker compose ps
curl http://127.0.0.1:8000/api/health

# Enter container for debugging
docker compose exec backend sh
```

---

## Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with output
pytest -v
```

Tests mock Ollama — they don't require a real Ollama instance.
