from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime
from functools import reduce
from hashlib import md5
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from curl_cffi import requests as curl_requests
import qrcode
from qrcode.image.svg import SvgPathImage

from bilibrain.core.config import Settings
from bilibrain.db.database import Database


AUTH_COOKIE_NAMES = {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"}
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


class BilibiliClient:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.browser = curl_requests.Session(impersonate="chrome")
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_expires_at = 0.0
        self._session_cache: dict[str, Any] | None = None
        self._session_cache_expires_at = 0.0
        self.client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            },
            follow_redirects=False,
        )

    async def close(self) -> None:
        self.browser.close()
        await self.client.aclose()

    def _invalidate_session_cache(self) -> None:
        self._session_cache = None
        self._session_cache_expires_at = 0.0

    def _restore_cookies(self) -> None:
        cookies = self.db.load_state("auth_cookies") or {}
        self.client.cookies.clear()
        self.browser.cookies.clear()
        for name, value in cookies.items():
            self.client.cookies.set(name, value, domain=".bilibili.com")
            self.browser.cookies.set(name, value, domain=".bilibili.com")

    def _persist_cookies(self) -> None:
        interesting: dict[str, str] = {}
        for cookie in self.client.cookies.jar:
            if "bilibili.com" not in cookie.domain:
                continue
            interesting[cookie.name] = cookie.value
        for cookie in self.browser.cookies.jar:
            if "bilibili.com" not in cookie.domain:
                continue
            # Login-confirmed auth cookies must come from the QR polling client,
            # otherwise stale browser-session cookies can overwrite the new account.
            if cookie.name in AUTH_COOKIE_NAMES:
                continue
            interesting[cookie.name] = cookie.value
        if interesting:
            self.db.save_state("auth_cookies", interesting)
            self._invalidate_session_cache()

    def _warmup_browser_cookies_sync(self) -> None:
        cookie_names = set(self.browser.cookies.keys())
        if {"buvid3", "b_nut"} <= cookie_names:
            return
        self.browser.get(
            "https://www.bilibili.com/",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

    def _api_headers(self) -> dict[str, str]:
        return {
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    def _get_mixin_key(self, raw: str) -> str:
        return reduce(lambda acc, idx: acc + raw[idx], MIXIN_KEY_ENC_TAB, "")[:32]

    def _get_wbi_keys_sync(self) -> tuple[str, str]:
        if self._wbi_keys and time.time() < self._wbi_expires_at:
            return self._wbi_keys

        self._warmup_browser_cookies_sync()
        response = self.browser.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=self._api_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (0, None):
            raise RuntimeError(payload.get("message") or payload.get("msg") or "获取 WBI key 失败。")

        data = payload.get("data") or {}
        wbi_img = data.get("wbi_img") or {}
        img_url = wbi_img.get("img_url") or ""
        sub_url = wbi_img.get("sub_url") or ""
        img_key = Path(urlparse(img_url).path).stem
        sub_key = Path(urlparse(sub_url).path).stem
        if not img_key or not sub_key:
            raise RuntimeError("Bilibili 未返回有效的 WBI key。")

        self._wbi_keys = (img_key, sub_key)
        self._wbi_expires_at = time.time() + 300
        return self._wbi_keys

    def _enc_wbi(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        img_key, sub_key = self._get_wbi_keys_sync()
        mixin_key = self._get_mixin_key(img_key + sub_key)
        request_params["wts"] = round(time.time())
        cleaned_items = []
        for key, value in sorted(request_params.items()):
            cleaned_value = "".join(char for char in str(value) if char not in "!'()*")
            cleaned_items.append((key, cleaned_value))
        query = urlencode(cleaned_items)
        signed_params = dict(cleaned_items)
        signed_params["w_rid"] = md5((query + mixin_key).encode("utf-8")).hexdigest()
        return signed_params

    def _request_json_sync(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        use_wbi: bool = False,
    ) -> dict[str, Any]:
        self._warmup_browser_cookies_sync()
        request_params = self._enc_wbi(params) if use_wbi else params
        response = self.browser.get(
            url,
            params=request_params,
            headers=self._api_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (0, None):
            raise RuntimeError(payload.get("message") or payload.get("msg") or "Bilibili API 返回失败。")
        return payload

    async def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        use_wbi: bool = False,
    ) -> dict[str, Any]:
        async with self._request_lock:
            wait_seconds = self.settings.bili_api_delay - (time.monotonic() - self._last_request_at)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            self._restore_cookies()
            try:
                payload = await asyncio.to_thread(self._request_json_sync, url, params, use_wbi)
            except Exception as exc:
                self._last_request_at = time.monotonic()
                if isinstance(exc, RuntimeError):
                    raise
                raise RuntimeError(str(exc)) from exc

            self._persist_cookies()
            self._last_request_at = time.monotonic()
            return payload

    async def get_session(self) -> dict[str, Any]:
        if self._session_cache and time.monotonic() < self._session_cache_expires_at:
            return dict(self._session_cache)

        cookies = self.db.load_state("auth_cookies") or {}
        if not cookies:
            session = {"logged_in": False}
            self._session_cache = dict(session)
            self._session_cache_expires_at = time.monotonic() + max(self.settings.session_cache_ttl_seconds, 1)
            return session
        try:
            payload = await self._get_json("https://api.bilibili.com/x/web-interface/nav")
        except Exception:
            session = {"logged_in": False}
            self._session_cache = dict(session)
            self._session_cache_expires_at = time.monotonic() + max(self.settings.session_cache_ttl_seconds, 1)
            return session
        data = payload.get("data") or {}
        session = {
            "logged_in": bool(data.get("isLogin")),
            "user_name": data.get("uname"),
            "uid": data.get("mid"),
        }
        self._session_cache = dict(session)
        self._session_cache_expires_at = time.monotonic() + max(self.settings.session_cache_ttl_seconds, 1)
        return session

    async def start_qr_login(self) -> dict[str, str]:
        payload = await self._get_json(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        )
        data = payload["data"]
        qr = qrcode.make(data["url"], image_factory=SvgPathImage)
        buffer = io.BytesIO()
        qr.save(buffer)
        return {
            "qrcode_key": data["qrcode_key"],
            "url": data["url"],
            "svg": buffer.getvalue().decode("utf-8"),
        }

    async def poll_qr_login(self, qrcode_key: str) -> dict[str, Any]:
        self._restore_cookies()
        response = await self.client.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        code = data.get("code")
        if code == 0:
            self._persist_cookies()
            self._invalidate_session_cache()
            session = await self.get_session()
            return {"status": "confirmed", **session}
        if code == 86101:
            return {"status": "pending", "message": "等待扫码"}
        if code == 86090:
            return {"status": "scanned", "message": "已扫码，请在手机端确认"}
        if code == 86038:
            return {"status": "expired", "message": "二维码已过期，请重新生成"}
        return {"status": "failed", "message": data.get("message") or "扫码登录失败"}

    async def list_folders(self, uid: int | None = None) -> list[dict[str, Any]]:
        target_uid = int(uid or 0)
        if not target_uid:
            session = await self.get_session()
            if not session.get("logged_in"):
                raise RuntimeError("请先扫码登录 Bilibili。")
            target_uid = int(session.get("uid") or 0)
        if not target_uid:
            raise RuntimeError("当前登录状态缺少 UID，无法读取收藏夹。")
        payload = await self._get_json(
            "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
            params={"up_mid": target_uid},
            use_wbi=True,
        )
        data = payload.get("data") or {}
        if isinstance(data, list):
            items = data
        else:
            items = data.get("list") or []
        if items is None:
            raise RuntimeError("Bilibili 返回的收藏夹列表为空。")
        if not isinstance(items, list):
            raise RuntimeError(f"Bilibili 收藏夹列表返回格式异常：{type(items).__name__}")
        folders = [
            {
                "folder_id": int(item["id"]),
                "title": item["title"],
                "media_count": int(item.get("media_count") or 0),
            }
            for item in items
        ]
        return self.db.save_folders(target_uid, folders)

    async def list_folder_videos(self, folder_id: int) -> list[dict[str, Any]]:
        page = 1
        videos: list[dict[str, Any]] = []
        while True:
            payload = await self._get_json(
                "https://api.bilibili.com/x/v3/fav/resource/list",
                params={
                    "media_id": folder_id,
                    "pn": page,
                    "ps": 20,
                    "platform": "web",
                    "keyword": "",
                    "order": "mtime",
                    "type": 0,
                    "tid": 0,
                },
                use_wbi=True,
            )
            data = payload.get("data") or {}
            medias = data.get("medias") or []
            for index, media in enumerate(medias):
                raw_bvid = str(media.get("bvid") or "").strip()
                resource_id = media.get("id") or media.get("fav_time") or f"page{page}-idx{index}"
                is_invalid = not raw_bvid
                bvid = raw_bvid or f"invalid:{folder_id}:{resource_id}"
                upper = media.get("upper") or {}
                pubtime = media.get("pubtime")
                videos.append(
                    {
                        "bvid": bvid,
                        "title": media.get("title") or ("已失效视频" if is_invalid else bvid),
                        "up_name": upper.get("name") or ("视频已失效" if is_invalid else None),
                        "cover_url": self._resolve_cover_url(media.get("cover")),
                        "duration": int(media.get("duration") or 0),
                        "is_invalid": is_invalid,
                        "published_at": (
                            datetime.utcfromtimestamp(pubtime) if pubtime else None
                        ),
                    }
                )
            if not medias or not data.get("has_more"):
                break
            page += 1
        return videos

    def _resolve_subtitle_url(self, subtitle_url: str | None) -> str | None:
        if not subtitle_url:
            return None
        raw = subtitle_url.strip()
        if not raw or raw == "/":
            return None
        if raw.startswith("//"):
            return f"https:{raw}"
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return raw
        if raw.startswith("/"):
            return urljoin("https://api.bilibili.com", raw)
        return urljoin("https://api.bilibili.com/", raw)

    def _resolve_cover_url(self, cover_url: str | None) -> str | None:
        if not cover_url:
            return None
        raw = str(cover_url).strip()
        if not raw or raw == "/":
            return None
        if raw.startswith("//"):
            return f"https:{raw}"
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return raw
        if raw.startswith("/"):
            return urljoin("https://i0.hdslb.com", raw)
        return raw

    def _subtitle_priority(self, candidate: dict[str, Any]) -> tuple[int, int]:
        lan = (candidate.get("lan") or "").lower()
        is_ai = lan.startswith("ai-") or candidate.get("type") == 1
        is_zh = "zh" in lan
        if is_zh and not is_ai:
            return (0, 0)
        if not is_ai:
            return (1, 0)
        if is_zh:
            return (2, 0)
        return (3, 0)

    def _classify_subtitle_source(self, candidate: dict[str, Any]) -> str:
        lan = (candidate.get("lan") or "").lower()
        if lan.startswith("ai-") or candidate.get("type") == 1:
            return "ai-auto"
        if lan.startswith("zh"):
            return "manual-zh"
        return "manual"

    async def fetch_audio_track(self, bvid: str) -> dict[str, Any]:
        view_payload = await self._get_json(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            use_wbi=True,
        )
        view_data = view_payload.get("data") or {}
        cid = view_data.get("cid")
        if not cid:
            pages = view_data.get("pages") or []
            cid = pages[0]["cid"] if pages else None
        if not cid:
            raise RuntimeError(f"{bvid} 没有可用 cid，无法提取音频。")

        playurl_payload = await self._get_json(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "qn": 64, "fnval": 16, "fourk": 1},
        )
        dash_data = ((playurl_payload.get("data") or {}).get("dash") or {})
        audio_tracks = dash_data.get("audio") or []
        if not audio_tracks:
            raise RuntimeError(f"{bvid} 没有可用音频流。")

        chosen = min(audio_tracks, key=lambda item: int(item.get("bandwidth") or 0))
        audio_url = chosen.get("baseUrl") or chosen.get("base_url")
        if not audio_url:
            backups = chosen.get("backupUrl") or chosen.get("backup_url") or []
            audio_url = backups[0] if backups else None
        if not audio_url:
            raise RuntimeError(f"{bvid} 音频流 URL 为空。")

        return {
            "cid": int(cid),
            "audio_url": audio_url,
            "mime_type": chosen.get("mimeType") or chosen.get("mime_type") or "audio/mp4",
            "bandwidth": int(chosen.get("bandwidth") or 0),
            "track_id": chosen.get("id"),
        }

    async def download_audio_track(self, bvid: str, output_path: Path) -> dict[str, Any]:
        track = await self.fetch_audio_track(bvid)
        self._restore_cookies()
        async with self.client.stream(
            "GET",
            track["audio_url"],
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            with output_path.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    file.write(chunk)
        return track

    async def fetch_subtitles(self, bvid: str) -> dict[str, Any]:
        view_payload = await self._get_json(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            use_wbi=True,
        )
        view_data = view_payload.get("data") or {}
        cid = view_data.get("cid")
        if not cid:
            pages = view_data.get("pages") or []
            cid = pages[0]["cid"] if pages else None
        if not cid:
            raise RuntimeError(f"{bvid} 没有可用 cid。")

        player_payload = await self._get_json(
            "https://api.bilibili.com/x/player/v2",
            params={"bvid": bvid, "cid": cid},
        )
        subtitle_data = player_payload.get("data", {}).get("subtitle", {})
        subtitles = subtitle_data.get("subtitles") or []
        if not subtitles:
            raise RuntimeError(f"{bvid} 没有官方或 CC 字幕。")

        candidates = sorted(subtitles, key=self._subtitle_priority)
        chosen = None
        subtitle_url = None
        for candidate in candidates:
            resolved_url = self._resolve_subtitle_url(candidate.get("subtitle_url"))
            if resolved_url:
                chosen = candidate
                subtitle_url = resolved_url
                break
        if not chosen or not subtitle_url:
            raise RuntimeError(f"{bvid} 返回了字幕候选，但字幕 URL 无效。")
        response = await self.client.get(subtitle_url)
        response.raise_for_status()
        subtitle_payload = response.json()
        body = subtitle_payload.get("body") or []
        normalized = [
            {
                "from": float(item["from"]),
                "to": float(item["to"]),
                "content": item["content"],
            }
            for item in body
        ]
        await asyncio.sleep(self.settings.bili_api_delay)
        return {
            "cid": int(cid),
            "source": self._classify_subtitle_source(chosen),
            "subtitles": normalized,
        }
