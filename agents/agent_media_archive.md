# Agent: Archive Media

Your goal is to migrate every file that is currently on primary storage to
archive/secondary storage, freeing up the primary disk. You crawl the entire
media folder tree using the server-side folder stack tools, and use the file
navigation context to step through each folder's files.

Do not download, inspect, or modify any file content. This is a storage-tier
operation only.

All tool calls use the lms: prefix (the "lms" MCP server must be connected).

────────────────────────────────────────────────────────────────────────────────
STEP 0 — ensure authenticated
────────────────────────────────────────────────────────────────────────────────

Call lms:auth_get_session_info.
If it returns an error field, call lms:auth_login first.
Continue once the session is valid.

────────────────────────────────────────────────────────────────────────────────
STEP 1 — initialise the folder stack
────────────────────────────────────────────────────────────────────────────────

  lms:folder_stack_create(seed_folder_id="")

Store the returned stack_id.
Log: "Stack created — <depth> root folders queued."

If depth == 0, log "No folders found at root. Nothing to do." and stop.

────────────────────────────────────────────────────────────────────────────────
STEP 2 — process folders until the stack is empty
────────────────────────────────────────────────────────────────────────────────

Loop:

  ### 2a. Pop the next folder

    lms:folder_stack_pop(stack_id)
    → { folder_id, empty, depth }

  If empty == true: crawl is complete. Break out of the loop.

  ### 2b. Push this folder's children onto the stack

    lms:folder_stack_push_children(stack_id, folder_id=folder_id)
    → { pushed, depth }

  Log: "Folder <folder_id> — <pushed> subfolders queued, stack depth <depth>"
  Increment folders_visited.

  ### 2c. Open the folder for file navigation

    lms:files_open(folder_id=folder_id)
    → { folder_name, file_count, index, file }

  If file_count == 0: no files here, return to top of loop.

  Log: "  <folder_name> — <file_count> files"

  ### 2d. Step through every file

  The first file is already current after files_open. Process it, then
  call files_next to advance until done.

  Loop:

    current = lms:files_current()   ← on first iteration this is free (no
                                       network call); file is already loaded

    file = current["file"]
    Increment files_seen.

    If file["archive"] == true:
      Increment already_archived.

    If file["archive"] == false:
      lms:media_migrate_file(file_id=file["id"], force_archive=true)

      If success:
        Log: "    ARCHIVED <filename>"
        Increment archived_count.

      If error:
        Log: "    ERROR <filename> — <error message>"
        Increment error_count.

    Advance:
      lms:files_next()
      → { done, ... } or { index, file, ... }

    If done == true: break out of file loop.
    Otherwise loop back to files_current.

  Return to top of Step 2 loop (next folder).

────────────────────────────────────────────────────────────────────────────────
STEP 3 — close the stack
────────────────────────────────────────────────────────────────────────────────

  lms:folder_stack_close(stack_id)

────────────────────────────────────────────────────────────────────────────────
STEP 4 — final summary
────────────────────────────────────────────────────────────────────────────────

  ── Archive Migration Complete ──────────────────
  Folders visited    : <n>
  Files examined     : <n>
  Already archived   : <n>
  Newly archived     : <n>
  Errors             : <n>
  ────────────────────────────────────────────────

If error_count > 0, list each errored file and its error message after the
summary table.

────────────────────────────────────────────────────────────────────────────────
TRACKING — keep running totals throughout
────────────────────────────────────────────────────────────────────────────────

  folders_visited  : folders popped and entered
  files_seen       : total files examined
  already_archived : files skipped because archive == true
  archived_count   : files successfully migrated this run
  error_count      : files that returned an error on migrate

────────────────────────────────────────────────────────────────────────────────
NOTES
────────────────────────────────────────────────────────────────────────────────

- Root folders contain only subfolders, never files. folder_stack_create seeds
  the stack with root's subfolders automatically — root itself is never popped.

- files_open loads the entire file list for the folder upfront. files_next
  steps through it without additional network calls per file.

- Do not skip inactive folders — inactive files still occupy primary storage.

- Processing is sequential. The MCP server is single-instance.

- If the server restarts mid-crawl both the stack and file context are lost.
  Restart from Step 1. Already-archived files will be skipped on the second
  pass since their archive flag will be true.
