# Test Data for Manyok-style Evaluation

Generated with seed=42, error_ratio=18%

## Error Types

Following Manyok & Balagadde (2022), errors are injected using four operations:

- **Transposition**: swap two adjacent character units
- **Substitution**: replace one character unit with another from the Nuer alphabet
- **Deletion**: remove one character unit
- **Insertion**: insert a random Nuer character unit

Character units are base letters with their combining marks (e.g., ɛ̈ is one unit).

## Verification

- Every `real` token is verified to be in `lexicon.tsv`
- Every `nonword` token is verified NOT to be in `lexicon.tsv`
- If an injected error happens to be a real word, it is discarded and the token kept as `real`

## Files

| File | Description | Total | Real | Non-word | Trans | Subst | Del | Ins |
|------|-------------|-------|------|----------|-------|-------|-----|-----|
| test_narrative.tsv | High-frequency words (narrative text simulation) | 500 | 416 | 84 | 18 | 19 | 18 | 29 |
| test_mixed.tsv | Mixed-frequency words (general text) | 400 | 331 | 69 | 15 | 20 | 19 | 15 |
| test_rare.tsv | Full frequency distribution (including rare words) | 350 | 288 | 62 | 14 | 15 | 19 | 14 |

Seed: 42
