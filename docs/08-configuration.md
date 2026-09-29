# MCP Server — Configuration Reference

## File location

```
mcp_media_server/
└── config.json        ← edit this file before running the server
```

`config.json` is read once at startup.  Restart the MCP server after any change.

---

## Full schema

```json
{
  "server": {
    "host": "192.168.1.100",
    "port": 8000,
    "https": false,
    "ssl_verify": true
  },
  "auth": {
    "username": "myuser",
    "password": "mypassword",
    "pin": "",
    "totp_token": ""
  },
  "scratch": {
    "path": "/tmp/mcp_scratch",
    "max_age_days": 7
  }
}
```

---

## Field reference

### `server`

| Field | Type | Required | Description |
|---|---|---|---|
| `host` | string | yes | Hostname or IP address of the media server |
| `port` | integer | yes | Port number |
| `https` | boolean | yes | `true` to use HTTPS, `false` for HTTP |
| `ssl_verify` | boolean | no | `true` (default) to verify the SSL certificate. Set `false` for self-signed certificates |

`ssl_verify` is ignored when `https` is `false`.

**Constructed base URL:** `{scheme}://{host}:{port}`  
Examples:
- `http://localhost:8000`
- `https://192.168.1.50:8443`
- `https://mediaserver.local:443`

### `auth`

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | yes | Login username |
| `password` | string | yes | Login password |
| `pin` | string | no | PIN if the server requires one. Leave `""` if unused |
| `totp_token` | string | no | TOTP/2FA token string if required. Leave `""` if unused |

### `scratch`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Absolute path to a local directory used for downloaded files |
| `max_age_days` | integer | no | `7` | Files older than this are deleted from scratch on MCP server startup |

The scratch directory is created automatically on startup if it does not exist.  
Downloaded files are named `<file_id>.<ext>` — the file's server UUID plus the extension derived from its MIME type. If a file with that name already exists in scratch, the download is skipped and the existing path is returned.

---

## Example configurations

### Local HTTP server (development)

```json
{
  "server": {
    "host": "localhost",
    "port": 8000,
    "https": false,
    "ssl_verify": true
  },
  "auth": {
    "username": "admin",
    "password": "secret",
    "pin": "",
    "totp_token": ""
  },
  "scratch": {
    "path": "/tmp/mcp_scratch",
    "max_age_days": 7
  }
}
```

### LAN server with self-signed HTTPS certificate

```json
{
  "server": {
    "host": "192.168.1.100",
    "port": 8443,
    "https": true,
    "ssl_verify": false
  },
  "auth": {
    "username": "admin",
    "password": "secret",
    "pin": "",
    "totp_token": ""
  },
  "scratch": {
    "path": "C:/Users/me/mcp_scratch",
    "max_age_days": 3
  }
}
```

---

## Security notes

- **Do not commit `config.json` to version control.** Add it to `.gitignore`.
- `ssl_verify: false` suppresses certificate warnings but does not encrypt traffic any less — HTTPS is still used. It only skips certificate chain validation, which is acceptable for a trusted local network with a self-signed cert.
- If `ssl_verify: false` is set, the `requests` library will emit `InsecureRequestWarning` messages to stderr. The MCP server suppresses these automatically using `urllib3.disable_warnings()`.
