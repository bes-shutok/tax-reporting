"""End-to-end test verifying the README documents the example workflow.

Ensures key documentation does not drift: the README must mention the example
directory, the command to run it, and the Token origin column semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

README = Path("README.md")


@pytest.mark.e2e
class TestReadmeExampleDocumentation:
    def test_readme_mentions_example_directory(self):
        content = README.read_text()
        assert "resources/source/example" in content

    def test_readme_mentions_example_run_command(self):
        content = README.read_text()
        assert "uv run tax-reporting" in content
        assert "--source" in content or "source_file" in content

    def test_readme_mentions_example_output_file(self):
        content = README.read_text()
        assert "extract.xlsx" in content

    def test_readme_mentions_features_demonstrated(self):
        content = README.read_text()
        lower = content.lower()
        for feature in ("capital gains", "dividend", "crypto", "leftover"):
            assert feature in lower, f"README should mention '{feature}' feature"

    def test_readme_explains_token_origin_is_blank(self):
        content = README.read_text()
        assert "Token origin" in content
        assert "blank" in content.lower()

    def test_readme_states_example_data_is_synthetic(self):
        content = README.read_text()
        lower = content.lower()
        assert "synthetic" in lower or "demo" in lower or "fake" in lower
        assert "not tax advice" in lower or "tax advice" in lower
