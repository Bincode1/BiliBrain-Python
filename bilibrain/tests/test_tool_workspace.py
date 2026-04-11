from bilibrain.tools.workspace import normalize_workspace_path


def test_normalize_workspace_path_rejects_parent_escape(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()

    try:
        normalize_workspace_path(root, "../secret.txt")
    except ValueError as exc:
        assert "workspace" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
