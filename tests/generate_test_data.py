#!/usr/bin/env python3
"""
generate_test_data.py — Build labelled test files for the Manyok-style evaluation.

Creates tests/data/ with 3 TSV files, each containing tokens with labels
(real / nonword) and error metadata.  About 15-20% of tokens are injected
errors.  Errors follow Manyok's four categories: transposition, substitution,
deletion, insertion.

Every injected non-word is verified NOT to be in the lexicon.
Every "real" token is verified to BE in the lexicon.
Tokens that fail verification are discarded and regenerated.

Usage:  python tests/generate_test_data.py
"""

import sys, random, unicodedata, csv, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from checker import SpellChecker, nfc_lower, split_into_units, units_to_str, tokenize_with_offsets

SEED = 42
ERROR_RATIO = 0.18          # ~18 % of tokens will be errors
MAX_INJECT_ATTEMPTS = 50    # retries per word if generated error is in lexicon

BASE = Path(__file__).resolve().parent.parent
LEXICON_PATH = BASE / "lexicon.tsv"
CORPUS_TSV   = BASE / "tsv" / "corpus_wordlist.tsv"
DATA_DIR     = BASE / "tests" / "data"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_corpus_words(path: Path) -> list[tuple[str, int]]:
    """Load word,freq pairs from a TSV."""
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            w = nfc_lower(parts[0])
            freq = int(parts[1]) if len(parts) > 1 else 1
            words.append((w, freq))
    return words


def weighted_sample(words_freqs: list[tuple[str, int]], n: int, rng: random.Random) -> list[str]:
    """Sample n words weighted by frequency (with replacement)."""
    words, freqs = zip(*words_freqs)
    return rng.choices(words, weights=freqs, k=n)


def inject_error(word: str, error_type: str, alphabet: list[str],
                 rng: random.Random) -> str | None:
    """
    Apply one error of the given type to word (operates on character units).
    Returns the mutated word, or None if the operation can't be applied.
    """
    units = split_into_units(word)
    # strip leading "/" for edits
    has_slash = False
    if units and units[0] == "/":
        has_slash = True
        units = units[1:]

    prefix = "/" if has_slash else ""
    n = len(units)

    if error_type == "transposition":
        if n < 2:
            return None
        i = rng.randint(0, n - 2)
        new = units[:i] + [units[i + 1], units[i]] + units[i + 2:]
        return prefix + units_to_str(new)

    elif error_type == "substitution":
        if n < 1:
            return None
        i = rng.randint(0, n - 1)
        candidates = [c for c in alphabet if c != units[i]]
        if not candidates:
            return None
        c = rng.choice(candidates)
        new = units[:i] + [c] + units[i + 1:]
        return prefix + units_to_str(new)

    elif error_type == "deletion":
        if n < 2:  # don't delete from single-unit words
            return None
        i = rng.randint(0, n - 1)
        new = units[:i] + units[i + 1:]
        return prefix + units_to_str(new)

    elif error_type == "insertion":
        if n < 1:
            return None
        i = rng.randint(0, n)
        c = rng.choice(alphabet)
        new = units[:i] + [c] + units[i:]
        return prefix + units_to_str(new)

    return None


def build_alphabet(sc: SpellChecker) -> list[str]:
    """Get the character-unit alphabet from the spell checker."""
    return sorted(sc._alphabet)


def generate_test_file(
    name: str,
    description: str,
    words_freqs: list[tuple[str, int]],
    target_tokens: int,
    sc: SpellChecker,
    alphabet: list[str],
    rng: random.Random,
    out_dir: Path,
) -> dict:
    """Generate one labelled test file. Returns stats dict."""
    # Sample real words
    sampled = weighted_sample(words_freqs, target_tokens, rng)

    # Filter to only words that are actually in the lexicon
    real_tokens = [w for w in sampled if sc.is_known(w)]
    if len(real_tokens) < target_tokens * 0.7:
        # pad if too many were removed
        real_tokens = real_tokens[:target_tokens]
    real_tokens = real_tokens[:target_tokens]

    # Decide which positions get errors
    n = len(real_tokens)
    n_errors = int(n * ERROR_RATIO)
    error_indices = set(rng.sample(range(n), min(n_errors, n)))

    error_types = ["transposition", "substitution", "deletion", "insertion"]
    rows = []
    stats = {"total": 0, "real": 0, "nonword": 0,
             "transposition": 0, "substitution": 0, "deletion": 0, "insertion": 0,
             "discarded": 0}

    for idx in range(n):
        word = real_tokens[idx]
        if idx in error_indices:
            # Try to inject an error
            etype = rng.choice(error_types)
            success = False
            for _ in range(MAX_INJECT_ATTEMPTS):
                mutated = inject_error(word, etype, alphabet, rng)
                if mutated and mutated != word and not sc.is_known(nfc_lower(mutated)):
                    rows.append({
                        "token": mutated,
                        "label": "nonword",
                        "intended": word,
                        "error_type": etype,
                    })
                    stats["nonword"] += 1
                    stats[etype] += 1
                    stats["total"] += 1
                    success = True
                    break
            if not success:
                # Could not generate a valid non-word; keep as real
                rows.append({
                    "token": word,
                    "label": "real",
                    "intended": "",
                    "error_type": "",
                })
                stats["real"] += 1
                stats["total"] += 1
                stats["discarded"] += 1
        else:
            rows.append({
                "token": word,
                "label": "real",
                "intended": "",
                "error_type": "",
            })
            stats["real"] += 1
            stats["total"] += 1

    # Write TSV
    out_path = out_dir / f"{name}.tsv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["token", "label", "intended", "error_type"])
        for row in rows:
            writer.writerow([row["token"], row["label"], row["intended"], row["error_type"]])

    stats["file"] = str(out_path.name)
    stats["description"] = description
    print(f"  {name}.tsv: {stats['total']} tokens "
          f"({stats['real']} real, {stats['nonword']} nonword, "
          f"{stats['discarded']} failed injections)")
    return stats


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rng = random.Random(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading lexicon and corpus...")
    sc = SpellChecker(str(LEXICON_PATH))
    corpus = load_corpus_words(CORPUS_TSV)
    alphabet = build_alphabet(sc)
    print(f"  Lexicon: {len(sc.lexicon)} words")
    print(f"  Corpus unique words: {len(corpus)}")
    print(f"  Alphabet units: {len(alphabet)}")
    print()

    # Split corpus words into groups for different test files
    # Sort by frequency descending
    corpus_sorted = sorted(corpus, key=lambda x: -x[1])

    # File 1: High-frequency words (narrative/story-like text)
    high_freq = [(w, f) for w, f in corpus_sorted if f >= 5]
    # File 2: Mixed-frequency words
    mid_freq = [(w, f) for w, f in corpus_sorted if f >= 2]
    # File 3: Full distribution (including rare words)
    all_words = corpus_sorted

    files_config = [
        ("test_narrative", "High-frequency words (narrative text simulation)", high_freq, 500),
        ("test_mixed", "Mixed-frequency words (general text)", mid_freq, 400),
        ("test_rare", "Full frequency distribution (including rare words)", all_words, 350),
    ]

    print("Generating test files...")
    all_stats = []
    for name, desc, wf, target in files_config:
        stats = generate_test_file(name, desc, wf, target, sc, alphabet, rng, DATA_DIR)
        all_stats.append(stats)

    # Write README
    readme_path = DATA_DIR / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("# Test Data for Manyok-style Evaluation\n\n")
        f.write(f"Generated with seed={SEED}, error_ratio={ERROR_RATIO:.0%}\n\n")
        f.write("## Error Types\n\n")
        f.write("Following Manyok & Balagadde (2022), errors are injected using four operations:\n\n")
        f.write("- **Transposition**: swap two adjacent character units\n")
        f.write("- **Substitution**: replace one character unit with another from the Nuer alphabet\n")
        f.write("- **Deletion**: remove one character unit\n")
        f.write("- **Insertion**: insert a random Nuer character unit\n\n")
        f.write("Character units are base letters with their combining marks (e.g., ɛ̈ is one unit).\n\n")
        f.write("## Verification\n\n")
        f.write("- Every `real` token is verified to be in `lexicon.tsv`\n")
        f.write("- Every `nonword` token is verified NOT to be in `lexicon.tsv`\n")
        f.write("- If an injected error happens to be a real word, it is discarded and the token kept as `real`\n\n")
        f.write("## Files\n\n")
        f.write("| File | Description | Total | Real | Non-word | Trans | Subst | Del | Ins |\n")
        f.write("|------|-------------|-------|------|----------|-------|-------|-----|-----|\n")
        for s in all_stats:
            f.write(f"| {s['file']} | {s['description']} | {s['total']} | {s['real']} | {s['nonword']} "
                    f"| {s['transposition']} | {s['substitution']} | {s['deletion']} | {s['insertion']} |\n")
        f.write(f"\nSeed: {SEED}\n")

    print(f"\nREADME written to {readme_path}")
    print("Done.")


if __name__ == "__main__":
    main()
