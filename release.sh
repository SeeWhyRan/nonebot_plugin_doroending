#!/bin/bash

# nonebot-plugin-doroending 构建和发布脚本
# 使用方法：./release.sh [选项]
# 选项:
#   --build-only    只构建，不发布
#   --version=V     指定版本号
#   --testpypi      发布到 TestPyPI
#   --pypi          （默认）发布到 PyPI

set -e  # 遇到错误时退出脚本

echo "🎉 NoneBot doro结局插件构建发布脚本"
echo "======================================"

# 默认参数
BUILD_ONLY=false
SPECIFIED_VERSION=""
TARGET_REPO="pypi"  # 默认发布到 PyPI

# 解析命令行参数
for arg in "$@"; do
    case $arg in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --version=*)
            SPECIFIED_VERSION="${arg#*=}"
            shift
            ;;
        --testpypi)
            TARGET_REPO="testpypi"
            shift
            ;;
        --pypi)
            TARGET_REPO="pypi"
            shift
            ;;
        *)
            # 未知参数
            ;;
    esac
done

# 检查当前目录
if [ ! -f "pyproject.toml" ]; then
    echo "❌ 错误：请在插件项目根目录下运行此脚本"
    exit 1
fi

# 检查 .pypirc 配置文件
PYPIRC_FILE="$HOME/.pypirc"
LOCAL_PYPIRC_FILE=".pypirc"

if [ -f "$LOCAL_PYPIRC_FILE" ]; then
    echo "🔧 检测到项目目录下的 .pypirc 配置文件"
    PYPIRC_FILE="$LOCAL_PYPIRC_FILE"
elif [ -f "$PYPIRC_FILE" ]; then
    echo "🔧 检测到用户目录下的 .pypirc 配置文件"
else
    echo "⚠️  未检测到 .pypirc 配置文件，将使用默认 PyPI 配置"
fi

# 显示目标仓库信息
if [ "$TARGET_REPO" = "testpypi" ]; then
    echo "🧪 目标仓库: TestPyPI"
    REPO_NAME="TestPyPI"
    REPO_URL="https://test.pypi.org/project/nonebot-plugin-doroending/"
else
    echo "🚀 目标仓库: PyPI"
    REPO_NAME="PyPI"
    REPO_URL="https://pypi.org/project/nonebot-plugin-doroending/"
fi

# 获取当前版本
CURRENT_VERSION=$(grep '^version =' pyproject.toml | sed -E 's/version = "([^"]+)"/\1/')
echo "📦 当前版本: $CURRENT_VERSION"

# 版本更新询问
echo ""
echo "🔄 是否要更新版本号？"
echo "   1. 保持当前版本 ($CURRENT_VERSION)"
echo "   2. 自动递增版本号"
echo "   3. 手动指定版本号"
read -p "请选择 (1/2/3): " VERSION_CHOICE

case $VERSION_CHOICE in
    1)
        NEW_VERSION=$CURRENT_VERSION
        echo "📌 保持版本: $NEW_VERSION"
        ;;
    2)
        # 自动递增版本号
        MAJOR=$(echo $CURRENT_VERSION | cut -d. -f1)
        MINOR=$(echo $CURRENT_VERSION | cut -d. -f2)
        PATCH=$(echo $CURRENT_VERSION | cut -d. -f3)
        NEW_PATCH=$((PATCH + 1))
        NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
        echo "📈 自动生成新版本号: $NEW_VERSION"
        ;;
    3)
        if [ -n "$SPECIFIED_VERSION" ]; then
            NEW_VERSION=$SPECIFIED_VERSION
            echo "📋 使用命令行指定的版本号: $NEW_VERSION"
        else
            read -p "请输入新版本号 (例如: 0.2.0): " NEW_VERSION
            if [ -z "$NEW_VERSION" ]; then
                echo "⚠️  未输入版本号，使用当前版本: $CURRENT_VERSION"
                NEW_VERSION=$CURRENT_VERSION
            fi
        fi
        ;;
    *)
        echo "⚠️  无效选择，保持当前版本"
        NEW_VERSION=$CURRENT_VERSION
        ;;
esac

# 如果版本号发生变化，更新 pyproject.toml
if [ "$NEW_VERSION" != "$CURRENT_VERSION" ]; then
    echo "🔄 更新版本号到 $NEW_VERSION"
    sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml
    
    # 询问是否提交版本更新
    echo ""
    read -p "📝 是否提交版本更新到 Git? (y/n): " COMMIT_VERSION
    
    if [[ $COMMIT_VERSION =~ ^[Yy]$ ]]; then
        git add pyproject.toml
        git commit -m "🔖 发布版本 v$NEW_VERSION"
        git push origin main
        echo "✅ 版本更新已提交并推送"
    fi
fi

echo ""
echo "🔨 开始构建..."
echo "----------------------"

# 清理旧构建文件
echo "🧹 清理旧构建文件..."
rm -rf dist/ build/ nonebot_plugin_doroending.egg-info/ || true

# 构建包
echo "🔨 正在构建包..."
python -m build

# 检查构建结果
echo "🔍 检查构建文件..."
twine check dist/*

# 显示构建结果
echo ""
echo "📊 构建完成！"
echo "文件列表:"
ls -lh dist/
echo ""

# 如果指定了只构建，则退出
if [ "$BUILD_ONLY" = true ]; then
    echo "✅ 构建完成（仅构建模式）"
    echo "📦 版本: $NEW_VERSION"
    echo "📁 构建文件保存在 dist/ 目录"
    exit 0
fi

# 如果是命令行指定的仓库，直接发布
if [ -n "$2" ] && [[ "$2" =~ ^--(testpypi|pypi)$ ]]; then
    echo "🚀 正在上传到 $REPO_NAME..."
    if [ "$TARGET_REPO" = "testpypi" ]; then
        twine upload --repository testpypi dist/*
    else
        twine upload dist/*
    fi
    
    echo ""
    echo "🎊 发布成功！"
    echo "📦 版本: $NEW_VERSION"
    echo "🔗 $REPO_NAME: $REPO_URL"
    echo ""
    if [ "$TARGET_REPO" = "testpypi" ]; then
        echo "📢 测试安装命令:"
        echo "   pip install --index-url https://test.pypi.org/simple/ nonebot-plugin-doroending==$NEW_VERSION"
    else
        echo "📢 用户可以通过以下命令安装:"
        echo "   pip install nonebot-plugin-doroending==$NEW_VERSION"
        echo "   或"
        echo "   pip install --upgrade nonebot-plugin-doroending"
    fi
    exit 0
fi

# 交互式发布选择
echo "🚀 请选择发布目标："
echo "   1. PyPI (生产环境)"
echo "   2. TestPyPI (测试环境)"
echo "   3. 不发布，仅完成构建"
read -p "请选择 (1/2/3): " PUBLISH_CHOICE

case $PUBLISH_CHOICE in
    1)
        echo "🚀 正在上传到 PyPI..."
        twine upload dist/*
        
        echo ""
        echo "🎊 发布成功！"
        echo "📦 版本: $NEW_VERSION"
        echo "🔗 PyPI: https://pypi.org/project/nonebot-plugin-doroending/"
        echo ""
        echo "📢 用户可以通过以下命令安装:"
        echo "   pip install nonebot-plugin-doroending==$NEW_VERSION"
        echo "   或"
        echo "   pip install --upgrade nonebot-plugin-doroending"
        ;;
    2)
        echo "🧪 正在上传到 TestPyPI..."
        twine upload --repository testpypi dist/*
        
        echo ""
        echo "✅ 测试发布完成！"
        echo "🔗 TestPyPI: https://test.pypi.org/project/nonebot-plugin-doroending/"
        echo ""
        echo "📢 测试安装命令:"
        echo "   pip install --index-url https://test.pypi.org/simple/ nonebot-plugin-doroending==$NEW_VERSION"
        ;;
    3|*)
        echo "✅ 构建完成（未发布）"
        echo "📦 版本: $NEW_VERSION"
        echo "📁 构建文件保存在 dist/ 目录"
        echo "💡 如需稍后发布，可运行:"
        echo "   twine upload dist/*                    # 发布到 PyPI"
        echo "   或"
        echo "   twine upload --repository testpypi dist/*  # 发布到 TestPyPI"
        ;;
esac

echo ""
echo "🔗 Github: https://github.com/SeeWhyRan/nonebot_plugin_doroending"
echo "🔗 Gitee: https://gitee.com/seewhy_ran/nonebot_plugin_doroending"
echo "======================================"