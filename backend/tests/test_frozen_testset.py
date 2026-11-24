"""CI guard: once the team freezes evaluation/data/test, any edit to it fails the build."""

import pytest

from evaluation.freeze import verify
from evaluation.io import TEST_DIR, is_frozen


@pytest.mark.skipif(
    not is_frozen(TEST_DIR), reason="test set not frozen yet (python -m evaluation.freeze evaluation/data/test)"
)
def test_frozen_test_set_is_unchanged():
    assert verify(TEST_DIR) == []
