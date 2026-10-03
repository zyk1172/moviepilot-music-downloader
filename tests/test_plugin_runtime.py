"""Runtime regressions for plugin paths that can be exercised without MoviePilot."""
import ast
import asyncio
import hashlib
import importlib.util
import inspect
import re
import threading
import time
import typing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
FILES = ["01 Song Alpha.flac", "02 Song Beta.flac"]
LIVE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="MusicDownloaderTestLive")


class Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class PluginBase:
    def __init__(self):
        self.data = {}

    def get_data(self, key):
        return self.data.get(key)

    def save_data(self, key, value):
        self.data[key] = value

    def del_data(self, key):
        self.data.pop(key, None)

    def update_config(self, config):
        self.config = config

    def post_message(self, **_kwargs):
        pass


class DownloadChain:
    query_mode = "error"

    def list_torrents(self, **_kwargs):
        if self.query_mode == "error":
            raise ConnectionError("simulated downloader outage")
        if self.query_mode == "none":
            return None
        if self.query_mode == "delay":
            time.sleep(0.15)
            return []
        return []

    def download_torrent(self, _torrent):
        return b"torrent-content", "Album", FILES


def load_plugin(version):
    path = ROOT / f"plugins.{version}" / "musicdownloader" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MusicDownloader"
    )
    screener_path = path.with_name("screener.py")
    spec = importlib.util.spec_from_file_location(f"runtime_screener_{version}", screener_path)
    screener = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(screener)

    namespace = {
        **vars(typing),
        "__name__": f"musicdownloader_{version}_runtime_test",
        "asyncio": asyncio,
        "hashlib": hashlib,
        "re": re,
        "datetime": datetime,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "_PluginBase": PluginBase,
        "DEFAULT_LABEL": "music",
        "DEFAULT_CATEGORY": "music",
        "IntervalTrigger": lambda **kwargs: kwargs,
        "Event": object,
        "TorrentInfo": SimpleNamespace,
        "Body": lambda **_kwargs: None,
        "eventmanager": SimpleNamespace(register=lambda _event: lambda fn: fn),
        "EventType": SimpleNamespace(CommandExcute="command"),
        "MessageType": SimpleNamespace(Download="download"),
        "logger": Logger(),
        "DownloadChain": DownloadChain,
        "validate_download_save_path": lambda path: path,
        "SystemConfigOper": lambda: SimpleNamespace(get=lambda _key: []),
        "SystemConfigKey": SimpleNamespace(IndexerSites="indexers"),
        "_VERIFY_CACHE": {},
        "_VERIFY_TTL": 600,
        "_LIVE_POOL": LIVE_POOL,
        "_sha1_text": lambda value: hashlib.sha1(value.encode()).hexdigest(),
        "HashUtils": SimpleNamespace(sha1=lambda value: hashlib.sha1(value.encode()).hexdigest()),
        "TorrentHelper": lambda: SimpleNamespace(
            get_fileinfo_from_torrent_content=lambda _content: ("Album", FILES)
        ),
        "check_torrent_files": screener.check_torrent_files,
        "norm": screener.norm,
    }
    exec(compile(ast.Module(body=[plugin_class], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["MusicDownloader"], namespace


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_command_handler_awaits_host_registered_command_args(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    calls = []

    async def run_search(**kwargs):
        calls.append(kwargs)

    plugin._run_command_search = run_search

    async def scenario():
        assert inspect.iscoroutinefunction(plugin_class.command_handler)
        await plugin.command_handler(SimpleNamespace(event_data={
            "cmd": "/音乐下载", "arg_str": "Artist Album", "user": "user-1", "channel": "chat"
        }))
        await plugin.command_handler(SimpleNamespace(event_data={
            "cmd": "/音乐下载 Artist Album", "user": "user-2", "channel": "chat"
        }))

    asyncio.run(scenario())
    assert calls == [
        {"artist": "Artist", "album": "Album", "keyword": None,
         "userid": "user-1", "channel": "chat"},
        {"artist": "Artist", "album": "Album", "keyword": None,
         "userid": "user-2", "channel": "chat"},
    ]


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_auto_download_selects_only_confirmed_album_match(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    candidates = [
        {"ref": "correct:1", "title": "Artist Wanted Album FLAC", "quality": 90,
         "relevance": 70, "album_matched": True, "seeders": 5, "quality_label": "FLAC"},
        {"ref": "wrong:2", "title": "Artist Other Album HiRes", "quality": 100,
         "relevance": 30, "album_matched": False, "seeders": 10, "quality_label": "HiRes"},
    ]
    picked = []

    async def search(**_kwargs):
        return {"results": candidates, "album_matched_any": True}

    async def download(**kwargs):
        picked.append(kwargs["ref"])
        return {"success": True, "data": {"hash": "1234567890123456"}}

    plugin.do_search = search
    plugin.do_download = download
    asyncio.run(plugin._run_command_search("Artist", "Wanted Album", None, None, None))
    assert picked == ["correct:1"]


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_downloader_failure_preserves_history_and_empty_success_cleans_orphans(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    history = [{"hash": "still-active", "status": "downloading"}]
    plugin.save_data("downloads", history.copy())

    async def scenario():
        for mode in ("error", "none"):
            DownloadChain.query_mode = mode
            response = await plugin.api_history_clean({"orphans": True})
            assert response["success"] is False
            assert plugin.get_data("downloads") == history
        DownloadChain.query_mode = "empty"
        response = await plugin.api_history_clean({"orphans": True})
        assert response["success"] is True
        assert response["data"] == {"before": 1, "after": 0}

    try:
        asyncio.run(scenario())
    finally:
        plugin.stop_service()


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_async_live_query_does_not_block_event_loop(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    plugin.save_data("downloads", [{"hash": "task-1", "status": "downloading"}])
    DownloadChain.query_mode = "delay"

    async def scenario():
        started = time.perf_counter()

        async def heartbeat():
            await asyncio.sleep(0.01)
            return time.perf_counter() - started

        _tasks, delay = await asyncio.gather(plugin.api_tasks(), heartbeat())
        assert delay < 0.1

    try:
        asyncio.run(scenario())
    finally:
        plugin.stop_service()
        DownloadChain.query_mode = "error"


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_webhook_post_does_not_block_event_loop(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    plugin._notify_enabled = True
    plugin._notify_url = "https://example.invalid/hook"
    completed = threading.Event()

    def slow_post(_body):
        time.sleep(0.15)
        completed.set()
        return True

    plugin._send_result_webhook = slow_post

    async def scenario():
        started = time.perf_counter()
        plugin._push_result("test", {}, "title", "message")
        await asyncio.sleep(0.01)
        assert time.perf_counter() - started < 0.1
        assert await asyncio.to_thread(completed.wait, 1)

        completed.clear()
        started = time.perf_counter()
        async def heartbeat():
            await asyncio.sleep(0.01)
            return time.perf_counter() - started

        response, delay = await asyncio.gather(plugin.api_notify_test(), heartbeat())
        assert delay < 0.1
        assert response["success"] is True
        assert completed.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_paused_download_can_resume_complete_and_callback(version):
    plugin_class, _namespace = load_plugin(version)
    plugin = plugin_class()
    history = [{"hash": "task-1", "title": "Album", "status": "downloading"}]
    plugin._push_result = lambda *_args, **_kwargs: True

    plugin._reconcile_status(history, {"task-1": {"state": "paused", "progress": 20}})
    assert history[0]["status"] == "paused"
    plugin._reconcile_status(history, {"task-1": {"state": "downloading", "progress": 50}})
    assert history[0]["status"] == "downloading"
    plugin._reconcile_status(history, {"task-1": {"state": "paused", "progress": 50}})
    assert history[0]["status"] == "paused"
    plugin._reconcile_status(history, {"task-1": {"state": "completed", "progress": 100}})
    assert history[0]["status"] == "completed"

    history[0]["status"] = "paused"
    plugin.save_data("downloads", history)
    asyncio.run(plugin.api_on_complete(hash="task-1"))
    assert history[0]["status"] == "completed"


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_verification_cache_is_scoped_to_song_and_interval_zero_disables_job(version):
    plugin_class, namespace = load_plugin(version)
    namespace["_VERIFY_CACHE"].clear()
    torrent = SimpleNamespace(enclosure="https://example.invalid/same-torrent")

    first = plugin_class._verify_torrent_content(torrent, "Song Alpha", None)
    second = plugin_class._verify_torrent_content(torrent, "Song Gamma", None)
    assert first[0] is True
    assert second[0] is False

    plugin = plugin_class()
    plugin.init_plugin({"enabled": True, "music_dir": "/mock/music", "reconcile_interval_min": 0})
    assert plugin._reconcile_interval_min == 0
    assert plugin.get_service() == []
    plugin.stop_service()
