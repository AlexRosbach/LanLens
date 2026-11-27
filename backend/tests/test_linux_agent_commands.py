import importlib.util
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "linux_agent", Path(__file__).resolve().parents[1] / "assets/linux_agent/lanlens-agent.py"
)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def test_agent_executes_argument_vectors_without_shell():
    with patch.object(agent.subprocess, "run") as subprocess_run:
        subprocess_run.return_value.stdout = "result\n"
        assert agent.run(["ip", "addr", "show", "dev", "eth0;unexpected"]) == "result"
        assert subprocess_run.call_args.args[0] == ["ip", "addr", "show", "dev", "eth0;unexpected"]
        assert not subprocess_run.call_args.kwargs.get("shell", False)


def test_agent_software_inventory_preserves_package_fields():
    with patch.object(agent.shutil, "which", return_value="/usr/bin/dpkg-query"), patch.object(
        agent, "run", return_value="package\t1.2\tamd64\n"
    ) as run:
        assert agent.software() == [{"name": "package", "version": "1.2", "architecture": "amd64"}]
        assert run.call_args.args[0][:2] == ["dpkg-query", "-W"]
