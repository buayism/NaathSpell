#!/usr/bin/env python3
"""
evaluate.py — Evaluate the spell checker against a labelled test set.

Reads tests/test_tokens.tsv with columns: token<TAB>label[<TAB>intended]
Labels: OK = correct word, ERR = misspelled.

Reports:
  Errors caught (recall)  = ERR tokens flagged / all ERR tokens
  False alarms            = OK tokens flagged / all OK tokens
  Precision               = ERR tokens flagged / all flagged tokens
  Overall accuracy        = correct decisions / all tokens
  Suggestion hit rate     = ERR tokens where intended appears in top-5
"""

import sys
from pathlib import Path

# Add project root to path so we can import checker
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker import SpellChecker


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    base = Path(__file__).resolve().parent.parent
    test_file = base / "tests" / "test_tokens.tsv"

    if not test_file.exists():
        print(f"ERROR: {test_file} not found.")
        sys.exit(1)

    # Load test data
    rows: list[dict] = []
    with open(test_file, encoding="utf-8") as f:
        header = f.readline().strip().split("\t")
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            row = {}
            for i, col in enumerate(header):
                row[col] = parts[i] if i < len(parts) else ""
            rows.append(row)

    print(f"Loaded {len(rows)} test tokens from {test_file.name}")
    print()

    # Init checker
    lexicon_path = base / "lexicon.tsv"
    if not lexicon_path.exists():
        print(f"ERROR: {lexicon_path} not found. Run review_lexicon.py first.")
        sys.exit(1)

    sc = SpellChecker(lexicon_path, user_additions_path=base / "user_additions.tsv")
    print(f"Lexicon size: {len(sc.lexicon)} words")
    print()

    # Evaluate
    total_ok = 0
    total_err = 0
    ok_flagged = 0
    err_flagged = 0
    ok_not_flagged = 0
    err_not_flagged = 0
    suggestion_hits = 0
    suggestion_possible = 0

    print(f"{'Token':20s} {'Label':6s} {'Flagged':8s} {'Intended':15s} {'Suggestions':40s} {'Hit':4s}")
    print("-" * 95)

    for row in rows:
        token = row["token"]
        label = row["label"].upper()
        intended = row.get("intended", "").strip()

        # Check token through the checker
        results = sc.check_text(token)
        flagged = False
        for r in results:
            if r["normalized"]:
                flagged = not r["is_known"]
                break

        suggestions = sc.suggest(sc.nfc_lower(token), n=5) if flagged else []
        sugg_str = ", ".join(suggestions) if suggestions else ""

        hit = ""
        if label == "OK":
            total_ok += 1
            if flagged:
                ok_flagged += 1
            else:
                ok_not_flagged += 1
        elif label == "ERR":
            total_err += 1
            if flagged:
                err_flagged += 1
            else:
                err_not_flagged += 1
            if intended:
                suggestion_possible += 1
                intended_norm = sc.nfc_lower(intended)
                if intended_norm in suggestions:
                    suggestion_hits += 1
                    hit = "YES"
                else:
                    hit = "no"

        status = "FLAGGED" if flagged else "ok"
        print(f"{token:20s} {label:6s} {status:8s} {intended:15s} {sugg_str:40s} {hit:4s}")

    print("-" * 95)
    print()

    # Compute metrics
    total = len(rows)
    all_flagged = ok_flagged + err_flagged
    correct_decisions = ok_not_flagged + err_flagged

    recall = err_flagged / total_err if total_err else 0
    false_alarm_rate = ok_flagged / total_ok if total_ok else 0
    precision = err_flagged / all_flagged if all_flagged else 0
    accuracy = correct_decisions / total if total else 0
    sugg_rate = suggestion_hits / suggestion_possible if suggestion_possible else 0

    print("=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Total tokens:           {total}")
    print(f"  OK tokens:              {total_ok}")
    print(f"  ERR tokens:             {total_err}")
    print(f"  Flagged tokens:         {all_flagged}")
    print()
    print(f"  Errors caught (recall)  = {err_flagged}/{total_err} = {recall:.1%}")
    print(f"    Definition: ERR tokens flagged / all ERR tokens")
    print(f"  False alarms            = {ok_flagged}/{total_ok} = {false_alarm_rate:.1%}")
    print(f"    Definition: OK tokens flagged / all OK tokens")
    if all_flagged:
        print(f"  Precision               = {err_flagged}/{all_flagged} = {precision:.1%}")
    else:
        print(f"  Precision               = N/A (no tokens flagged)")
    print(f"    Definition: ERR tokens flagged / all flagged tokens")
    print(f"  Overall accuracy        = {correct_decisions}/{total} = {accuracy:.1%}")
    print(f"    Definition: correct decisions / all tokens")
    if suggestion_possible:
        print(f"  Suggestion hit rate     = {suggestion_hits}/{suggestion_possible} = {sugg_rate:.1%}")
    else:
        print(f"  Suggestion hit rate     = N/A (no intended forms given)")
    print(f"    Definition: ERR tokens where intended word appears in top-5 suggestions")
    print("=" * 60)


if __name__ == "__main__":
    main()
