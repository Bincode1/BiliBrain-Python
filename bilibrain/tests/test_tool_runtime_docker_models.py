from bilibrain.tools.runtime.docker_models import DockerSandboxConfig


def test_docker_sandbox_config_has_safe_defaults():
    config = DockerSandboxConfig()

    assert config.read_only_rootfs is True
    assert config.network_disabled is True
    assert config.user != "root"
