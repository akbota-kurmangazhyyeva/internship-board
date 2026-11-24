# Synthetic example dataset

**Not real data and not the frozen test set.** Eight invented postings (fictional employers) with hand-written
labels, two personas and relevance judgments. It exists only to show the file formats and to smoke-test the
metric scripts in CI:

    python -m evaluation.validate evaluation/example
    python -m evaluation.eval_extraction --data evaluation/example --errors --no-save
    python -m evaluation.eval_dedup --data evaluation/example --no-save
    python -m evaluation.eval_ranking --data evaluation/example --no-save

Numbers on these eight postings mean nothing about real quality. The real evaluation uses
`evaluation/data/test` (40 real postings, labelled by the team, frozen).
