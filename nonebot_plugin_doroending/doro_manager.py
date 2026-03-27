"""
Doro 结局管理器模块

用于管理“Doro结局”条目，支持数据的持久化存储（JSON 文件）、图片下载与管理、
以及结局条目的增删改查操作。

主要类：
- DoroEnding：结局数据模型，包含 ID、名称、英文名称、图片文件名。
- DoroEndingManager：核心管理器，封装所有操作，基于 anyio 实现异步文件 I/O，
  使用 aiohttp 下载图片，依赖 imghdr 识别图片格式。

基本用法：
1. 实例化管理器，传入 JSON 数据文件路径和图片存放目录。
   manager = DoroEndingManager(data_file=Path("endings.json"), pic_dir=Path("pics"))
2. 异步加载已有数据（若文件存在）：
   await manager.load()
3. 执行各种操作，例如：
   - 查询所有结局：manager.get_all()
   - 按 ID/名称查找：manager.get_by_id(1) / manager.get_by_name("结局名")
   - 搜索关键词：manager.search("doro")
   - 添加结局：await manager.add("新结局", "new_ending", image_url="...")
   - 删除结局：await manager.remove(1)  # 按 ID 或名称
   - 更新结局：await manager.update(1, name="新名字")
4. 操作会自动保存数据文件，无需手动调用 save()（但 load() 需要手动执行一次）。

注意事项：
- 图片下载支持 jpg/png/gif/webp/bmp，默认保存为 .jpg。
- 单张图片大小限制为 10MB。
- 英文名称作为唯一标识，添加时不可重复。
- 所有文件读写均为异步非阻塞，适合在异步框架（如 NoneBot）中使用。
"""

import re
import json
import imghdr
from pathlib import Path
from typing import Union, Optional
from dataclasses import asdict, dataclass

import anyio
import aiohttp
from nonebot import logger


@dataclass
class DoroEnding:
    id: int
    name: str
    english_name: str
    pic: str = ""


class DoroEndingManager:
    """doro 结局管理器"""

    def __init__(self, data_file: Path, pic_dir: Path) -> None:
        self.data_file = data_file
        self.pic_dir = pic_dir
        self.pic_dir.mkdir(parents=True, exist_ok=True)
        self._endings: list[DoroEnding] = []
        self._max_id = 0
        self._total_ending = 0

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    async def load(self) -> bool:
        if not self.data_file.exists():
            logger.warning(f"数据文件不存在: {self.data_file}")
            return False
        try:
            async with await anyio.open_file(self.data_file, encoding="utf-8") as f:
                raw = json.loads(await f.read())
            self._endings = [DoroEnding(**item) for item in raw.get("datas", [])]
            self._max_id = int(raw.get("max_id", 0))
            logger.info(f"已加载 {len(self._endings)} 条结局")
        except ValueError as e:
            logger.error(f"加载失败: {e}")
            return False
        return True

    async def save(self) -> bool:
        try:
            data = {
                "datas": [asdict(e) for e in self._endings],
                "max_id": self._max_id,
                "total": len(self._endings),
            }
            async with await anyio.open_file(self.data_file, "w", encoding="utf-8") as f:  # noqa: E501
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            logger.debug("数据已保存")
        except ValueError as e:
            logger.error(f"保存失败: {e}")
            return False
        return True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_all(self) -> list[DoroEnding]:
        return self._endings.copy()

    def get_by_id(self, ending_id: int) -> Optional[DoroEnding]:
        for e in self._endings:
            if e.id == ending_id:
                return e
        return None

    def get_by_name(self, name: str) -> Optional[DoroEnding]:
        for e in self._endings:
            if e.name == name:
                return e
        return None

    def search(self, keyword: str) -> list[DoroEnding]:
        keyword = keyword.lower()
        return [e for e in self._endings if keyword in e.name.lower() or keyword in e.english_name.lower()]

    # ------------------------------------------------------------------
    # 增删改
    # ------------------------------------------------------------------
    async def add(
        self,
        name: str,
        english_name: str,
        image_url: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ) -> DoroEnding:
        for e in self._endings:
            if e.english_name == english_name:
                raise ValueError(f"英文名 '{english_name}' 已存在")  # noqa: TRY003

        new_id = self._max_id + 1
        pic_name = ""

        if image_url or image_bytes:
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", english_name)[:50]
            base_path = self.pic_dir / f"{new_id:08d}_{safe_name}"

            try:
                if image_bytes:
                    ext = self._detect_ext(image_bytes)
                    path = base_path.with_suffix(ext)
                    async with await anyio.open_file(path, "wb") as f:
                        await f.write(image_bytes)
                    pic_name = path.name
                elif image_url:
                    path = await self._download_image(image_url, base_path)
                    if path:
                        pic_name = path.name
            except Exception as e:
                raise ValueError(f"图片保存失败: {e}") from e  # noqa: TRY003

        ending = DoroEnding(new_id, name, english_name, pic_name)
        self._endings.append(ending)
        self._max_id = new_id
        await self.save()
        logger.info(f"添加结局: {name} (ID: {new_id})")
        return ending

    async def remove(self, target: Union[int, str]) -> bool:
        ending = self.get_by_id(target) if isinstance(target, int) else self.get_by_name(target)  # noqa: E501
        if not ending:
            return False

        if ending.pic:
            img_path = self.pic_dir / ending.pic
            if await anyio.Path(img_path).exists():
                await anyio.Path(img_path).unlink()

        self._endings.remove(ending)
        if ending.id == self._max_id:
            self._max_id = max((e.id for e in self._endings), default=0)
        await self.save()
        logger.info(f"删除结局: {ending.name} (ID: {ending.id})")
        return True

    async def update(
        self, ending_id: int, name: Optional[str] = None, english_name: Optional[str] = None
    ) -> DoroEnding:
        ending = self.get_by_id(ending_id)
        if not ending:
            raise ValueError(f"未找到 ID 为 {ending_id} 的结局")  # noqa: TRY003

        if name is not None and name != ending.name:
            ending.name = name

        if english_name is not None and english_name != ending.english_name:
            for e in self._endings:
                if e.id != ending_id and e.english_name == english_name:
                    raise ValueError(f"英文名 '{english_name}' 已存在")  # noqa: TRY003
            ending.english_name = english_name

        await self.save()
        logger.info(f"更新结局: {ending.name} (ID: {ending.id})")
        return ending

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _detect_ext(self, data: bytes) -> str:
        fmt = imghdr.what(None, data)
        if fmt in ("jpeg", "jpg"):
            return ".jpg"
        if fmt == "png":
            return ".png"
        if fmt == "gif":
            return ".gif"
        if fmt == "webp":
            return ".webp"
        if fmt == "bmp":
            return ".bmp"
        return ".jpg"

    async def _download_image(self, url: str, save_path: Path) -> Optional[Path]:
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.read()
                if len(data) > 10 * 1024 * 1024:  # 10MB 限制
                    logger.error("图片过大 (超过10MB)")
                    return None
                ext = self._detect_ext(data)
                save_path = save_path.with_suffix(ext)
                async with await anyio.open_file(save_path, "wb") as f:
                    await f.write(data)
                return save_path
        except ValueError as e:
            logger.error(f"下载图片失败 {url}: {e}")
            return None
