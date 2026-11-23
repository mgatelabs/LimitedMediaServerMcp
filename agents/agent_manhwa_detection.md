# Agent: Manhwa Detection

Your goal is to find books that are incorrectly classified as "page" style
when they are actually manhwa — content published as one long vertical strip
broken into tall portrait images, not discrete manga-style pages.

When a manhwa is confirmed, update its style from "page" to "scroll".
Books that look like stripped/stitched manga are flagged for manual repair
but not modified.

If no book IDs are specified, process ALL books in the library.

All tool calls use the lms: prefix (the "lms" MCP server must be connected).

The search cursor is item-level: search_books returns the current item
envelope, cursor_next/cursor_prev step one item at a time, and a new search
replaces any previous one. The chapter and image cursors work the same way
over the current book's chapters and the current chapter's files — they are
opened by volume_list_chapters / volume_list_images and stepped with
chapter_next/chapter_prev and image_next/image_prev. There is no cursor_id
to track at any level.

Configuration:
- IMAGES_TO_CHECK = 4 (images fetched from the first chapter per book)

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

content is the current book (id, name, style, tags, …). You do not need
the cursor_id — cursor_next/cursor_prev operate on the active search.

────────────────────────────────────────────────────────────────────────
STEP 2 — step through every book
────────────────────────────────────────────────────────────────────────

For the current item, then each subsequent item:

  If content["style"] != "page": skip — already scroll style, nothing to do.

  Otherwise inspect it (Steps 3–6 below), then advance.

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
STEP 3 — collect images from the first chapter
────────────────────────────────────────────────────────────────────────

  lms:volume_list_chapters()   ← book_id omitted: uses the book the
                                   cursor is pointing at
  → { "chapters": [ {name, value}, … ] }   (value = chapter_id)

If this errors, log "SKIP <name> — volume_list_chapters failed" and move on.
If chapters is empty, log "SKIP <name> — no chapters" and move on.

volume_list_chapters points the chapter cursor at chapters[0], so the image
cursor opens on the first chapter too:

  lms:volume_list_images()   ← chapter_id and book_id omitted: defaults to
                               the chapter cursor's current chapter (chapter 1)
  → { "files": ["001.jpg", …] }

If this errors, log "SKIP <name> — volume_list_images failed" and move on.
If files is empty, log "SKIP <name> — first chapter has no images" and move on.

volume_list_images points the image cursor at files[0]. Fetch up to
IMAGES_TO_CHECK (4) images by leaving chapter_id/filename/book_id omitted —
every call applies to the image cursor's current file — stepping with
image_next between fetches:

  image_contents = []
  lms:volume_get_image()
  → [ImageContent, TextContent]
  Add the ImageContent to image_contents. If the call errors: stop collecting.
  Repeat up to 4 times, calling lms:image_next() between fetches. If
  image_next returns a status sentinel (the chapter has fewer than 4
  files), stop collecting.

If image_contents is empty, log "SKIP <name> — could not fetch images" and move on.

────────────────────────────────────────────────────────────────────────
STEP 4 — vision classification (single call per book)
────────────────────────────────────────────────────────────────────────

Send all collected ImageContent blocks in a single vision turn with this prompt:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ You are classifying comic/manga images to determine their layout style. │
  │                                                                         │
  │ Examine the provided images and determine whether they are:             │
  │                                                                         │
  │ MANHWA — tall vertical strip images designed to be scrolled             │
  │   continuously. Indicators:                                             │
  │   • Image height is significantly greater than width (portrait ratio    │
  │     roughly 2:1 or taller)                                              │
  │   • Panels flow top-to-bottom in a single column with no horizontal     │
  │     breaks between panels                                               │
  │   • The strip reads as one continuous vertical narrative                │
  │   • Typically full-colour throughout                                    │
  │   • Common origins: Korean webtoon / manhwa                            │
  │                                                                         │
  │ STRIPPED-MANGA — standard manga pages that have been stitched together  │
  │   into a tall vertical strip, but the content is still manga, not       │
  │   manhwa. This is a modified/repackaged file that needs repair.         │
  │   Indicators (ALL of the following must be present):                    │
  │   • Image is tall and vertical (portrait ratio roughly 2:1 or taller)  │
  │   • Content is predominantly black and white — manga-style lineart      │
  │   • Colour appears only in isolated spots: a logo, title card,          │
  │     watermark, or small decorative element. The overwhelming majority   │
  │     of the image area is greyscale/black-and-white.                     │
  │   • You can see panel borders or gutters typical of manga page layout   │
  │     (horizontal cuts where pages were joined)                           │
  │                                                                         │
  │ PAGE — discrete comic/manga pages read individually                     │
  │   • Each image is a self-contained page                                 │
  │   • Aspect ratio is roughly square or landscape (width ≥ 60% of height) │
  │   • Panels may be arranged in a 2D grid, not purely a single column     │
  │   • Typical manga or comic book format                                  │
  │                                                                         │
  │ IMPORTANT DISTINCTION — MANHWA vs STRIPPED-MANGA:                      │
  │   Full-colour vertical strip → MANHWA                                   │
  │   Black-and-white vertical strip (colour only in logos/watermarks)      │
  │     → STRIPPED-MANGA                                                    │
  │                                                                         │
  │ Look at ALL provided images before deciding. The classification should  │
  │ be consistent across them.                                              │
  │                                                                         │
  │ Return a JSON object and NOTHING else:                                  │
  │ {                                                                       │
  │   "style": "manhwa" | "stripped-manga" | "page",                        │
  │   "confidence": "high" | "medium" | "low",                             │
  │   "reason": "<one short sentence>"                                      │
  │ }                                                                       │
  └─────────────────────────────────────────────────────────────────────────┘

Parse the JSON response. If parsing fails, retry once adding:
"Return only valid JSON, no other text."
If it fails again, log "SKIP <name> — vision parse failure" and move on.

────────────────────────────────────────────────────────────────────────
STEP 5 — act on the classification
────────────────────────────────────────────────────────────────────────

If style == "page" OR confidence == "low":
  Log "KEEP <name> (<id>) — classified as page (confidence: <confidence>)"
  Move on. Do not write anything.

If style == "stripped-manga" AND confidence is "high" or "medium":
  Add to flagged_list: { id, name, confidence, reason }
  Log "FLAGGED <name> (<id>) — stripped manga detected, needs repair"
  Do NOT change the style field. Move on.

If style == "manhwa" AND confidence is "high" or "medium":
  Proceed to Step 6.

────────────────────────────────────────────────────────────────────────
STEP 6 — update style to scroll
────────────────────────────────────────────────────────────────────────

  lms:volume_update_style(style="scroll")   ← book_id omitted: applies to
                                               the book the cursor points at

If the call errors, log the error and do not retry.

Verify:
  lms:volume_get_style()   ← book_id omitted: applies to the book the
                              cursor points at
  → confirm it returns "scroll"

Log:
  UPDATED <name> (<id>) — style changed to scroll
            confidence: <confidence>
            reason: <reason from vision>

────────────────────────────────────────────────────────────────────────
FINAL SUMMARY
────────────────────────────────────────────────────────────────────────

  Page-style books inspected : <n>
  Updated to scroll          : <n>
  Flagged (stripped manga)   : <n>
  Kept as page               : <n>
  Skipped (errors/no images) : <n>

  Updated books:
    - <name> (<id>)
    - ...

  Flagged books (stripped manga — needs repair):
    - <name> (<id>)  [confidence: <confidence>]  <reason>
    - ...

If no books were flagged, omit the Flagged books section.
