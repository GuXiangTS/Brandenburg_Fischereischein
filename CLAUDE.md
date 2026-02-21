# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A self-contained mobile quiz app (single HTML file) for studying the Brandenburg fishing license (Fischereischein) exam. The app is generated from a PDF question bank by a Python setup script.

## Commands

**Generate the app (with full translation):**
```bash
python scripts/setup.py YOUR_GOOGLE_API_KEY
```

**Generate without translation (German only, for testing):**
```bash
python scripts/setup.py --no-translate
```

**Requires:** `pip install pymupdf` (the `fitz` package)

## Architecture

```
scripts/setup.py                ← single script: parse PDF → translate → generate HTML
Brandenburg_...pdf              ← source question bank (43 pages, 558 questions)
fischereischein.html            ← generated output (self-contained, ~188 KB)
```

### PDF Parsing (`parse_pdf`)

The PDF is rotated 90°. Each question occupies a vertical "column" of words:
- **x-axis** = which question (column boundaries found by locating `lfdNr` digits at y≈730–760)
- **y-axis** = section within the question:
  - `y=410–740`: question text
  - `y=290–410`: Answer A (always the correct answer in the raw PDF)
  - `y=175–290`: Answer B
  - `y=50–175`: Answer C

Words are sorted `(x ascending, y descending)` within each section to correctly reconstruct wrapped text. Words are deduplicated by `(round(x0), round(y0))` because the PDF stores each word twice (main content + answer-key duplicate column on the right).

### Translation

Uses **Google Translate Basic v2** API (`translation.googleapis.com/language/translate/v2`). All 558 × 4 strings (question + 3 answers) are batched in groups of 100. The API key is passed as `sys.argv[1]`.

### HTML App (`APP_HTML` string in setup.py)

A single-page vanilla JS app embedded as a Python string template. The placeholder `__QUESTIONS_JSON__` is replaced with the serialized question data. Key app behaviors:

- **Correct answer is always `ans_a`** in the data — answers are shuffled per-question at display time (Fisher-Yates)
- **Progress persisted in `localStorage`** under keys: `fs_seen` (array of seen indices), `fs_wrong` (booklet indices), `fs_apiKey`, `fs_wc` (word translation cache)
- **Learning queue**: unseen questions first (shuffled), then seen questions (shuffled)
- **Word-level translation**: each German word is wrapped in a `<span class="word">` at render time via `wrapWords()`. Click calls Google Translate v2 directly from the browser, caches results in `fs_wc`
- **Booklet mode**: re-quizzes only `fs_wrong` indices; correct answers remove from booklet, wrong answers add to it

## Key Design Decisions

- **No server required** — the HTML file works when opened directly via `file://` in Safari on iPhone
- **Pre-translated strings** are embedded in the HTML data; word-level translation uses the API key stored in localStorage settings
- **Page footer text** ("Seite X von 42") is stripped via `clean_text()` regex post-processing after PDF extraction
