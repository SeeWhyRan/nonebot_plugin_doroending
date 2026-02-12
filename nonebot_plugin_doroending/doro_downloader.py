"""
Doro 资源下载器模块

用于从 GitHub/Gitee 双源异步下载 Doro 结局相关静态资源：
- 图片目录：DoroEndingPic/
- 元数据文件：doroendings.json

核心功能：
- 优先使用 GitHub，失败自动回退到 Gitee。
- 递归下载整个目录结构。
- 已有文件且大小 > 100B 时自动跳过（断点续传）。
- 统计下载、跳过、失败数量。
- 返回包含状态、来源、JSON 数据、本地路径的 DownloadResult。

典型用法：
    downloader = AssetDownloader(Path("./data"))
    result = await downloader.download()
    if result.success:
        json_data = result.json_data   # 已解析的字典
        local_path = result.local_path # 下载根目录
"""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import aiofiles
import aiohttp
from nonebot import logger


@dataclass
class DownloadResult:
    success: bool
    message: str
    source: Literal["github", "gitee"] = "github"
    json_data: Optional[dict] = None
    local_path: Optional[Path] = None


class AssetDownloader:
    """极简双源异步下载器（自动回退，强制 Path）"""

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir
        self.timeout = 30

        # 双源配置（GitHub + Gitee）
        self.sources = {
            "github": {
                "api": "https://api.github.com/repos/SeeWhyRan/doroending_pic_assets/contents",
                "raw": "https://raw.githubusercontent.com/SeeWhyRan/doroending_pic_assets/main",
            },
            "gitee": {
                "api": "https://gitee.com/api/v5/repos/seewhy_ran/doroending_pic_assets/contents",
                "raw": "https://gitee.com/seewhy_ran/doroending_pic_assets/raw/main",
            },
        }
        self.current = "github"
        self.session: Optional[aiohttp.ClientSession] = None

        # 统计
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0

    async def _request(self, url: str) -> Optional[bytes]:
        """GET 请求，返回字节数据，失败返回 None"""
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.debug(f"{self.current.upper()} {resp.status}: {url}")
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    async def _download_file(self, raw_url: str, save_path: Path) -> bool:
        """下载单个文件，已存在且 >100B 则跳过"""
        if save_path.exists() and save_path.stat().st_size > 100:
            self.skipped += 1
            return True

        data = await self._request(raw_url)
        if not data:
            self.failed += 1
            return False

        save_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(save_path, "wb") as f:
            await f.write(data)
        self.downloaded += 1
        return True

    async def _download_dir(self, api_path: str, local_dir: Path) -> None:
        """递归下载目录"""
        url = f"{self.sources[self.current]['api']}/{api_path}" if api_path else self.sources[self.current]["api"]
        data = await self._request(url)
        if not data:
            return

        try:
            items = json.loads(data.decode())
        except:
            return

        for item in items:
            name = item["name"]
            if item.get("type") == "file" or "download_url" in item:
                raw = f"{self.sources[self.current]['raw']}/{api_path}/{name}" if api_path else f"{self.sources[self.current]['raw']}/{name}"
                await self._download_file(raw, local_dir / name)
            elif item.get("type") == "dir":
                sub = f"{api_path}/{name}" if api_path else name
                await self._download_dir(sub, local_dir / name)

    async def _try_source(self) -> tuple[bool, Optional[dict]]:
        """尝试使用当前源下载，返回 (是否成功, JSON数据)"""
        self.downloaded = self.skipped = self.failed = 0

        root_data = await self._request(self.sources[self.current]["api"])
        if not root_data:
            return False, None

        try:
            root = json.loads(root_data.decode())
        except:
            return False, None

        has_pic = any(i["name"] == "DoroEndingPic" and i.get("type") == "dir" for i in root)
        has_json = any(i["name"] == "doroendings.json" for i in root)

        if has_pic:
            await self._download_dir("DoroEndingPic", self.target_dir / "DoroEndingPic")
        if has_json:
            json_path = self.target_dir / "doroendings.json"
            raw_json = f"{self.sources[self.current]['raw']}/doroendings.json"
            if await self._download_file(raw_json, json_path):
                try:
                    async with aiofiles.open(json_path, "r", encoding="utf-8") as f:
                        json_data = json.loads(await f.read())
                except:
                    json_data = None
            else:
                json_data = None
        else:
            json_data = None

        success = True
        if has_json and not (self.target_dir / "doroendings.json").exists():
            success = False
        if has_pic and not any((self.target_dir / "DoroEndingPic").iterdir()):
            success = False

        return success, json_data

    async def download(self) -> DownloadResult:
        """主入口：先 GitHub，失败则自动切 Gitee"""
        self.target_dir.mkdir(parents=True, exist_ok=True)
        start = time.time()

        async with aiohttp.ClientSession(headers={"User-Agent": "DoroDownloader/2.0"}) as session:
            self.session = session

            self.current = "github"
            success, json_data = await self._try_source()

            if not success:
                self.current = "gitee"
                logger.warning("GitHub 失败，切换到 Gitee...")
                success, json_data = await self._try_source()

        elapsed = time.time() - start
        msg = f"下载完成，耗时 {elapsed:.1f}s | 成功: {self.downloaded} 跳过: {self.skipped} 失败: {self.failed}" if success \
               else f"下载失败（已尝试 GitHub 和 Gitee），耗时 {elapsed:.1f}s"

        logger.info(f"{'✅' if success else '❌'} {msg}")
        return DownloadResult(success, msg, self.current, json_data, self.target_dir)


async def download_assets(target_dir: Path) -> dict:
    """一键下载，必须传入 Path 对象"""
    dl = AssetDownloader(target_dir)
    res = await dl.download()
    return {
        "success": res.success,
        "message": res.message,
        "source": res.source,
        "json_data": res.json_data,
        "local_path": str(res.local_path) if res.local_path else None,
    }
