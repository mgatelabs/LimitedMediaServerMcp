# MCP Server — Auth Tool Contracts

## Overview

These two tools are called internally by the HttpClient retry logic.  
They are also exposed as MCP tools so the AI can trigger them explicitly if needed.

---

## Tool: `auth_login`

**Purpose:** Authenticate against the media server and store the resulting JWT.

**MCP tool name:** `auth_login`

**Parameters:** none (credentials come from environment variables)

**Backend endpoint:** `POST /api/auth/login`

**Form fields sent:**

| Field | Value |
|---|---|
| `username` | `credentials.username` from `config.json` |
| `password` | `credentials.password` from `config.json` |
| `token` | `credentials.totp_token` from `config.json` (empty string if absent) |
| `pin` | `credentials.pin` from `config.json` (empty string if absent) |

**Expected response:**

```json
{
  "status": "ok",
  "message": "...",
  "token": "<jwt-string>"
}
```

**Behaviour on success:**
1. Decode the JWT payload: `base64(payload)` → JSON
2. Store in `SessionStore`: `token`, `exp`, `username`, `features`, `limits`
3. Return `{"success": true, "username": "<username>", "expires_in": <seconds>}`

**Behaviour on failure:**
- Server returns `status != "ok"` → raise `RuntimeError(message)`
- No `token` in response → raise `RuntimeError("Login response contained no token")`

---

## Tool: `auth_renew`

**Purpose:** Renew an existing valid token before it expires.

**MCP tool name:** `auth_renew`

**Parameters:** none

**Backend endpoint:** `POST /api/auth/renew`

**Headers:** `Authorization: Bearer <current-token>`

**Form fields sent:** (empty form)

**Expected response:** same shape as `auth_login`

**Behaviour:** identical to `auth_login` success/failure handling above.

**When called automatically:** HttpClient calls `auth_renew` (falling back to `auth_login`) when `exp - time.time() < 60`.

---

## Internal: `SessionStore`

```python
@dataclass
class SessionStore:
    token: str = ""
    exp: int = 0
    username: str = ""
    features: int = 0
    limits: dict = field(default_factory=dict)

    def is_valid(self) -> bool:
        return bool(self.token) and (self.exp - time.time()) > 60

    def clear(self) -> None:
        self.token = ""
        self.exp = 0
```

One module-level singleton: `SESSION = SessionStore()`

See `11-session-features.md` for the full feature bitmask reference and the `auth_get_session_info` tool.
