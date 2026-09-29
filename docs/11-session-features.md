# MCP Server — Session Features & Limits

## Overview

After login, the JWT payload contains a `features` integer bitmask and a `limits` object.  
These are decoded from the token's middle segment and stored in `SessionStore` alongside the token itself.

The agent can call `auth_get_session_info` to inspect its own capabilities before attempting operations.

---

## Feature bitmask

`features` is an integer where each bit represents one capability.  
A feature is **enabled** when `(features & FLAG) == FLAG`.

### Management features

| Flag | Value | Meaning |
|---|---|---|
| `MANAGE_APP` | 1 | Full application administration |
| `MANAGE_VOLUME` | 4 | Create, edit, delete volumes (books) |
| `MANAGE_PROCESSES` | 8 | Cancel, stop, restart background tasks |
| `MANAGE_MEDIA` | 16 | Upload, move, delete media files and folders |

### Plugin features

| Flag | Value | Meaning |
|---|---|---|
| `GENERAL_PLUGINS` | 32 | Run general-purpose plugins |
| `UTILITY_PLUGINS` | 64 | Run utility plugins |
| `VOLUME_PLUGINS` | 128 | Run volume/book plugins |
| `MEDIA_PLUGINS` | 512 | Run media file plugins |

### Viewing features

| Flag | Value | Meaning |
|---|---|---|
| `VIEW_PROCESSES` | 1024 | View background task list and logs |
| `VIEW_VOLUME` | 2048 | Browse and read volumes (books, chapters, images) |
| `VIEW_MEDIA` | 16384 | Browse and read media files and folders |

### Extra features

| Flag | Value | Meaning |
|---|---|---|
| `BOOKMARKS` | 32768 | Access bookmark functionality |
| `HARD_SESSIONS` | 65536 | Establish hard (pinned) sessions |

Reserved bits (2, 256, 4096, 8192, 131072–8388608) are placeholders — ignore them.

---

## Limits

The `limits` object is also embedded in the JWT payload alongside `features`:

```json
{
  "volume": 100,
  "media": 500
}
```

| Field | Meaning |
|---|---|
| `volume` | Maximum number of volumes (books) the user may have |
| `media` | Maximum number of media files the user may have |

A value of `0` typically means no limit (server-defined behaviour — treat with care).

---

## SessionStore update

`SessionStore` must store `features` and `limits` in addition to `token`, `username`, and `exp`.  
These are decoded from the JWT payload on every login or renew, just like `exp`.

```python
@dataclass
class SessionStore:
    token: str = ""
    username: str = ""
    exp: int = 0
    features: int = 0
    limits: dict = field(default_factory=lambda: {"volume": 0, "media": 0})

    def has_feature(self, flag: int) -> bool:
        return (self.features & flag) == flag

    def is_valid(self) -> bool:
        if not self.token or not self.username or not self.exp:
            return False
        return self.exp > (time.time() + 60)
```

`has_feature` is a convenience method — the agent can also read `features` directly.

---

## Tool: `auth_get_session_info`

**Purpose:** Return the current session's decoded capabilities and limits without making a network call.

**MCP tool name:** `auth_get_session_info`

**Parameters:** none

**Implementation:** reads directly from the in-memory `SESSION` singleton — no HTTP call needed.

**Returns:**
```json
{
  "username": "alice",
  "exp": 1700000000,
  "seconds_remaining": 3540,
  "features": 2692,
  "limits": { "volume": 100, "media": 500 },
  "flags": {
    "MANAGE_APP": false,
    "MANAGE_VOLUME": true,
    "MANAGE_PROCESSES": false,
    "MANAGE_MEDIA": false,
    "GENERAL_PLUGINS": false,
    "UTILITY_PLUGINS": false,
    "VOLUME_PLUGINS": true,
    "MEDIA_PLUGINS": false,
    "VIEW_PROCESSES": true,
    "VIEW_VOLUME": true,
    "VIEW_MEDIA": false,
    "BOOKMARKS": false,
    "HARD_SESSIONS": false
  }
}
```

`flags` is a pre-expanded convenience map — the agent can read it directly rather than computing bitwise operations.  
`seconds_remaining` is derived from `exp - now()`; negative means the session has expired.

**Error:** if not logged in (token empty or expired), returns an error message — agent should call `auth_login` first.

---

## Agent guidance

- Call `auth_get_session_info` at the start of a session to understand what operations are permitted.
- Before calling a tool, check the relevant flag:
  - Volume read operations → `VIEW_VOLUME`
  - Volume write operations → `MANAGE_VOLUME`
  - Media read operations → `VIEW_MEDIA`
  - Media write operations → `MANAGE_MEDIA`
  - Plugin execution → relevant plugin flag (`VOLUME_PLUGINS`, `MEDIA_PLUGINS`, `UTILITY_PLUGINS`, `GENERAL_PLUGINS`)
  - Process viewing → `VIEW_PROCESSES`
  - Process management (cancel/stop/restart) → `MANAGE_PROCESSES`
- If a flag is not set, inform the user rather than attempting the call — the server will reject it.
- `limits` indicate storage quotas, not current usage. The agent cannot directly query current usage from this endpoint.

---

## Flag bitmask reference

Quick reference for the implementing AI:

```python
class Feature:
    MANAGE_APP        = 1
    MANAGE_VOLUME     = 4
    MANAGE_PROCESSES  = 8
    MANAGE_MEDIA      = 16
    GENERAL_PLUGINS   = 32
    UTILITY_PLUGINS   = 64
    VOLUME_PLUGINS    = 128
    MEDIA_PLUGINS     = 512
    VIEW_PROCESSES    = 1024
    VIEW_VOLUME       = 2048
    VIEW_MEDIA        = 16384
    BOOKMARKS         = 32768
    HARD_SESSIONS     = 65536
```

All named flags from `FeatureFlagsService` that carry functional meaning are listed above.  
Reserved values (2, 256, 4096, 8192, 131072–8388608) are omitted intentionally.
