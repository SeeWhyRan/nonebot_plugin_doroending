import json
import random
from datetime import datetime

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

from .model import Config, DoroEnding, DoroEndingManager
from .resourse import download_doro_assets

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

# 在插件启动时加载
from nonebot import get_driver

driver = get_driver()
# 保存加载的数据
data: dict = {}
# 保存用户和结局的映射
user_doro_map: dict = {}
# 保存当前数据的日期
current_date: str = ""

@driver.on_startup
async def startup():
    # 插件初始化
    global _doro_manager  # noqa: PLW0602
    global user_doro_map  # noqa: PLW0603
    global current_date  # noqa: PLW0603
    loaded = await _doro_manager.load_from_file()
    # 如果本地没有数据，则尝试从github下载
    if not loaded:
        logger.warning("本地无结局数据 即将从github上下载...")
        result = download_doro_assets(
            target_dir="./data/nonebot_plugin_doroending",
            token=config.GITHUB_TOKEN
            )
        logger.info(f"最终结果: {result['success']}")
        logger.info(f"消息: {result['message']}")
        if result['json_data']:
            logger.info(f"JSON记录数: {len(result['json_data'])}")
        logger.info(f"保存路径: {result['local_path']}")
    # 尝试再次加载数据
    loaded = await _doro_manager.load_from_file()
    logger.debug("当前结局数据统计信息：")
    logger.debug(_doro_manager.get_statistics())
    logger.debug("结局列表如下")
    # 加载日期记录
    current_date = read_dict_from_json(
        filename="./data/nonebot_plugin_doroending/doro_date_record.json"
        ).get("date", "")
    # 加载文件中保存的用户结局映射
    user_doro_map = read_dict_from_json(
        filename="./data/nonebot_plugin_doroending/user_doro_map.json"
        )
    logger.info(f"加载日期记录: {current_date}")
    logger.info(f"已加载用户结局映射记录数: {len(user_doro_map)}")
    logger.debug(f"当前用户结局映射: {user_doro_map}")
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
    # 获取当前日期
    global current_date  # noqa: PLW0603
    global _doro_manager  # noqa: PLW0602
    today = datetime.now().strftime("%Y-%m-%d")
    # 如果日期已过期，清空用户结局映射并更新日期
    if current_date != today:
        logger.info(f"日期已过期，清空用户结局映射。原日期: {current_date}, 今天: {today}")
        user_doro_map.clear()
        current_date = today
        # 保存新的日期记录
        write_dict_to_json({"date": current_date}, filename="./data/nonebot_plugin_doroending/doro_date_record.json")
        # 清空用户映射文件
        write_dict_to_json({}, filename="./data/nonebot_plugin_doroending/user_doro_map.json")
    # 判断是否已有记录
    # 日志记录当前用户ID和现有的用户结局映射
    logger.debug(f"当前用户ID: {event.user_id}")
    logger.debug(f"现有用户结局映射: {user_doro_map}")
    # 如果用户已有记录，直接使用已有的结局
    if str(event.user_id) in user_doro_map:
        logger.debug(f"用户（{event.user_id}）已有记录，使用已有结局")
        # 获取用户对应的结局id
        doro_id = user_doro_map[str(event.user_id)]
        # 查找对应的结局信息
        doro_info = _doro_manager.get_ending_by_id(doro_id)
        if doro_info:
            # 找到结局，返回图片
            abs_image_path = await anyio.Path(
                f"./data/nonebot_plugin_doroending/DoroEndingPic/{doro_info.pic}"
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
        user_doro_map[str(event.user_id)] = doro_info.id
        # 保存映射到文件
        write_dict_to_json(
            user_doro_map,
            filename="./data/nonebot_plugin_doroending/user_doro_map.json"
            )
        logger.debug(f"记录用户（{event.user_id}）的结局ID为 {doro_info.id}")
        # 构建图片路径
        image_path = await anyio.Path(
            f"./data/nonebot_plugin_doroending/DoroEndingPic/{doro_info.pic}"
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

def write_dict_to_json(data_dict, filename="./data/nonebot_plugin_doroending/user_doro_map.json"):
    """
    将Python字典写入JSON文件
    Args:
        data_dict: 要写入的字典
        filename: 文件名，默认为 "user_doro_map.json"
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
        logger.debug(f"字典已成功写入 {filename}")
    except Exception as e:
        logger.error(f"写入文件时出错: {e}")

def read_dict_from_json(filename="./data/nonebot_plugin_doroending/user_doro_map.json"):
    """
    从JSON文件中读取Python字典
    Args:
        filename: 文件名，默认为 "user_doro_map.json"
    Returns:
        读取到的字典，如果读取失败则返回空字典
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.debug(f"字典已成功从 {filename} 读取")
        return data
    except FileNotFoundError:
        logger.warning(f"文件 {filename} 不存在，返回空字典")
        return {}
    except json.JSONDecodeError:
        logger.warning(f"文件 {filename} 格式错误，返回空字典")
        return {}
    except Exception as e:
        logger.error(f"读取文件时出错: {e}")
        return {}
