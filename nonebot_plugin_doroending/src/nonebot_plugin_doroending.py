import json
import random
from pathlib import Path

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
    SUPERUSER: str = ""

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
data: dict = {}

@driver.on_startup
async def startup():
    global data
    data = await load_doro_data()
    logger.info(f"已加载 {data['total']} 个doro结局")
    logger.debug(f"Loaded doro endings data: {data}")

    # 访问数据
    logger.debug(f"总数: {data['total']}")
    logger.debug(f"数据条数: {len(data['datas'])}")

    # 遍历所有数据
    for item in data["datas"]:
        logger.debug(
            f"ID: {item['id']}, 名称: {item['name']}, "
            f"英文名: {item['english_name']}, 图片: {item['pic']}"
        )

get_doro_ending = on_command("今日doro结局")
add_doro_ending = on_command("添加doro结局", permission=SUPERUSER)
remove_doro_ending = on_command("删除doro结局", permission=SUPERUSER)
list_doro_endings = on_command("列出doro结局",  permission=SUPERUSER)

@get_doro_ending.handle()
async def handle_doro_ending() -> None:
    doro_ending = random.randint(1, data["total"])
    doro_info = data["datas"][doro_ending - 1]

    # 获取图片文件名
    image_name = doro_info["pic"]

    # 构建图片路径
    image_path = f"./datas/DoroEndingPic/{image_name}"
    abs_image_path = await anyio.Path(image_path).resolve()
    # 返回图片消息
    await get_doro_ending.finish(MessageSegment.image(f"file://{abs_image_path}"))

@add_doro_ending.handle()
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
        return

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
        return

    # 提取纯文本部分（去除图片CQ码）
    # 先获取纯文本参数
    text_args = args.extract_plain_text().strip()

    if not text_args:
        await add_doro_ending.finish("请提供两个名字，用空格隔开！")
        return

    # 分割名字
    name_parts = text_args.split()
    min_name_count = 2
    if len(name_parts) < min_name_count:
        await add_doro_ending.finish("请提供两个名字，用空格隔开！")
        return

    name = name_parts[0]
    english_name = name_parts[1]
    logger.debug(f"Received names: {name}, {english_name}, image: {image_url}")
    # 生成新的ID
    new_id = data["max_id"] + 1

    # 处理图片保存
    pic_filename = f"{new_id:08d}_{english_name}.jpg"
    pic_path = Path("./datas/DoroEndingPic") / pic_filename

    try:
        if image_url:  # 如果有图片URL
            # 下载图片
            async with (
                await anyio.open_file(pic_path, "wb") as img_file,
                aiohttp.ClientSession() as session,
                session.get(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response,
            ):
                response.raise_for_status()  # 检查请求是否成功
                content = await response.read()
                await img_file.write(content)

            pic_saved = True
        else:
            pic_saved = False
            pic_filename = ""  # 或者设为默认值
    except (OSError, aiohttp.ClientError) as e:
        logger.error(f"图片保存失败: {e}")
        pic_saved = False
        pic_filename = ""

    # 创建新的doro结局对象
    new_doro_ending = {
        "id": new_id,
        "name": name,
        "english_name": english_name,
        "pic": pic_filename if pic_saved else ""
    }

    # 添加到数据中
    data["datas"].append(new_doro_ending)
    data["max_id"] = new_id
    data["total"] += 1

    # 保存更新后的JSON文件
    try:
        async with await anyio.open_file(
            "./datas/doroendings.json",
            "w",
            encoding="utf-8"
            ) as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    except OSError as e:
        logger.error(f"JSON保存失败: {e}")

    # 示例反馈，显示接收到的信息
    feedback = "doro结局已添加\n"
    feedback += f"ID: {new_id}\n"
    feedback += f"中文名: {name}\n"
    feedback += f"英文名: {english_name}\n"
    feedback += f"图片: {image_url or '已接收图片'}"

    await add_doro_ending.finish(feedback)

@remove_doro_ending.handle()
async def handle_rdoro_ending(
    args: Message = CommandArg()
) -> None:
    # 获取参数
    target = args.extract_plain_text().strip()

    # 检查是否提供了参数
    if not target:
        await remove_doro_ending.finish(
            "请提供要删除的doro结局的ID或名称\n"
            "格式：/删除doro结局 [ID或中文名]\n"
            "例如：/删除doro结局 123 或 /删除doro结局 结局名称"
        )
        return

    try:
        # 加载数据
        async with await anyio.open_file(
            "./datas/doroendings.json",
            "r",
            encoding="utf-8"
        ) as f:
            content = await f.read()
            data = json.loads(content)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"加载doro结局数据失败: {e}")
        await remove_doro_ending.finish("加载doro结局数据失败，请稍后再试")
        return

    # 查找要删除的条目
    to_delete = None
    delete_index = -1

    # 先尝试按ID查找
    if target.isdigit():
        target_id = int(target)
        for i, item in enumerate(data["datas"]):
            if item["id"] == target_id:
                to_delete = item
                delete_index = i
                break

    # 如果按ID没找到，尝试按中文名查找
    if not to_delete:
        for i, item in enumerate(data["datas"]):
            if item["name"] == target:
                to_delete = item
                delete_index = i
                break

    # 如果都没找到
    if not to_delete:
        await remove_doro_ending.finish(f"未找到ID或名称为 '{target}' 的doro结局")
        return

    try:
        # 删除对应的图片文件（如果存在）
        if to_delete.get("pic"):
            pic_path = Path("./datas/DoroEndingPic") / to_delete["pic"]
            if pic_path.exists():
                await anyio.Path(pic_path).unlink()
                logger.info(f"已删除图片文件: {pic_path}")

        # 从数据中删除
        data["datas"].pop(delete_index)
        data["total"] -= 1

        # 如果删除的是最大ID的条目，需要更新max_id
        if to_delete["id"] == data["max_id"] and data["datas"]:
            # 重新计算最大ID
            data["max_id"] = max(item["id"] for item in data["datas"])
        elif not data["datas"]:  # 如果删完了所有数据
            data["max_id"] = 0

        # 保存更新后的数据
        async with await anyio.open_file(
            "./datas/doroendings.json",
            "w",
            encoding="utf-8"
        ) as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

        # 构建反馈信息
        feedback = "✅ doro结局已成功删除\n"
        feedback += f"ID: {to_delete['id']}\n"
        feedback += f"中文名: {to_delete['name']}\n"
        feedback += f"英文名: {to_delete.get('english_name', 'N/A')}\n"

        if to_delete.get("pic"):
            feedback += f"图片文件: {to_delete['pic']} (已删除)"

        await remove_doro_ending.finish(feedback)

    except OSError as e:
        logger.error(f"删除doro结局失败: {e}")
        await remove_doro_ending.finish("删除doro结局时发生错误，请稍后再试")

@list_doro_endings.handle()
async def handle_list_doro_endings(
    event: MessageEvent,
    bot: Bot
) -> None:
    # 构建合并转发节点列表
    nodes = []
    nodes.append(
        ("doro结局", bot.self_id, Message("以下是所有doro结局"))
    )
    # 每50个结局放一条消息
    split_num = 50
    pair = []
    for idx, data_item in enumerate(data["datas"], 1):
        msg = (
            f"{data_item['id']}. {data_item['name']}\n"
        )
        pair.append(msg)
        if len(pair) == split_num or idx == len(data["datas"]):
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
