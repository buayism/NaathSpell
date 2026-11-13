# Nuer Spell Checker

A dictionary-lookup spell checker for the Nuer language with edit-distance suggestions.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

### 1. Build the lexicon (already done)

```bash
cd scripts
py -3 build_lexicon.py
```

Reads `src/corpus.docx` and `src/spoken audio then transcribed.docx`, merges with `tsv/merged_wordlist.tsv`, and produces `final_wordlist.tsv`.

### 2. Review the lexicon

```bash
py -3 scripts/review_lexicon.py
```

Generates review files in `tsv/` and copies `final_wordlist.tsv` to `lexicon.tsv`. Hand-edit `lexicon.tsv` after reviewing.

### 3. Run the spell checker (Streamlit app)

```bash
streamlit run app.py
```

Paste Nuer text, click **Check Spelling**, and review flagged words with suggestions.

### 4. Evaluate the checker

```bash
py -3 scripts/evaluate.py
```

Runs the checker against `tests/test_tokens.tsv` and reports precision, recall, accuracy, and suggestion hit rate.

## Project Structure

```
spell-checker/
├── app.py                  # Streamlit spell-checker UI
├── checker.py              # Core spell-checking module
├── lexicon.tsv             # Active lexicon (copy of final_wordlist.tsv)
├── final_wordlist.tsv      # Merged wordlist (do not edit directly)
├── user_additions.tsv      # User-added words (created automatically)
├── requirements.txt
├── README.md
├── scripts/
│   ├── build_lexicon.py    # Lexicon builder from .docx files
│   ├── review_lexicon.py   # Review helper
│   └── evaluate.py         # Evaluation script
├── src/
│   ├── corpus.docx
│   └── spoken audio then transcribed.docx
├── tsv/
│   ├── merged_wordlist.tsv
│   ├── corpus_wordlist.tsv
│   ├── review_low_freq.tsv
│   ├── review_slash.tsv
│   └── review_odd.tsv
└── tests/
    └── test_tokens.tsv
```

## Nuer Language Notes

- Special letters: ɛ, ɔ, ŋ, ɣ
- Combining diacritics: ̈ (diaeresis), ̱ (macron below) — these attach to base letters (ɛ̈, ɔ̈, ä, i̱, etc.)
- Negation prefix `/`: placed directly before a word (e.g. `/cu` vs `cu`)
- All text is NFC-normalised and lowercased for matching
