import asyncio
import imghdr
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, TypedDict

import aiohttp
import anyio
from nonebot import logger, on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata, get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """插件配置类"""
    SUPERUSER: str = ""

# 配置类
class ImageConfig:
    """图片配置"""
    max_size: int = 10 * 1024 * 1024  # 10MB
    timeout: int = 30  # 秒
    allowed_extensions: tuple = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    max_filename_length: int = 255
    # Content-Type 到文件扩展名的映射 - 使用 ClassVar 注解
    content_type_to_ext: ClassVar[dict[str, str]] = field(
        default_factory=lambda: {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
    )

@dataclass
class DoroEnding:
    """doro结局数据类"""
    id: int
    name: str
    english_name: str
    pic: str = ""

class DoroEndingUpdate(TypedDict, total=False):
    """doro结局允许修改的数据字典类型"""
    name: str
    english_name: str

class DoroDataDict(TypedDict):
    """doro结局数据字典类型"""
    datas: list["DoroEnding"]
    max_id: int
    total: int

class DoroEndingManager:
    """
    doro结局管理器
    load_from_file      读取json
    save_to_file        保存到json
    get_all_endings     获取结局列表
    get_ending_by_id    id查询结局
    get_ending_by_name  name查询结局
    search_endings      查询结局
    add_ending          增加结局
    remove_ending       删除结局
    update_ending       更新结局
    get_statistics      获取统计信息
    cleanup_images      清理无用图片
    validate_image_file 验证图片
    """
    DUPLICATE_NAME_MSG = "中文名 '{}' 已存在" # 重复名称错误消息模板
    NOT_FOUND_ID_MSG = "未找到ID为 {} 的结局" # 未找到ID错误消息模板
    DUPLICATE_ENGLISH_NAME_MSG = "英文名 '{}' 已存在" # 重复英文名错误消息模板
    DUPLICATE_CHINESE_NAME_MSG = "中文名 '{}' 已存在" # 重复中文名错误消息模板
    FILE_TOO_LARGE_MSG = "图片文件过大，最大允许'{}'字节"  # 图片文件过大错误消息模板
    UNSUPPORTED_FORMAT_MSG = "不支持的图片格式，允许的格式:'{}'"  # 不支持的图片格式错误消息模板  # noqa: E501
    SAVE_FAILED_MSG = "图片保存失败'{}'"  # 图片保存失败模板
    def __init__(
            self,
            data_file: str = "./datas/doroendings.json",
            pic_dir: str = "./datas/DoroEndingPic",
            image_config: Optional[ImageConfig] = None
            ) -> None:
        self.data_file = Path(data_file)
        self.pic_dir = Path(pic_dir)
        self.image_config = image_config or ImageConfig()
        self._data: DoroDataDict = {
            "datas": [],
            "max_id": 0,
            "total": 0
        }
        self._dirty = False  # 数据是否已修改（需要同步到文件）
        self._lock = asyncio.Lock()  # 并发锁
        self.pic_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在
    def _raise_value_error(self, msg_template: str, *args: Any):
        """统一的异常抛出函数"""
        raise ValueError(msg_template.format(*args))

    async def load_from_file(self) -> bool:
        """从文件加载数据到内存"""
        async with self._lock:  # 加锁保护
            try:
                if not self.data_file.exists():
                    logger.warning(f"数据文件不存在: {self.data_file}")
                    return False
                async with await anyio.open_file(
                    self.data_file,
                    "r",
                    encoding="utf-8"
                    ) as f:
                    content = await f.read()
                    # 解析JSON数据
                    raw_data: dict[str, Any] = json.loads(content)
                    loaded_data: DoroDataDict = {
                        "datas": [DoroEnding(**item) for item in raw_data.get("datas", [])],  # noqa: E501
                        "max_id": int(raw_data.get("max_id", 0)),
                        "total": int(raw_data.get("total", 0)),
                        }
                    # 更新内存数据
                    self._data = loaded_data
                    self._dirty = False
                    logger.info(f"成功加载 {len(self._data['datas'])} 条doro结局数据")
                    return True
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载数据文件失败: {e}")
                return False

    async def save_to_file(self) -> bool:
        """将内存中的数据保存到文件"""
        async with self._lock:  # 加锁保护
            if not self._dirty:
                logger.debug("数据未修改，跳过保存")
                return True
            try:
                # 准备保存数据
                save_data: dict[str, Any] = {
                    "datas": [asdict(item) for item in self._data["datas"]],
                    "max_id": self._data["max_id"],
                    "total": self._data["total"],
                }
                # 创建备份文件
                if self.data_file.exists():
                    backup_file = self.data_file.with_suffix(".json.bak")
                    await anyio.Path(self.data_file).rename(backup_file)
                # 写入新数据
                async with await anyio.open_file(
                    self.data_file,
                    "w",
                    encoding="utf-8"
                    ) as f:
                    await f.write(json.dumps(save_data, ensure_ascii=False, indent=2))
            except OSError as e:
                logger.error(f"保存数据文件失败: {e}")
                return False
            self._dirty = False
            logger.info("数据已保存到文件")
            return True

    def get_all_endings(self) -> list[DoroEnding]:
        """获取所有结局数据"""
        return self._data["datas"]

    def get_ending_by_id(self, ending_id: int) -> Optional[DoroEnding]:
        """根据ID获取结局"""
        for ending in self._data["datas"]:
            if ending.id == ending_id:
                return ending
        return None

    def get_ending_by_name(self, name: str) -> Optional[DoroEnding]:
        """根据中文名获取结局"""
        for ending in self._data["datas"]:
            if ending.name == name:
                return ending
        return None

    def search_endings(self, keyword: str) -> list[DoroEnding]:
        """搜索结局（支持中文名和英文名模糊搜索）"""
        keyword = keyword.lower()
        return [
            ending for ending in self._data["datas"]
            if (
                keyword in ending.name.lower() or
                keyword in ending.english_name.lower()
            )
        ]

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        # 移除非法文件名字符
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
        # 限制长度
        if len(filename) > self.image_config.max_filename_length:
            # 使用 Path 对象的方法
            path = Path(filename)
            stem, suffix = path.stem, path.suffix
            # 计算允许的主文件名长度
            max_stem_length = self.image_config.max_filename_length - len(suffix)
            if max_stem_length > 0:
                filename = stem[:max_stem_length] + suffix
            else:
                # 如果扩展名已经超过最大长度，只保留部分扩展名
                filename = suffix[-self.image_config.max_filename_length:]
        return filename

    def _detect_image_extension(self, image_bytes: bytes) -> str:
        """检测图片字节数据的格式并返回对应扩展名"""
        # 使用imghdr检测图片格式
        image_format = imghdr.what(None, image_bytes)
        if image_format:
            # 映射到标准扩展名
            format_to_ext = {
                "jpeg": ".jpg",
                "jpg": ".jpg",
                "png": ".png",
                "gif": ".gif",
                "webp": ".webp",
                "bmp": ".bmp",
            }
            return format_to_ext.get(image_format, ".jpg")
        return ".jpg"  # 默认扩展名

    async def _download_and_save_image(
        self,
        image_url: str,
        save_path: Path
    ) -> bool:
        """下载并保存图片，返回是否成功"""
        try:
            # 使用单个 async with 语句管理多个上下文
            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=self.image_config.timeout)
                ) as response
            ):
                response.raise_for_status()
                # 检查文件大小
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.image_config.max_size:
                    logger.warning(f"图片文件过大: {content_length} bytes")
                    return False
                # 读取数据
                image_bytes = await response.read()
                # 检查实际大小
                if len(image_bytes) > self.image_config.max_size:
                    logger.warning(f"图片文件过大: {len(image_bytes)} bytes")
                    return False
                # 根据Content-Type或字节数据检测扩展名
                #content_type = response.headers.get("Content-Type", "").lower()
                #if content_type in self.image_config.content_type_to_ext:
                #    ext = self.image_config.content_type_to_ext[content_type]
                #else:
                #    ext = self._detect_image_extension(image_bytes)
                # 确保扩展名在允许的列表中
                #if ext not in self.image_config.allowed_extensions:
                #    logger.warning(f"不支持的图片格式: {ext}")
                #    return False
                # 修改保存路径的扩展名
                #save_path = save_path.with_suffix(ext)
                # 保存文件
                async with await anyio.open_file(save_path.with_suffix(".jpg"), "wb") as img_file:
                    await img_file.write(image_bytes)
                logger.debug(f"图片已保存: {save_path.name}")
                return True
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"下载图片失败 {image_url}: {e}")
            return False

    async def add_ending(
        self,
        name: str,
        english_name: str,
        image_url: Optional[str] = None,
        image_bytes: Optional[bytes] = None
    ) -> Optional[DoroEnding]:
        """添加新的doro结局"""
        async with self._lock:  # 加锁保护整个添加过程
            # 检查名称是否已存在
            if self.get_ending_by_name(name):
                raise ValueError(self.DUPLICATE_NAME_MSG.format(name))
            # 生成新的ID
            new_id = self._data["max_id"] + 1
            # 处理图片
            pic_filename = ""
            if image_url or image_bytes:
                # 清理英文名用于文件名
                safe_english_name = self._sanitize_filename(english_name)
                pic_filename = f"{new_id:08d}_{safe_english_name}"
                pic_path = self.pic_dir / pic_filename
                try:
                    if image_bytes:
                        # 检查字节数据大小
                        if len(image_bytes) > self.image_config.max_size:
                            self._raise_value_error(
                                self.FILE_TOO_LARGE_MSG,
                                self.image_config.max_size
                            )
                        # 检测图片格式
                        #ext = self._detect_image_extension(image_bytes)
                        #if ext not in self.image_config.allowed_extensions:
                        #   self._raise_value_error(
                        #        self.UNSUPPORTED_FORMAT_MSG,
                        #        self.image_config.allowed_extensions
                        #    )
                        #pic_path = pic_path.with_suffix(ext)
                        pic_filename = pic_path.name + ".jpg"
                        # 直接保存字节数据
                        async with await anyio.open_file(pic_path, "wb") as img_file:
                            await img_file.write(image_bytes)
                        logger.debug(f"图片已保存: {pic_filename}")
                    elif image_url:
                        # 从URL下载图片
                        success = await self._download_and_save_image(image_url, pic_path)  # noqa: E501
                        if success:
                            # 获取实际保存的文件名（可能扩展名已改变）
                            pic_filename = pic_path.with_suffix("").name + ".jpg"
                            # 查找实际保存的文件
                            #for ext in self.image_config.allowed_extensions:
                            #    actual_path = pic_path.with_suffix(ext)
                            #    if actual_path.exists():
                            #        pic_filename = actual_path.name
                            #        break
                        else:
                            raise RuntimeError("图片下载失败")
                except (OSError, aiohttp.ClientError, ValueError) as e:
                    logger.error(f"图片保存失败: {e}")
                    # 如果图片保存失败，抛出异常
                    self._raise_value_error(
                        self.SAVE_FAILED_MSG,
                        e
                    )
            # 创建新的结局对象
            new_ending = DoroEnding(
                id=new_id,
                name=name,
                english_name=english_name,
                pic=pic_filename
            )
            # 添加到内存数据
            self._data["datas"].append(new_ending)
            self._data["max_id"] = new_id
            self._data["total"] += 1
            self._dirty = True
            logger.info(f"已添加新结局: {name} (ID: {new_id})")
            return new_ending

    async def remove_ending(self, target: Any) -> bool:
        """删除doro结局（支持ID或中文名）"""
        async with self._lock:  # 加锁保护
            ending = None
            # 根据类型查找
            if isinstance(target, int):
                ending = self.get_ending_by_id(target)
            elif isinstance(target, str):
                if target.isdigit():
                    ending = self.get_ending_by_id(int(target))
                else:
                    ending = self.get_ending_by_name(target)
            if not ending:
                return False
            try:
                # 删除图片文件
                if ending.pic:
                    pic_path = self.pic_dir / ending.pic
                    if await anyio.Path(pic_path).exists():
                        await anyio.Path(pic_path).unlink()
                        logger.info(f"已删除图片文件: {pic_path}")
                # 从内存中删除
                self._data["datas"].remove(ending)
                self._data["total"] -= 1
                # 如果删除的是最大ID的条目，重新计算max_id
                if ending.id == self._data["max_id"] and self._data["datas"]:
                    self._data["max_id"] = max(item.id for item in self._data["datas"])
                elif not self._data["datas"]:
                    self._data["max_id"] = 0
                self._dirty = True
                logger.info(f"已删除结局: {ending.name} (ID: {ending.id})")
            except OSError as e:
                logger.error(f"删除结局失败: {e}")
                return False
            return True

    async def update_ending(
            self,
            target: int,
            **kwargs: DoroEndingUpdate
            ) -> Optional[DoroEnding]:
        """更新doro结局信息"""
        async with self._lock:  # 加锁保护
            # 查找结局
            ending = self.get_ending_by_id(target)
            if not ending:
                logger.warning(f"未找到ID为 {target} 的结局")
                # 抛出异常，表示未找到ID
                raise ValueError(self.NOT_FOUND_ID_MSG.format(target))
            # 检查名称冲突
            field_mapping = {
                "name": ("name", self.DUPLICATE_CHINESE_NAME_MSG),
                "english_name": ("english_name", self.DUPLICATE_ENGLISH_NAME_MSG)
            }
            for field, (attr_name, error_msg) in field_mapping.items():
                if field in kwargs and kwargs[field] != getattr(ending, field):
                    new_value = kwargs[field]
                    # 检查是否有其他结局使用相同的名称
                    for e in self._data["datas"]:
                        if e.id != target and getattr(e, attr_name) == new_value:
                            logger.error(
                                f"{'中文名' if field == 'name' else '英文名'}"
                                f"'{new_value}' 已存在")
                            raise ValueError(error_msg.format(new_value))
            # 应用更新
            updated = False
            for key, value in kwargs.items():
                if hasattr(ending, key):
                    old_value = getattr(ending, key)
                    if old_value != value:
                        setattr(ending, key, value)
                        updated = True
                else:
                    logger.warning(f"跳过不存在的字段: {key}")
            # 标记脏数据
            if updated:
                self._dirty = True
                logger.info(f"已更新结局 '{ending.name}' (ID: {ending.id})")
            return ending

    def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "total": self._data["total"],
            "max_id": self._data["max_id"],
            "with_images": len([e for e in self._data["datas"] if e.pic]),
            "without_images": len([e for e in self._data["datas"] if not e.pic])
        }

    async def cleanup_images(self) -> list[str]:
        """清理无用的图片文件（没有对应记录的图片）"""
        async with self._lock:  # 加锁保护
            used_images = {ending.pic for ending in self._data["datas"] if ending.pic}
            # 获取所有图片文件
            pic_dir_path = anyio.Path(self.pic_dir)
            all_images = set()
            async for f in pic_dir_path.iterdir():
                if await f.is_file():
                    all_images.add(f.name)
            unused_images = list(all_images - used_images)
            cleaned = []
            failed_deletions = []
            # 遍历一次，收集所有要删除的文件路径
            to_delete = [pic_dir_path / image_name for image_name in unused_images]
            # 批量删除
            for image_path in to_delete:
                try:
                    await image_path.unlink()
                    cleaned.append(image_path.name)
                    logger.debug(f"清理图片: {image_path.name}")
                except OSError as e:  # noqa: PERF203
                    failed_deletions.append((image_path.name, str(e)))
            # 统一记录失败信息（避免每次失败都记录日志的开销）
            if failed_deletions:
                for image_name, error in failed_deletions:
                    logger.error(f"清理图片失败 {image_name}: {error}")
                logger.warning(f"成功清理 {len(cleaned)} 个文件，{len(failed_deletions)} 个文件清理失败")  # noqa: E501
            else:
                logger.info(f"已清理 {len(cleaned)} 个无用图片文件")
            return cleaned

    async def validate_image_file(self, ending_id: int) -> dict[str, Any]:  # noqa: PLR0911
        """验证图片文件是否存在且格式正确"""
        async with self._lock:  # 加锁保护
            ending = self.get_ending_by_id(ending_id)
            if not ending:
                return {"valid": False, "error": f"未找到ID为 {ending_id} 的结局"}
            if not ending.pic:
                return {"valid": False, "error": "该结局没有关联的图片"}
            pic_path = self.pic_dir / ending.pic
            if not await anyio.Path(pic_path).exists():
                return {"valid": False, "error": f"图片文件不存在: {pic_path}"}
            try:
                # 检查文件大小
                stat = await anyio.Path(pic_path).stat()
                if stat.st_size > self.image_config.max_size:
                    return {
                        "valid": False, 
                        "error": f"图片文件过大: {stat.st_size} bytes"
                    }
                # 检查文件格式
                async with await anyio.open_file(pic_path, "rb") as f:
                    header = await f.read(32)  # 读取前32字节用于检测
                detected_format = imghdr.what(None, header)
                if not detected_format:
                    return {"valid": False, "error": "无法识别图片格式"}
                return {
                    "valid": True,
                    "file_size": stat.st_size,
                    "format": detected_format,
                    "path": str(pic_path)
                }
            except OSError as e:
                return {"valid": False, "error": f"检查图片文件失败: {e}"}


# 全局管理器实例
_doro_manager: DoroEndingManager = DoroEndingManager()
config = get_plugin_config(Config)

__plugin_meta__ = PluginMetadata(
    name="今日doro结局",
    description="获取今日的doro结局",
    usage="发送“今日doro结局”获取今日的doro结局",
    type="application",
    homepage="https://github.com/SeeWhyRan/nonebot_plugin_doroending",
    config=Config,
    # 插件配置项类，如无需配置可不填写。

    supported_adapters={"~onebot.v11"},
    # 支持的适配器集合，其中 `~` 在此处代表前缀 `nonebot.adapters.`，
    # 其余适配器亦按此格式填写。
    # 若插件可以保证兼容所有适配器（即仅使用基本适配器功能）可不填写，
    # 否则应该列出插件支持的适配器。
)

__all__ = [
    "add_doro_ending",
    "get_doro_ending",
    "list_doro_endings",
    "remove_doro_ending",
]

async def load_doro_data():
    # 旧读取函数
    try:
        async with await anyio.open_file(
            "./datas/doroendings.json",
            "r",
            encoding="utf-8"
        ) as f:
            content = await f.read()
            return json.loads(content)
    except (OSError, aiohttp.ClientError) as e:
        logger.error(f"加载doro结局数据失败: {e}")
        return {"datas": [], "total": 0, "max_id": 0}

# 在插件启动时加载
from nonebot import get_driver

driver = get_driver()
# 保存加载的数据
data: dict = {}
# 保存用户和结局的映射
user_doro_map: dict = {}

@driver.on_startup
async def startup():
    # 插件初始化
    global _doro_manager  # noqa: PLW0602
    loaded = await _doro_manager.load_from_file()
    if not loaded:
        logger.warning("即将生成空数据")
        await _doro_manager.save_to_file()
    logger.debug("当前结局数据统计信息：")
    logger.debug(_doro_manager.get_statistics())
    logger.debug("结局列表如下")
    logger.debug(_doro_manager.get_all_endings())
    logger.info("doro结局插件已启动")


get_doro_ending = on_command("今日doro结局")
add_doro_ending = on_command("添加doro结局", permission=SUPERUSER)
remove_doro_ending = on_command("删除doro结局", permission=SUPERUSER)
list_doro_endings = on_command("列出doro结局",  permission=SUPERUSER)

@get_doro_ending.handle()
# 处理获取doro结局的命令
async def handle_doro_ending(
    event: MessageEvent
) -> None:
    # 判断是否已有记录
    global _doro_manager  # noqa: PLW0602
    if event.user_id in user_doro_map:
        logger.debug(f"用户（{event.user_id}）已有记录，使用已有结局")
        # 获取用户对应的结局id
        doro_id = user_doro_map[event.user_id]
        # 查找对应的结局信息
        doro_info = _doro_manager.get_ending_by_id(doro_id)
        if doro_info:
            # 找到结局，返回图片
            abs_image_path = await anyio.Path(
                f"./datas/DoroEndingPic/{doro_info.pic}"
                ).resolve()
            await get_doro_ending.finish(MessageSegment.image(f"file://{abs_image_path}"))
        else:
            # 如果找不到对应的结局，移除记录
            del user_doro_map[event.user_id]
            logger.debug(f"用户（{event.user_id}）的结局记录无效，重新选择结局")
    else:
        logger.debug(f"用户（{event.user_id}）没有记录，随机选择结局")
        # 随机选择一个结局
        data: list[DoroEnding] = _doro_manager.get_all_endings()
        doro_ending = random.randint(1, _doro_manager.get_statistics()["total"])
        doro_info = data[doro_ending - 1]
        # 记录用户和结局的映射
        user_doro_map[event.user_id] = doro_info.id
        # 构建图片路径
        image_path = await anyio.Path(
            f"./datas/DoroEndingPic/{doro_info.pic}"
            ).resolve()
        # 返回图片消息
        await get_doro_ending.finish(MessageSegment.image(f"file://{image_path}"))

@add_doro_ending.handle()
# 处理添加doro结局的命令
async def handle_add_doro_ending(
    event: MessageEvent,
    args: Message = CommandArg()
    ) -> None:
    # 获取原始消息
    raw_message = event.raw_message
    # 分离命令部分，获取参数
    cmd_len = len("/添加doro结局")
    params = raw_message[cmd_len:].strip()
    # 检查是否有参数
    if not params:
        await add_doro_ending.finish(
            "请提供两个名字和一张图片，格式：/添加doro结局 中文名 英文名 [图片]"
            )
    # 检查消息中是否有图片
    has_image = False
    image_url = None
    # 从事件消息中提取图片
    for segment in event.message:
        if segment.type == "image":
            has_image = True
            # 获取图片URL（不同适配器可能有不同字段）
            if "url" in segment.data:
                image_url = segment.data["url"]
            elif "file" in segment.data:
                image_url = segment.data["file"]
            break
    if not has_image:
        await add_doro_ending.finish(
            "请提供一张图片！格式：/添加doro结局 中文名 英文名 [图片]"
            )
    # 提取纯文本部分（去除图片CQ码）
    # 先获取纯文本参数
    text_args = args.extract_plain_text().strip()
    if not text_args:
        await add_doro_ending.finish("请提供两个名字，用空格隔开！")
    # 分割名字
    name_parts = text_args.split()
    min_name_count = 2
    if len(name_parts) < min_name_count:
        await add_doro_ending.finish("请提供两个名字，用空格隔开！")
    name = name_parts[0]
    english_name = name_parts[1]
    logger.debug(
        f"添加doro结局：中文名='{name}' 英文名='{english_name}' 图片URL='{image_url}'")
    try:
        await _doro_manager.add_ending(
        name = name,
        english_name = english_name,
        image_url = image_url
        )
        await _doro_manager.save_to_file()  # 保存数据到文件
        await add_doro_ending.finish("doro结局添加成功！")
    except ValueError as ve:
        await add_doro_ending.finish(f"添加doro结局失败: {ve}")

@remove_doro_ending.handle()
# 处理删除doro结局的命令
async def handle_rdoro_ending(
    args: Message = CommandArg()
) -> None:
    # 获取参数
    target = args.extract_plain_text().strip()
    # 检查是否提供了参数
    if not target:
        await remove_doro_ending.finish(
            "请提供要删除的doro结局的ID或中文名\n"
            "格式：/删除doro结局 [ID或中文名]\n"
            "例如：/删除doro结局 123 或 /删除doro结局 结局名称"
        )
    try:
        await _doro_manager.remove_ending(target)
        await remove_doro_ending.finish("doro结局删除成功！")
    except ValueError as ve:
        await remove_doro_ending.finish(f"删除doro结局失败: {ve}")

@list_doro_endings.handle()
# 处理列出doro结局的命令
async def handle_list_doro_endings(
    event: MessageEvent,
    bot: Bot
) -> None:
    # 获取所有结局数据
    data: list[DoroEnding] = _doro_manager.get_all_endings()
    tatal = _doro_manager.get_statistics()["total"]
    if tatal == 0:
        await list_doro_endings.finish("当前没有任何doro结局数据！")
    # 按ID排序
    data.sort(key=lambda x: x.id)
    # 构建合并转发节点列表
    nodes = []
    nodes.append(
        ("doro结局", bot.self_id, Message("以下是所有doro结局"))
    )
    # 每50个结局放一条消息
    split_num = 50
    pair = []
    for idx, data_item in enumerate(data, 1):
        msg = (
            f"{data_item.id}. {data_item.name}\n"
        )
        pair.append(msg)
        if len(pair) == split_num or idx == len(data):
            nodes.append(("doro结局", bot.self_id, Message("".join(pair))))
            pair = []
    # 发送合并转发消息
    await send_forward_msg(bot, event, nodes)
    await list_doro_endings.finish()

async def send_forward_msg(
    bot: Bot,
    event: MessageEvent,
    user_message: list[tuple[str, str, Message]],
):
    """
    发送 forward 消息

    > 参数：
        - bot: Bot 对象
        - event: MessageEvent 对象
        - user_message: 合并消息的用户信息列表

    > 返回值：
        - 成功：返回消息发送结果
        - 失败：抛出异常
    """

    def to_json(info: tuple[str, str, Message]):
        """
        将消息转换为 forward 消息的 json 格式
        """
        return {
            "type": "node",
            "data": {"name": info[0], "uin": info[1], "content": info[2]},
        }

    messages = [to_json(info) for info in user_message]

    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "send_group_forward_msg", group_id=event.group_id, messages=messages
        )
    else:
        await bot.call_api(
            "send_private_forward_msg", user_id=event.user_id, messages=messages
        )
