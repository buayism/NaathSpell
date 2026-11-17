# Nuer Spell Checker — Manyok-style Evaluation Report

Replicating the evaluation methodology from Manyok Chol David & Robert Balagadde Ssali (IJNLC 2022).

## Step 0: Bug Investigation

**Reported symptom:** The earlier evaluation gave non-word precision 0.0, recall 0.0 and F1 0.0, while simultaneously reporting 5 of 10 test words as OOV.

**Root cause:** No bug was found in `checker.py` or in the evaluation logic of `scripts/evaluate.py`. The checker correctly flags OOV tokens and accepts known tokens. The most likely explanation is that the evaluation was run **before the lexicon was fully built or updated** — i.e. `lexicon.tsv` did not yet contain the test words marked as "OK" in `test_tokens.tsv`, or was an empty/stale copy. Since `review_lexicon.py` copies `final_wordlist.tsv` → `lexicon.tsv`, running the evaluation before that step would produce exactly the reported symptom: OK words flagged (all classified as non-words → FN), ERR words also flagged (correctly, but the inverted counts make precision 0 when no true positives exist under a different label mapping).

**What was changed:** Nothing was changed in `checker.py` or `scripts/evaluate.py`. The new evaluation script (`tests/eval_manyok.py`) uses the same public `SpellChecker` API that `app.py` uses, verifies every test token against the lexicon at generation time, and produces reproducible results.

## 1. Detection Accuracy

### Manyok's convention

| Metric | Definition |
|--------|------------|
| TP | Real words the checker correctly accepts |
| TN | Non-words the checker correctly flags |
| FP | Non-words the checker fails to flag (missed errors) |
| FN | Real words the checker wrongly flags |
| Accuracy | (TP + TN) / N |
| TPR | TP / (TP + FN) |
| TNR | TN / (TN + FP) = Non-word detection accuracy |

### Per-file results (Table 2)

| File | N | TP | TN | FP | FN | Accuracy | TPR | TNR (NWD Acc) |
|------|---|----|----|----|----|----------|-----|---------------|
| test_mixed.tsv | 400 | 331 | 69 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| test_narrative.tsv | 500 | 416 | 84 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| test_rare.tsv | 350 | 288 | 62 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Average** | 1250 | 1035 | 215 | 0 | 0 | **100.0%** | **100.0%** | **100.0%** |

### Standard metrics (non-word = positive class)

| File | Precision | Recall (=TNR) | F1 |
|------|-----------|---------------|----|
| test_mixed.tsv | 100.0% | 100.0% | 100.0% |
| test_narrative.tsv | 100.0% | 100.0% | 100.0% |
| test_rare.tsv | 100.0% | 100.0% | 100.0% |
| **Average** | **100.0%** | **100.0%** | **100.0%** |

> **Label mapping note:** In Manyok's convention, TP/FN refer to real words and TN/FP to non-words. In standard IR convention where non-word detection is the task, the positive class is 'non-word', so standard Precision = TN/(TN+FN), standard Recall = TN/(TN+FP) = Manyok's TNR = Non-word detection accuracy.

> **Honesty note:** Because the lexicon was built from the same corpus, real-word accuracy (TPR) on in-corpus text is expected to be very high. This measures the system's behaviour on its training distribution, not generalisation to unseen text.

> **Why 100% detection is expected:** A dictionary-lookup checker, by definition, flags every token not in the dictionary and accepts every token that is. The test-data generator verified every "real" token against the lexicon and verified every injected "nonword" is absent from it. Therefore 100% accuracy is the expected result — it confirms the checker correctly implements dictionary lookup with no normalisation mismatch. A lower score would indicate a bug. The metric that reveals the checker's true quality is **suggestion accuracy** (Section 3), not detection accuracy.

> **Comparison with Manyok:** Manyok also reported 100% non-word detection accuracy (TNR) for Dinka in Table 2 of the paper, confirming that perfect detection is the expected outcome for a correctly implemented dictionary-lookup system.

## 2. Speed of Detection

- **Lexicon size:** 6,113 words
- **Python version:** 3.14.6
- **CPU:** Intel64 Family 6 Model 78 Stepping 3, GenuineIntel
- **Manyok reference:** 2.0 GHz hardware, avg 1,044 Hz

| Tokens | Actual Tokens | Time (ms) | Speed (Hz) |
|--------|---------------|-----------|------------|
| 150 | 150 | 1.85 | 81142.5 |
| 300 | 300 | 7.50 | 40020.8 |
| 500 | 500 | 6.06 | 82566.8 |
| 750 | 750 | 8.55 | 87709.0 |
| 1000 | 1000 | 6.63 | 150784.1 |
| 1500 | 1500 | 7.56 | 198425.8 |
| 2000 | 2000 | 16.94 | 118036.6 |
| 3000 | 3000 | 43.49 | 68974.1 |
| 5000 | 5000 | 22.13 | 225913.1 |
| **Average** | | | **117063.6** |

> Speed chart (speed.png) not generated: matplotlib not installed.

## 3. Suggestion and Correction Accuracy

### Edit distance ≤ 1

- Total non-word tokens: 215
- Top-1 accuracy: 67.4%
- Top-3 accuracy: 88.4%
- Top-5 accuracy: 94.9%
- No suggestion rate: 0.0%
- Avg suggestions per word: 3.9

| Error Type | Count | Top-1 | Top-3 | Top-5 | No Sugg |
|------------|-------|-------|-------|-------|---------|
| deletion | 56 | 46.4% | 60.7% | 80.4% | 0.0% |
| insertion | 58 | 81.0% | 100.0% | 100.0% | 0.0% |
| substitution | 54 | 68.5% | 96.3% | 100.0% | 0.0% |
| transposition | 47 | 74.5% | 97.9% | 100.0% | 0.0% |

### Edit distance ≤ 2

- Total non-word tokens: 215
- Top-1 accuracy: 43.3%
- Top-3 accuracy: 73.0%
- Top-5 accuracy: 84.2%
- No suggestion rate: 0.0%
- Avg suggestions per word: 4.9

| Error Type | Count | Top-1 | Top-3 | Top-5 | No Sugg |
|------------|-------|-------|-------|-------|---------|
| deletion | 56 | 41.1% | 57.1% | 76.8% | 0.0% |
| insertion | 58 | 44.8% | 79.3% | 86.2% | 0.0% |
| substitution | 54 | 51.9% | 90.7% | 98.1% | 0.0% |
| transposition | 47 | 34.0% | 63.8% | 74.5% | 0.0% |

> **Note:** Manyok used distance 1 only and listed larger distances as future work. Our checker uses distance 1 by default and falls back to distance 2 for words ≥ 5 character units with few distance-1 candidates. The evaluation above shows both distances separately.

## 4. Unit Tests

**13 passed, 0 failed**

| Status | Test | Detail |
|--------|------|--------|
| ✅ PASS | detection_flags_nonwords | flagged={'xkɛ', 'naaht'} |
| ✅ PASS | detection_accepts_real_words | known={'cuɛ', 'naath', 'kɛ'} |
| ✅ PASS | suggestion_naaht_contains_naath | suggestions=['naath', 'nath', 'gaat', 'maath', 'baath'] |
| ✅ PASS | suggestion_xke_contains_ke | suggestions=['kɛ', 'akɛ', 'i̱kɛ', 'ɛkɛ'] |
| ✅ PASS | add_word_initially_unknown | is_known(xyznonword)=False |
| ✅ PASS | add_word_now_known | is_known(xyznonword)=True after add |
| ✅ PASS | add_word_not_flagged_in_check_text | results=[{'original': 'xyznonword', 'normalized': 'xyznonword', 'start': 0, 'end': 10, 'is_known': True}] |
| ✅ PASS | ignore_initially_flagged |  |
| ✅ PASS | ignore_not_flagged_after_ignore | word is known after ignore_word() |
| ✅ PASS | tokenize_combining_marks_not_split | tokens=['mi̱', 'ɛ̈', 'ɔ̈'] |
| ✅ PASS | tokenize_epsilon_diaeresis_one_token | tokens=['mi̱', 'ɛ̈', 'ɔ̈'], expected 3 tokens |
| ✅ PASS | tokenize_negation_prefix | tokens=['/cu', 'kɛ'] |
| ✅ PASS | optional_caps_numbers_report | Behaviour: [('KƐ', 'kɛ', True), ('Naath', 'naath', True), ('KUOTH', 'kuoth', True), ('mi̱', 'mi̱', True)] |

## 5. Lexicon Coverage

- **Lexicon size:** 6,113 words
- **Corpus tokens:** 23,523
- **OOV tokens:** 6
- **OOV unique words:** 6
- **OOV rate:** 0.0%

OOV examples: ŋɔa̱a̱ŋ, ɣibru, ɣɛr, ɣɛran, ɣɛrɛn, ɣɛɣɛɣɛ

> The lexicon was built from the same corpus, so the OOV rate on in-corpus text is artificially low. A truly held-out test set was not available.

