# Agent: Tag Characters

Your goal is to identify named characters in the first few chapters of every
book in the library and save their names as tags.

If specific book IDs are provided when this agent is invoked, process only
those books. Otherwise process ALL books in the library.

All tool calls use the lms: prefix (the "lms" MCP server must be connected).

The search cursor is item-level: search_books returns the current item
envelope, cursor_next/cursor_prev step one item at a time, and a new search
replaces any previous one. The chapter and image cursors work the same way
over the current book's chapters and the current chapter's files — they are
opened by volume_list_chapters / volume_list_images and stepped with
chapter_next/chapter_prev and image_next/image_prev. There is no cursor_id
to track at any level.

Configuration:
- IMAGES_PER_CHAPTER = 6   (max images taken from each chapter)
- CHAPTERS_TO_SCAN   = 4   (stop collecting after 4 chapters)
- Total images per book: up to 24 (4 chapters × 6 images)

────────────────────────────────────────────────────────────────────────
STEP 0 — ensure authenticated
────────────────────────────────────────────────────────────────────────

Call lms:auth_get_session_info.
If it returns an error field, call lms:auth_login first.
Continue once the session is valid.

────────────────────────────────────────────────────────────────────────
STEP 1 — start the search over all books
────────────────────────────────────────────────────────────────────────

  lms:search_books()   ← no filters; returns the first item

The envelope has the shape:

  { cursor_id, type: "v", index, content, total }

content is the current book (id, name, tags, style, …). You do not need
the cursor_id — cursor_next/cursor_prev operate on the active search.

────────────────────────────────────────────────────────────────────────
STEP 2 — step through every book
────────────────────────────────────────────────────────────────────────

For the current item, then each subsequent item:

  Check content["tags"] — if any tag starts with "MC:", this book is already
  processed. Log "SKIP <name> (<id>) — already tagged (MC: present)" and
  advance to the next item.

  Otherwise inspect it (Steps 3–7 below), then advance.

Advance:

  lms:cursor_next()

  - Normal step: returns the next item envelope. Loop back.
  - { status: "exhausted", offset, total }: the fetched items are done.
    If offset < total, re-issue the SAME search with that offset
    (lms:search_books(offset=<offset>) — it replaces the cursor and
    returns the next item); otherwise the library is fully processed.

When the loop ends:
  lms:cursor_close()

────────────────────────────────────────────────────────────────────────
STEP 3 — collect images across the first chapters
────────────────────────────────────────────────────────────────────────

  lms:volume_list_chapters()   ← book_id omitted: uses the book the
                                   cursor is pointing at
  → { "chapters": [ {name, value}, … ] }   (value = chapter_id)

If this errors, log "SKIP <name> — volume_list_chapters failed" and move on.
If chapters is empty, log "SKIP <name> — no chapters" and move on.

Take up to CHAPTERS_TO_SCAN (4) chapters: chapters[0..3].

volume_list_chapters points the chapter cursor at chapters[0]. For each
chapter — starting from the one the chapter cursor points at; stop once
24 images are collected or the cursor returns a status sentinel:

  lms:volume_list_images()   ← chapter_id/book_id omitted: applies to the
                               chapter the chapter cursor points at
  → { "files": ["001.jpg", …] }
  This points the image cursor at files[0].

  For the first 6 files (skip a chapter that has none):

    lms:volume_get_image()   ← chapter_id/filename/book_id omitted: applies
                               to the image the image cursor points at
    → [ImageContent, TextContent]
    Add the ImageContent to image_contents.
    If the call errors: skip this file and continue.

    lms:image_next()   ← advance to the next file; if a status sentinel is
                         returned, the chapter has fewer than 6 files —
                         stop fetching for this chapter.

  lms:chapter_next()   ← advance to the next chapter; if a status sentinel
                         is returned, the book has fewer than 4 chapters.

Track: chapters_scanned (chapters entered) and images collected.

If image_contents is empty after collection:
  Log "SKIP <name> — could not fetch any images" and move on.

────────────────────────────────────────────────────────────────────────
STEP 4 — vision pass (single call over all images)
────────────────────────────────────────────────────────────────────────

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

────────────────────────────────────────────────────────────────────────
STEP 5 — normalise and prefix character names
────────────────────────────────────────────────────────────────────────

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

────────────────────────────────────────────────────────────────────────
STEP 6 — merge with existing tags (additive only)
────────────────────────────────────────────────────────────────────────

existing_tags = content["tags"] from the current item (already in memory)
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

────────────────────────────────────────────────────────────────────────
STEP 7 — write tags and verify
────────────────────────────────────────────────────────────────────────

  lms:volume_update_tags(tags=merged_tags)   ← book_id omitted: applies to
                                                the book the cursor points at

If this errors, log the error and do not retry.

Verify:
  lms:volume_get_tags()   ← book_id omitted: applies to the book the
                             cursor points at
  → confirm the returned list contains the new names.

Log:
  TAGGED <name> (<id>)
    Chapters scanned : <chapters_scanned>
    Images collected : <count>
    MC : <comma-separated MC: names, or "none">
    PC : <comma-separated PC: names, or "none">
    AN : <comma-separated AN: names, or "none">
    Added : <comma-separated new prefixed tags>

────────────────────────────────────────────────────────────────────────
FINAL SUMMARY
────────────────────────────────────────────────────────────────────────

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
