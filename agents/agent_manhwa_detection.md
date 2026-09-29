# Agent: Manhwa Detection

Your goal is to find books that are incorrectly classified as "page" style
when they are actually manhwa — content published as one long vertical strip
broken into tall portrait images, not discrete manga-style pages.

When a manhwa is confirmed, update its style from "page" to "scroll".
Books that look like stripped/stitched manga are flagged for manual repair
but not modified.

If no book IDs are specified, process ALL books in the library.

All tool calls use the lms: prefix (the "lms" MCP server must be connected).

Configuration:
- IMAGES_TO_CHECK = 4 (images fetched from the first chapter per book)

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

Store the cursor_id. You will page through it to find page-style books.

────────────────────────────────────────────────────────────────────────────────
STEP 2 — process books as you page through the cursor
────────────────────────────────────────────────────────────────────────────────

For each page of cursor results (starting with the first page already returned
by search_books, then advancing with cursor_next):

  For each item in items[]:

    If item["style"] != "page": skip — already scroll style, nothing to do.

    Otherwise inspect it (Steps 3–6 below), then continue to the next item.

  Advance:
    lms:cursor_next(cursor_id)
    If done == true: break out of the loop.

When the loop ends:
  lms:cursor_close(cursor_id)

────────────────────────────────────────────────────────────────────────────────
STEP 3 — load the book and collect images from first chapter
────────────────────────────────────────────────────────────────────────────────

  lms:book_select(book_id=item["id"])
  → loads the book, its chapters, and the first chapter's image list

If book_select errors, log "SKIP <name> — book_select failed" and move on.
If chapter_count == 0, log "SKIP <name> — no chapters" and move on.
If image_count == 0, log "SKIP <name> — first chapter has no images" and move on.

Collect up to IMAGES_TO_CHECK (4) images using book_next_image:

  image_contents = []
  image_contents.append( current image from book_select result )  ← index 0 is
                                                                     already loaded

  repeat up to 3 more times:
    lms:book_next_image()
    → [ImageContent, TextContent]  or  { "done": true }
    If done == true: stop collecting.
    If ImageContent returned: add to image_contents.
    If call errors: stop collecting.

If image_contents is empty, log "SKIP <name> — could not fetch images" and move on.

Note: book_next_image crosses chapter boundaries automatically. Since we only
want the first chapter's images, stop collecting as soon as done==true OR
the TextContent shows chapter_index > 0.

────────────────────────────────────────────────────────────────────────────────
STEP 4 — vision classification (single call per book)
────────────────────────────────────────────────────────────────────────────────

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

────────────────────────────────────────────────────────────────────────────────
STEP 5 — act on the classification
────────────────────────────────────────────────────────────────────────────────

If style == "page" OR confidence == "low":
  Log "KEEP <name> (<id>) — classified as page (confidence: <confidence>)"
  Move on. Do not write anything.

If style == "stripped-manga" AND confidence is "high" or "medium":
  Add to flagged_list: { id, name, confidence, reason }
  Log "FLAGGED <name> (<id>) — stripped manga detected, needs repair"
  Do NOT change the style field. Move on.

If style == "manhwa" AND confidence is "high" or "medium":
  Proceed to Step 6.

────────────────────────────────────────────────────────────────────────────────
STEP 6 — update style to scroll
────────────────────────────────────────────────────────────────────────────────

Use book_update on the currently selected book (no need to re-fetch book_id):

  lms:book_update(style="scroll")

If the call errors, log the error and do not retry.

Verify:
  lms:book_get_context()  → confirm style == "scroll"

Log:
  UPDATED <name> (<id>) — style changed to scroll
            confidence: <confidence>
            reason: <reason from vision>

────────────────────────────────────────────────────────────────────────────────
FINAL SUMMARY
────────────────────────────────────────────────────────────────────────────────

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
