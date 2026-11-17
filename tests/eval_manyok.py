#!/usr/bin/env python3
"""
eval_manyok.py — Replicable Manyok-style evaluation of the Nuer spell checker.

Replicates the evaluation methodology from:
  "Prototyping NLP Non-Word Detection System for Dinka Using Dictionary
   Lookup Approach" (Manyok Chol David & Robert Balagadde Ssali, IJNLC 2022)

Runs five test suites:
  1. Detection accuracy on labelled test files
  2. Speed of detection (tokens vs time)
  3. Suggestion / correction accuracy (edit distance 1 and 2)
  4. Unit tests (pytest-compatible, plain assertions)
  5. Lexicon coverage (OOV rate)

Usage:
  python tests/eval_manyok.py          # full evaluation
  python -m pytest tests/eval_manyok.py -v   # run unit tests only (needs pytest)

Outputs:
  results/eval_report.md      — markdown report with all tables
  results/eval_results.json   — machine-readable results
  results/detection.csv       — per-file detection metrics
  results/speed.csv           — speed experiment table
  results/suggestion.csv      — suggestion accuracy table
  results/speed.png           — line chart (if matplotlib available)
"""

import sys
import os
import csv
import json
import time
import platform
import unicodedata
import tempfile
import shutil
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Setup paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE       = SCRIPT_DIR.parent
DATA_DIR   = SCRIPT_DIR / "data"
RESULTS    = BASE / "results"

sys.path.insert(0, str(BASE))
from checker import SpellChecker, nfc_lower, tokenize_with_offsets, split_into_units

LEXICON_PATH = BASE / "lexicon.tsv"
CORPUS_TSV   = BASE / "tsv" / "corpus_wordlist.tsv"

# Try matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def safe_div(a, b):
    return a / b if b else 0.0


def load_test_file(path: Path) -> list[dict]:
    """Load a labelled TSV test file."""
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def fmt_pct(v):
    return f"{v:.1%}"


def fmt_f(v, d=4):
    return f"{v:.{d}f}"

# ============================================================================
# TEST 1 — Detection accuracy on labelled test files
# ============================================================================

def run_detection(sc: SpellChecker, data_dir: Path) -> dict:
    """Run detection on all test files and compute Manyok metrics."""
    test_files = sorted(data_dir.glob("test_*.tsv"))
    if not test_files:
        print("  ERROR: No test_*.tsv files found in", data_dir)
        return {}

    all_results = []
    for tf in test_files:
        rows = load_test_file(tf)
        # TP = real words correctly accepted (is_known=True, label=real)
        # TN = non-words correctly flagged  (is_known=False, label=nonword)
        # FP = non-words missed (is_known=True, label=nonword)  — checker fails to flag
        # FN = real words wrongly flagged (is_known=False, label=real)
        tp = tn = fp = fn = 0

        for row in rows:
            token = row["token"]
            label = row["label"].strip().lower()

            # Use the public API
            results = sc.check_text(token)
            is_known = True  # default
            for r in results:
                if r["normalized"]:
                    is_known = r["is_known"]
                    break

            if label == "real":
                if is_known:
                    tp += 1
                else:
                    fn += 1
            elif label == "nonword":
                if not is_known:
                    tn += 1
                else:
                    fp += 1

        n = tp + tn + fp + fn
        accuracy = safe_div(tp + tn, n)
        tpr = safe_div(tp, tp + fn)
        tnr = safe_div(tn, tn + fp)
        nwd_accuracy = tnr  # Manyok: NWD/TNW = TN/(TN+FP) = TNR

        # Standard metrics (non-word as positive class)
        std_precision = safe_div(tn, tn + fn)      # predicted non-word correctly / all predicted non-word
        std_recall = safe_div(tn, tn + fp)          # = TNR = Manyok's NWD accuracy
        std_f1 = safe_div(2 * std_precision * std_recall, std_precision + std_recall)

        result = {
            "file": tf.name,
            "N": n,
            "TP": tp, "TN": tn, "FP": fp, "FN": fn,
            "accuracy": accuracy,
            "TPR": tpr,
            "TNR": tnr,
            "NWD_accuracy": nwd_accuracy,
            "std_precision": std_precision,
            "std_recall": std_recall,
            "std_F1": std_f1,
        }
        all_results.append(result)

        print(f"  {tf.name}: N={n} TP={tp} TN={tn} FP={fp} FN={fn} "
              f"Acc={fmt_pct(accuracy)} TPR={fmt_pct(tpr)} TNR={fmt_pct(tnr)}")

    # Averages
    if all_results:
        avg = {}
        for key in ["accuracy", "TPR", "TNR", "NWD_accuracy",
                     "std_precision", "std_recall", "std_F1"]:
            avg[key] = sum(r[key] for r in all_results) / len(all_results)
        avg["N"] = sum(r["N"] for r in all_results)
        avg["TP"] = sum(r["TP"] for r in all_results)
        avg["TN"] = sum(r["TN"] for r in all_results)
        avg["FP"] = sum(r["FP"] for r in all_results)
        avg["FN"] = sum(r["FN"] for r in all_results)
    else:
        avg = {}

    return {"per_file": all_results, "average": avg}


# ============================================================================
# TEST 2 — Speed of detection
# ============================================================================

def run_speed(sc: SpellChecker, data_dir: Path) -> dict:
    """Measure detection speed at increasing token counts."""
    # Build a large pool of tokens from test data
    pool = []
    for tf in sorted(data_dir.glob("test_*.tsv")):
        rows = load_test_file(tf)
        pool.extend(r["token"] for r in rows)

    if not pool:
        print("  ERROR: No tokens for speed test")
        return {}

    # Extend pool by repeating
    while len(pool) < 6000:
        pool = pool + pool

    targets = [150, 300, 500, 750, 1000, 1500, 2000, 3000, 5000]
    results = []
    repeats = 3

    for target_n in targets:
        tokens = pool[:target_n]
        # Build a single text string
        text = " ".join(tokens)

        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            # Time only tokenize + lookup (the detection step)
            norm = nfc_lower(text)
            tok_info, _ = tokenize_with_offsets(norm)
            for ti in tok_info:
                sc.is_known(ti["token"])
            t1 = time.perf_counter()
            times.append(t1 - t0)

        median_time = sorted(times)[len(times) // 2]
        actual_tokens = len(tok_info)
        hz = safe_div(actual_tokens, median_time)
        ms = median_time * 1000

        results.append({
            "target_tokens": target_n,
            "actual_tokens": actual_tokens,
            "time_ms": round(ms, 2),
            "hz": round(hz, 1),
        })
        print(f"  {target_n:5d} tokens → {actual_tokens:5d} actual, "
              f"{ms:8.2f} ms, {hz:8.1f} Hz")

    avg_hz = sum(r["hz"] for r in results) / len(results) if results else 0

    return {
        "experiments": results,
        "avg_hz": round(avg_hz, 1),
        "python_version": sys.version.split()[0],
        "cpu": platform.processor(),
        "lexicon_size": len(sc.lexicon),
    }


# ============================================================================
# TEST 3 — Suggestion and correction accuracy
# ============================================================================

def suggest_at_max_distance(sc: SpellChecker, token: str, max_dist: int,
                            n: int = 5) -> list[str]:
    """
    Generate suggestions limited to a specific max edit distance.

    For max_dist=1: only use distance-1 edits (no distance-2 fallback).
    For max_dist=2: use the standard suggest() which includes distance-2.
    """
    token = nfc_lower(token)
    candidates = []
    seen = set()

    def _add(w):
        if w not in seen and w != token:
            seen.add(w)
            candidates.append(w)

    # Slash toggle (always)
    if token.startswith("/"):
        pos = token[1:]
        if pos in sc.lexicon:
            _add(pos)
    else:
        neg = "/" + token
        if neg in sc.lexicon:
            _add(neg)

    # Distance-1 edits
    units = split_into_units(token)
    has_slash = False
    if units and units[0] == "/":
        has_slash = True
        word_units = units[1:]
    else:
        word_units = units

    prefix = "/" if has_slash else ""
    d1 = sc._dl1(word_units, prefix)
    for w in d1:
        if w in sc.lexicon:
            _add(w)

    # Distance-2 edits (only if max_dist >= 2)
    if max_dist >= 2 and len([c for c in candidates if c in sc.lexicon]) < n:
        d2 = sc._edits_at_distance(word_units, 2, has_slash)
        for w in d2:
            if w in sc.lexicon:
                _add(w)

    # Rank by frequency
    ranked = sorted(
        [c for c in candidates if c in sc.lexicon],
        key=lambda w: (-sc.lexicon.get(w, 0), len(w)),
    )
    return ranked[:n]


def run_suggestion(sc: SpellChecker, data_dir: Path) -> dict:
    """Evaluate suggestion accuracy by error type and edit distance."""
    # Collect all non-word rows with known intended words
    nonwords = []
    for tf in sorted(data_dir.glob("test_*.tsv")):
        rows = load_test_file(tf)
        for r in rows:
            if r["label"].strip().lower() == "nonword" and r.get("intended", "").strip():
                nonwords.append(r)

    if not nonwords:
        print("  ERROR: No non-word tokens with intended words found")
        return {}

    results_by_dist = {}
    for max_dist in [1, 2]:
        by_type = {}
        total_hit1 = total_hit3 = total_hit5 = 0
        total_no_sugg = 0
        total_sugg_count = 0

        for row in nonwords:
            token = row["token"]
            intended = nfc_lower(row["intended"].strip())
            etype = row.get("error_type", "unknown").strip()

            suggestions = suggest_at_max_distance(sc, token, max_dist, n=5)
            n_sugg = len(suggestions)
            total_sugg_count += n_sugg

            if n_sugg == 0:
                total_no_sugg += 1

            hit1 = intended in suggestions[:1]
            hit3 = intended in suggestions[:3]
            hit5 = intended in suggestions[:5]

            if hit1: total_hit1 += 1
            if hit3: total_hit3 += 1
            if hit5: total_hit5 += 1

            if etype not in by_type:
                by_type[etype] = {"total": 0, "hit1": 0, "hit3": 0, "hit5": 0, "no_sugg": 0}
            by_type[etype]["total"] += 1
            if hit1: by_type[etype]["hit1"] += 1
            if hit3: by_type[etype]["hit3"] += 1
            if hit5: by_type[etype]["hit5"] += 1
            if n_sugg == 0: by_type[etype]["no_sugg"] += 1

        n_total = len(nonwords)
        results_by_dist[max_dist] = {
            "total": n_total,
            "top1_acc": safe_div(total_hit1, n_total),
            "top3_acc": safe_div(total_hit3, n_total),
            "top5_acc": safe_div(total_hit5, n_total),
            "no_suggestion_rate": safe_div(total_no_sugg, n_total),
            "avg_suggestions": safe_div(total_sugg_count, n_total),
            "by_type": by_type,
        }

        print(f"  Distance ≤ {max_dist}: top-1={fmt_pct(safe_div(total_hit1, n_total))} "
              f"top-3={fmt_pct(safe_div(total_hit3, n_total))} "
              f"top-5={fmt_pct(safe_div(total_hit5, n_total))} "
              f"no_sugg={fmt_pct(safe_div(total_no_sugg, n_total))} "
              f"avg_sugg={safe_div(total_sugg_count, n_total):.1f}")

    return results_by_dist


# ============================================================================
# TEST 4 — Unit tests (pytest-compatible with plain assertions)
# ============================================================================

def _run_unit_tests(sc: SpellChecker):
    """Run unit tests and return (passed, failed, details)."""
    passed = 0
    failed = 0
    details = []

    def _test(name, condition, msg=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            details.append(("PASS", name, msg))
        else:
            failed += 1
            details.append(("FAIL", name, msg))

    # --- Detection: a sentence with induced non-words flags exactly those tokens ---
    text = "kɛ naath xkɛ cuɛ naaht"
    results = sc.check_text(text)
    flagged_tokens = {r["normalized"] for r in results if not r["is_known"]}
    known_tokens = {r["normalized"] for r in results if r["is_known"]}

    _test("detection_flags_nonwords",
          "xkɛ" in flagged_tokens and "naaht" in flagged_tokens,
          f"flagged={flagged_tokens}")

    _test("detection_accepts_real_words",
          "kɛ" in known_tokens and "naath" in known_tokens and "cuɛ" in known_tokens,
          f"known={known_tokens}")

    # --- Suggestion: for known misspellings, the correct word is among suggestions ---
    sugg_naath = sc.suggest("naaht", n=5)
    _test("suggestion_naaht_contains_naath",
          "naath" in sugg_naath,
          f"suggestions={sugg_naath}")

    sugg_xke = sc.suggest("xkɛ", n=5)
    _test("suggestion_xke_contains_ke",
          "kɛ" in sugg_xke,
          f"suggestions={sugg_xke}")

    # --- Add: add a flagged word to a temporary lexicon copy ---
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_lex = Path(tmpdir) / "lexicon.tsv"
        shutil.copy2(str(LEXICON_PATH), str(tmp_lex))
        tmp_user = Path(tmpdir) / "user_additions.tsv"

        tmp_sc = SpellChecker(str(tmp_lex), user_additions_path=str(tmp_user))

        # Word should be unknown initially
        test_word = "xyznonword"
        _test("add_word_initially_unknown",
              not tmp_sc.is_known(test_word),
              f"is_known({test_word})={tmp_sc.is_known(test_word)}")

        # Add it
        tmp_sc.add_word(test_word)
        _test("add_word_now_known",
              tmp_sc.is_known(test_word),
              f"is_known({test_word})={tmp_sc.is_known(test_word)} after add")

        # Check it's not flagged in check_text
        results2 = tmp_sc.check_text(test_word)
        is_known_after = all(r["is_known"] for r in results2)
        _test("add_word_not_flagged_in_check_text",
              is_known_after,
              f"results={results2}")

    # --- Ignore: an ignored word is not flagged again ---
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_lex = Path(tmpdir) / "lexicon.tsv"
        shutil.copy2(str(LEXICON_PATH), str(tmp_lex))
        tmp_sc2 = SpellChecker(str(tmp_lex))

        ignore_word = "xyzignoretest"
        _test("ignore_initially_flagged",
              not tmp_sc2.is_known(ignore_word))

        tmp_sc2.ignore_word(ignore_word)
        _test("ignore_not_flagged_after_ignore",
              tmp_sc2.is_known(ignore_word),
              "word is known after ignore_word()")

    # --- Tokenization: Nuer special characters and combining diacritics ---
    # i̱ = i + U+0331 COMBINING MACRON BELOW — must stay together
    text_diac = "mi̱ ɛ̈ ɔ̈"
    results_diac = sc.check_text(text_diac)
    tokens_diac = [r["normalized"] for r in results_diac]
    _test("tokenize_combining_marks_not_split",
          "mi̱" in tokens_diac,
          f"tokens={tokens_diac}")

    # Test that ɛ̈ (ɛ + combining diaeresis) is one token
    has_epsilon_diaeresis = any("ɛ" in t and "\u0308" in t for t in tokens_diac) or "ɛ̈" in tokens_diac
    # It might not be in the lexicon but it should be one token
    _test("tokenize_epsilon_diaeresis_one_token",
          has_epsilon_diaeresis or len(tokens_diac) == 3,
          f"tokens={tokens_diac}, expected 3 tokens")

    # Negation prefix
    text_neg = "/cu kɛ"
    results_neg = sc.check_text(text_neg)
    neg_tokens = [r["normalized"] for r in results_neg]
    _test("tokenize_negation_prefix",
          "/cu" in neg_tokens,
          f"tokens={neg_tokens}")

    # --- Numbers, all-caps, Title Case (optional, report behaviour) ---
    text_caps = "KƐ Naath KUOTH 123 mi̱"
    results_caps = sc.check_text(text_caps)
    caps_info = [(r["original"], r["normalized"], r["is_known"]) for r in results_caps]
    # Just report, don't assert pass/fail
    _test("optional_caps_numbers_report",
          True,  # always pass, just documenting
          f"Behaviour: {caps_info}")

    return passed, failed, details


# ============================================================================
# TEST 5 — Lexicon coverage
# ============================================================================

def run_coverage(sc: SpellChecker) -> dict:
    """Measure lexicon coverage and OOV rate."""
    lexicon_size = len(sc.lexicon)

    # Try to find held-out text
    # The merged_wordlist.tsv has words NOT from the corpus — those came from
    # other sources.  The corpus was used to build the lexicon, so it's not
    # truly held-out.  We note this honestly.
    # For OOV, we use corpus_wordlist.tsv words against the lexicon
    oov_tokens = 0
    total_tokens = 0
    oov_words = []

    if CORPUS_TSV.exists():
        with open(CORPUS_TSV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                word = nfc_lower(parts[0])
                freq = int(parts[1]) if len(parts) > 1 else 1
                total_tokens += freq
                if not sc.is_known(word):
                    oov_tokens += freq
                    oov_words.append(word)

    oov_rate = safe_div(oov_tokens, total_tokens)

    return {
        "lexicon_size": lexicon_size,
        "total_corpus_tokens": total_tokens,
        "oov_tokens": oov_tokens,
        "oov_rate": oov_rate,
        "oov_unique_words": len(oov_words),
        "oov_examples": oov_words[:20],
        "note": ("The lexicon was built from the same corpus, so the OOV rate "
                 "on in-corpus text is artificially low. A truly held-out test "
                 "set was not available."),
    }


# ============================================================================
# Report generation
# ============================================================================

def write_report(detection, speed, suggestion, unit_tests, coverage, out_dir: Path):
    """Write the full markdown report and supporting files."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- eval_report.md ---
    report_path = out_dir / "eval_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Nuer Spell Checker — Manyok-style Evaluation Report\n\n")
        f.write("Replicating the evaluation methodology from Manyok Chol David & "
                "Robert Balagadde Ssali (IJNLC 2022).\n\n")

        # --- 1. Detection ---
        f.write("## 1. Detection Accuracy\n\n")
        f.write("### Manyok's convention\n\n")
        f.write("| Metric | Definition |\n")
        f.write("|--------|------------|\n")
        f.write("| TP | Real words the checker correctly accepts |\n")
        f.write("| TN | Non-words the checker correctly flags |\n")
        f.write("| FP | Non-words the checker fails to flag (missed errors) |\n")
        f.write("| FN | Real words the checker wrongly flags |\n")
        f.write("| Accuracy | (TP + TN) / N |\n")
        f.write("| TPR | TP / (TP + FN) |\n")
        f.write("| TNR | TN / (TN + FP) = Non-word detection accuracy |\n\n")

        f.write("### Per-file results (Table 2)\n\n")
        f.write("| File | N | TP | TN | FP | FN | Accuracy | TPR | TNR (NWD Acc) |\n")
        f.write("|------|---|----|----|----|----|----------|-----|---------------|\n")
        if detection.get("per_file"):
            for r in detection["per_file"]:
                f.write(f"| {r['file']} | {r['N']} | {r['TP']} | {r['TN']} | {r['FP']} | {r['FN']} "
                        f"| {fmt_pct(r['accuracy'])} | {fmt_pct(r['TPR'])} | {fmt_pct(r['TNR'])} |\n")
            avg = detection["average"]
            f.write(f"| **Average** | {avg['N']} | {avg['TP']} | {avg['TN']} | {avg['FP']} | {avg['FN']} "
                    f"| **{fmt_pct(avg['accuracy'])}** | **{fmt_pct(avg['TPR'])}** | **{fmt_pct(avg['TNR'])}** |\n")

        f.write("\n### Standard metrics (non-word = positive class)\n\n")
        f.write("| File | Precision | Recall (=TNR) | F1 |\n")
        f.write("|------|-----------|---------------|----|\n")
        if detection.get("per_file"):
            for r in detection["per_file"]:
                f.write(f"| {r['file']} | {fmt_pct(r['std_precision'])} "
                        f"| {fmt_pct(r['std_recall'])} | {fmt_pct(r['std_F1'])} |\n")
            avg = detection["average"]
            f.write(f"| **Average** | **{fmt_pct(avg['std_precision'])}** "
                    f"| **{fmt_pct(avg['std_recall'])}** | **{fmt_pct(avg['std_F1'])}** |\n")

        f.write("\n> **Label mapping note:** In Manyok's convention, TP/FN refer to real words "
                "and TN/FP to non-words. In standard IR convention where non-word detection is "
                "the task, the positive class is 'non-word', so standard Precision = TN/(TN+FN), "
                "standard Recall = TN/(TN+FP) = Manyok's TNR = Non-word detection accuracy.\n\n")

        f.write("> **Honesty note:** Because the lexicon was built from the same corpus, "
                "real-word accuracy (TPR) on in-corpus text is expected to be very high. "
                "This measures the system's behaviour on its training distribution, not "
                "generalisation to unseen text.\n\n")

        # --- 2. Speed ---
        f.write("## 2. Speed of Detection\n\n")
        if speed:
            f.write(f"- **Lexicon size:** {speed['lexicon_size']:,} words\n")
            f.write(f"- **Python version:** {speed['python_version']}\n")
            f.write(f"- **CPU:** {speed['cpu']}\n")
            f.write(f"- **Manyok reference:** 2.0 GHz hardware, avg 1,044 Hz\n\n")

            f.write("| Tokens | Actual Tokens | Time (ms) | Speed (Hz) |\n")
            f.write("|--------|---------------|-----------|------------|\n")
            for e in speed["experiments"]:
                f.write(f"| {e['target_tokens']} | {e['actual_tokens']} "
                        f"| {e['time_ms']:.2f} | {e['hz']:.1f} |\n")
            f.write(f"| **Average** | | | **{speed['avg_hz']:.1f}** |\n\n")

            if HAS_MPL:
                f.write("![Speed chart](speed.png)\n\n")
            else:
                f.write("> Speed chart (speed.png) not generated: matplotlib not installed.\n\n")

        # --- 3. Suggestion ---
        f.write("## 3. Suggestion and Correction Accuracy\n\n")
        if suggestion:
            for dist in [1, 2]:
                if dist not in suggestion:
                    continue
                s = suggestion[dist]
                f.write(f"### Edit distance ≤ {dist}\n\n")
                f.write(f"- Total non-word tokens: {s['total']}\n")
                f.write(f"- Top-1 accuracy: {fmt_pct(s['top1_acc'])}\n")
                f.write(f"- Top-3 accuracy: {fmt_pct(s['top3_acc'])}\n")
                f.write(f"- Top-5 accuracy: {fmt_pct(s['top5_acc'])}\n")
                f.write(f"- No suggestion rate: {fmt_pct(s['no_suggestion_rate'])}\n")
                f.write(f"- Avg suggestions per word: {s['avg_suggestions']:.1f}\n\n")

                f.write("| Error Type | Count | Top-1 | Top-3 | Top-5 | No Sugg |\n")
                f.write("|------------|-------|-------|-------|-------|---------|\n")
                for etype, data in sorted(s["by_type"].items()):
                    t = data["total"]
                    f.write(f"| {etype} | {t} "
                            f"| {fmt_pct(safe_div(data['hit1'], t))} "
                            f"| {fmt_pct(safe_div(data['hit3'], t))} "
                            f"| {fmt_pct(safe_div(data['hit5'], t))} "
                            f"| {fmt_pct(safe_div(data['no_sugg'], t))} |\n")
                f.write("\n")

            f.write("> **Note:** Manyok used distance 1 only and listed larger distances "
                    "as future work. Our checker uses distance 1 by default and falls back "
                    "to distance 2 for words ≥ 5 character units with few distance-1 candidates. "
                    "The evaluation above shows both distances separately.\n\n")

        # --- 4. Unit tests ---
        f.write("## 4. Unit Tests\n\n")
        if unit_tests:
            p, fa, details = unit_tests
            f.write(f"**{p} passed, {fa} failed**\n\n")
            f.write("| Status | Test | Detail |\n")
            f.write("|--------|------|--------|\n")
            for status, name, msg in details:
                icon = "✅" if status == "PASS" else "❌"
                # Escape pipes in msg
                safe_msg = msg.replace("|", "\\|")
                f.write(f"| {icon} {status} | {name} | {safe_msg} |\n")
            f.write("\n")

        # --- 5. Coverage ---
        f.write("## 5. Lexicon Coverage\n\n")
        if coverage:
            f.write(f"- **Lexicon size:** {coverage['lexicon_size']:,} words\n")
            f.write(f"- **Corpus tokens:** {coverage['total_corpus_tokens']:,}\n")
            f.write(f"- **OOV tokens:** {coverage['oov_tokens']}\n")
            f.write(f"- **OOV unique words:** {coverage['oov_unique_words']}\n")
            f.write(f"- **OOV rate:** {fmt_pct(coverage['oov_rate'])}\n\n")
            if coverage["oov_examples"]:
                f.write("OOV examples: " + ", ".join(coverage["oov_examples"][:10]) + "\n\n")
            f.write(f"> {coverage['note']}\n\n")

    print(f"  Report: {report_path}")

    # --- CSV files ---
    if detection.get("per_file"):
        csv_path = out_dir / "detection.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=detection["per_file"][0].keys())
            w.writeheader()
            w.writerows(detection["per_file"])
        print(f"  CSV: {csv_path}")

    if speed and speed.get("experiments"):
        csv_path = out_dir / "speed.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=speed["experiments"][0].keys())
            w.writeheader()
            w.writerows(speed["experiments"])
        print(f"  CSV: {csv_path}")

    if suggestion:
        csv_path = out_dir / "suggestion.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["max_dist", "error_type", "count", "top1", "top3", "top5", "no_sugg"])
            for dist, s in sorted(suggestion.items()):
                for etype, data in sorted(s["by_type"].items()):
                    t = data["total"]
                    w.writerow([dist, etype, t,
                                fmt_pct(safe_div(data["hit1"], t)),
                                fmt_pct(safe_div(data["hit3"], t)),
                                fmt_pct(safe_div(data["hit5"], t)),
                                fmt_pct(safe_div(data["no_sugg"], t))])
        print(f"  CSV: {csv_path}")

    # --- speed.png ---
    if HAS_MPL and speed and speed.get("experiments"):
        fig, ax = plt.subplots(figsize=(8, 5))
        tokens = [e["actual_tokens"] for e in speed["experiments"]]
        times = [e["time_ms"] for e in speed["experiments"]]
        ax.plot(tokens, times, "o-", linewidth=2, markersize=6)
        ax.set_xlabel("Tokens")
        ax.set_ylabel("Time (ms)")
        ax.set_title("Detection Speed: Tokens vs Time")
        ax.grid(True, alpha=0.3)
        png_path = out_dir / "speed.png"
        fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Chart: {png_path}")
    elif not HAS_MPL:
        print("  Chart: SKIPPED (matplotlib not installed)")

    # --- JSON ---
    json_data = {
        "detection": detection,
        "speed": speed,
        "suggestion": {str(k): v for k, v in suggestion.items()} if suggestion else {},
        "unit_tests": {"passed": unit_tests[0], "failed": unit_tests[1],
                       "details": [(s, n, m) for s, n, m in unit_tests[2]]} if unit_tests else {},
        "coverage": coverage,
    }
    json_path = out_dir / "eval_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"  JSON: {json_path}")


# ============================================================================
# Pytest-compatible test functions (TEST 4)
# ============================================================================

def _get_checker():
    """Get a SpellChecker instance for tests."""
    return SpellChecker(str(LEXICON_PATH))


def test_detection_flags_nonwords():
    sc = _get_checker()
    results = sc.check_text("kɛ naath xkɛ cuɛ naaht")
    flagged = {r["normalized"] for r in results if not r["is_known"]}
    assert "xkɛ" in flagged, f"xkɛ should be flagged, flagged={flagged}"
    assert "naaht" in flagged, f"naaht should be flagged, flagged={flagged}"


def test_detection_accepts_real_words():
    sc = _get_checker()
    results = sc.check_text("kɛ naath cuɛ")
    known = {r["normalized"] for r in results if r["is_known"]}
    assert "kɛ" in known
    assert "naath" in known
    assert "cuɛ" in known


def test_suggestion_contains_intended():
    sc = _get_checker()
    assert "naath" in sc.suggest("naaht", n=5)
    assert "kɛ" in sc.suggest("xkɛ", n=5)


def test_add_word_to_temp_lexicon():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_lex = Path(tmpdir) / "lexicon.tsv"
        shutil.copy2(str(LEXICON_PATH), str(tmp_lex))
        tmp_user = Path(tmpdir) / "user_additions.tsv"
        sc = SpellChecker(str(tmp_lex), user_additions_path=str(tmp_user))

        assert not sc.is_known("xyznonword")
        sc.add_word("xyznonword")
        assert sc.is_known("xyznonword")

        results = sc.check_text("xyznonword")
        assert all(r["is_known"] for r in results)


def test_ignore_word():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_lex = Path(tmpdir) / "lexicon.tsv"
        shutil.copy2(str(LEXICON_PATH), str(tmp_lex))
        sc = SpellChecker(str(tmp_lex))

        word = "xyzignoretest"
        assert not sc.is_known(word)
        sc.ignore_word(word)
        assert sc.is_known(word)


def test_tokenize_combining_marks():
    sc = _get_checker()
    results = sc.check_text("mi̱ naath")
    tokens = [r["normalized"] for r in results]
    assert "mi̱" in tokens, f"mi̱ should be one token, got {tokens}"
    # Combining macron below (U+0331) must not split
    for t in tokens:
        assert "\u0331" not in t or t == "mi̱" or "i\u0331" in t, \
            f"combining mark split: {t!r}"


def test_tokenize_negation_prefix():
    sc = _get_checker()
    results = sc.check_text("/cu kɛ")
    tokens = [r["normalized"] for r in results]
    assert "/cu" in tokens, f"/cu should be a token, got {tokens}"


def test_optional_numbers_caps():
    """Document current behaviour for numbers, caps, Title Case. Always passes."""
    sc = _get_checker()
    results = sc.check_text("KƐ Naath KUOTH 123 mi̱")
    info = [(r["original"], r["normalized"], r["is_known"]) for r in results]
    # Numbers (123) should not appear as tokens (tokenizer only yields letters+marks)
    token_texts = [r["normalized"] for r in results]
    assert "123" not in token_texts, "digits should not be tokens"
    # Just document, don't enforce specific behaviour for caps
    print(f"  Caps/numbers behaviour: {info}")


# ============================================================================
# Main — run all tests
# ============================================================================

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("NUER SPELL CHECKER — MANYOK-STYLE EVALUATION")
    print("=" * 70)
    print()

    # Init checker
    sc = SpellChecker(str(LEXICON_PATH))
    print(f"Lexicon: {len(sc.lexicon):,} words")
    print(f"Python:  {sys.version.split()[0]}")
    print(f"CPU:     {platform.processor()}")
    print()

    # Generate test data if not present
    test_files = list(DATA_DIR.glob("test_*.tsv"))
    if not test_files:
        print("Test data not found. Run: python tests/generate_test_data.py")
        print("Attempting to generate...")
        gen_script = SCRIPT_DIR / "generate_test_data.py"
        if gen_script.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("gen", str(gen_script))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.main()
            print()
        else:
            print("ERROR: generate_test_data.py not found")
            sys.exit(1)

    # --- TEST 1: Detection ---
    print("-" * 70)
    print("TEST 1: Detection Accuracy")
    print("-" * 70)
    detection = run_detection(sc, DATA_DIR)
    print()

    # --- TEST 2: Speed ---
    print("-" * 70)
    print("TEST 2: Speed of Detection")
    print("-" * 70)
    speed = run_speed(sc, DATA_DIR)
    print()

    # --- TEST 3: Suggestion ---
    print("-" * 70)
    print("TEST 3: Suggestion Accuracy")
    print("-" * 70)
    suggestion = run_suggestion(sc, DATA_DIR)
    print()

    # --- TEST 4: Unit Tests ---
    print("-" * 70)
    print("TEST 4: Unit Tests")
    print("-" * 70)
    p, fa, details = _run_unit_tests(sc)
    unit_tests = (p, fa, details)
    for status, name, msg in details:
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} {name}: {msg}")
    print(f"  {p} passed, {fa} failed")
    print()

    # --- TEST 5: Coverage ---
    print("-" * 70)
    print("TEST 5: Lexicon Coverage")
    print("-" * 70)
    coverage = run_coverage(sc)
    print(f"  Lexicon: {coverage['lexicon_size']:,} words")
    print(f"  Corpus tokens: {coverage['total_corpus_tokens']:,}")
    print(f"  OOV tokens: {coverage['oov_tokens']} ({fmt_pct(coverage['oov_rate'])})")
    print(f"  OOV unique: {coverage['oov_unique_words']}")
    if coverage["oov_examples"]:
        print(f"  OOV examples: {', '.join(coverage['oov_examples'][:10])}")
    print(f"  Note: {coverage['note']}")
    print()

    # --- Write report ---
    print("-" * 70)
    print("WRITING REPORTS")
    print("-" * 70)
    write_report(detection, speed, suggestion, unit_tests, coverage, RESULTS)
    print()

    # --- Summary ---
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if detection.get("average"):
        avg = detection["average"]
        print(f"  Avg Accuracy:           {fmt_pct(avg['accuracy'])}")
        print(f"  Avg TPR:                {fmt_pct(avg['TPR'])}")
        print(f"  Avg TNR (NWD Acc):      {fmt_pct(avg['TNR'])}")
        print(f"  Avg Precision (std):    {fmt_pct(avg['std_precision'])}")
        print(f"  Avg Recall (std):       {fmt_pct(avg['std_recall'])}")
        print(f"  Avg F1 (std):           {fmt_pct(avg['std_F1'])}")
    if speed:
        print(f"  Avg Speed:              {speed['avg_hz']:.1f} Hz")
    if suggestion:
        for dist in [1, 2]:
            if dist in suggestion:
                s = suggestion[dist]
                print(f"  Suggestion (dist≤{dist}):  "
                      f"top-1={fmt_pct(s['top1_acc'])} "
                      f"top-3={fmt_pct(s['top3_acc'])} "
                      f"top-5={fmt_pct(s['top5_acc'])}")
    if coverage:
        print(f"  OOV rate:               {fmt_pct(coverage['oov_rate'])}")
    if unit_tests:
        print(f"  Unit tests:             {unit_tests[0]} passed, {unit_tests[1]} failed")
    print("=" * 70)


if __name__ == "__main__":
    main()
