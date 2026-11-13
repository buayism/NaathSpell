#!/usr/bin/env python3
"""
checker.py — Nuer non-word spell checker (core module, no UI).

Uses the SAME tokenizer logic as build_lexicon.py:
  - NFC normalisation + lowercase
  - Word = maximal run of Unicode letters (L*) + combining marks (M*)
  - "/" directly before a word (after whitespace / line-start / opener) is
    kept as part of the token → "cu" ≠ "/cu"

Public API
----------
  SpellChecker(lexicon_path, user_additions_path=None)
  .check_text(text, ignore_capitalised=False)  →  list[dict]
  .suggest(token, n=5)                         →  list[str]
  .add_word(word)                              →  None
  .ignore_word(word)                           →  None
  .nfc_lower(text)                             →  str   (class method)
"""

import sys
import unicodedata
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Tokenizer — identical logic to build_lexicon.py
# ---------------------------------------------------------------------------

def nfc_lower(text: str) -> str:
    """NFC-normalise and lowercase."""
    return unicodedata.normalize("NFC", text).lower()


def _is_letter_or_mark(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M")


# Opening quotes / brackets that can precede a negation "/"
_OPENERS = set("\"'«([{‹‟„⸢⸤\u201C\u2018\u00AB")


def tokenize_with_offsets(text: str):
    """
    Tokenize *text* (must already be NFC-lowered) and return
    (tokens, non_neg_slash_count) where each token is a dict:
      {"token": str, "start": int, "end": int}

    start/end are character offsets into the NFC-lowered text.
    """
    tokens: list[dict] = []
    non_neg_slash = 0
    buf: list[str] = []
    buf_start: int = 0
    has_neg_prefix = False
    neg_start: int = 0
    i = 0
    n = len(text)

    def flush():
        nonlocal has_neg_prefix, neg_start
        if buf:
            word = "".join(buf)
            if any(unicodedata.category(c)[0] == "L" for c in word):
                if has_neg_prefix:
                    tokens.append({
                        "token": "/" + word,
                        "start": neg_start,
                        "end": buf_start + len(word),
                    })
                else:
                    tokens.append({
                        "token": word,
                        "start": buf_start,
                        "end": buf_start + len(word),
                    })
            buf.clear()
            has_neg_prefix = False

    while i < n:
        ch = text[i]

        if _is_letter_or_mark(ch):
            if not buf:
                buf_start = i
            buf.append(ch)
            i += 1
            continue

        if ch == "/":
            if buf:
                flush()
                non_neg_slash += 1
                i += 1
                continue

            if i == 0:
                is_neg = True
            else:
                prev = text[i - 1]
                is_neg = prev.isspace() or prev in _OPENERS

            if is_neg and (i + 1 < n) and unicodedata.category(text[i + 1])[0] == "L":
                has_neg_prefix = True
                neg_start = i
                i += 1
                continue
            else:
                non_neg_slash += 1
                i += 1
                continue
        else:
            flush()
            i += 1
            continue

    flush()
    return tokens, non_neg_slash


# ---------------------------------------------------------------------------
# Character-unit helpers
#
# A "character unit" is a base letter followed by zero or more combining
# marks.  Edit-distance operations work on these units so that ɛ̈ (ɛ + ̈)
# is never split into two edits.
# ---------------------------------------------------------------------------

def split_into_units(word: str) -> list[str]:
    """
    Split a word into character units: each unit is a base letter + any
    trailing combining marks.  A leading "/" (negation) is its own unit.
    """
    units: list[str] = []
    i = 0
    n = len(word)

    # Handle leading "/"
    if n > 0 and word[0] == "/":
        units.append("/")
        i = 1

    while i < n:
        ch = word[i]
        cat = unicodedata.category(ch)
        if cat[0] == "L":
            # Base letter — start a unit
            unit = ch
            j = i + 1
            while j < n and unicodedata.category(word[j])[0] == "M":
                unit += word[j]
                j += 1
            units.append(unit)
            i = j
        elif cat[0] == "M":
            # Orphan combining mark (shouldn't happen in well-formed text)
            # Attach it to previous unit if possible
            if units and units[-1] != "/":
                units[-1] += ch
            else:
                units.append(ch)
            i += 1
        else:
            # Unexpected character — treat as its own unit
            units.append(ch)
            i += 1

    return units


def units_to_str(units: list[str]) -> str:
    return "".join(units)


# ---------------------------------------------------------------------------
# SpellChecker
# ---------------------------------------------------------------------------

class SpellChecker:
    """Dictionary-lookup spell checker with edit-distance suggestions."""

    nfc_lower = staticmethod(nfc_lower)

    def __init__(self, lexicon_path, user_additions_path=None):
        self.lexicon: dict[str, int] = {}
        self._ignored: set[str] = set()
        self._user_additions_path = Path(user_additions_path) if user_additions_path else None
        self._alphabet: set[str] = set()   # character units in the lexicon

        # Load main lexicon
        self._load_tsv(Path(lexicon_path))

        # Load user additions if they exist
        if self._user_additions_path and self._user_additions_path.exists():
            self._load_tsv(self._user_additions_path)

        # Build the edit alphabet from all lexicon words
        self._build_alphabet()

    def _load_tsv(self, path: Path):
        with open(path, encoding="utf-8") as f:
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
                    self.lexicon[word] = self.lexicon.get(word, 0) + freq
                elif len(parts) == 1:
                    word = nfc_lower(parts[0])
                    self.lexicon[word] = self.lexicon.get(word, 0) + 1

    def _build_alphabet(self):
        """Extract every unique character-unit found in the lexicon."""
        units: set[str] = set()
        for word in self.lexicon:
            for u in split_into_units(word):
                if u != "/":
                    units.add(u)
        self._alphabet = units

    def is_known(self, token: str) -> bool:
        """Check if a normalised token is in the lexicon or ignored."""
        return token in self.lexicon or token in self._ignored

    def check_text(self, text: str, ignore_capitalised: bool = False):
        """
        Check text and return a list of results.

        Each result is a dict:
          original   — substring as it appears in the original text
          normalized — NFC-lowered token
          start      — character offset in original text
          end        — character offset in original text
          is_known   — bool
        """
        # We need to map offsets from the normalised text back to the
        # original.  Since NFC + lowercase can change string lengths in
        # rare cases, we build a mapping.
        norm_text = nfc_lower(text)
        tokens_info, _ = tokenize_with_offsets(norm_text)

        results: list[dict] = []
        for info in tokens_info:
            tok = info["token"]
            start = info["start"]
            end = info["end"]

            # Skip pure-digit tokens (shouldn't appear since the tokenizer
            # only yields letters+marks, but guard anyway)
            if all(c.isdigit() for c in tok.replace("/", "")):
                continue

            # Original text slice (approximate — offsets refer to norm_text)
            orig_slice = text[start:end]

            # Capitalisation check: if the option is on and the original word
            # starts with an uppercase letter and it's not the first word,
            # treat it as known (likely a proper noun).
            if ignore_capitalised and start > 0:
                # Check if the original text at this position starts uppercase
                first_letter = ""
                for ch in orig_slice:
                    if unicodedata.category(ch)[0] == "L":
                        first_letter = ch
                        break
                if first_letter and first_letter.isupper():
                    results.append({
                        "original": orig_slice,
                        "normalized": tok,
                        "start": start,
                        "end": end,
                        "is_known": True,
                    })
                    continue

            known = self.is_known(tok)
            results.append({
                "original": orig_slice,
                "normalized": tok,
                "start": start,
                "end": end,
                "is_known": known,
            })

        return results

    def suggest(self, token: str, n: int = 5) -> list[str]:
        """
        Generate up to *n* spelling suggestions for an unknown *token*.

        Strategy:
        1. Slash-toggle: if "/X" is unknown but "X" exists (or vice versa),
           put that first.
        2. Damerau-Levenshtein distance 1 candidates from the lexicon.
        3. If no distance-1 candidates and the word has >= 5 units, try
           distance 2.
        4. Rank by corpus frequency descending, then by shorter length.
        """
        token = nfc_lower(token)
        candidates: list[str] = []
        seen: set[str] = set()

        def _add(w):
            if w not in seen and w != token:
                seen.add(w)
                candidates.append(w)

        # 1. Slash-toggle
        if token.startswith("/"):
            pos = token[1:]
            if pos in self.lexicon:
                _add(pos)
        else:
            neg = "/" + token
            if neg in self.lexicon:
                _add(neg)

        # 2. Distance-1 edits
        units = split_into_units(token)
        # Strip the leading "/" unit for edit operations if present
        has_slash = False
        if units and units[0] == "/":
            has_slash = True
            word_units = units[1:]
        else:
            word_units = units

        d1 = self._edits_at_distance(word_units, 1, has_slash)
        for w in d1:
            if w in self.lexicon:
                _add(w)

        # 3. Distance-2 fallback if len >= 5 and few d1 candidates
        if len([c for c in candidates if c in self.lexicon]) < n and len(word_units) >= 5:
            d2 = self._edits_at_distance(word_units, 2, has_slash)
            for w in d2:
                if w in self.lexicon:
                    _add(w)

        # 4. Rank by frequency desc, then shorter length
        ranked = sorted(
            [c for c in candidates if c in self.lexicon],
            key=lambda w: (-self.lexicon.get(w, 0), len(w)),
        )

        # Keep slash-toggle first if it was found
        result: list[str] = []
        for c in candidates:
            if c in self.lexicon and c not in ranked:
                continue
            # Slash-toggle candidates were added first
        # Actually, let's just do: if the first candidate is the slash-toggle,
        # keep it at position 0 and then add the rest from ranked.
        slash_toggle = None
        if candidates and (
            (token.startswith("/") and candidates[0] == token[1:]) or
            (not token.startswith("/") and candidates[0] == "/" + token)
        ):
            slash_toggle = candidates[0]

        result = []
        if slash_toggle and slash_toggle in self.lexicon:
            result.append(slash_toggle)
        for w in ranked:
            if w not in result:
                result.append(w)
            if len(result) >= n:
                break

        return result[:n]

    def _edits_at_distance(self, word_units: list[str], dist: int,
                           has_slash: bool) -> set[str]:
        """Generate all strings within Damerau-Levenshtein distance *dist*."""
        prefix = "/" if has_slash else ""
        if dist == 1:
            return self._dl1(word_units, prefix)
        else:
            # Distance 2: apply dl1 to every dl1 result
            d1_set = self._dl1(word_units, prefix)
            d2_set: set[str] = set()
            for w in d1_set:
                # Re-parse into units
                wu = split_into_units(w)
                hs = False
                if wu and wu[0] == "/":
                    hs = True
                    wu = wu[1:]
                pfx = "/" if hs else ""
                for w2 in self._dl1(wu, pfx):
                    if w2 in self.lexicon:
                        d2_set.add(w2)
                        if len(d2_set) > 500:  # cap to avoid explosion
                            return d2_set
            return d2_set

    def _dl1(self, units: list[str], prefix: str) -> set[str]:
        """
        All strings within Damerau-Levenshtein distance 1 of the given units.
        Operations: delete, transpose, substitute, insert.
        All operations work on character-units (not raw code points).
        """
        results: set[str] = set()
        n = len(units)
        alpha = self._alphabet

        # Deletes
        for i in range(n):
            new = units[:i] + units[i+1:]
            results.add(prefix + units_to_str(new))

        # Transposes
        for i in range(n - 1):
            new = units[:i] + [units[i+1], units[i]] + units[i+2:]
            results.add(prefix + units_to_str(new))

        # Substitutes
        for i in range(n):
            for c in alpha:
                if c != units[i]:
                    new = units[:i] + [c] + units[i+1:]
                    results.add(prefix + units_to_str(new))

        # Inserts
        for i in range(n + 1):
            for c in alpha:
                new = units[:i] + [c] + units[i:]
                results.add(prefix + units_to_str(new))

        return results

    def add_word(self, word: str):
        """
        Add a word to the session lexicon and append it to user_additions.tsv.
        Never rewrites lexicon.tsv.
        """
        word = nfc_lower(word)
        if word in self.lexicon:
            return
        self.lexicon[word] = 1
        # Update alphabet
        for u in split_into_units(word):
            if u != "/":
                self._alphabet.add(u)
        # Persist
        if self._user_additions_path:
            with open(self._user_additions_path, "a", encoding="utf-8", newline="") as f:
                f.write(f"{word}\t1\n")

    def ignore_word(self, word: str):
        """Ignore a word for this session only (not persisted)."""
        word = nfc_lower(word)
        self._ignored.add(word)
