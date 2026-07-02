import subprocess

from dashboard.commands import PROJECT_ROOT, command_env, python_command


def test_python_command_uses_current_interpreter():
    command = python_command("research_lab_runner.py", "--help")
    assert command[0].endswith("python") or "python" in command[0]
    assert command[1] == "research_lab_runner.py"
    assert command[2] == "--help"


def test_command_env_sets_pythonpath():
    env = command_env()
    assert str(PROJECT_ROOT) in env["PYTHONPATH"]


def test_research_lab_runner_help_runs():
    result = subprocess.run(
        python_command("research_lab_runner.py", "--help"),
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=command_env(),
        check=False,
    )
    assert result.returncode == 0
    assert "Research Lab" in result.stdout
