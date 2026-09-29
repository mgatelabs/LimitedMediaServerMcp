# MCP Server — Client Integration Guide

> **Status: placeholder** — full step-by-step instructions to be written.  
> Core constraints and context are recorded here so they are not lost.

---

## Deployment constraint

**The MCP server must run on the same machine as the AI agent.**

This is not optional and remote deployment is explicitly unsupported. The scratch directory (`config.json` → `scratch.path`) is a local filesystem path. Tools like `media_download_file`, `scratch_create_file`, and `media_upload_file` exchange local paths with the agent. If the MCP server and the agent run on different machines those paths are meaningless to the agent and there is no facility to transfer scratch file content over the wire.

---

## Transport options

The MCP server supports two transports — the end user chooses based on their setup:

| Transport | When to use |
|---|---|
| **stdio** | Agent and MCP server run as a single integrated process (most common for local desktop use) |
| **TCP** | Agent and MCP server run as separate processes on the same machine, communicating over a local port |

Both are valid as long as the scratch directory is on shared local storage accessible to both processes.

---

## Primary target: OpenCode

> Full configuration steps to be documented here.

Key things to cover:
- Where to place / reference the MCP server in OpenCode config
- How to specify stdio vs TCP transport
- How to set the working directory so relative paths resolve correctly
- Verifying the connection (smoke-test sequence from `05-implementation-guide.md` Step 10)

---

## Other clients

> To be added as needed.

Likely candidates: Claude Desktop, Cursor, VS Code extensions that support MCP.  
The transport and scratch constraints apply equally to all clients.
