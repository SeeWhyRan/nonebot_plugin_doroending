import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal

import requests
from nonebot import logger
from nonebot.plugin import get_plugin_config

from .model import Config

config = get_plugin_config(Config)


@dataclass
class DownloadResult:
    """下载结果的数据类"""
    success: bool
    message: str
    source: str = "unknown"  # 新增：标记数据源
    json_data: Optional[dict] = None
    local_path: Optional[Path] = None


class GitRepoDownloader:
    """Git仓库资源下载器（支持GitHub和Gitee）"""
    def __init__(
        self,
        repo_owner: str = "SeeWhyRan",
        repo_name: str = "doroending_pic_assets",
        target_dir: str = "./data/doro_assets",
        timeout: int = 30,
        token: str = "",
        use_gitee_fallback: bool = True,
        gitee_owner: str = "seewhy_ran",
        gitee_repo: str = "doroending_pic_assets"
    ):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.target_dir = Path(target_dir)
        self.timeout = timeout
        self.token = token
        self.use_gitee_fallback = use_gitee_fallback
        self.gitee_owner = gitee_owner
        self.gitee_repo = gitee_repo
        # 当前使用的源
        self.current_source: Literal["github", "gitee"] = "github"
        # 初始化URL
        self._update_urls()
        # 统计信息
        self.downloaded_files = 0
        self.skipped_files = 0
        self.failed_files = 0

    def _update_urls(self):
        """根据当前源更新URL"""
        if self.current_source == "github":
            self.base_api_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents"
            self.raw_base_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/main"
        else:  # gitee
            self.base_api_url = f"https://gitee.com/api/v5/repos/{self.gitee_owner}/{self.gitee_repo}/contents"
            self.raw_base_url = f"https://gitee.com/{self.gitee_owner}/{self.gitee_repo}/raw/main"

    def _switch_to_gitee(self):
        """切换到Gitee源"""
        if self.current_source == "gitee":
            return False  # 已经是Gitee，无需切换
        logger.warning("GitHub连接失败，尝试切换到Gitee源...")
        self.current_source = "gitee"
        self._update_urls()
        return True

    def _make_request(self, url: str) -> Optional[requests.Response]:
        """统一的请求方法，添加认证头"""
        headers = {
            'User-Agent': 'DoroEndingDownloader/1.0'
        }
        # 只在GitHub请求中添加token
        if self.current_source == "github" and self.token:
            headers['Authorization'] = f'token {self.token}'
        try:
            response = requests.get(url, headers=headers, timeout=self.timeout)
            # 检查是否是网络连接问题或GitHub不可用
            if response.status_code >= 500 or response.status_code == 403:
                # 403可能是速率限制，500是服务器错误
                if self.use_gitee_fallback:
                    logger.warning(f"{self.current_source.upper()}返回状态码 {response.status_code}，准备切换到备用源")
                return None
            return response
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"连接{self.current_source.upper()}失败: {e}")
            if self.use_gitee_fallback:
                return None
            raise

    def _download_file(self, url: str, save_path: Path) -> bool:
        """下载单个文件"""
        try:
            # 如果文件已存在且大小合理，跳过下载
            if save_path.exists() and save_path.stat().st_size > 100:
                self.skipped_files += 1
                logger.debug(f"跳过已存在的文件: {save_path.name}")
                return True
            logger.debug(f"正在从{self.current_source.upper()}下载: {save_path.name}")
            response = self._make_request(url)
            # 如果请求失败且允许切换到Gitee，则返回False让上层处理
            if response is None and self.use_gitee_fallback:
                return False
            # 如果请求失败且不允许切换源，直接计为失败
            if response is None:
                self.failed_files += 1
                logger.error(f"下载文件失败 {save_path.name}: 无法连接到{self.current_source.upper()}")
                return False
            response.raise_for_status()
            # 确保目录存在
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with save_path.open("wb") as f:
                f.write(response.content)
            self.downloaded_files += 1
            logger.debug(f"下载成功: {save_path.name}")
            return True
        except requests.RequestException as e:
            logger.error(f"下载文件失败 {save_path.name}: {e}")
            if self.use_gitee_fallback:
                return False
            self.failed_files += 1
            return False
        except Exception as e:
            logger.error(f"处理文件失败 {save_path.name}: {e}")
            self.failed_files += 1
            return False

    def _download_directory(self, dir_path: str, local_base_path: Path) -> bool:
        """递归下载目录（顺序执行）"""
        try:
            # 获取目录内容
            api_url = f"{self.base_api_url}/{dir_path}"
            response = self._make_request(api_url)
            # 如果请求失败且允许切换到Gitee，则返回False让上层处理
            if response is None:
                return False
            if response.status_code == 404:
                logger.warning(f"目录不存在或为空: {dir_path}")
                return True
            response.raise_for_status()
            contents = response.json()
            # 顺序处理目录中的每个项目
            for item in contents:
                item_name = item['name']
                item_type = item.get('type', 'file')  # Gitee API可能不同
                # 处理Gitee的API响应格式
                if 'type' not in item and 'download_url' in item:
                    item_type = 'file'
                remote_path = f"{dir_path}/{item_name}" if dir_path else item_name
                if item_type == 'file':
                    # 构建下载URL
                    if self.current_source == "github":
                        raw_url = f"{self.raw_base_url}/{remote_path}"
                    else:  # gitee
                        # Gitee API中可能包含download_url字段
                        if 'download_url' in item:
                            raw_url = item['download_url']
                        else:
                            raw_url = f"{self.raw_base_url}/{remote_path}"
                    local_path = local_base_path / item_name
                    success = self._download_file(raw_url, local_path)
                    if not success:
                        return False  # 下载失败，需要切换源
                elif item_type == 'dir':
                    # 递归下载子目录
                    sub_dir_path = local_base_path / item_name
                    sub_dir_path.mkdir(exist_ok=True)
                    success = self._download_directory(remote_path, sub_dir_path)
                    if not success:
                        return False  # 子目录下载失败，需要切换源
            return True
        except Exception as e:
            logger.error(f"处理目录失败 {dir_path}: {e}")
            return False

    def _download_json_file(self) -> tuple[bool, Optional[dict]]:
        """下载并解析JSON文件"""
        json_path = self.target_dir / "doroendings.json"
        # 构建JSON文件URL
        if self.current_source == "github":
            raw_url = f"{self.raw_base_url}/doroendings.json"
        else:  # gitee
            raw_url = f"{self.raw_base_url}/doroendings.json"
        # 下载JSON文件
        success = self._download_file(raw_url, json_path)
        if not success:
            return False, None
        # 验证JSON格式
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            logger.info(f"JSON文件验证成功，包含 {len(json_data)} 条记录")
            return True, json_data
        except json.JSONDecodeError as e:
            logger.warning(f"JSON文件格式错误: {e}")
            return False, None
        except Exception as e:
            logger.warning(f"JSON文件读取失败: {e}")
            return False, None

    def _try_with_fallback(self, operation) -> tuple[bool, bool]:
        """
        尝试执行操作，如果失败则切换到备用源重试
        Returns:
            tuple[bool, bool]: (操作是否成功, 是否切换了源)
        """
        # 第一次尝试（GitHub）
        result = operation()
        if result:
            return True, False  # 成功，未切换源
        # 如果失败且允许切换到Gitee，且当前是GitHub源
        if self.use_gitee_fallback and self.current_source == "github":
            if self._switch_to_gitee():
                # 使用Gitee重试
                logger.info(f"使用Gitee源重试: {self.gitee_owner}/{self.gitee_repo}")
                result = operation()
                return result, True  # 返回结果和切换状态
        return False, False

    def download(self) -> DownloadResult:
        """执行下载任务"""
        logger.info(f"开始下载 {self.repo_owner}/{self.repo_name} (源: {self.current_source.upper()})")
        logger.info(f"保存到: {self.target_dir.absolute()}")
        logger.debug("-" * 50)
        start_time = time.time()
        source_switched = False
        # 创建目标目录
        self.target_dir.mkdir(parents=True, exist_ok=True)
        try:
            # 获取仓库根目录内容
            def get_root_contents():
                response = self._make_request(self.base_api_url)
                if response is None:
                    return None
                if response.status_code != 200:
                    logger.error(f"无法访问仓库，HTTP状态码: {response.status_code}")
                    return None
                return response.json()
            success, switched = self._try_with_fallback(get_root_contents)
            if switched:
                source_switched = True
            if not success:
                return DownloadResult(
                    False,
                    "无法访问GitHub和Gitee仓库，请检查网络连接",
                    self.current_source
                )
            root_contents = get_root_contents() if success else None
            if root_contents is None:
                return DownloadResult(
                    False,
                    "无法获取仓库内容",
                    self.current_source
                )
            # 检查需要的文件/目录是否存在
            has_doro_pic = False
            has_json = False
            for item in root_contents:
                item_name = item.get('name', item.get('path', ''))
                item_type = item.get('type', 'file')
                if 'type' not in item and 'download_url' in item:
                    item_type = 'file'
                if item_name == "DoroEndingPic" and item_type == 'dir':
                    has_doro_pic = True
                elif item_name == "doroendings.json":
                    has_json = True
            # 下载DoroEndingPic目录
            if has_doro_pic:
                pic_dir = self.target_dir / "DoroEndingPic"
                pic_dir.mkdir(exist_ok=True)
                logger.info(f"开始从{self.current_source.upper()}下载图片目录...")
                def download_pic_dir():
                    return self._download_directory("DoroEndingPic", pic_dir)
                success, switched = self._try_with_fallback(download_pic_dir)
                if switched:
                    source_switched = True
                if not success:
                    logger.error("图片目录下载失败")
            # 下载JSON文件
            json_data = None
            if has_json:
                logger.info(f"开始从{self.current_source.upper()}下载JSON配置文件...")
                def download_json():
                    return self._download_json_file()
                success, switched = self._try_with_fallback(lambda: self._download_json_file()[0])
                if switched:
                    source_switched = True
                if success:
                    json_data = self._download_json_file()[1]
                else:
                    logger.error("JSON文件下载失败")
            # 计算耗时
            elapsed_time = time.time() - start_time
            # 输出统计信息
            logger.debug("-" * 50)
            logger.info("下载统计:")
            logger.info(f"  数据源: {self.current_source.upper()}")
            if source_switched:
                logger.info("  ⚠️ 已切换到备用源")
            logger.info(f"  成功下载: {self.downloaded_files} 个文件")
            logger.info(f"  跳过已存在: {self.skipped_files} 个文件")
            logger.info(f"  失败文件: {self.failed_files} 个")
            logger.info(f"  总耗时: {elapsed_time:.2f} 秒")
            # 验证最终结果
            json_file = self.target_dir / "doroendings.json"
            pic_dir = self.target_dir / "DoroEndingPic"
            success = True
            message = f"下载完成，耗时 {elapsed_time:.2f} 秒，数据源: {self.current_source.upper()}"
            if source_switched:
                message += " (已使用备用源)"
            if has_json and not json_file.exists():
                success = False
                message = f"JSON文件下载失败 (数据源: {self.current_source.upper()})"
            elif has_doro_pic and (not pic_dir.exists() or not any(pic_dir.iterdir())):
                success = False
                message = f"图片目录下载失败或为空 (数据源: {self.current_source.upper()})"
            return DownloadResult(
                success=success,
                message=message,
                source=self.current_source,
                json_data=json_data,
                local_path=self.target_dir
            )
        except Exception as e:
            logger.error(f"下载过程出错: {e}")
            return DownloadResult(
                False,
                f"下载过程出错: {e} (数据源: {self.current_source.upper()})",
                self.current_source
            )


def download_doro_assets(
    repo_owner: str = "SeeWhyRan",
    repo_name: str = "doroending_pic_assets",
    target_dir: str = "./data/doro_assets",
    token: str = "",
    use_gitee_fallback: bool = True,  # 新增参数：是否使用Gitee备用源
    gitee_owner: str = "seewhy_ran",  # 新增参数：Gitee仓库所有者
    gitee_repo: str = "doroending_pic_assets"  # 新增参数：Gitee仓库名称
) -> dict:
    """
    下载doro结局图片资源的主函数（支持GitHub和Gitee双源）
    Args:
        repo_owner: GitHub仓库所有者
        repo_name: GitHub仓库名称
        target_dir: 本地保存目录
        token: GitHub Personal Access Token (可选)
        use_gitee_fallback: 是否在GitHub连接失败时使用Gitee作为备用源
        gitee_owner: Gitee仓库所有者
        gitee_repo: Gitee仓库名称
    """
    downloader = GitRepoDownloader(
        repo_owner=repo_owner,
        repo_name=repo_name,
        target_dir=target_dir,
        token=token,
        use_gitee_fallback=use_gitee_fallback,
        gitee_owner=gitee_owner,
        gitee_repo=gitee_repo
    )
    result = downloader.download()
    return {
        'success': result.success,
        'message': result.message,
        'source': result.source,
        'json_data': result.json_data,
        'local_path': str(result.local_path) if result.local_path else None
    }


def main():
    """直接运行测试"""
    logger.info("测试Git仓库资源下载...")
    # 配置GitHub Token（如果有）
    YOUR_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # 替换为你的token或留空
    # 测试下载，启用Gitee备用源
    result = download_doro_assets(
        target_dir="./datas",
        token=YOUR_TOKEN,
        use_gitee_fallback=True,
        gitee_owner="seewhy_ran",
        gitee_repo="doroending_pic_assets"
    )
    logger.info(f"最终结果: {result['success']}")
    logger.info(f"数据源: {result['source']}")
    logger.info(f"消息: {result['message']}")
    if result['json_data']:
        logger.info(f"JSON记录数: {len(result['json_data'])}")
    logger.info(f"保存路径: {result['local_path']}")


if __name__ == "__main__":
    main()