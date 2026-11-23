# MCP Server — Vision Workflow: Extracting Book Metadata from Images

## Purpose

This document describes how a vision-capable AI agent (e.g. Claude Sonnet/Opus) should use the MCP tools to extract metadata from book images and write the results back to the server.  It is intended as guidance for the agent, not for the MCP server implementer.

---

## Why images instead of existing metadata

Books on this server often have minimal metadata — a short title and maybe a few tags.  The full content (characters, genre, themes, art style, setting) is only visible in the pages themselves.  The agent uses vision to read that content and populate the structured fields the server provides.

---

## Writable fields

| MCP tool | Field | What to put here |
|---|---|---|
| `volume_update_title` | `name` | Clean, properly capitalised title if the current one is wrong or romanised |
| `volume_update_alt_name` | `alt_name` | Original-language title, subtitle, or common alternative name |
| `volume_update_tags` | `tags[]` | Genre, themes, demographics, art style — see tag guidance below |

---

## Step-by-step agent workflow

### 1. Pick a book

```
volume_list_books(limit=50, filter_text="")
```

Choose a book whose tags list is empty or very short — those are the best candidates.

### 2. Get all images from the first chapter

```
volume_list_chapters(book_id="<id>")
→ chapters[]  →  the chapter cursor is now pointing at chapters[0]

volume_list_images()   ← chapter_id/book_id omitted: applies to the chapter
                         the chapter cursor points at
→ files[]  →  list of all image filenames; the image cursor points at files[0]
```

### 3. Vision-scan each image in the chapter

Iterate through the chapter and fetch each image individually — the image
cursor steps with `image_next`, so `chapter_id`/`filename` can stay omitted:

```
volume_get_image()   ← applies to the image the image cursor points at
→ returns [ImageContent, TextContent]  ← pass ImageContent directly to vision
image_next()         ← next file; stop when a status sentinel is returned
```

**Each call is independently authenticated by the server.** The server verifies on every request that the user has access to that specific content — sequential per-image calls are the correct and only pattern. There is no batch image endpoint.

Limit the vision pass to a reasonable number of images (e.g. first 5–10) if the chapter is very long — the cover and early pages are usually sufficient for metadata extraction.

### 4. Analyse with vision

Send the fetched `ImageContent` blocks to the vision model with a structured prompt.  Example prompt:

```
You are a metadata extraction assistant for a digital book library.
Analyse the provided images (cover and/or early pages) and return a JSON object with:

{
  "title":    "<clean English title, or null if already correct>",
  "alt_name": "<original-language or alternative title, or null if none>",
  "tags":     ["<tag1>", "<tag2>", ...]
}

Tag guidance:
- Genre:       action, romance, comedy, drama, horror, mystery, fantasy, sci-fi, slice-of-life, sports, historical
- Demographic: shounen, shoujo, seinen, josei, all-ages
- Art style:   4-koma, full-colour, black-and-white
- Themes:      school-life, isekai, mecha, supernatural, cooking, music, martial-arts, office
- Origin:      manga, manhwa, manhua, webtoon, comic

Only include tags that are clearly supported by the images.  Return at most 8 tags.
If a field cannot be determined from the images, set it to null.
```

### 5. Normalise tags against the server vocabulary

```
volume_list_tags()                         ← get full known tag list
volume_guess_tags(values=",".join(tags))   ← only if tags came from a raw/unstructured string
```

Cross-reference vision output against known tags. See tag guidance section below.

### 6. Write the results back

Parse the JSON from the vision model response, then call only the tools where the value is non-null:

```python
if result["title"]:
    volume_update_title(book_id=book_id, name=result["title"])

if result["alt_name"]:
    volume_update_alt_name(book_id=book_id, alt_name=result["alt_name"])

if result["tags"]:
    volume_update_tags(book_id=book_id, tags=result["tags"])
```

### 7. Verify

Call the single-field getters (`volume_get_name`, `volume_get_alt_name`, `volume_get_tags`) and confirm the saved values match what was written.

---

## Tag guidance for the agent

Use the existing tag vocabulary where possible.  Before writing new tags, call `volume_list_tags()` and match against what already exists in the system.  This keeps the tag space clean.

If a word from the vision result is not in the existing tag list, use it only if it is clearly a useful genre/theme word (not a character name, location, or plot summary).

---

## What NOT to store

- **Character names** → do not put in tags or alt_name; there is no dedicated field for them in the MVP
- **Plot summaries** → do not put in alt_name; that field is for title variants only
- **Guesses** → if the image quality is too low or the content is ambiguous, leave that field null rather than guess

---

## Workflow for bulk processing

To process multiple books in one session:

```
volume_list_books(limit=100, filter_tags="")   ← get all books
for each book where book.tags is empty:
    run the 6-step workflow above
    wait briefly between books to avoid hammering the server
```

The agent should process books sequentially (not in parallel) because the MCP server is single-instance.

---

## Access control

The media server enforces per-request access control on every image and file fetch. Two things the agent must understand:

**Per-request verification:** every `volume_get_image` call is independently verified by the server. There is no session-level "unlock" — access is checked on each request against the authenticated user's permissions.

**Rating limits:** every folder and book has a `rating` value. If the content's rating exceeds the user's configured rating limit (`SESSION.limits.volume` for books, `SESSION.limits.media` for media), the server treats the content as if it does not exist — list calls omit it, and direct fetch calls return an access error. The agent cannot work around this; the content is simply not accessible with the current credentials.

**Practical implication:** if `volume_list_books` returns fewer books than expected, or `volume_get_image` returns an error on a known book, the most likely cause is a rating limit mismatch — not a bug. Check `auth_get_session_info` to see the current `limits.volume` value.

---

## Error handling

| Error | Action |
|---|---|
| `volume_get_image` returns HTTP error | Skip this image, try the next filename |
| `volume_get_image` returns access error | Content rating exceeds user limit — skip the entire book, do not retry |
| `volume_list_books` returns empty or fewer books than expected | Check `auth_get_session_info` limits — some books may be hidden by rating filter |
| Vision model returns malformed JSON | Retry once with a stricter prompt; if still bad, skip the book |
| `volume_update_*` returns error message | Log the error, do not retry, move to the next book |
| Token expired mid-workflow | The MCP server auto-re-logins; the failing call will be retried once automatically |
