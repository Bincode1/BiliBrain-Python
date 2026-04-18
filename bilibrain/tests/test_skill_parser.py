from bilibrain.skills.parser import parse_skill_file


def test_parse_skill_file_supports_basic_frontmatter(tmp_path):
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: demo-skill
description: Use for testing the skill parser.
when-to-use: Use when a user asks for parser validation.
input-hint: Provide the skill with a frontmatter-heavy markdown file.
examples:
  - Parse a SKILL.md file with inline tool declarations.
  - Validate a frontmatter block that contains examples.
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
    assert manifest.short_description == "Demo parser skill"
    assert manifest.when_to_use == "Use when a user asks for parser validation."
    assert manifest.input_hint == "Provide the skill with a frontmatter-heavy markdown file."
    assert manifest.examples == [
        "Parse a SKILL.md file with inline tool declarations.",
        "Validate a frontmatter block that contains examples.",
    ]
    assert manifest.allowed_tools == ["read_file", "run_command"]
    assert manifest.allow_model_invocation is False
    assert manifest.metadata["short-description"] == "Demo parser skill"
    assert "Follow the test workflow." in manifest.body
