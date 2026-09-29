# MCP Server — Architecture

## High-level component diagram

```
┌─────────────────────────────────────────────────┐
│  Local AI Agent (Claude / any MCP client)        │
│                                                  │
│  calls MCP tools via stdio JSON-RPC              │
└──────────────────────┬──────────────────────────┘
                       │ stdio (MCP protocol)
┌──────────────────────▼──────────────────────────┐
│  mcp_server.py  (entry point)                    │
│  ┌─────────────────────────────────────────────┐ │
│  │  ToolRouter                                  │ │
│  │  routes tool calls → handler functions       │ │
│  └───────┬─────────────────────────────────────┘ │
│          │                                        │
│  ┌───────▼──────────┐  ┌────────────────────────┐│
│  │  AuthClient       │  │  SessionStore           ││
│  │  login / renew    │  │  token, exp, username   ││
│  └───────┬──────────┘  └────────────────────────┘│
│          │                                        │
│  ┌───────▼──────────┐                            │
│  │  HttpClient       │                            │
│  │  shared requests  │                            │
│  │  auto-retry on    │                            │
│  │  401 / expired    │                            │
│  └───────┬──────────┘                            │
└──────────┼──────────────────────────────────────┘
           │ HTTP (multipart/form-data)
┌──────────▼──────────────────────────────────────┐
│  Local Python Media Server                        │
│  /api/auth/*   /api/media/*   /api/volume/*       │
└─────────────────────────────────────────────────┘
```

## Module layout

```
mcp_media_server/
├── mcp_server.py          # entry point — registers all tools, starts stdio loop
├── session.py             # SessionStore dataclass + JWT decode helpers
├── http_client.py         # HttpClient — shared requests.Session, auth-retry wrapper
├── auth_client.py         # login(), renew() calling /api/auth/*
├── media_client.py        # all /api/media/* calls
├── volume_client.py       # all /api/volume/* calls
├── config.py              # SERVER_URL, credential env-var loading
└── requirements.txt       # mcp, requests
```

## Configuration

The server reads these values from **environment variables** (or a `.env` file):

| Variable | Purpose |
|---|---|
| `MEDIA_SERVER_URL` | Base URL, e.g. `http://localhost:8000` |
| `MEDIA_USERNAME` | Login username |
| `MEDIA_PASSWORD` | Login password |
| `MEDIA_PIN` | Login pin (pass `""` if unused) |
| `MEDIA_TOTP_TOKEN` | TOTP token string (pass `""` if unused) |

## Authentication lifecycle

```
tool call arrives
      │
      ▼
is token present AND not expired?
      │ yes                │ no / expired
      │                    ▼
      │            call login()
      │            store token + exp
      ▼
attach  Authorization: Bearer <token>  header
      │
      ▼
send HTTP request
      │
  HTTP 401?
      │ yes                │ no
      ▼                    ▼
call login()          return result
retry once
```

### Token expiry check

Decode the JWT payload (base64 middle segment, no verification needed — the server verifies).  
Compare `exp` (Unix seconds) to `time.time()`.  
Treat as expired if `exp - time.time() < 60` (60-second safety margin).

## Error strategy

- Non-2xx HTTP responses → raise `RuntimeError(f"HTTP {status}: {body_text}")` 
- Server returns `{"status": "error", "message": "..."}` → raise `RuntimeError(message)`
- Tool handlers catch exceptions and return them as MCP error responses so the AI can read the reason
- Single retry on 401 only; all other errors propagate immediately

## Data transport

All write/list calls use `multipart/form-data` POST, matching the existing backend.  
File downloads use `GET` with `?file_id=` query param or a direct content URL.  
Image retrieval returns **base64-encoded bytes** inside the MCP tool result so the AI can inspect or save them.
