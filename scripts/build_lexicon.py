#!/usr/bin/env python3
"""
build_lexicon.py — Extract, count, and merge a word-frequency lexicon.

Reads two .docx files (corpus.docx, spoken audio then transcribed.docx),
extracts every unique word, counts frequencies, and merges them with an
existing merged_wordlist.tsv into final_wordlist.tsv.

Tokenizer rules
----------------
1. All text is normalised to Unicode NFC and lowercased.
2. A "word" is a maximal run of Unicode letters (category L*) plus any
   combining marks (category M*) that follow a letter.  Digits, punctuation,
   and other characters are word-separators.
3. NEGATION PREFIX: a "/" that appears immediately before a letter and is
   preceded by whitespace, start-of-string, or an opening quote/bracket is
   kept as part of the token (e.g. "/cu" is a distinct entry from "cu").
4. A "/" in any other position (mid-word, between words with no space,
   numeric fractions like 1/2) is treated as a plain separator, NOT as a
   negation marker.  The script reports how many such non-negation "/" cases
   were encountered.
"""

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# python-docx
from docx import Document

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def nfc_lower(text: str) -> str:
    """NFC-normalise and lowercase."""
    return unicodedata.normalize("NFC", text).lower()


def _is_letter_or_mark(ch: str) -> bool:
    """Return True if ch is a Unicode letter or combining mark."""
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M")


def extract_text_from_docx(path: str) -> str:
    """Return all text in a .docx: paragraphs + table cells + headers/footers."""
    doc = Document(path)
    parts: list[str] = []

    # paragraphs (body)
    for para in doc.paragraphs:
        parts.append(para.text)

    # tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    parts.append(para.text)

    # headers and footers — try each, guard against missing attributes
    for section in doc.sections:
        for hdr_attr in ("header", "first_page_header", "even_page_header"):
            hdr = getattr(section, hdr_attr, None)
            if hdr is not None:
                try:
                    linked = hdr.is_linked_to_previous
                except Exception:
                    linked = True
                if not linked:
                    for para in hdr.paragraphs:
                        parts.append(para.text)
        for ftr_attr in ("footer", "first_page_footer", "even_page_footer"):
            ftr = getattr(section, ftr_attr, None)
            if ftr is not None:
                try:
                    linked = ftr.is_linked_to_previous
                except Exception:
                    linked = True
                if not linked:
                    for para in ftr.paragraphs:
                        parts.append(para.text)

    return "\n".join(parts)


def find_nonletter_chars(text: str) -> set[str]:
    """Return every character that is not a Unicode letter, combining mark, or whitespace."""
    out: set[str] = set()
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] not in ("L", "M") and not ch.isspace():
            out.add(ch)
    return out


# ---------------------------------------------------------------------------
# Tokenizer
#
# Walks through the text character by character.  Accumulates "word" chars
# (letters + combining marks).  When a "/" is encountered, checks whether it
# qualifies as a negation prefix; if so, it becomes part of the next word
# token.  Otherwise, it acts as a separator.
# ---------------------------------------------------------------------------

# Characters that can immediately precede a negation "/"
_OPENERS = set("\"'«([{‹‟„⸢⸤\u201C\u2018\u00AB")


def tokenize(text: str):
    """
    Yield tokens from *text* (which must already be NFC-lowercased).
    Returns a tuple (list_of_tokens, non_negation_slash_count).
    Each token is a string; "/"-prefixed negation tokens start with "/".
    """
    tokens: list[str] = []
    non_neg_slash = 0
    buf: list[str] = []       # accumulator for current word
    has_neg_prefix = False     # True if current word starts with "/"
    i = 0
    n = len(text)

    def flush():
        nonlocal has_neg_prefix
        if buf:
            word = "".join(buf)
            # Make sure it actually contains at least one letter (not just marks)
            if any(unicodedata.category(c)[0] == "L" for c in word):
                if has_neg_prefix:
                    tokens.append("/" + word)
                else:
                    tokens.append(word)
            buf.clear()
            has_neg_prefix = False

    while i < n:
        ch = text[i]

        if _is_letter_or_mark(ch):
            buf.append(ch)
            i += 1
            continue

        if ch == "/":
            # Is there a word being built?  If so, flush it first — the "/"
            # is between two words or inside something.
            if buf:
                flush()
                # Now decide: is this "/" a negation prefix for the NEXT word?
                # After flushing, the preceding context is the end of the
                # previous word, which is NOT whitespace/opener, so this is
                # NOT a negation slash.
                non_neg_slash += 1
                i += 1
                continue

            # No word in buffer.  Check if this is a negation prefix.
            # Look at what precedes this position.
            if i == 0:
                is_neg = True
            else:
                prev = text[i - 1]
                is_neg = prev.isspace() or prev in _OPENERS
            # Also, the next char must be a letter for this to be a negation prefix.
            if is_neg and (i + 1 < n) and unicodedata.category(text[i + 1])[0] == "L":
                has_neg_prefix = True
                i += 1
                continue
            else:
                non_neg_slash += 1
                i += 1
                continue
        else:
            # Any other character (digit, punctuation, whitespace, etc.)
            flush()
            i += 1
            continue

    flush()
    return tokens, non_neg_slash


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # Force UTF-8 output on Windows to handle combining marks and special letters
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base = Path(".")
    docx_files = [
        base / "corpus.docx",
        base / "spoken audio then transcribed.docx",
    ]
    tsv_file = base / "merged_wordlist.tsv"

    # -----------------------------------------------------------------------
    # STEP 1 — Inspect
    # -----------------------------------------------------------------------
    print("=" * 70)
    print("STEP 1 — INSPECTION")
    print("=" * 70)

    # TSV format
    print("\n--- merged_wordlist.tsv format ---")
    print("  No header row.  Two columns: word <TAB> frequency.")
    print("  Sorted by frequency descending.  UTF-8.  CRLF line endings.")
    with open(tsv_file, encoding="utf-8") as f:
        lines = f.readlines()
    non_empty = [l for l in lines if l.strip()]
    print(f"  Total non-empty lines (words): {len(non_empty)}")

    # Scan .docx files for non-letter characters
    raw_texts: dict[str, str] = {}
    for p in docx_files:
        raw = extract_text_from_docx(str(p))
        raw_texts[p.name] = raw
        chars = find_nonletter_chars(raw)
        sorted_chars = sorted(chars, key=lambda c: (unicodedata.category(c), ord(c)))
        print(f"\n--- Non-letter characters in '{p.name}' ---")
        for ch in sorted_chars:
            cat = unicodedata.category(ch)
            name = unicodedata.name(ch, "?")
            print(f"  U+{ord(ch):04X}  {repr(ch):8s}  {cat}  {name}")

    # -----------------------------------------------------------------------
    # STEP 2 — Extraction
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STEP 2 — EXTRACTION")
    print("=" * 70)

    per_file_words: dict[str, Counter] = {}
    corpus_counter: Counter = Counter()
    total_non_neg_slashes = 0

    for fname, raw in raw_texts.items():
        text = nfc_lower(raw)
        tokens, nns = tokenize(text)
        file_counter: Counter = Counter(tokens)
        per_file_words[fname] = file_counter
        corpus_counter += file_counter
        total_non_neg_slashes += nns
        print(f"  '{fname}': {len(file_counter)} unique words, "
              f"{sum(file_counter.values())} total tokens")

    print(f"\n  Non-negation '/' occurrences (treated as separators): "
          f"{total_non_neg_slashes}")

    # -----------------------------------------------------------------------
    # STEP 3 — Merge with existing TSV
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STEP 3 — MERGE")
    print("=" * 70)

    tsv_counter: Counter = Counter()
    with open(tsv_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                word = nfc_lower(parts[0])
                try:
                    freq = int(parts[1])
                except ValueError:
                    freq = 1
                tsv_counter[word] += freq

    final_counter: Counter = Counter()
    final_counter.update(tsv_counter)
    final_counter.update(corpus_counter)

    print(f"  Unique words in merged_wordlist.tsv: {len(tsv_counter)}")
    print(f"  Unique words in corpus (docx files): {len(corpus_counter)}")
    print(f"  Unique words in final merged:        {len(final_counter)}")

    new_words = set(corpus_counter.keys()) - set(tsv_counter.keys())
    print(f"  New words added (not in original TSV): {len(new_words)}")

    # -----------------------------------------------------------------------
    # STEP 4 — Output
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STEP 4 — OUTPUT FILES")
    print("=" * 70)

    # corpus_wordlist.tsv  (docx-only words)
    corpus_out = base / "corpus_wordlist.tsv"
    sorted_corpus = sorted(corpus_counter.items(), key=lambda x: (-x[1], x[0]))
    with open(corpus_out, "w", encoding="utf-8", newline="") as f:
        for word, freq in sorted_corpus:
            f.write(f"{word}\t{freq}\n")
    print(f"  Written: {corpus_out}  ({len(sorted_corpus)} entries)")

    # final_wordlist.tsv  (merged, same format as merged_wordlist.tsv)
    final_out = base / "final_wordlist.tsv"
    sorted_final = sorted(final_counter.items(), key=lambda x: (-x[1], x[0]))
    with open(final_out, "w", encoding="utf-8", newline="") as f:
        for word, freq in sorted_final:
            f.write(f"{word}\t{freq}\n")
    print(f"  Written: {final_out}  ({len(sorted_final)} entries)")

    # -----------------------------------------------------------------------
    # STEP 5 — Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("STEP 5 — REPORT")
    print("=" * 70)

    # Per-file counts
    for fname, ctr in per_file_words.items():
        print(f"\n  '{fname}': {len(ctr)} unique words")

    print(f"\n  corpus_wordlist.tsv unique words: {len(corpus_counter)}")
    print(f"  merged_wordlist.tsv unique words: {len(tsv_counter)}")
    print(f"  final_wordlist.tsv  unique words: {len(final_counter)}")
    print(f"  New words added:                  {len(new_words)}")

    # "/"-prefixed tokens
    neg_tokens = {w: c for w, c in corpus_counter.items() if w.startswith("/")}
    print(f"\n  '/'-prefixed (negation) tokens: {len(neg_tokens)}")
    if neg_tokens:
        examples = sorted(neg_tokens.items(), key=lambda x: -x[1])[:10]
        print("  Examples (token -> freq, positive form -> freq if exists):")
        for tok, freq in examples:
            pos = tok[1:]  # strip the "/"
            pos_freq_corpus = corpus_counter.get(pos, 0)
            pos_freq_tsv = tsv_counter.get(pos, 0)
            print(f"    {tok:20s} freq={freq:<4d}   "
                  f"positive '{pos}' corpus={pos_freq_corpus} tsv={pos_freq_tsv}")

    # 20 most frequent words
    print("\n  20 most frequent words (final_wordlist.tsv):")
    for word, freq in sorted_final[:20]:
        print(f"    {word:20s} {freq}")

    # 20 words with frequency 1 (hapax legomena) — for typo review
    hapax = [(w, f) for w, f in sorted_final if f == 1]
    print(f"\n  Words with frequency 1 (hapax legomena): {len(hapax)} total")
    print("  20 examples for manual typo review:")
    for word, freq in hapax[:20]:
        print(f"    {word}")

    # Tokens with unexpected characters
    print("\n  Tokens containing unexpected characters:")
    unexpected_count = 0
    for word in sorted(corpus_counter.keys()):
        for ch in word:
            if ch == "/":
                continue  # negation prefix is expected
            cat = unicodedata.category(ch)
            if cat[0] not in ("L", "M"):
                print(f"    {word!r}  (char U+{ord(ch):04X} "
                      f"= {unicodedata.name(ch, '?')})")
                unexpected_count += 1
                break
    if unexpected_count == 0:
        print("    (none)")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
