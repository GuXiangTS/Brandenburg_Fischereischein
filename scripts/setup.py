#!/usr/bin/env python3
"""
Fischereischein Quiz App Setup

Usage:
    python scripts/setup.py YOUR_GOOGLE_API_KEY
    python scripts/setup.py --no-translate   (skip translation, German only)

Requires: pip install pymupdf

Outputs: index.html, manifest.json, sw.js, icon.svg
"""

import sys, json, os, time, re
import urllib.request, urllib.parse, urllib.error
import fitz  # pymupdf


def clean_text(s):
    """Remove PDF page-footer artifacts like 'Seite 41 von 42'."""
    s = re.sub(r'\s*Seite\s+\d+\s+von\s+\d+', '', s)
    s = re.sub(r'\s*Seite\s+\d+', '', s)
    s = re.sub(r'\s+von\s+\d+$', '', s)
    return s.strip()


# ---------------------------------------------------------------------------
# PDF Parsing
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path):
    doc = fitz.open(pdf_path)

    def parse_page(page):
        words_raw = page.get_text('words')
        # Deduplicate by rounded (x0, y0)
        seen = set()
        words = []
        for w in words_raw:
            key = (round(w[0]), round(w[1]))
            if key not in seen:
                seen.add(key)
                words.append(w)

        # Each question is a vertical column; find column x-origins via lfdNr row.
        # Threshold x>40 (not 70) to also catch the last question on the final page
        # which sits at x≈48 due to the rotated layout. Column header labels at x≈34
        # use encoded text and never match ^\d+$ so they are safely excluded.
        col_xs = sorted(set(
            round(w[0]) for w in words
            if 730 < w[1] < 760 and w[0] > 40 and re.match(r'^\d+$', w[4])
        ))
        if not col_xs:
            return []

        boundaries = col_xs + [col_xs[-1] + 100]

        # Y-axis bands (page is rotated 90°; y decreases top→bottom)
        Y = {'q': (410, 740), 'a': (290, 410), 'b': (175, 290), 'c': (50, 175)}

        def section_text(col_words, band):
            y_lo, y_hi = Y[band]
            items = [(w[0], w[1], w[4]) for w in col_words if y_lo <= w[1] < y_hi]
            items.sort(key=lambda t: (t[0], -t[1]))  # x asc, y desc for wraps
            return ' '.join(t for _, _, t in items)

        questions = []
        for i, cx in enumerate(col_xs):
            col = [w for w in words if (cx - 1) <= w[0] < (boundaries[i+1] - 1)]

            # Question text: skip the leading lfdNr digit at y≈739
            qw = [(w[0], w[1], w[4]) for w in col
                  if 410 <= w[1] < 740 and not (w[1] > 730 and w[4].isdigit())]
            qw.sort(key=lambda t: (t[0], -t[1]))
            q_text = ' '.join(t for _, _, t in qw).strip()

            a = section_text(col, 'a')
            b = section_text(col, 'b')
            c = section_text(col, 'c')

            if q_text and a:
                questions.append({
                    'question_de': clean_text(q_text),
                    'ans_a_de': clean_text(a),
                    'ans_b_de': clean_text(b),
                    'ans_c_de': clean_text(c),
                })

        return questions

    all_q = []
    for pg in range(1, len(doc)):  # skip page 1 (overview)
        all_q.extend(parse_page(doc[pg]))
    return all_q


# ---------------------------------------------------------------------------
# Translation (Google Translate Basic v2)
# ---------------------------------------------------------------------------

def translate_batch(texts, api_key, retries=3):
    url = 'https://translation.googleapis.com/language/translate/v2'
    params = urllib.parse.urlencode({'key': api_key})
    body = json.dumps({'q': texts, 'source': 'de', 'target': 'en', 'format': 'text'}).encode()
    req = urllib.request.Request(
        f'{url}?{params}', data=body,
        headers={'Content-Type': 'application/json'}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                return [t['translatedText'] for t in result['data']['translations']]
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt+1} after error: {e}")
            time.sleep(2)


def translate_all(questions, api_key):
    fields_de = ['question_de', 'ans_a_de', 'ans_b_de', 'ans_c_de']
    fields_en = ['question_en', 'ans_a_en', 'ans_b_en', 'ans_c_en']

    all_texts = [q[f] for q in questions for f in fields_de]
    translated = []

    batch_size = 100
    total_batches = (len(all_texts) + batch_size - 1) // batch_size
    for i in range(0, len(all_texts), batch_size):
        batch_num = i // batch_size + 1
        print(f"  Translating batch {batch_num}/{total_batches}...")
        translated.extend(translate_batch(all_texts[i:i+batch_size], api_key))

    idx = 0
    for q in questions:
        for f_en in fields_en:
            q[f_en] = translated[idx]
            idx += 1

    return questions


# ---------------------------------------------------------------------------
# HTML App (self-contained)
# ---------------------------------------------------------------------------

APP_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#1B4332">
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icon.svg">
<title>Fischereischein Quiz</title>
<style>
:root {
  --green-dark: #1B4332;
  --green: #2D6A4F;
  --green-mid: #40916C;
  --green-light: #74C69D;
  --green-pale: #D8F3DC;
  --bg: #F4F7F5;
  --card: #FFFFFF;
  --text: #1A2E1F;
  --text-muted: #5A7566;
  --border: #D4E6DA;
  --correct: #198754;
  --correct-bg: #D1F0E0;
  --wrong: #C0392B;
  --wrong-bg: #FDECEA;
  --radius: 14px;
  --shadow: 0 2px 12px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100dvh;
  font-size: 16px;
  line-height: 1.5;
}

.screen { display: none; flex-direction: column; min-height: 100dvh; }
.screen.active { display: flex; }

/* ── Header ── */
.header {
  background: var(--green-dark);
  color: #fff;
  padding: 14px 16px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-title { flex: 1; font-size: 17px; font-weight: 600; }
.header-sub { font-size: 13px; opacity: 0.75; margin-top: 1px; }
.btn-icon {
  background: rgba(255,255,255,0.15);
  border: none;
  color: #fff;
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; font-size: 18px;
  transition: background 0.15s;
  flex-shrink: 0;
}
.btn-icon:active { background: rgba(255,255,255,0.3); }

/* ── Progress bar ── */
.progress-bar {
  height: 3px;
  background: var(--border);
}
.progress-fill {
  height: 100%;
  background: var(--green-light);
  transition: width 0.3s ease;
}

/* ── Scrollable content ── */
.content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── Home screen ── */
.home-hero {
  text-align: center;
  padding: 32px 16px 24px;
}
.home-icon { font-size: 64px; margin-bottom: 12px; }
.home-title { font-size: 26px; font-weight: 700; color: var(--green-dark); }
.home-sub { color: var(--text-muted); margin-top: 6px; font-size: 15px; }

.home-stats {
  background: var(--card);
  border-radius: var(--radius);
  padding: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
  box-shadow: var(--shadow);
}
.stat { text-align: center; }
.stat-num { font-size: 24px; font-weight: 700; color: var(--green); }
.stat-label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.home-btns { display: flex; flex-direction: column; gap: 10px; }

.btn {
  display: flex; align-items: center; gap: 12px;
  background: var(--card);
  border: 2px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  cursor: pointer;
  text-align: left;
  width: 100%;
  transition: transform 0.1s, box-shadow 0.1s;
  box-shadow: var(--shadow);
}
.btn:active { transform: scale(0.98); box-shadow: none; }
.btn.primary { background: var(--green); border-color: var(--green); color: #fff; }
.btn.primary .btn-label { color: #fff; }
.btn.primary .btn-desc { color: rgba(255,255,255,0.75); }
.btn.danger { border-color: var(--wrong); }
.btn.danger .btn-icon-wrap { color: var(--wrong); }

.btn-icon-wrap { font-size: 28px; flex-shrink: 0; }
.btn-label { font-size: 17px; font-weight: 600; color: var(--text); }
.btn-desc { font-size: 13px; color: var(--text-muted); margin-top: 2px; }

/* ── Quiz screen ── */
.question-card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
}
.question-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.question-text {
  font-size: 18px;
  font-weight: 500;
  line-height: 1.55;
  color: var(--text);
}
.question-text-en {
  font-size: 15px;
  color: var(--text-muted);
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  line-height: 1.5;
  display: none;
}
.question-text-en.show { display: block; }

.translate-btn {
  display: flex; align-items: center; gap: 8px;
  background: var(--green-pale);
  color: var(--green-dark);
  border: 1px solid var(--green-light);
  border-radius: 24px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  width: fit-content;
  transition: background 0.15s;
}
.translate-btn:active { background: var(--green-light); }
.translate-btn.active { background: var(--green-light); }

.answers-list { display: flex; flex-direction: column; gap: 10px; }

.answer-btn {
  background: var(--card);
  border: 2px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  cursor: pointer;
  text-align: left;
  width: 100%;
  transition: border-color 0.15s, background 0.15s;
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.answer-btn:active:not(:disabled) { background: var(--green-pale); }
.answer-btn:disabled { cursor: default; }
.answer-letter {
  flex-shrink: 0;
  width: 28px; height: 28px;
  border-radius: 50%;
  background: var(--bg);
  border: 2px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 13px;
  color: var(--text-muted);
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.answer-body { flex: 1; }
.answer-text-de { font-size: 16px; font-weight: 500; line-height: 1.4; }
.answer-text-en { font-size: 13px; color: var(--text-muted); margin-top: 4px; display: none; line-height: 1.4; }
.answer-text-en.show { display: block; }

.answer-btn.correct {
  border-color: var(--correct);
  background: var(--correct-bg);
}
.answer-btn.correct .answer-letter {
  background: var(--correct);
  border-color: var(--correct);
  color: #fff;
}
.answer-btn.wrong {
  border-color: var(--wrong);
  background: var(--wrong-bg);
}
.answer-btn.wrong .answer-letter {
  background: var(--wrong);
  border-color: var(--wrong);
  color: #fff;
}

.feedback-bar {
  border-radius: var(--radius);
  padding: 14px 16px;
  font-weight: 600;
  font-size: 15px;
  display: none;
}
.feedback-bar.correct {
  display: block;
  background: var(--correct-bg);
  color: var(--correct);
  border: 1px solid var(--correct);
}
.feedback-bar.wrong {
  display: block;
  background: var(--wrong-bg);
  color: var(--wrong);
  border: 1px solid var(--wrong);
}

.next-btn {
  background: var(--green);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 16px;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: background 0.15s;
  display: none;
}
.next-btn.show { display: block; }
.next-btn:active { background: var(--green-mid); }

/* ── Word translation tooltip ── */
.word {
  cursor: pointer;
  border-bottom: 1px dotted var(--green-mid);
  display: inline;
  transition: background 0.1s;
  border-radius: 2px;
}
.word:hover, .word.active { background: var(--green-pale); }

#tooltip {
  position: fixed;
  background: var(--green-dark);
  color: #fff;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  pointer-events: none;
  z-index: 1000;
  max-width: 200px;
  text-align: center;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  transform: translateX(-50%);
}
#tooltip::after {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-bottom: none;
  border-top-color: var(--green-dark);
}
#tooltip.below::after {
  bottom: auto;
  top: -6px;
  border-top: none;
  border-bottom: 6px solid var(--green-dark);
}

/* ── Booklet mode empty state ── */
.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--text-muted);
}
.empty-state .icon { font-size: 48px; margin-bottom: 16px; }
.empty-state h3 { font-size: 20px; color: var(--text); margin-bottom: 8px; }
.empty-state p { font-size: 15px; line-height: 1.5; }

/* ── Settings screen ── */
.settings-section {
  background: var(--card);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
}
.settings-item {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.settings-item:last-child { border-bottom: none; }
.settings-label { font-size: 13px; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.settings-input {
  width: 100%;
  border: 2px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 15px;
  font-family: monospace;
  color: var(--text);
  background: var(--bg);
}
.settings-input:focus { outline: none; border-color: var(--green-mid); }
.settings-desc { font-size: 13px; color: var(--text-muted); margin-top: 6px; line-height: 1.4; }

.settings-save-btn {
  background: var(--green);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 14px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: background 0.15s;
}
.settings-save-btn:active { background: var(--green-mid); }

.danger-btn {
  background: var(--card);
  color: var(--wrong);
  border: 2px solid var(--wrong);
  border-radius: var(--radius);
  padding: 14px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: background 0.15s;
}
.danger-btn:active { background: var(--wrong-bg); }

.badge {
  display: inline-flex;
  align-items: center;
  background: var(--wrong);
  color: #fff;
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 13px;
  font-weight: 600;
  margin-left: 8px;
}

/* ── Completion screen ── */
.completion-card {
  background: var(--card);
  border-radius: var(--radius);
  padding: 32px 20px;
  text-align: center;
  box-shadow: var(--shadow);
}
.completion-icon { font-size: 56px; margin-bottom: 16px; }
.completion-title { font-size: 24px; font-weight: 700; color: var(--green-dark); }
.completion-sub { color: var(--text-muted); margin-top: 8px; font-size: 15px; line-height: 1.5; }
.completion-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 24px 0; }
.completion-stat { background: var(--bg); border-radius: 10px; padding: 14px; }
.completion-stat-num { font-size: 28px; font-weight: 700; color: var(--green); }
.completion-stat-label { font-size: 13px; color: var(--text-muted); }

.mode-badge {
  display: inline-block;
  background: var(--green-pale);
  color: var(--green-dark);
  border-radius: 12px;
  padding: 3px 10px;
  font-size: 13px;
  font-weight: 600;
}
</style>
</head>
<body>

<!-- ══════════════════════════════════════════════════════
     HOME SCREEN
═══════════════════════════════════════════════════════ -->
<div id="screen-home" class="screen active">
  <div style="background: var(--green-dark); padding: 14px 16px; display: flex; justify-content: space-between; align-items: center;">
    <div>
      <div style="color:#fff; font-size:18px; font-weight:700;">🎣 Fischereischein</div>
      <div style="color:rgba(255,255,255,0.65); font-size:13px;">Brandenburg Prüfungsvorbereitung</div>
    </div>
    <button class="btn-icon" onclick="showScreen('settings')" title="Einstellungen">⚙️</button>
  </div>

  <div class="content">
    <div class="home-stats">
      <div class="stat">
        <div class="stat-num" id="stat-total">558</div>
        <div class="stat-label">Fragen gesamt</div>
      </div>
      <div class="stat">
        <div class="stat-num" id="stat-seen">0</div>
        <div class="stat-label">Gesehen</div>
      </div>
      <div class="stat">
        <div class="stat-num" id="stat-wrong">0</div>
        <div class="stat-label">Im Merkheft</div>
      </div>
    </div>

    <div class="home-btns">
      <button class="btn primary" onclick="startLearn()">
        <span class="btn-icon-wrap">📚</span>
        <div>
          <div class="btn-label">Lernen</div>
          <div class="btn-desc" id="btn-learn-desc">Alle Fragen, ungesehene zuerst</div>
        </div>
      </button>

      <button class="btn" id="btn-booklet" onclick="startBooklet()">
        <span class="btn-icon-wrap">📕</span>
        <div>
          <div class="btn-label">Merkheft <span class="badge" id="booklet-badge">0</span></div>
          <div class="btn-desc">Falsch beantwortete Fragen wiederholen</div>
        </div>
      </button>
    </div>

    <div style="text-align:center; color: var(--text-muted); font-size: 13px; padding: 8px;">
      Tippe auf ein deutsches Wort für die Übersetzung.<br>
      Benutze „Übersetzen" für die vollständige englische Übersetzung.
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     QUIZ SCREEN
═══════════════════════════════════════════════════════ -->
<div id="screen-quiz" class="screen">
  <div class="header">
    <button class="btn-icon" onclick="goHome()" title="Zurück">←</button>
    <div>
      <div class="header-title" id="quiz-mode-label">Lernen</div>
      <div class="header-sub" id="quiz-progress">Frage 1 von 558</div>
    </div>
    <button class="btn-icon" onclick="showScreen('settings')" title="Einstellungen">⚙️</button>
  </div>
  <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>

  <div class="content" id="quiz-content">
    <div class="question-card">
      <div class="question-meta" id="question-meta">Frage 1</div>
      <div class="question-text" id="question-text"></div>
      <div class="question-text-en" id="question-text-en"></div>
    </div>

    <button class="translate-btn" id="translate-btn" onclick="toggleTranslation()">
      <span>🌐</span> <span id="translate-btn-label">Übersetzen</span>
    </button>

    <div class="answers-list" id="answers-list"></div>

    <div class="feedback-bar" id="feedback-bar"></div>

    <button class="next-btn" id="next-btn" onclick="nextQuestion()">
      Weiter →
    </button>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     COMPLETION SCREEN
═══════════════════════════════════════════════════════ -->
<div id="screen-done" class="screen">
  <div class="header">
    <button class="btn-icon" onclick="goHome()">←</button>
    <div><div class="header-title">Fertig!</div></div>
  </div>
  <div class="content">
    <div class="completion-card">
      <div class="completion-icon" id="done-icon">🎉</div>
      <div class="completion-title" id="done-title">Runde abgeschlossen!</div>
      <div class="completion-sub" id="done-sub"></div>
      <div class="completion-stats">
        <div class="completion-stat">
          <div class="completion-stat-num" id="done-correct">0</div>
          <div class="completion-stat-label">Richtig</div>
        </div>
        <div class="completion-stat">
          <div class="completion-stat-num" id="done-wrong">0</div>
          <div class="completion-stat-label">Falsch</div>
        </div>
      </div>
      <button class="btn primary" style="width:100%; justify-content:center;" onclick="startLearn()">
        <span class="btn-icon-wrap">🔄</span>
        <div><div class="btn-label">Nochmal lernen</div></div>
      </button>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════
     SETTINGS SCREEN
═══════════════════════════════════════════════════════ -->
<div id="screen-settings" class="screen">
  <div class="header">
    <button class="btn-icon" onclick="goHome()">←</button>
    <div><div class="header-title">Einstellungen</div></div>
  </div>
  <div class="content">
    <div class="settings-section">
      <div class="settings-item">
        <div class="settings-label">Google Translate API-Schlüssel</div>
        <input class="settings-input" id="api-key-input" type="password"
               placeholder="AIza..." autocomplete="off" autocorrect="off">
        <div class="settings-desc">
          Für Wort-für-Wort-Übersetzung per Tipp. Verwende Google Cloud Translation Basic (v2) –
          kostenlos bis 500.000 Zeichen/Monat.
        </div>
      </div>
    </div>
    <button class="settings-save-btn" onclick="saveSettings()">Speichern</button>

    <div class="settings-section" style="margin-top: 8px;">
      <div class="settings-item">
        <div class="settings-label">Fortschritt</div>
        <div class="settings-desc" id="settings-stats"></div>
      </div>
    </div>

    <button class="danger-btn" onclick="confirmReset()">Fortschritt zurücksetzen</button>
    <button class="danger-btn" style="margin-top:8px;" onclick="confirmClearBooklet()">
      Merkheft leeren
    </button>
  </div>
</div>

<!-- Tooltip -->
<div id="tooltip" style="display:none;"></div>

<script>
// ═══════════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════════
const QUESTIONS = __QUESTIONS_JSON__;

// ═══════════════════════════════════════════════════════
// STORAGE
// ═══════════════════════════════════════════════════════
const S = {
  _get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  _set: (k, v) => localStorage.setItem(k, JSON.stringify(v)),

  get seen()    { return this._get('fs_seen', []); },
  set seen(v)   { this._set('fs_seen', v); },
  get wrong()   { return this._get('fs_wrong', []); },
  set wrong(v)  { this._set('fs_wrong', v); },
  get apiKey()  { return localStorage.getItem('fs_apiKey') || ''; },
  set apiKey(v) { localStorage.setItem('fs_apiKey', v); },
  get wc()      { return this._get('fs_wc', {}); },
  set wc(v)     { this._set('fs_wc', v); },
};

// ═══════════════════════════════════════════════════════
// APP STATE
// ═══════════════════════════════════════════════════════
let state = {
  mode: 'learn',      // 'learn' | 'booklet'
  queue: [],          // array of question indices
  current: 0,         // position in queue
  answered: false,
  showTrans: false,
  sessionCorrect: 0,
  sessionWrong: 0,
  shuffledAnswers: [], // [{text_de, text_en, correct}]
};

// ═══════════════════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════════════════
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById('screen-' + name).classList.add('active');
  if (name === 'home') refreshHome();
  if (name === 'settings') refreshSettings();
  hideTooltip();
}

function goHome() {
  showScreen('home');
}

// ═══════════════════════════════════════════════════════
// HOME
// ═══════════════════════════════════════════════════════
function refreshHome() {
  const seen = S.seen;
  const wrong = S.wrong;
  const unseen = QUESTIONS.length - seen.length;

  document.getElementById('stat-total').textContent = QUESTIONS.length;
  document.getElementById('stat-seen').textContent = seen.length;
  document.getElementById('stat-wrong').textContent = wrong.length;
  document.getElementById('booklet-badge').textContent = wrong.length;
  document.getElementById('btn-learn-desc').textContent =
    unseen > 0 ? `${unseen} ungesehen · ${seen.length} gesehen` : 'Alle Fragen gesehen';

  const bookletBtn = document.getElementById('btn-booklet');
  bookletBtn.style.opacity = wrong.length === 0 ? '0.5' : '1';
}

// ═══════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════
function refreshSettings() {
  document.getElementById('api-key-input').value = S.apiKey;
  const seen = S.seen.length;
  document.getElementById('settings-stats').textContent =
    `${seen} von ${QUESTIONS.length} Fragen gesehen · ${S.wrong.length} im Merkheft · ${Object.keys(S.wc).length} Wörter gecacht`;
}

function saveSettings() {
  const key = document.getElementById('api-key-input').value.trim();
  S.apiKey = key;
  showToast('Gespeichert ✓');
}

function confirmReset() {
  if (confirm('Gesamten Fortschritt zurücksetzen? (Gesehen-Liste und Merkheft werden gelöscht)')) {
    S.seen = [];
    S.wrong = [];
    showToast('Fortschritt zurückgesetzt');
    refreshSettings();
  }
}

function confirmClearBooklet() {
  if (confirm('Merkheft leeren?')) {
    S.wrong = [];
    showToast('Merkheft geleert');
    refreshSettings();
  }
}

// ═══════════════════════════════════════════════════════
// LEARN / BOOKLET START
// ═══════════════════════════════════════════════════════
function buildLearnQueue() {
  const seen = new Set(S.seen);
  const unseen = [], seenArr = [];
  QUESTIONS.forEach((_, i) => (seen.has(i) ? seenArr : unseen).push(i));
  shuffle(unseen);
  shuffle(seenArr);
  return [...unseen, ...seenArr];
}

function startLearn() {
  state.mode = 'learn';
  state.queue = buildLearnQueue();
  state.current = 0;
  state.sessionCorrect = 0;
  state.sessionWrong = 0;
  if (state.queue.length === 0) return;
  document.getElementById('quiz-mode-label').textContent = 'Lernen';
  showScreen('quiz');
  showQuestion();
}

function startBooklet() {
  const wrong = S.wrong;
  if (wrong.length === 0) { showToast('Merkheft ist leer'); return; }
  state.mode = 'booklet';
  state.queue = shuffle([...wrong]);
  state.current = 0;
  state.sessionCorrect = 0;
  state.sessionWrong = 0;
  document.getElementById('quiz-mode-label').textContent = 'Merkheft';
  showScreen('quiz');
  showQuestion();
}

// ═══════════════════════════════════════════════════════
// QUIZ LOGIC
// ═══════════════════════════════════════════════════════
function showQuestion() {
  if (state.current >= state.queue.length) {
    showCompletion();
    return;
  }

  state.answered = false;
  state.showTrans = false;

  const qIdx = state.queue[state.current];
  const q = QUESTIONS[qIdx];

  // Shuffle answers (correct is always ans_a)
  state.shuffledAnswers = shuffle([
    { text_de: q.ans_a_de, text_en: q.ans_a_en || '', correct: true },
    { text_de: q.ans_b_de, text_en: q.ans_b_en || '', correct: false },
    { text_de: q.ans_c_de, text_en: q.ans_c_en || '', correct: false },
  ]);

  // Progress
  const total = state.queue.length;
  const pos = state.current + 1;
  document.getElementById('quiz-progress').textContent =
    `Frage ${pos} von ${total}`;
  document.getElementById('progress-fill').style.width = `${(pos / total) * 100}%`;
  document.getElementById('question-meta').textContent =
    state.mode === 'booklet' ? '📕 Merkheft' : `Frage ${qIdx + 1}`;

  // Question text (words clickable)
  document.getElementById('question-text').innerHTML = wrapWords(q.question_de);
  const enEl = document.getElementById('question-text-en');
  enEl.textContent = q.question_en || '';
  enEl.classList.remove('show');

  // Translate button
  const transBtn = document.getElementById('translate-btn');
  transBtn.classList.remove('active');
  document.getElementById('translate-btn-label').textContent = 'Übersetzen';
  transBtn.style.display = q.question_en ? 'flex' : 'none';

  // Answers
  const letters = ['A', 'B', 'C'];
  const list = document.getElementById('answers-list');
  list.innerHTML = '';
  state.shuffledAnswers.forEach((ans, i) => {
    const btn = document.createElement('button');
    btn.className = 'answer-btn';
    btn.dataset.idx = i;
    btn.onclick = () => selectAnswer(i);
    btn.innerHTML = `
      <div class="answer-letter">${letters[i]}</div>
      <div class="answer-body">
        <div class="answer-text-de">${wrapWords(ans.text_de)}</div>
        <div class="answer-text-en">${ans.text_en || ''}</div>
      </div>`;
    list.appendChild(btn);
  });

  // Reset feedback
  const fb = document.getElementById('feedback-bar');
  fb.className = 'feedback-bar';
  fb.textContent = '';
  document.getElementById('next-btn').classList.remove('show');
  hideTooltip();
}

function selectAnswer(idx) {
  if (state.answered) return;
  state.answered = true;

  const ans = state.shuffledAnswers[idx];
  const qIdx = state.queue[state.current];
  const buttons = document.querySelectorAll('.answer-btn');

  buttons.forEach((btn, i) => {
    btn.disabled = true;
    if (state.shuffledAnswers[i].correct) {
      btn.classList.add('correct');
    } else if (i === idx && !ans.correct) {
      btn.classList.add('wrong');
    }
  });

  const fb = document.getElementById('feedback-bar');
  if (ans.correct) {
    fb.className = 'feedback-bar correct';
    fb.textContent = '✓ Richtig!';
    state.sessionCorrect++;
    // Remove from wrong booklet if it was there
    const wrong = S.wrong.filter(i => i !== qIdx);
    S.wrong = wrong;
  } else {
    fb.className = 'feedback-bar wrong';
    fb.textContent = '✗ Falsch – die richtige Antwort ist grün markiert.';
    state.sessionWrong++;
    // Add to wrong booklet
    const wrong = S.wrong;
    if (!wrong.includes(qIdx)) S.wrong = [...wrong, qIdx];
  }

  // Mark as seen
  const seen = S.seen;
  if (!seen.includes(qIdx)) S.seen = [...seen, qIdx];

  document.getElementById('next-btn').classList.add('show');

  // Auto-show English translations on answer reveal
  if (state.showTrans) {
    document.querySelectorAll('.answer-text-en').forEach(el => el.classList.add('show'));
  }
}

function nextQuestion() {
  state.current++;
  showQuestion();
}

function toggleTranslation() {
  state.showTrans = !state.showTrans;
  const qIdx = state.queue[state.current];
  const q = QUESTIONS[qIdx];

  document.getElementById('question-text-en').classList.toggle('show', state.showTrans);
  document.getElementById('translate-btn').classList.toggle('active', state.showTrans);
  document.getElementById('translate-btn-label').textContent =
    state.showTrans ? 'Ausblenden' : 'Übersetzen';

  document.querySelectorAll('.answer-text-en').forEach(el =>
    el.classList.toggle('show', state.showTrans)
  );
}

// ═══════════════════════════════════════════════════════
// COMPLETION
// ═══════════════════════════════════════════════════════
function showCompletion() {
  const total = state.sessionCorrect + state.sessionWrong;
  const pct = total > 0 ? Math.round((state.sessionCorrect / total) * 100) : 100;

  document.getElementById('done-icon').textContent = pct >= 80 ? '🎉' : pct >= 50 ? '💪' : '📖';
  document.getElementById('done-title').textContent =
    state.mode === 'booklet' ? 'Merkheft abgeschlossen!' : 'Runde abgeschlossen!';
  document.getElementById('done-sub').textContent =
    `${pct}% korrekt – ${state.sessionCorrect} richtig, ${state.sessionWrong} falsch.`;
  document.getElementById('done-correct').textContent = state.sessionCorrect;
  document.getElementById('done-wrong').textContent = state.sessionWrong;

  showScreen('done');
}

// ═══════════════════════════════════════════════════════
// WORD TRANSLATION TOOLTIP
// ═══════════════════════════════════════════════════════
function wrapWords(text) {
  if (!text) return '';
  return text.split(/(\s+)/).map(token => {
    if (/^\s+$/.test(token)) return token;
    const clean = token.replace(/^[.,!?;:()\[\]"']+|[.,!?;:()\[\]"']+$/g, '');
    if (!clean || /^\d+$/.test(clean)) return token;
    return `<span class="word" onclick="onWordClick(event, '${escAttr(clean)}')">${token}</span>`;
  }).join('');
}

function escAttr(s) {
  return s.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

let activeWordEl = null;

async function onWordClick(event, word) {
  event.stopPropagation();
  const el = event.currentTarget;

  // Toggle off if same word
  if (activeWordEl === el) {
    hideTooltip();
    return;
  }

  hideTooltip();
  activeWordEl = el;
  el.classList.add('active');
  showTooltipEl(el, '…');

  const translation = await translateWordCached(word);
  if (activeWordEl === el) {
    showTooltipEl(el, translation || '(keine Übersetzung)');
  }
}

async function translateWordCached(word) {
  const cache = S.wc;
  if (cache[word]) return cache[word];

  const apiKey = S.apiKey;
  if (!apiKey) {
    showToast('Bitte API-Schlüssel in den Einstellungen eingeben');
    return null;
  }

  try {
    const url = `https://translation.googleapis.com/language/translate/v2?key=${encodeURIComponent(apiKey)}&q=${encodeURIComponent(word)}&source=de&target=en&format=text`;
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.error) { showToast('API-Fehler: ' + data.error.message); return null; }
    const result = data.data.translations[0].translatedText;
    const updated = S.wc;
    updated[word] = result;
    S.wc = updated;
    return result;
  } catch (e) {
    showToast('Übersetzungsfehler: ' + e.message);
    return null;
  }
}

function showTooltipEl(el, text) {
  const tip = document.getElementById('tooltip');
  tip.textContent = text;
  tip.style.display = 'block';
  tip.classList.remove('below');

  const rect = el.getBoundingClientRect();
  const tipW = tip.offsetWidth;
  const tipH = tip.offsetHeight;

  let top = rect.top - tipH - 10;
  let below = false;
  if (top < 8) { top = rect.bottom + 10; below = true; }
  if (below) tip.classList.add('below');

  let left = rect.left + rect.width / 2;
  left = Math.max(tipW / 2 + 8, Math.min(left, window.innerWidth - tipW / 2 - 8));

  tip.style.top = top + 'px';
  tip.style.left = left + 'px';
}

function hideTooltip() {
  document.getElementById('tooltip').style.display = 'none';
  if (activeWordEl) { activeWordEl.classList.remove('active'); activeWordEl = null; }
}

document.addEventListener('click', hideTooltip);

// ═══════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

let toastTimer;
function showToast(msg) {
  clearTimeout(toastTimer);
  let t = document.getElementById('toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast';
    t.style.cssText = `
      position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      background:#333; color:#fff; padding:10px 20px; border-radius:24px;
      font-size:14px; z-index:2000; max-width:80vw; text-align:center;
      box-shadow:0 4px 16px rgba(0,0,0,0.3); transition:opacity 0.3s;`;
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = '1';
  toastTimer = setTimeout(() => { t.style.opacity = '0'; }, 2500);
}

// ═══════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════
refreshHome();

// Register service worker for offline/PWA support
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js', { scope: './' })
    .catch(() => {}); // silently ignore failures (e.g. file:// protocol)
}
</script>
</body>
</html>
"""


def build_html(questions):
    questions_json = json.dumps(questions, ensure_ascii=False, separators=(',', ':'))
    return APP_HTML.replace('__QUESTIONS_JSON__', questions_json)


def build_manifest():
    return json.dumps({
        "name": "Fischereischein Quiz",
        "short_name": "Fischerei",
        "description": "Brandenburg fishing license exam preparation",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#1B4332",
        "theme_color": "#1B4332",
        "icons": [
            {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
        ]
    }, indent=2)


def build_sw():
    return """\
const CACHE = 'fischerei-v1';
const ASSETS = ['./index.html', './manifest.json', './icon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
"""


def build_icon():
    # Simple SVG icon with fishing rod emoji feel
    return """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="22" fill="#1B4332"/>
  <text x="50" y="68" font-size="56" text-anchor="middle" font-family="serif">🎣</text>
</svg>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    pdf_path = os.path.join(project_dir, 'Brandenburg_Fischereischein_Exam_Question_Bank.pdf')
    output_path = os.path.join(project_dir, 'index.html')

    print(f"Parsing PDF: {pdf_path}")
    questions = parse_pdf(pdf_path)
    print(f"  Found {len(questions)} questions")

    if sys.argv[1] == '--no-translate':
        print("Skipping translation (--no-translate)")
        for q in questions:
            q['question_en'] = ''
            q['ans_a_en'] = ''
            q['ans_b_en'] = ''
            q['ans_c_en'] = ''
    else:
        api_key = sys.argv[1]
        print(f"Translating {len(questions) * 4} strings via Google Translate Basic v2...")
        try:
            questions = translate_all(questions, api_key)
            print("  Translation complete")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  Translation API error {e.code}: {body}")
            print("  Falling back to untranslated mode")
            for q in questions:
                q.setdefault('question_en', '')
                q.setdefault('ans_a_en', '')
                q.setdefault('ans_b_en', '')
                q.setdefault('ans_c_en', '')

    print("Building app files...")
    files = {
        output_path:                                build_html(questions),
        os.path.join(project_dir, 'manifest.json'): build_manifest(),
        os.path.join(project_dir, 'sw.js'):          build_sw(),
        os.path.join(project_dir, 'icon.svg'):       build_icon(),
    }
    for path, content in files.items():
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n✓ Generated:")
    for path in files:
        print(f"  {os.path.basename(path)}")
    print(f"\n  index.html is {size_kb:.0f} KB")
    print(f"\nNext: push to GitHub and enable GitHub Pages.")
    print(f"Then open the Pages URL in Safari → Share → Add to Home Screen.")
