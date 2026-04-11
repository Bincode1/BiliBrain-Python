from bilibrain.skills.parser import parse_skill_file


def test_parse_skill_file_supports_basic_frontmatter(tmp_path):
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: demo-skill
description: Use for testing the skill parser.
allowed-tools: [read_file, run_command]
disable-model-invocation: true
metadata:
  short-description: Demo parser skill
---

# Demo Skill

Follow the test workflow.
""",
        encoding="utf-8",
    )

    manifest = parse_skill_file(skill_file)

    assert manifest.name == "demo-skill"
    assert manifest.description == "Use for testing the skill parser."
    assert manifest.allowed_tools == ["read_file", "run_command"]
    assert manifest.allow_model_invocation is False
    assert manifest.metadata["short-description"] == "Demo parser skill"
    assert "Follow the test workflow." in manifest.body
