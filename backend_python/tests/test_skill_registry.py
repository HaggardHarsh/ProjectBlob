from types import SimpleNamespace

import pytest

from blob.skills.registry import SkillRegistry


def test_registry_returns_registered_skill():
    registry = SkillRegistry()
    skill = SimpleNamespace(name="sample", description="sample skill")
    registry.register(skill)
    assert registry.get_skill("sample") is skill
    assert registry.get_skill("unknown") is None


SKILL_YAML = """\
skill:
  name: Echo Example
  description: Echo a phrase
  permissions: [shell.execute]
  tools:
    - name: echo_text
      description: Echo text
      command: "echo {text}"
      args:
        - name: text
          required: true
  response_template: "Echoed: {result}"
"""


def test_install_persists_and_executes_without_shell(tmp_path):
    source = tmp_path / "sample.skill.yaml"
    source.write_text(SKILL_YAML)
    install_dir = tmp_path / "installed"
    registry = SkillRegistry(install_dir)
    assert registry.install_file(source) == "echo_example"
    marker = tmp_path / "unsafe"
    result = registry.get_skill("echo_example.echo_text").execute({"text": f"$(touch {marker})"})
    assert result.success
    assert result.output.startswith("Echoed: $(touch")
    assert not marker.exists()
    restarted = SkillRegistry(install_dir)
    assert restarted.load_directory(install_dir) == []
    assert restarted.get_skill("echo_example.echo_text") is not None


def test_install_rejects_shell_pipeline_and_hash_mismatch(tmp_path):
    source = tmp_path / "bad.skill.yaml"
    source.write_text(SKILL_YAML.replace("echo {text}", "echo {text} | cat"))
    registry = SkillRegistry(tmp_path / "installed")
    with pytest.raises(ValueError, match="pipelines"):
        registry.install_file(source)
    source.write_text(SKILL_YAML)
    with pytest.raises(ValueError, match="hash"):
        registry.install_file(source, expected_hash=b"wrong")


def test_install_rejects_unsupported_write_permission(tmp_path):
    source = tmp_path / "write.skill.yaml"
    source.write_text(SKILL_YAML.replace("shell.execute", "filesystem.write"))
    with pytest.raises(ValueError, match="Unsupported permissions"):
        SkillRegistry(tmp_path / "installed").install_file(source)
