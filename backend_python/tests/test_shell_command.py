from blob.skills.builtin.shell_command import ShellCommandSkill


def test_shell_command_does_not_expand_shell_metacharacters(tmp_path):
    marker = tmp_path / "should_not_exist"
    result = ShellCommandSkill().execute({"command": f"echo $(touch {marker})"})
    assert result.success
    assert not marker.exists()


def test_shell_command_rejects_unsafe_find_action():
    result = ShellCommandSkill().execute({"command": "find . -exec sh -c true ;"})
    assert not result.success
