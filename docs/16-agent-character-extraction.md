# Agent Script — Character Extraction and Tagging

## Purpose

Given one or more book IDs, this agent script:
1. Opens each book and reads the first 4 chapters via vision.
2. Extracts key character names from the images.
3. Merges the discovered character names into the book's existing tags.

> **Note on tag conventions:** The general vision workflow in `06-vision-workflow.md`
> explicitly excludes character names from tags. This script is a deliberate exception
> to that rule. Character names are stored as tags here because there is no dedicated
> character field in the current data model. Use this script only when character
> tagging is explicitly desired — do not apply it as part of a general metadata pass.

---

## Prerequisites

- Session must be authenticated. Call `auth_login` if `auth_get_session_info` returns
  an error or shows an expired session.
- The model running this script must support vision (image input).
- The books must be accessible under the current user's `SESSION.limits.volume`.
  If a book is missing from results or returns an access error, skip it —
  it is hidden by the rating limit.

---

## Input

A list of one or more book IDs, supplied by the user or calling context.

```
book_ids: ["abc123", "def456", ...]
```

Process each book sequentially — the MCP server is single-instance.

---

## Step-by-step script

### Phase 1 — for each book_id

#### Step 1. Fetch book details

```
volume_get_book(book_id)
```

Store the full book definition. You will need the existing `tags` list in Step 6.
If this call returns an error, skip the book and log the reason.

#### Step 2. Fetch chapter list

```
volume_list_chapters(book_id)
→ chapters[]   ← list of {name, value} objects
```

This call also points the **chapter cursor** at `chapters[0]` (single-active
list cursor — see `07-pagination-tools.md`), so `chapter_id` can be omitted
from the image calls below and `chapter_next` can step through the book.

Take only the first 4 chapters: `chapters[0..3]`.
If the book has fewer than 4 chapters, use all of them.
If `chapters` is empty, skip the book.

---

### Phase 2 — vision pass over chapters 1–4

For each chapter — the chapter cursor starts at `chapters[0]`; step with
`chapter_next` and stop at 4 chapters or the `exhausted` sentinel:

#### Step 3. List images in the chapter

```
volume_list_images()   ← chapter_id/book_id omitted: applies to the chapter
                         the chapter cursor points at
→ files[]   ← list of image filenames
```

This call also points the **image cursor** at `files[0]`.

#### Step 4. Fetch images for vision

Fetch up to **6 images** from each chapter — the first 6 in `files[]`.
6 per chapter × 4 chapters = up to 24 images total.

Fewer is fine if a chapter has fewer than 6 images.

```
volume_get_image()   ← chapter_id/filename/book_id omitted: applies to the
                       image the image cursor points at
→ [ImageContent, TextContent]
keep the ImageContent for the vision call below
skip this image and continue if the call returns an error

image_next()   ← step to the next file; stop fetching for this chapter
                 when a status sentinel is returned (fewer than 6 files)
```

Collect all `ImageContent` blocks from across all 4 chapters into a single list.

#### Step 5. Vision call — extract character names

Send all collected `ImageContent` blocks to the vision model in a single call
with this prompt:

```
You are a character extraction assistant for a digital book library.

Examine the provided images (pages from the first few chapters of a book).
Identify all **named characters** that appear or are referred to.

Rules:
- Only include characters who are named — either shown in dialogue, narration,
  or a title card. Do not invent names or guess.
- Include both main and secondary characters if they are clearly named.
- Return each character name exactly as it appears in the images
  (preserve original capitalisation and spelling).
- If a character has multiple names (e.g. a given name and a family name used
  interchangeably), include only the most common form seen in these pages.
- If no named characters can be identified, return an empty list.
- Do not include place names, organisation names, or titles (e.g. "King", "Doctor").

Return a JSON object:
{
  "characters": ["Name One", "Name Two", ...]
}

Return only the JSON object. No commentary.
```

If the vision model returns malformed JSON, retry once with the instruction
"Return only valid JSON, no other text." If it fails again, skip this book.

---

### Phase 3 — merge and write tags

#### Step 6. Normalise character names

For each name in `characters[]`:
- Trim leading/trailing whitespace.
- Convert to lowercase.
- Replace spaces with hyphens (e.g. `"Luffy"` → `"luffy"`, `"Monkey D. Luffy"` → `"monkey-d.-luffy"`).
- Drop any name that is empty after normalisation.
- Drop any name longer than 40 characters — likely a misread line of dialogue.

#### Step 7. Merge with existing tags

Fetch the current tag list from the book definition stored in Step 1:
`existing_tags = book["tags"]`  (list of strings)

Build the merged list:
```
new_tags = existing_tags + [name for name in normalised_names
                             if name not in existing_tags]
```

Do not remove any existing tags. Only append names that are not already present.

If `new_tags` is identical to `existing_tags` (nothing new found), skip the write
and log "no new characters found".

#### Step 8. Write tags back

```
volume_update_tags(book_id, tags=new_tags)
```

If this call returns an error, log it and do not retry.

#### Step 9. Verify

```
volume_get_tags(book_id)
```

Confirm the returned tag list includes the newly added character names.
Log a success summary: book name, how many new character tags were added, the names added.

---

## Error handling

| Situation | Action |
|---|---|
| `volume_get_book` returns error | Skip book, log reason, continue to next |
| `volume_list_chapters` returns empty | Skip book, log "no chapters" |
| `volume_list_images` returns error for a chapter | Skip that chapter, continue with remaining chapters |
| `volume_get_image` returns error for a file | Skip that image, continue with next filename |
| Vision model returns malformed JSON after retry | Skip book, log "vision parse failure" |
| Vision model returns empty `characters` list | Skip write, log "no characters identified" |
| `volume_update_tags` returns error | Log error, do not retry |
| Access error on any call (rating limit) | Skip the entire book — content is not accessible |
| All 4 chapters yield zero readable images | Skip book, log "could not fetch any images" |

---

## Per-book output summary

After processing each book, output:

```
Book: <name> (<book_id>)
  Chapters scanned: <n> of 4
  Images fetched:   <n>
  Characters found: <list of normalised names, or "none">
  Tags added:       <list of new names, or "none — already present / none found">
  Result:           success | skipped (<reason>)
```

---

## Example run (single book)

```
Input: book_ids = ["manga-001"]

Step 1: volume_get_book("manga-001")
        → name="One Piece Vol.1", existing tags=["action","shounen"]

Step 2: volume_list_chapters("manga-001")
        → chapters = [{name:"Ch.1", value:"ch001"}, {name:"Ch.2", value:"ch002"},
                      {name:"Ch.3", value:"ch003"}, {name:"Ch.4", value:"ch004"}]
        → use all 4

Step 3-4 (ch001): volume_list_images → 22 files → fetch files[0..5] → 6 ImageContents
Step 3-4 (ch002): volume_list_images → 19 files → fetch files[0..5] → 6 ImageContents
Step 3-4 (ch003): volume_list_images → 21 files → fetch files[0..5] → 6 ImageContents
Step 3-4 (ch004): volume_list_images → 18 files → fetch files[0..5] → 6 ImageContents
Total: 24 ImageContent blocks

Step 5: vision call → {"characters": ["Luffy", "Zoro", "Nami", "Shanks"]}

Step 6: normalise → ["luffy", "zoro", "nami", "shanks"]

Step 7: existing = ["action", "shounen"]
        new_tags = ["action", "shounen", "luffy", "zoro", "nami", "shanks"]

Step 8: volume_update_tags("manga-001", tags=["action","shounen","luffy","zoro","nami","shanks"])

Step 9: volume_get_tags("manga-001") → confirm tags saved

Output:
  Book: One Piece Vol.1 (manga-001)
  Chapters scanned: 4 of 4
  Images fetched:   24
  Characters found: luffy, zoro, nami, shanks
  Tags added:       luffy, zoro, nami, shanks
  Result:           success
```

---

## Limits and caveats

- **Image count:** 6 images × 4 chapters = 24 images maximum per book. This is
  intentionally conservative to stay within vision context limits. Increase the
  per-chapter limit cautiously — large batches may exceed model context.
- **Chapter count:** fixed at 4. The first 4 chapters are chosen because they
  typically introduce the main cast. Increasing this will improve recall for
  large-cast books at the cost of more API calls and more context usage.
- **New tags are never removed:** this script is additive only. Running it twice
  on the same book is safe — duplicate names are filtered in Step 7.
- **No deduplication against existing tags:** if a character named "luffy" is
  already a tag from a prior run, Step 7 skips it.
- **Not a genre/theme pass:** this script does not add genre tags. Run the
  standard vision workflow from `06-vision-workflow.md` separately if genre tags
  are also needed.
