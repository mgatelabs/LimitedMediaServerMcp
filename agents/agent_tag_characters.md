# Agent: Tag Characters

Your goal is to identify named characters in the first few chapters of every
book in the library and save their names as tags.

If specific book IDs are provided when this agent is invoked, process only
those books. Otherwise process ALL books in the library.

Configuration:
- IMAGES_TO_COLLECT = 24  (max total images per book — 4 chapters × 6 images)
- CHAPTERS_TO_SCAN  = 4   (stop collecting once 4 chapter boundaries are crossed)

All tool calls use the lms: prefix (the "lms" MCP server must be connected).

────────────────────────────────────────────────────────────────────────────────
STEP 0 — ensure authenticated
────────────────────────────────────────────────────────────────────────────────

Call lms:auth_get_session_info.
If it returns an error field, call lms:auth_login first.
Continue once the session is valid.

────────────────────────────────────────────────────────────────────────────────
STEP 1 — open a cursor over all books
────────────────────────────────────────────────────────────────────────────────

  lms:search_books()   ← no filters; returns first page + cursor_id

Store the cursor_id. You will page through it to process every book.

────────────────────────────────────────────────────────────────────────────────
STEP 2 — process books as you page through the cursor
────────────────────────────────────────────────────────────────────────────────

For each page of cursor results (starting with the first page already returned
by search_books, then advancing with cursor_next):

  For each item in items[]:

    Check item["tags"] — if any tag starts with "MC:", this book is already
    processed. Log "SKIP <name> (<id>) — already tagged (MC: present)" and
    continue to the next item.

    Otherwise inspect it (Steps 3–7 below), then continue to the next item.

  Advance:
    lms:cursor_next(cursor_id)
    If done == true: break out of the loop.

When the loop ends:
  lms:cursor_close(cursor_id)

────────────────────────────────────────────────────────────────────────────────
STEP 3 — load the book and begin collecting images
────────────────────────────────────────────────────────────────────────────────

  lms:book_select(book_id=item["id"])
  → loads the book, its chapters, and the first chapter's image list

If book_select errors, log "SKIP <name> — book_select failed" and move on.
If chapter_count == 0, log "SKIP <name> — no chapters" and move on.
If image_count == 0, log "SKIP <name> — first chapter has no images" and move on.

Collect up to IMAGES_TO_COLLECT (24) images across up to CHAPTERS_TO_SCAN (4)
chapters using book_next_image:

  image_contents  = []
  chapters_seen   = { 0 }   ← chapter index 0 is already loaded
  chapters_done   = 1       ← counter of distinct chapter indices seen

  image_contents.append( current image from book_select result )  ← index 0

  repeat until image_contents has 24 items OR chapters_done >= 4:
    lms:book_next_image()
    → [ImageContent, TextContent]  or  { "done": true }

    If done == true: stop collecting.
    If call errors: stop collecting.

    Read chapter_index from the TextContent payload.
    If chapter_index not in chapters_seen:
      chapters_seen.add(chapter_index)
      chapters_done += 1
      If chapters_done > CHAPTERS_TO_SCAN: stop collecting.

    Add ImageContent to image_contents.

If image_contents is empty after collection:
  Log "SKIP <name> — could not fetch any images" and move on.

────────────────────────────────────────────────────────────────────────────────
STEP 4 — vision pass (single call over all images)
────────────────────────────────────────────────────────────────────────────────

Send all collected ImageContent blocks in a single vision turn with this prompt:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ You are a character extraction assistant for a digital book library.    │
  │                                                                         │
  │ Examine the provided images (pages from the first few chapters of a     │
  │ book). Identify all NAMED characters and classify each one by role.     │
  │                                                                         │
  │ Character roles:                                                        │
  │   MC  — Main character. The protagonist the story follows. There is     │
  │          usually only one, occasionally two.                            │
  │   PC  — Party/companion character. A named ally, friend, or recurring   │
  │          companion who supports the MC.                                 │
  │   AN  — Antagonist/enemy. A named villain, rival, or opposing force.   │
  │                                                                         │
  │ Rules:                                                                  │
  │ - Only include characters who are explicitly named in dialogue,         │
  │   narration, or a title card. Do not guess or infer names.             │
  │ - Return each name exactly as it appears (preserve capitalisation).     │
  │ - If a character has multiple names used interchangeably, return only   │
  │   the most frequently used form seen in these pages.                    │
  │ - Do not include place names, organisation names, or honorific titles   │
  │   used alone (e.g. "King", "Doctor", "Sensei").                        │
  │ - If a named character's role is unclear from these pages alone,        │
  │   classify them as PC rather than guess.                                │
  │ - If no named characters can be identified, return empty lists.         │
  │                                                                         │
  │ Return a JSON object and NOTHING else:                                  │
  │ {                                                                       │
  │   "mc": ["Name"],                                                       │
  │   "pc": ["Name One", "Name Two", ...],                                  │
  │   "an": ["Name One", ...]                                               │
  │ }                                                                       │
  └─────────────────────────────────────────────────────────────────────────┘

Parse the JSON response. If parsing fails, retry once adding:
"Return only valid JSON, no other text."
If it fails again, log "SKIP <name> — vision parse failure" and move on.

If all three lists are empty after a successful parse:
  Log "SKIP <name> — no characters identified" and move on.

────────────────────────────────────────────────────────────────────────────────
STEP 5 — normalise and prefix character names
────────────────────────────────────────────────────────────────────────────────

For each role bucket and its prefix:
  mc  → prefix "MC:"
  pc  → prefix "PC:"
  an  → prefix "AN:"

For each name in each bucket:
  1. Trim whitespace.
  2. Preserve original capitalisation (do NOT lowercase — names are proper nouns).
  3. Replace runs of internal whitespace with a single space.
  4. Discard names that are empty or longer than 60 characters after normalisation.
  5. Prepend the role prefix: e.g. "MC:Luffy", "PC:Zoro", "AN:Arlong"

Collect all prefixed names into a single flat list: tagged_names[]

────────────────────────────────────────────────────────────────────────────────
STEP 6 — merge with existing tags (additive only)
────────────────────────────────────────────────────────────────────────────────

existing_tags = item["tags"] from the cursor page (already in memory)
new_names     = tagged_names NOT already in existing_tags
                (match on the full prefixed string, e.g. "MC:Luffy")
merged_tags   = existing_tags + new_names

If new_names is empty:
  Log "SKIP <name> — no new characters (all already tagged or none found)"
  and move on.

Do NOT remove any existing tags. This pass is additive only.

Note: if a character was previously tagged without a prefix (e.g. "luffy") and
is now found as "MC:Luffy", both will exist in the tag list. Do not attempt to
deduplicate or remove the old unprefixed tag — leave that for manual cleanup.

────────────────────────────────────────────────────────────────────────────────
STEP 7 — write tags and verify
────────────────────────────────────────────────────────────────────────────────

Use book_update on the currently selected book (no need to re-fetch book_id):

  lms:book_update(tags=merged_tags)

If this errors, log the error and do not retry.

Verify:
  lms:book_get_context()  → confirm saved tags contain the new names.

Log:
  TAGGED <name> (<id>)
    Chapters scanned : <chapters_done>
    Images collected : <count>
    MC : <comma-separated MC: names, or "none">
    PC : <comma-separated PC: names, or "none">
    AN : <comma-separated AN: names, or "none">
    Added : <comma-separated new prefixed tags>

────────────────────────────────────────────────────────────────────────────────
FINAL SUMMARY
────────────────────────────────────────────────────────────────────────────────

  Books processed  : <n>
  Tagged           : <n>
  Skipped          : <n>
  Tags written     : <total count of new tags saved across all books>

  Tagged books:
    - <name> (<id>)  MC:<…>  PC:<…>  AN:<…>
    - ...

  Skipped books:
    - <name> (<id>) — <reason>
    - ...
