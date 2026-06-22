from __future__ import annotations

from pathlib import Path

from scripts.check_secrets import find_plaintext_secrets, format_findings


def test_find_plaintext_secrets_allows_placeholders_and_examples(tmp_path: Path):
    config = tmp_path / "services.yaml"
    config.write_text(
        """
llm:
  mimo:
    llm_config:
      api_key: ${MIMO_API_KEY}
      base_url: https://token-plan-cn.example/v1
  example:
    llm_config:
      api_key: your_api_key_here
  empty:
    llm_config:
      api_key: ""
""",
        encoding="utf-8",
    )

    assert find_plaintext_secrets([config]) == []


def test_find_plaintext_secrets_reports_location_without_secret_value(tmp_path: Path):
    secret_value = "tp-cnw2lg3ag0pm5au71lp3e34xmg2d1mct7dprkc3pzpmbuxhx"
    config = tmp_path / "services.yaml"
    config.write_text(
        f"""
llm:
  mimo:
    llm_config:
      api_key: {secret_value}
""",
        encoding="utf-8",
    )

    findings = find_plaintext_secrets([config])
    assert len(findings) == 1
    assert findings[0].path == config
    assert findings[0].key_path == "llm.mimo.llm_config.api_key"

    message = format_findings(findings)
    assert "llm.mimo.llm_config.api_key" in message
    assert secret_value not in message
