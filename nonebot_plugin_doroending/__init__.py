import random
import json  # noqa: N999
from pathlib import Path
from datetime import datetime

from nonebot.adapters import Bot
from nonebot.params import Depends
from nonebot.permission import SuperUser
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot import logger, require, get_driver

from .doro_downloader import download_assets
from .doro_manager import DoroEnding, DoroEndingManager

require("nonebot_plugin_localstore")
require("nonebot_plugin_alconna")
require("nonebot_plugin_uninfo")

import nonebot_plugin_localstore as store
from nonebot_plugin_uninfo import Uninfo
from nonebot_plugin_alconna import (
    Args,
    Text,
    Field,
    Image,
    Match,
    Alconna,
    CustomNode,
    Subcommand,
    UniMessage,
    on_alconna,
)

__plugin_meta__ = PluginMetadata(
    name="今日doro结局",
    description="获取今日的doro结局",
    usage="发送“今日doro结局”获取今日的doro结局",
    type="application",
    homepage="https://github.com/SeeWhyRan/nonebot_plugin_doroending",
    # 插件配置项类，如无需配置可不填写。
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    # 支持的适配器集合，其中 `~` 在此处代表前缀 `nonebot.adapters.`，
    # 其余适配器亦按此格式填写。
    # 若插件可以保证兼容所有适配器（即仅使用基本适配器功能）可不填写，
    # 否则应该列出插件支持的适配器。
)
driver = get_driver()

# ---------- 统一使用 localstore 数据目录 ----------
PLUGIN_DATA_DIR = store.get_plugin_data_dir()
DORO_ENDING_PIC_DIR = PLUGIN_DATA_DIR / "DoroEndingPic"
JSON_FILE = PLUGIN_DATA_DIR / "doroendings.json"
DATE_RECORD_FILE = PLUGIN_DATA_DIR / "doro_date_record.json"
USER_MAP_FILE = PLUGIN_DATA_DIR / "user_doro_map.json"

# 全局管理器
_doro_manager = DoroEndingManager(data_file=JSON_FILE, pic_dir=DORO_ENDING_PIC_DIR)
user_doro_map: dict = {}
current_date: str = ""


# ---------- 启动时自动下载 ----------
@driver.on_startup
async def startup() -> None:
    """插件初始化：若 JSON 文件不存在则自动下载"""
    global _doro_manager, user_doro_map, current_date  # noqa: PLW0602, PLW0603

    # 1. 如果数据文件不存在，执行下载
    if not JSON_FILE.exists():
        logger.warning("未找到本地结局数据，开始从 GitHub/Gitee 下载...")
        result = await download_assets(PLUGIN_DATA_DIR)
        if result["success"]:
            logger.success(f"资源下载成功，来源: {result['source'].upper()}")
            logger.info(f"JSON 记录数: {len(result['json_data'] or [])}")
        else:
            logger.error(f"资源下载失败: {result['message']}")
            raise RuntimeError("DoroEnding 插件初始化失败：无法解析资源文件")  # noqa: TRY003
    else:
        logger.info("本地结局数据已存在，跳过下载")

    # 2. 加载结局数据
    loaded = await _doro_manager.load()
    if not loaded:
        logger.error("结局数据加载失败，插件可能无法正常工作")
    else:
        logger.debug("结局数据加载成功")
        logger.debug(_doro_manager.get_all())

    # 3. 加载日期记录和用户映射
    current_date = read_dict_from_json(DATE_RECORD_FILE).get("date", "")
    user_doro_map = read_dict_from_json(USER_MAP_FILE)
    logger.info(f"加载日期记录: {current_date}")
    logger.info(f"已加载用户结局映射记录数: {len(user_doro_map)}")
    logger.info("doro结局插件已启动")


doro_ending = on_alconna(
    Alconna(
        "doro",
        Subcommand(
            "add",
            Args["zh", str, Field(completion=lambda: "请输入中文名")][
                "en", str, Field(completion=lambda: "请输入英文名")
            ]["img", Image, Field(completion=lambda: "请发送一张图片")],
            alias="添加doro结局",
        ),
        Subcommand(
            "remove", Args["id", str, Field(completion=lambda: "请输入要删除的doro结局ID")], alias="删除doro结局"
        ),
        Subcommand("list", alias="列出doro结局"),
    ),
    use_cmd_start=True,
    comp_config={"lite": True},
)
doro_ending.shortcut("今日doro结局", {"command": "doro", "fuzzy": False, "prefix": True})
doro_ending.shortcut("添加doro结局", {"command": "doro add", "fuzzy": True, "prefix": True})
doro_ending.shortcut("删除doro结局", {"command": "doro remove", "fuzzy": True, "prefix": True})
doro_ending.shortcut("列出doro结局", {"command": "doro list", "fuzzy": True, "prefix": True})


@doro_ending.assign("$main")
# 处理获取doro结局的命令
async def handle_doro_ending(user: Uninfo):
    # 获取当前日期
    global current_date  # noqa: PLW0603
    global _doro_manager  # noqa: PLW0602
    today = datetime.now().strftime("%Y-%m-%d")  # noqa: DTZ005
    # 如果日期已过期，清空用户结局映射并更新日期
    uid = user.user.id
    if current_date != today:
        logger.info(f"日期已过期，清空用户结局映射。原日期: {current_date}, 今天: {today}")  # noqa: E501
        user_doro_map.clear()
        current_date = today
        # 保存新的日期记录
        write_dict_to_json({"date": current_date}, file_path=DATE_RECORD_FILE)
        # 清空用户映射文件
        write_dict_to_json({}, file_path=USER_MAP_FILE)
    # 判断是否已有记录
    # 日志记录当前用户ID和现有的用户结局映射
    logger.debug(f"当前用户ID: {user.user.id}")
    logger.debug(f"现有用户结局映射: {user_doro_map}")
    # 如果用户已有记录，直接使用已有的结局
    if uid in user_doro_map:
        logger.debug(f"用户（{user.user.id}）已有记录，使用已有结局")
        # 获取用户对应的结局id
        doro_id = user_doro_map[uid]
        # 查找对应的结局信息
        doro_info = _doro_manager.get_by_id(doro_id)
        if doro_info:
            img_path = DORO_ENDING_PIC_DIR / doro_info.pic
            # 确保文件存在，然后发送
            await UniMessage.image(path=img_path).finish()
        else:
            # 如果找不到对应的结局，移除记录
            del user_doro_map[uid]
            logger.debug(f"用户（{uid}）的结局记录无效，重新选择结局")
    else:
        logger.debug(f"用户（{uid}）没有记录，随机选择结局")
        # 随机选择一个结局
        data: list[DoroEnding] = _doro_manager.get_all()
        doro_ending = random.randint(1, len(data))
        doro_info = data[doro_ending - 1]
        # 记录用户和结局的映射
        user_doro_map[uid] = doro_info.id
        # 保存映射到文件
        write_dict_to_json(user_doro_map, file_path=USER_MAP_FILE)
        logger.debug(f"记录用户（{uid}）的结局ID为 {doro_info.id}")
        # 构建图片路径
        img_path = DORO_ENDING_PIC_DIR / doro_info.pic
        # 返回图片消息
        await UniMessage.image(path=img_path).finish()


@doro_ending.assign("add")
# 处理添加doro结局的命令
async def handle_add_doro_ending(
    zh: Match[str], en: Match[str], img: Match[Image], is_superuser: bool = Depends(SuperUser())
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    logger.debug(f"添加doro结局：中文名='{zh.result}' 英文名='{en.result}' 图片URL='{img.result.url}'")
    try:
        await _doro_manager.add(name=zh.result, english_name=en.result, image_url=img.result.url)
        await UniMessage(f"doro结局 '{zh.result}' 添加成功！").finish()
    except ValueError as ve:
        await UniMessage(f"添加doro结局失败: {ve}").finish()


@doro_ending.assign("remove")
# 处理删除doro结局的命令
async def handle_remove_doro_ending(id: Match[str], is_superuser: bool = Depends(SuperUser())) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    # 获取参数
    target = id.result
    # 检查是否提供了参数
    if not target:
        await UniMessage(
            "请提供要删除的doro结局的ID或中文名\n"
            "格式：/删除doro结局 [ID或中文名]\n"
            "例如：/删除doro结局 123 或 /删除doro结局 结局名称"
        ).finish()
    try:
        await _doro_manager.remove(target)
        await UniMessage("doro结局删除成功！").finish()
    except ValueError as ve:
        await UniMessage(f"删除doro结局失败: {ve}").finish()


@doro_ending.assign("list")
# 处理列出doro结局的命令
async def handle_list_doro_endings(bot: Bot, is_superuser: bool = Depends(SuperUser())) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    # 获取所有结局数据
    data: list[DoroEnding] = _doro_manager.get_all()
    tatal = len(data)
    if tatal == 0:
        await UniMessage("当前没有任何doro结局数据！").finish()
    # 按ID排序
    data.sort(key=lambda x: x.id)
    # 构建合并转发节点列表
    nodes = []
    nodes.append(CustomNode(bot.self_id, "doro结局", "以下是所有doro结局"))
    # 每50个结局放一条合并消息
    split_num = 50
    msg_list = [
        UniMessage(Text(f"{item.id}. {item.name}\n") + Image(path=DORO_ENDING_PIC_DIR / item.pic)) for item in data
    ]
    split_msg_list = [msg_list[i : i + split_num] for i in range(0, tatal, split_num)]
    for data_item in split_msg_list:
        nodes = [CustomNode(bot.self_id, "doro结局", msg) for msg in data_item]
        await UniMessage.reference(*nodes).send()


def write_dict_to_json(data_dict: dict, file_path: Path) -> None:
    """
    将Python字典写入JSON文件（使用Path对象）
    Args:
        data_dict: 要写入的字典
        file_path: Path对象，文件保存路径
    """
    try:
        # 自动创建父目录
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open(mode="w", encoding="utf-8") as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
        logger.debug(f"字典已成功写入 {file_path}")
    except ValueError as e:
        logger.error(f"写入文件时出错: {e}")


def read_dict_from_json(file_path: Path) -> dict:
    """
    从JSON文件中读取Python字典（使用Path对象）
    Args:
        file_path: Path对象，文件路径
    Returns:
        读取到的字典，如果读取失败则返回空字典
    """
    try:
        with file_path.open(mode="r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug(f"字典已成功从 {file_path} 读取")
    except FileNotFoundError:
        logger.warning(f"文件 {file_path} 不存在，返回空字典")
        return {}
    except json.JSONDecodeError:
        logger.warning(f"文件 {file_path} 格式错误，返回空字典")
        return {}
    except ValueError as e:
        logger.error(f"读取文件时出错: {e}")
        return {}
    return data
