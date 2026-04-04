import random
import json  # noqa: N999
from pathlib import Path
from datetime import datetime

from nonebot.adapters import Bot
from nonebot.params import Depends
from nonebot.permission import SuperUser
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot import logger, require, get_driver

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
    AlconnaMatcher,
    on_alconna,
)

from .doro_downloader import download_assets
from .doro_manager import DoroEnding, DoroEndingManager

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
            Args["zh?", str, Field(completion=lambda: "请输入中文名")][
                "en?", str, Field(completion=lambda: "请输入英文名")
            ]["img?", Image, Field(completion=lambda: "请发送一张图片")],
            alias="添加doro结局",
        ),
        Subcommand(
            "remove",
            Args["id?", str, Field(completion=lambda: "请输入要删除的doro结局ID或中文名")],
            alias="删除doro结局",
        ),
        Subcommand(
            "update",
            Args["id?", str, Field(completion=lambda: "请输入要修改的doro结局ID")][
                "field?", str, Field(completion=lambda: "请输入 1(中文名) 或 2(英文名)")
            ]["value?", str, Field(completion=lambda: "请输入新的名称")],
            alias="修改doro结局",
        ),
        Subcommand("help", alias="doro结局帮助"),
        Subcommand("list", alias="列出doro结局"),
    ),
    use_cmd_start=True,
    comp_config={"lite": True},
)
doro_ending.shortcut("今日doro结局", {"command": "doro", "fuzzy": False, "prefix": True})
doro_ending.shortcut("添加doro结局", {"command": "doro add", "fuzzy": True, "prefix": True})
doro_ending.shortcut("删除doro结局", {"command": "doro remove", "fuzzy": True, "prefix": True})
doro_ending.shortcut("列出doro结局", {"command": "doro list", "fuzzy": True, "prefix": True})
doro_ending.shortcut("修改doro结局", {"command": "doro update", "fuzzy": True, "prefix": True})
doro_ending.shortcut("doro结局帮助", {"command": "doro help", "fuzzy": True, "prefix": True})

# 为子命令创建独立 matcher，避免不同子命令之间的会话状态相互干扰
add_cmd = doro_ending.dispatch("add")
remove_cmd = doro_ending.dispatch("remove")
update_cmd = doro_ending.dispatch("update")


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


@add_cmd.handle()
# 处理添加doro结局的命令
async def handle_add_doro_ending(
    matcher: AlconnaMatcher,
    zh: Match[str],
    en: Match[str],
    img: Match[Image],
    is_superuser: bool = Depends(SuperUser()),
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    # 将已提供的参数写入会话上下文
    if zh.available:
        matcher.set_path_arg("add.zh", zh.result)
    if en.available:
        matcher.set_path_arg("add.en", en.result)
    if img.available:
        matcher.set_path_arg("add.img", img.result)

# 交互式补全中文名
@add_cmd.got_path("add.zh", prompt="请输入结局的中文名：")
async def got_add_zh(matcher: AlconnaMatcher, zh: str) -> None:
    # 支持取消当前添加流程
    if zh.strip() in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局添加。").finish()
        return
    matcher.set_path_arg("add.zh", zh)

@add_cmd.got_path("add.en", prompt="请输入结局的英文名：")
async def got_add_en(matcher: AlconnaMatcher, en: str) -> None:
    if en.strip() in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局添加。").finish()
        return
    matcher.set_path_arg("add.en", en)

@add_cmd.got_path("add.img", prompt="请发送一张结局图片：")
async def got_add_img(
    zh: str,
    en: str,
    img: Image,
    is_superuser: bool = Depends(SuperUser()),
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    logger.debug(f"添加doro结局：中文名='{zh}' 英文名='{en}' 图片URL='{img.url}'")
    try:
        await _doro_manager.add(name=zh, english_name=en, image_url=img.url)
        await UniMessage(f"doro结局 '{zh}' 添加成功！").finish()
    except ValueError as ve:
        await UniMessage(f"添加doro结局失败: {ve}").finish()


@remove_cmd.handle()
# 处理删除doro结局的命令
async def handle_remove_doro_ending(
    matcher: AlconnaMatcher,
    id: Match[str],
    is_superuser: bool = Depends(SuperUser()),
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    if id.available:
        matcher.set_path_arg("remove.id", id.result)

@remove_cmd.got_path("remove.id", prompt="请输入要删除的doro结局ID或中文名：")
async def got_remove_id(id: str, is_superuser: bool = Depends(SuperUser())) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    if id.strip() in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局删除。").finish()
        return
    # 支持通过数字 ID 或中文名删除
    target: int | str
    if id.isdigit():
        target = int(id)
    else:
        target = id
    try:
        success = await _doro_manager.remove(target)
    except ValueError as ve:  # 兼容管理器可能抛出的异常
        await UniMessage(f"删除doro结局失败: {ve}").finish()
        return

    if success:
        await UniMessage("doro结局删除成功！").finish()
    else:
        await UniMessage("未找到指定的doro结局，请检查ID或名称是否正确。").finish()

@update_cmd.handle()
# 处理修改doro结局的命令
async def handle_update_doro_ending(
    matcher: AlconnaMatcher,
    id: Match[str],
    is_superuser: bool = Depends(SuperUser()),
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()
    if id.available:
        matcher.set_path_arg("update.id", id.result)

@update_cmd.got_path("update.id", prompt="请输入要修改的doro结局ID：")
async def got_update_id(matcher: AlconnaMatcher, id: str) -> None:
    if id.strip() in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局修改。").finish()
        return
    # 仅支持通过数字 ID 修改
    if not id.isdigit():
        await matcher.reject("ID 应为数字，请重新输入：")
    ending_id = int(id)
    if not _doro_manager.get_by_id(ending_id):
        await matcher.reject("未找到该 ID 的 doro 结局，请重新输入有效的 ID：")
    matcher.set_path_arg("update.id", ending_id)


@update_cmd.got_path("update.field", prompt="要修改什么？\n1. 中文名\n2. 英文名")
async def got_update_field(matcher: AlconnaMatcher, field: str) -> None:
    choice = field.strip()
    if choice in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局修改。").finish()
        return
    if choice in {"1", "中文", "中文名"}:
        matcher.set_path_arg("update.field", "name")
    elif choice in {"2", "英文", "英文名", "english", "en"}:
        matcher.set_path_arg("update.field", "english_name")
    else:
        await matcher.reject("无效的选项，请输入 1（中文名）或 2（英文名）：")

@update_cmd.got_path("update.value", prompt="请输入新的名称：")
async def got_update_value(
    id: int,
    field: str,
    value: str,
    is_superuser: bool = Depends(SuperUser()),
) -> None:
    if not is_superuser:
        await UniMessage.text("该指令仅超管可用").finish()

    if value.strip() in {"取消", "/取消", "结束", "算了", "cancel", "退出"}:
        await UniMessage.text("已取消本次 doro 结局修改。").finish()
        return

    update_kwargs: dict[str, str] = {}
    if field == "name":
        update_kwargs["name"] = value
        field_cn = "中文名"
    elif field == "english_name":
        update_kwargs["english_name"] = value
        field_cn = "英文名"
    else:
        await UniMessage("未知的修改类型，请重新开始命令。").finish()
        return

    try:
        ending = await _doro_manager.update(id, **update_kwargs)
    except ValueError as ve:
        await UniMessage(f"修改doro结局失败: {ve}").finish()
        return

    await UniMessage(
        f"doro结局修改成功！\nID: {ending.id}\n新的{field_cn}: {value}"
    ).finish()


@doro_ending.assign("help")
async def handle_doro_help(is_superuser: bool = Depends(SuperUser())) -> None:
    """根据用户身份返回 doro 结局帮助列表。"""

    lines: list[str] = [
        "doro 结局指令列表：",
        "- 今日doro结局：获取今日的 doro 结局",
        "- doro结局帮助：查看本帮助",
    ]

    if is_superuser:
        lines.extend(
            [
                "- 添加doro结局：添加新的结局，可一次性提供参数或对话式补全",
                "- 删除doro结局：按 ID 或中文名删除结局，支持对话式补全",
                "- 修改doro结局：按 ID 修改结局中文名/英文名，支持对话式补全",
                "- 列出doro结局：以合并转发形式列出所有结局",
            ]
        )

    await UniMessage("\n".join(lines)).finish()


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
