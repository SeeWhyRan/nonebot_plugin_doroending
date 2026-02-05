# **NoneBot-Plugin-DoroEnding**

一个有趣的 NoneBot2 插件，随机获取今日的 doro 结局，并支持bot管理员管理结局库。

## ✨ 功能特性

- 🎲 **随机获取**：每日随机获取一个 doro 结局
- 👑 **权限管理**：只有超级用户可以管理结局库
- 📝 **便捷管理**：添加、删除、查看所有结局

## 📦 安装方法

### 使用 pip 安装

#### 从 PyPI 安装

```shell

```

#### 从 git仓库 安装

```shell
pip install git+https://github.com/SeeWhyRan/nonebot_plugin_doroending.git
# 备用地址 pip install git+https://gitee.com/seewhy_ran/nonebot_plugin_doroending.git
```

### 手动安装

1. 克隆仓库：

```shell
git clone https://github.com/yourname/nonebot-plugin-doroending.git
# 备用地址 git clone https://gitee.com/seewhy_ran/doroending_pic_assets.git
cd nonebot-plugin-doroending
```

2. 将`nonebot-plugin-doroending/`文件夹放在你的nb项目的src文件夹下

3. 安装依赖：

```shell
pip install -e .
```

## ⚙️ 配置

在 NoneBot2 项目的 `.env` 文件中添加以下配置：


```env
# 设置超级用户（你的QQ号）
SUPERUSER="123456789"
```

## 📖 使用方法

### 基础命令

| 命令           | 功能                           | 权限     | 示例                                        |
| :------------- | :----------------------------- | :------- | :------------------------------------------ |
| `今日doro结局` | 随机获取一个 doro 结局         | 所有人   | `今日doro结局`                              |
| `列出doro结局` | 列出所有 doro 结局（合并转发） | 超级用户 | `列出doro结局`                              |
| `添加doro结局` | 添加新的 doro 结局             | 超级用户 | `添加doro结局 结局名 英文名 [图片]`         |
| `删除doro结局` | 删除指定的 doro 结局           | 超级用户 | `删除doro结局 123` 或 `删除doro结局 结局名` |

### 详细说明

#### 1. 获取今日结局

```
用户：今日doro结局
Bot： [发送随机结局图片]
```

![今日doro结局.png](./picture/今日doro结局.png)

#### 2. 添加新结局

```
bot主人：添加doro结局 欧润几结局 OrangeEnd [图片]
Bot：
	doro结局已添加
	ID: 3
	中文名: 欧润几结局
	英文名: OrangeEnd
	图片: 图片url
```

![添加doro结局1.png](./picture/添加doro结局1.png)

![添加doro结局2.png](./picture/添加doro结局2.png)

**注意事项：**

- 需要同时提供文字和图片
- 会自动生成唯一 ID

#### 3. 删除结局

```
bot主人：删除doro结局 3（或删除doro结局 欧润几结局）
Bot：
	✅ doro结局已成功删除
	ID: 3
	中文名: 欧润几结局
	英文名: OrangeEnd
	图片文件: 00000003_fired.jpg (已删除)
```

![删除doro结局](./picture/删除doro结局.png)

#### 4. 列出所有结局

```
bot主人：列出doro结局
Bot： [发送合并转发消息，包含所有结局列表]
```

![列出所有结局](./picture/列出doro结局.png)

## 🗂️ 数据结构

插件数据存储在 JSON 文件中，格式如下：

```json
{
  "datas": [
    {
      "id": 1,
      "name": "结局名称",
      "english_name": "english_name",
      "pic": "00000001_english.jpg"
    }
  ],
  "total": 1,
  "max_id": 1
}
```

图片文件保存在 `DoroEndingPic/` 目录下，命名格式为：`{ID:08d}_{english_name}.jpg`

## 🏗️ 项目结构

```
nonebot-plugin-doroending/
├── picture/            # README.md中的图片
├── nonebot_plugin_doroending/
│   └── src/
│       └── nonebot_plugin_doroending.py  # 插件代码
├── pyproject.toml       # 项目配置
├── README.md           # 本文件
└── LICENSE             # MIT许可证
```

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](https://github.com/SeeWhyRan/nonebot_plugin_doroending/blob/main/LICENSE) 文件。

## 🐛 问题反馈

如果您遇到任何问题或有建议，请通过以下方式反馈：

1. [提交 Issue](https://github.com/SeeWhyRan/nonebot_plugin_doroending/issues)
2. 在 NoneBot 官方社区讨论
3. 联系作者邮箱

## 💡 TODO

- 发布到社区
- 对话交互式添加/删除结局
- 对话交互式修改结局的中文和英文描述

## 📈 版本历史

### v0.1.2 (2026-2-5)
- **新增**：实现真正的每日固定结局
- **新增**：准备了结局图片文件，启动插件时检测到没有资源会自动从[Github](https://github.com/SeeWhyRan/doroending_pic_assets)或[Gitee](https://gitee.com/seewhy_ran/doroending_pic_assets)上下载

### v0.1.1 (2026-2-5)
- **重构**：将数据操作封装为 `DoroDataManager` 类，提升代码可维护性
- **优化**：在内存中缓存用户每日结局，为“每日固定”功能做准备

### v0.1.0 (2026-2-4)
- **首个发布版本**。
- 实现核心功能：随机获取、添加、删除、列出 doro 结局
- 支持 OneBot v11 适配器
- 完善的超级用户权限管理

------

**祝您使用愉快！每天都有一个惊喜的 doro 结局！🎉**

*如果这个插件对您有帮助，请给个 ⭐️ Star 支持一下！*