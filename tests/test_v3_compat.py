import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V3_INIT = ROOT / "plugins.v3" / "musicdownloader" / "__init__.py"
V3_PACKAGE = ROOT / "package.v3.json"
V2_PACKAGE = ROOT / "package.v2.json"


def _imports(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_v3_source_compiles_and_uses_v3_contracts():
    source = V3_INIT.read_text(encoding="utf-8")
    compile(source, str(V3_INIT), "exec")
    imports = _imports(source)

    forbidden_prefixes = ("app.core", "app.helper", "app.utils")
    assert not any(
        module == "app.plugins" or module.startswith(forbidden_prefixes)
        for module in imports
    )
    assert "app.sdk.plugin" in imports
    assert "app.sdk.media" in imports
    assert "app.sdk.events" in imports
    assert "app.application.directory" in imports
    assert "from app.db.oper.site import SiteOper" in source
    assert "from app.db.oper.systemconfig import SystemConfigOper" in source
    assert 'plugin_version = "3.0.0"' in source
    assert "MusicInfo(" in source
    assert "MediaType.MUSIC" in source
    assert "DownloadChain().download," not in source
    assert "_LIVE_POOL" not in source
    assert "NotificationType" not in source
    assert "MessageType.Download" in source


def test_v3_market_index_is_independent_from_v2_fallback():
    v2 = json.loads(V2_PACKAGE.read_text(encoding="utf-8"))["MusicDownloader"]
    v3 = json.loads(V3_PACKAGE.read_text(encoding="utf-8"))["MusicDownloader"]

    assert v2["v3"] is False
    assert v3["version"] == "3.0.0"
    assert v3["system_version"] == ">=3.0.0"
    assert v3["release"] is True
    assert "v3" not in v3
    assert v3["history"]["v3.0.0"]
