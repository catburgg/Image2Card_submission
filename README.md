# Image2Card · 图像知识卡片工具

> 北京大学「程序设计实习」大作业 —— 一个基于 Python 面向对象与 PyQt5 的桌面应用。
> 输入一张图片（菜单 / 路牌 / 学习材料等），自动识别其中的词条并生成可复习、可关联的**知识卡片**。

本目录为**交付包**，实际项目代码位于 [`Image2Card/`](./Image2Card) 子目录中。

---

## 一、项目简介

Image2Card 把"看到的图片"沉淀为"可管理的知识"。核心流程：

```
图片 ──▶ OCR (PaddleOCR) ──▶ VLM 理解 (OpenAI 兼容接口) ──▶ 结构化词条 + 知识卡片
                                                              │
                    ┌─────────────────────────┬──────────────┴────────────┐
                    ▼                          ▼                           ▼
               卡片库 (SQLite)           间隔复习 (Review)            关系图谱 (Graph)
                                                                    + 卡片对话 (Chat)
```

## 二、功能特性

- **图像识别**：PaddleOCR 提取文字，VLM 结合场景（菜单 / 路牌 / 学习材料）理解词条，输出带 bbox 的结构化结果。
- **知识卡片**：为每个词条生成摘要、正文、相关链接与关联词，支持人工编辑与候选卡片确认。
- **卡片库管理**：SQLite 持久化，支持分类工作区、图片来源追溯。
- **间隔复习**：基于熟悉度的复习会话，可"跳过已熟悉卡片"。
- **关系图谱**：networkx 构建卡片关联图，PageRank 计算重要度并驱动节点大小。
- **卡片对话**：针对单张卡片与模型对话，深入了解词条。
- **交互标注**：在原图上悬停 / 点击 bbox 查看卡片，支持缩放平移。

## 三、目录结构

```
Image2Card/
├── app.py              # 主程序入口（PyQt5 GUI）
├── demo.py             # 独立联调 Demo（识别 + 标注渲染）
├── ocr_cli.py          # OCR 命令行工具
├── core/               # 核心逻辑：vlm / ocr_service / renderer / graph /
│                       #           review / card_manager / card_chat / search ...
├── ui/                 # PyQt5 界面组件（主窗口、卡片表 / 图 / 详情、复习页 ...）
├── dataclass/models.py # 数据结构定义（pydantic 数据模型 + 全局配置）
├── storage/repository.py # SQLite 存储层
├── demo_samples/       # 演示样例图片（菜单 / 路牌 / 学习材料，见 ATTRIBUTION.md）
├── docs/               # 项目提案与设计文档（proposal.md / full_proposal.md）
├── environment.yml     # Conda 环境定义
├── requirements.txt    # pip 依赖
└── .env.example        # 环境变量模板（复制为 .env.local 后填入密钥）
```

## 四、环境与安装

要求 Python 3.12。

**方式 A · Conda（推荐）**

```bash
cd Image2Card
conda env create -f environment.yml
conda activate image2card
```

**方式 B · 已有 Python 3.12 环境**

```bash
cd Image2Card
# GPU 用户按需安装匹配的 paddlepaddle-gpu wheel
pip install -r requirements.txt
```

## 五、配置密钥

真实调用 VLM 需要配置密钥。**请勿提交真实密钥**——复制模板后在本地填写：

```bash
cd Image2Card
cp .env.example .env.local     # .env.local 已被 .gitignore 忽略
# 编辑 .env.local，填入 OPENAI_API_KEY / OPENAI_BASE_URL 等

# 加载到环境变量（macOS / Linux）
set -a && source .env.local && set +a
```

Windows PowerShell 加载方式见 `Image2Card/readme.md`。

## 六、运行

```bash
cd Image2Card

# 主程序（完整 GUI）
python app.py

# 或先跑联调 Demo（识别 + 图上标注）
python demo.py demo_samples/menus/toms_restaurant_menu.jpg
```

## 七、数据存储说明

应用运行时数据（卡片数据库 `cards.db`、导入的图片、用户偏好）保存在**用户主目录**下的
`~/.image2card/`，独立于本项目目录，不会污染交付包，也便于跨机器迁移。

## 八、说明

- 本交付包在原始项目基础上仅**清理了缓存与临时产物**（`__pycache__`、`.DS_Store`、日志、
  浏览器测试产物、临时测试图），并将真实密钥替换为 `.env.example` 模板，**核心代码逻辑未做任何改动**。
- 演示样例图片版权与来源见 `Image2Card/demo_samples/ATTRIBUTION.md`。
