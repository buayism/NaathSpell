#!/usr/bin/env python3
"""
review_lexicon.py — Generate review files from final_wordlist.tsv.

Outputs (in tsv/ directory):
  review_low_freq.tsv   — all freq-1 words, alphabetical, with empty keep? column
  review_slash.tsv      — every "/"-prefixed token + whether positive form exists
  review_odd.tsv        — tokens with characters outside the expected Nuer alphabet
  lexicon.tsv           — copy of final_wordlist.tsv for the checker to load
"""

import sys
import unicodedata
import shutil
from pathlib import Path


def nfc_lower(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def load_wordlist(path: Path) -> dict[str, int]:
    """Load a word<TAB>freq TSV into a dict."""
    words: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                w = nfc_lower(parts[0])
                try:
                    freq = int(parts[1])
                except ValueError:
                    freq = 1
                words[w] = words.get(w, 0) + freq
    return words


def build_expected_chars(words: dict[str, int], min_freq: int = 5) -> set[str]:
    """
    Build the set of expected code points (letters + combining marks) from
    high-frequency words.  Characters only seen in rare words may be typos.
    """
    chars: set[str] = set()
    for word, freq in words.items():
        if freq < min_freq:
            continue
        for ch in word:
            if ch == "/":
                continue
            cat = unicodedata.category(ch)
            if cat[0] in ("L", "M"):
                chars.add(ch)
    return chars


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base = Path(__file__).resolve().parent.parent  # project root
    final_tsv = base / "final_wordlist.tsv"
    tsv_dir = base / "tsv"
    tsv_dir.mkdir(exist_ok=True)

    if not final_tsv.exists():
        print(f"ERROR: {final_tsv} not found.")
        sys.exit(1)

    words = load_wordlist(final_tsv)
    print(f"Loaded {len(words)} words from {final_tsv.name}")

    # --- review_low_freq.tsv ---
    low_freq = sorted(w for w, f in words.items() if f == 1)
    out_low = tsv_dir / "review_low_freq.tsv"
    with open(out_low, "w", encoding="utf-8", newline="") as f:
        f.write("word\tfrequency\tkeep?\n")
        for w in low_freq:
            f.write(f"{w}\t1\t\n")
    print(f"  {out_low.name}: {len(low_freq)} words with frequency 1")

    # --- review_slash.tsv ---
    slash_tokens = sorted((w, f) for w, f in words.items() if w.startswith("/"))
    out_slash = tsv_dir / "review_slash.tsv"
    with open(out_slash, "w", encoding="utf-8", newline="") as f:
        f.write("negated_form\tfreq\tpositive_form\tpositive_exists\tpositive_freq\n")
        for w, freq in slash_tokens:
            pos = w[1:]
            pos_freq = words.get(pos, 0)
            exists = "yes" if pos in words else "no"
            f.write(f"{w}\t{freq}\t{pos}\t{exists}\t{pos_freq}\n")
    print(f"  {out_slash.name}: {len(slash_tokens)} '/'-prefixed tokens")

    # --- review_odd.tsv ---
    expected = build_expected_chars(words, min_freq=5)
    odd_tokens: list[tuple[str, int, str]] = []
    for w, freq in sorted(words.items()):
        odd_chars = []
        for ch in w:
            if ch == "/":
                continue
            cat = unicodedata.category(ch)
            if cat[0] in ("L", "M") and ch not in expected:
                name = unicodedata.name(ch, "?")
                odd_chars.append(f"U+{ord(ch):04X} {name}")
        if odd_chars:
            odd_tokens.append((w, freq, "; ".join(odd_chars)))

    out_odd = tsv_dir / "review_odd.tsv"
    with open(out_odd, "w", encoding="utf-8", newline="") as f:
        f.write("word\tfrequency\todd_characters\n")
        for w, freq, info in odd_tokens:
            f.write(f"{w}\t{freq}\t{info}\n")
    print(f"  {out_odd.name}: {len(odd_tokens)} tokens with unexpected characters")

    # --- Copy final_wordlist.tsv → lexicon.tsv ---
    lexicon_dst = base / "lexicon.tsv"
    shutil.copy2(str(final_tsv), str(lexicon_dst))
    print(f"  lexicon.tsv: copied from {final_tsv.name} ({len(words)} words)")

    print("\nDone. Review the files in tsv/, then hand-edit lexicon.tsv as needed.")


if __name__ == "__main__":
    main()
