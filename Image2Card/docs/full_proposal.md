

### Card 数据结构建议

```cpp
class Card {
public:
    QString id;
    QString term;              // 词条名
    QString language;          // 语言，可选
    QString category;          // 菜单/哲学/数学/历史/自定义
    int familiarity;           // 0-5 熟悉度

    QString userNote;          // 用户笔记，LLM 不可覆盖
    QString modelNote;         // 模型解释，可被用户编辑确认
    QString summary;           // 简短解释

    QStringList links;         // Wikipedia、博客、搜索链接
    QStringList sourceImageIds; // 出现在哪些图片中

    QDateTime createdAt;
    QDateTime updatedAt;
    QDateTime lastReviewedAt;

    QStringList relatedCardIds; // 关系图谱
};
```

你提到的“LLM 可以编辑自己的信息，不能编辑人的信息”非常好，建议明确变成一个亮点：

| 笔记类型 | 谁创建 | 谁能编辑 | 作用 |
|---|---|---|---|
| 用户笔记 | 用户 | 用户 | 个人理解、记忆方式 |
| 模型笔记 | LLM/程序 | 用户可确认或修改 | 初始解释、总结、链接摘要 |
| 来源记录 | 系统 | 系统维护 | 这个词从哪张图来 |

这个设计有很强的“状态管理”味道，适合体现工程复杂度。

---

## 4. 模块划分建议

你的模块划分基本合理，但我建议改成 5 个核心模块，而不是一开始就做很多花哨功能。

### 模块一：图片识别器 Image Analyzer

功能：

- 上传图片
- OCR 识别文字
- 提取候选专有名词/关键词
- 在原图上标注候选词区域
- 点击候选词创建卡片
- 自动过滤已熟悉或已存在词条

这是整个项目的入口，也是最有视觉冲击力的部分。

GUI 可以做成：

```text
左侧：原始图片 / 标注图片
右侧：识别出的候选词列表
底部：批量操作按钮
```

候选词可以有状态：

| 状态 | 含义 |
|---|---|
| 新词 | 词库中没有 |
| 已存在 | 词库中已有卡片 |
| 已熟悉 | 熟悉度较高，默认不加入 |
| 待确认 | 系统不确定，需要用户确认 |

这个状态设计很适合展示“不是简单 OCR，而是和知识库联动”。

---

### 模块二：卡片库 Card Library

这是核心存储模块。

功能：

- 所有卡片列表
- 搜索卡片
- 按熟悉度筛选
- 按来源图片筛选
- 按标签/类别筛选
- 查看卡片详情
- 编辑用户笔记
- 编辑模型笔记
- 添加/删除链接
- 查看该词出现过的图片

GUI 可以做成：

```text
左侧：筛选栏
中间：卡片网格 / 列表
右侧：卡片详情
```

卡片展示可以像 Anki 或 Notion 小卡片：

```text
+----------------------+
| term: Socrates       |
| 熟悉度: ★★☆☆☆        |
| 类型: 哲学            |
| 来源: 3 张图片        |
| 简介: 古希腊哲学家... |
+----------------------+
```

这个模块不难，但很能体现 GUI 复杂度。

---

### 模块三：来源图片库 Image Source Manager

这个模块你原本没有单独强调，但我建议加上。

因为你的项目叫“基于图片的知识库”，图片不应该只是一次性输入，而应该成为知识来源。

每张图片可以有：

```cpp
class SourceImage {
public:
    QString id;
    QString filePath;
    QString title;
    QString scene;        // 菜单/教材/论文/展板
    QString ocrText;
    QStringList cardIds;  // 从这张图片生成了哪些卡片
    QDateTime importedAt;
};
```

这样用户可以回看：

- 这张菜单里我识别了哪些菜名？
- 这页教材里有哪些知识点？
- 这个词第一次在哪张图里出现？
- 一张图片能不能变成一个“知识地图”？

这会让你的项目比普通卡片库更完整。

---

### 模块四：关系图谱 Knowledge Graph

这个模块可以做，但要控制复杂度。

你不一定要做真正复杂的图数据库。可以简单地用：

```cpp
class Relation {
public:
    QString fromCardId;
    QString toCardId;
    QString relationType; // related_to / is_a / part_of / contrast_with / appears_with
    double weight;
};
```

关系可以来自三种方式：

| 来源 | 说明 | 实现难度 |
|---|---|---|
| 用户手动添加 | 用户选择两个卡片建立关系 | 低 |
| 同图共现 | 两个词出现在同一张图片中，自动建立弱关系 | 低 |
| LLM/规则推荐 | 根据解释文本推荐关系 | 中高 |

建议 MVP 只做前两种：

- 同一张图片出现的词自动建立 “appears_with”
- 用户可以手动添加 “related_to”
- 图谱界面显示节点和连线

GUI 可以做成：

```text
中心节点：当前卡片
周围节点：相关卡片
点击节点：跳转卡片详情
边：关系类型
```

这会很加分，但不必做复杂推理。

---

### 模块五：复习/滚动学习 Review

你提到类似“百词斩 rollout 和复习”，这个方向也合理。

建议做一个轻量版本：

- 按熟悉度低的优先出现
- 按最近出现/最近创建排序
- 卡片正面显示 term
- 背面显示解释、图片来源、用户笔记
- 用户点击“认识 / 模糊 / 不认识”
- 更新 familiarity

这个功能非常适合生活类，也能让项目闭环：

> 不只是识别知识，还帮助用户消化知识。

---

## 5. 最有亮点的 GUI：图片变成可交互界面

你最后提到的这个功能非常重要：

> 在识别文字之后，对应网页链接或者预览会直接显示在文字周围，把图片实时渲染成一个新的小 UI 界面。

这是整个项目最有特色的 GUI 亮点。

可以设计成 **Annotated Image View**：

```text
原图上有很多高亮框：

[ Carbonara ]     [ Tiramisu ]
     ↓                ↓
  简介浮窗          链接按钮
  熟悉度            加入卡片
```

交互方式：

- 鼠标悬停在识别词上：显示简短解释
- 点击词框：打开卡片详情
- 右键：加入卡片 / 标记熟悉 / 忽略
- 已有卡片的词框用一种颜色
- 新词用另一种颜色
- 熟悉词可以淡化显示

这个 GUI 会明显区别于普通 OCR 工具。

建议你把它作为项目展示的核心页面。

---

## 6. 技术复杂度判断

你的项目复杂度主要不是算法 SOTA，而是**模块协同复杂度**。这非常符合优秀 Qt 作业的风格。

### 代码量预估

如果做成完整 MVP，大概会是：

| 模块 | 代码规模估计 |
|---|---:|
| 数据模型 Card/Image/Relation | 500–1000 行 |
| JSON/SQLite 存储 | 500–1000 行 |
| 图片导入与 OCR 接口 | 500–1500 行 |
| 主窗口与页面切换 | 800–1500 行 |
| 卡片库 GUI | 800–1500 行 |
| 图片标注 GUI | 1000–2000 行 |
| 卡片详情编辑 GUI | 500–1000 行 |
| 图谱/复习模块 | 1000–2500 行 |
| 总计 | 5000–12000 行左右 |

如果你们课程时间有限，建议目标放在 **5000–8000 行的可演示工程**，比追求功能全更稳。

---

## 7. 最小可行版本 MVP

我建议你的 MVP 这样定：

### 必做功能

1. 上传图片
2. OCR 得到文字
3. 自动提取候选词
4. 显示候选词列表
5. 用户选择词条生成卡片
6. 卡片支持熟悉度、解释、用户笔记、链接
7. 卡片库支持搜索、筛选、编辑
8. 每张卡片记录来源图片
9. 再次识别图片时，自动标记已有卡片/熟悉卡片
10. 图片上可以高亮词条区域或至少在旁边展示词条

这已经足够成为一个完整项目。

### 加分功能

1. 原图上浮窗预览解释
2. 知识图谱
3. 复习模式
4. 自动生成 Wikipedia/搜索链接
5. LLM 总结解释
6. 导入导出 JSON
7. SQLite 存储
8. 深色模式/主题切换
9. 标签系统
10. 多语言菜单/教材场景模板

### 不建议第一版强做

| 功能 | 原因 |
|---|---|
| 完全自动识别“专有名词” | 难度高，效果不稳定 |
| 复杂知识图谱推理 | 容易失控 |
| 基于图谱的复杂 QA | 对后端要求高，展示风险大 |
| 实时联网抓取多网页总结 | 网络、反爬、接口稳定性问题多 |
| 完整移动端拍照流程 | Qt 桌面作业里成本偏高 |
| 复杂 LLM agent | 容易把项目重点变成 API 调用 |

---

## 8. 关键风险与解决方式

### 风险一：OCR 和关键词提取不稳定

这是最大风险。

解决方式：
不要承诺“自动完美识别专有名词”，而是设计成：

> 系统给出候选词，用户确认后生成卡片。

这样即使识别不完美，产品逻辑仍然成立。

可以提供三种提取方式：

| 方式 | 说明 |
|---|---|
| 全部 OCR 词语 | 最简单 |
| 规则过滤 | 过滤太短、纯数字、常见词 |
| 用户手动框选/输入 | 兜底 |

这个“人机协作确认”比全自动更适合课程项目。

---

### 风险二：LLM 功能依赖外部 API

如果课程展示时网络不稳定，LLM 失败会很尴尬。

解决方式：

- LLM 总结作为可选功能
- 本地先生成搜索链接
- 没有 LLM 时，用户仍然可以手动编辑卡片
- 可以预置 demo 数据
- 可以缓存模型返回结果

也就是说，核心流程不能依赖 LLM。

---

### 风险三：知识图谱过度复杂

知识图谱很吸引人，但容易变成“画了很多点和线，却没实际用处”。

建议你让图谱服务于两个明确功能：

1. **查看相关词**
2. **从一张图片生成一组共现关系**

例如：

```text
菜单图片中出现：
Carbonara, Pecorino, Guanciale, Risotto

系统自动建立：
Carbonara -- appears_with -- Guanciale
Carbonara -- appears_with -- Pecorino
```

这就够了。

---

## 9. 推荐的最终项目结构

我建议你把项目讲成三层架构。

### 第一层：图片输入层

负责把图片变成候选词。

```text
Image Import
OCR
Term Extraction
Term Confirmation
```

### 第二层：卡片知识层

负责长期管理知识。

```text
Card Library
Source Image Library
Links
Notes
Familiarity
Relations
```

### 第三层：学习交互层

负责让知识被使用起来。

```text
Annotated Image View
Knowledge Graph
Review Mode
Search & Filter
```

这样的架构很清晰，答辩时也好讲。

---

## 10. 你可以强调的“优秀作业点”

这个 idea 有几个很适合作为亮点的地方：

### 亮点一：状态管理

普通大模型是“一次性问答”，你的系统是“长期知识管理”。

可以这样表述：

> 现有大模型可以识别图片并解释内容，但缺少长期状态管理。本项目将图片中的陌生术语转化为可编辑、可复习、可关联的知识卡片，并记录用户熟悉度和来源上下文。

### 亮点二：图片上下文

不是孤立词条，而是保留原始图片来源。

> 每张卡片都知道自己来自哪张图片，用户可以从词回到原始语境，也可以从图片查看所有相关卡片。

### 亮点三：人机协作

不是 LLM 替用户写知识库，而是用户和模型共同维护。

> 用户笔记和模型笔记分离，模型只能生成建议，用户保留最终编辑权。

### 亮点四：GUI 可视化强

图片标注、卡片库、知识图谱、复习界面都很适合 Qt 展示。

---

## 11. 一个更收敛的版本描述

你可以把项目描述改成这样：

> 本项目是一个基于图片的知识卡片管理系统。用户可以上传包含陌生术语的图片，例如菜单、教材、论文截图或展板。系统通过 OCR 和关键词提取识别候选词条，并结合已有卡片库判断该词是否已存在、是否已熟悉。用户确认后，系统为词条生成卡片，卡片包含词条名、熟悉度、用户笔记、模型解释、互联网链接、来源图片以及相关卡片。系统还提供图片标注视图、卡片库搜索筛选、知识关系图和复习模式，帮助用户把一次性的图片识别转化为长期可管理的知识积累。

这个表述比“基于图片的知识库”更完整。

---

## 12. 建议的功能优先级

我建议这样排：

| 优先级 | 功能 | 是否必须 |
|---|---|---|
| P0 | 图片上传 | 必须 |
| P0 | OCR/文字识别 | 必须 |
| P0 | 候选词列表 | 必须 |
| P0 | 卡片创建/编辑/删除 | 必须 |
| P0 | 熟悉度 | 必须 |
| P0 | 来源图片绑定 | 必须 |
| P0 | 本地保存 JSON/SQLite | 必须 |
| P1 | 卡片搜索/筛选 | 强烈建议 |
| P1 | 自动生成搜索/Wikipedia 链接 | 强烈建议 |
| P1 | 图片上高亮词条 | 强烈建议 |
| P1 | LLM 解释生成 | 可作为亮点 |
| P2 | 知识图谱 | 加分 |
| P2 | 复习模式 | 加分 |
| P3 | 图谱 QA | 展示型功能，不建议早做 |

---

## 13. GUI 页面建议

最终可以有 5 个主页面：

### 1. 图片识别页

```text
+------------------------------------------------+
| 上传图片 | OCR | 提取词条 | 批量生成卡片        |
+------------------------+-----------------------+
|                        | 候选词列表             |
|       原图/标注图       | [新] Carbonara         |
|                        | [已有] Tiramisu        |
|                        | [熟悉] Tomato          |
+------------------------+-----------------------+
```

### 2. 卡片库页

```text
+----------------+------------------------------+
| 搜索            | Card Grid                    |
| 熟悉度筛选       | Socrates / Carbonara / ...   |
| 标签筛选         |                              |
+----------------+------------------------------+
```

### 3. 卡片详情页

```text
词条：Carbonara
熟悉度：★★☆☆☆

用户笔记：
[我自己的理解...]

模型解释：
[一种意大利面...]

链接：
Wikipedia / Google / Blog

来源图片：
menu_001.jpg, menu_004.jpg

相关卡片：
Guanciale, Pecorino, Pasta
```

### 4. 图片来源页

```text
图片：Rome_Menu.jpg

从这张图生成的卡片：
Carbonara
Pecorino
Guanciale
Tiramisu
```

### 5. 复习/图谱页

复习页适合做成卡片翻转。
图谱页适合做成节点连线图。

---

## 14. 最终判断

这个 idea **合理，而且有优秀作业潜质**。

它的优势是：

- 痛点真实；
- 生活/学习场景清楚；
- GUI 展示空间很大；
- 数据结构自然；
- 复杂度主要来自工程组织，而不是难算法；
- 可以做 MVP，也可以扩展出高级功能；
- 很符合“实用性强、贴近日常生活”的方向。

最需要改进的是**收敛边界**。建议主线定为：

> **图片 → 候选词 → 卡片 → 卡片库 → 复习/关联**

LLM、联网总结、知识图谱 QA 都作为锦上添花，而不是核心依赖。

一句话评价：

> 这是一个很好的程序设计实习选题，但成功关键不是“让模型多聪明”，而是把图片识别、卡片管理、熟悉度状态、来源追踪和 GUI 交互做成一个稳定、完整、可演示的桌面产品。

-----

> OCR和LM不会结合,就完全使用现在最新的视觉语言模型来解决这个任务,因为反正也是这个demo,就不太成本可以无所谓。这个视觉的识别模块是可以支持用户自定义的。

这样改是合理的，而且**更符合 demo 型优秀作业的展示逻辑**：你不必把精力花在传统 OCR、分词、NER、翻译这些脆弱模块上，而是把它们统一抽象成一个 **Vision-Language Model 识别器插件**。项目重点回到你真正想做的东西：**图片知识状态管理系统**。

我会建议你把“识别器模块”重新定义为：

> **可插拔的视觉语言模型分析器**：用户上传图片后，系统调用用户配置的 VLM，对图片中的陌生术语、概念、实体、外语词、公式符号等进行识别，并返回结构化候选卡片。

---

## 1. 这比 OCR + LM 更好

传统路线是：

```text
图片 → OCR → 文本清洗 → 分词/实体识别 → 搜索/解释 → 卡片
```

你的新路线是：

```text
图片 → VLM → 结构化候选卡片 → 用户确认 → 卡片库
```

这更适合你的项目，因为你的目标不是研究 OCR，而是做一个**基于图片的知识库产品**。

VLM 可以一次性处理：

| 能力 | OCR + 规则 | VLM |
|---|---|---|
| 多语言菜单 | 可以，但要接翻译 | 可以直接解释 |
| 数学题图片 | OCR 容易乱 | 可以识别概念/公式 |
| 哲学教材截图 | 要做实体抽取 | 可以直接提名词 |
| 展板/海报 | 版面复杂 | 可以理解上下文 |
| 手写笔记 | OCR 风险高 | VLM 通常更稳 |
| 非文本视觉线索 | 基本做不了 | 可以结合图片理解 |

所以这个设计更干净。

---

## 2. 但不要叫“识别器”，建议叫“图片理解器”

“识别器”听起来像 OCR。你的模块更像：

> **Image Understanding Engine**
> 图片理解引擎

或者：

> **VLM Analyzer**
> 视觉语言模型分析器

它的输入不是“图片里的文字”，而是“这张图里有哪些值得变成卡片的知识点”。

这个区别很重要。

比如一张菜单里不一定只识别菜名，还可以识别：

- 菜名；
- 食材；
- 烹饪方式；
- 地域特色；
- 过敏风险；
- 价格单位；
- 推荐点菜策略。

一张数学作业里也不只是识别文字，还可以识别：

- 出现了哪些概念；
- 哪些公式；
- 哪些定理；
- 哪些符号；
- 哪些步骤可能需要复习。

这就是 VLM 相比 OCR 的优势。

---

## 3. 识别器应该返回结构化 JSON

为了让工程稳定，你最好不要让 VLM 返回一段自然语言，而是强制返回结构化结果。

例如：

```json
{
  "scene_type": "restaurant_menu",
  "language": "Italian",
  "summary": "A restaurant menu containing several Italian pasta and dessert items.",
  "items": [
    {
      "term": "Carbonara",
      "type": "dish",
      "original_text": "Spaghetti Carbonara",
      "short_explanation": "A Roman pasta dish made with eggs, cheese, cured pork, and black pepper.",
      "why_selected": "Likely unfamiliar food term for travelers.",
      "familiarity_suggestion": 1,
      "links": [
        {
          "title": "Wikipedia",
          "url": "https://en.wikipedia.org/wiki/Carbonara"
        }
      ],
      "bbox": {
        "x": 120,
        "y": 240,
        "w": 180,
        "h": 32
      },
      "related_terms": ["Guanciale", "Pecorino Romano"]
    }
  ]
}
```

这里面最重要的是：

| 字段 | 用途 |
|---|---|
| `term` | 卡片标题 |
| `type` | 菜品/概念/人名/公式/术语 |
| `short_explanation` | 初始模型笔记 |
| `why_selected` | 为什么值得变成卡片 |
| `links` | 初始互联网链接 |
| `bbox` | 在图片上做高亮框 |
| `related_terms` | 初始知识图谱关系 |
| `familiarity_suggestion` | 初始熟悉度建议 |

如果 VLM 不稳定返回 bbox，也没关系。可以设计为可选字段：

```json
"bbox": null
```

没有 bbox 时，就只在右侧候选列表中显示。

---

## 4. 用户自定义识别器是很好的工程亮点

你说“视觉识别模块可以支持用户自定义”，这个非常加分。

可以设计成一个配置页：

```text
模型配置
--------------------------------
识别器类型：
[ OpenAI / Gemini / Claude / 本地模型 / 自定义 HTTP ]

API Key:
[ **************** ]

模型名称:
[ gpt-4o / gemini-1.5-pro / ... ]

Prompt 模板:
[ 请识别这张图片中适合制作知识卡片的术语... ]

输出格式:
[ JSON Schema ]

测试按钮:
[ 用示例图片测试 ]
```

这样你的项目从“调用一个模型”变成了“支持可插拔模型后端”。这很有工程味。

---

## 5. 建议抽象一个 Analyzer 接口

你可以在 C++/Qt 里设计类似接口。

```cpp
struct CandidateCard {
    QString term;
    QString type;
    QString originalText;
    QString shortExplanation;
    QString whySelected;
    int familiaritySuggestion;
    QStringList links;
    QRect bbox;
    QStringList relatedTerms;
};

struct AnalyzeResult {
    QString sceneType;
    QString language;
    QString summary;
    QList<CandidateCard> candidates;
};

class IImageAnalyzer {
public:
    virtual ~IImageAnalyzer() = default;
    virtual AnalyzeResult analyze(const QString& imagePath) = 0;
};
```

然后具体实现可以有：

```cpp
class OpenAIImageAnalyzer : public IImageAnalyzer {};
class GeminiImageAnalyzer : public IImageAnalyzer {};
class MockImageAnalyzer : public IImageAnalyzer {};
class CustomHttpAnalyzer : public IImageAnalyzer {};
```

特别建议你一定做一个 `MockImageAnalyzer`。

原因是：

- 展示时不怕网络挂；
- 调试 GUI 不依赖 API；
- 老师看得出你有工程兜底；
- 可以内置几张 demo 图和固定返回结果。

---

## 6. 识别器不是直接入库，而是进入“确认队列”

即使使用最新 VLM，也不建议自动创建全部卡片。更好的流程是：

```text
上传图片
  ↓
VLM 分析
  ↓
候选卡片列表
  ↓
与已有卡片库比对
  ↓
用户确认 / 合并 / 忽略 / 标熟悉
  ↓
正式入库
```

这样可以避免：

- 模型胡编；
- 重复卡片；
- 识别出太多无关词；
- 用户熟悉的词被反复加入；
- 模型解释不准确。

这个确认队列是你的产品价值之一。

候选项可以有不同状态：

| 状态 | 说明 |
|---|---|
| New | 新卡片 |
| Existing | 词库中已有 |
| Familiar | 用户已熟悉 |
| Similar | 与已有卡片相似，建议合并 |
| Ignored | 用户忽略 |
| Uncertain | 模型不确定 |

这比“VLM 一步生成知识库”要更稳。

---

## 7. 词库反向影响 VLM Prompt，这是很好的点

你前面说“识别器需要参考词条库”，这个仍然保留，而且更重要。

在调用 VLM 前，可以把用户已有知识状态作为上下文传给模型。

例如 prompt 里附带：

```text
用户已有卡片：
- Carbonara，熟悉度 4
- Tiramisu，熟悉度 5
- Risotto，熟悉度 2
- Pecorino Romano，熟悉度 1

请不要重复推荐熟悉度 >= 4 的词。
如果图片中出现已有卡片，请标记为 existing。
优先推荐用户不熟悉、但对理解图片有帮助的术语。
```

这就体现了你的核心差异化：

> 不是“看图解释”，而是“基于用户已有知识状态的看图建库”。

这个非常值得在答辩里强调。

---

## 8. VLM Prompt 可以支持场景模板

为了支持用户自定义，可以让用户选择场景：

| 场景模板 | 识别重点 |
|---|---|
| 旅游菜单 | 菜名、食材、烹饪方式、过敏原、推荐解释 |
| 教材/讲义 | 概念、定理、术语、人名、流派 |
| 数学作业 | 公式、符号、知识点、题型 |
| 论文截图 | 专业术语、方法、指标、作者/模型名 |
| 博物馆展板 | 人物、年代、地点、事件、专有名词 |
| 自定义 | 用户自己写 prompt |

这个非常适合作为 GUI 的下拉框：

```text
识别模式：[旅游菜单 v]
```

不同模式对应不同 Prompt。

比如“旅游菜单模式”可以要求：

```text
请优先识别：
1. 菜名
2. 地方特色食材
3. 烹饪方式
4. 可能影响点餐的过敏原或禁忌
5. 不要识别普通价格、编号、标点
```

“数学作业模式”可以要求：

```text
请优先识别：
1. 数学概念
2. 定理名称
3. 重要符号
4. 题型
5. 可能需要复习的前置知识
```

这让“用户自定义识别模块”变得很具体。

---

## 9. 复杂度判断：这个版本更适合优秀作业

把 OCR/NER 改成 VLM 后，算法复杂度下降，但**工程和 GUI 复杂度反而更清楚**。

主要复杂度变成：

| 复杂度来源 | 说明 |
|---|---|
| API 抽象 | 多模型/自定义 HTTP 后端 |
| Prompt 管理 | 场景模板、用户自定义 prompt |
| JSON 解析 | 模型返回结构化卡片 |
| 结果校验 | 缺字段、格式错、重复词处理 |
| 卡片库比对 | 新词/已有/熟悉/相似合并 |
| 图片标注 | bbox 高亮、点击词条 |
| 状态管理 | 候选 → 确认 → 入库 |
| 本地持久化 | 卡片、图片、关系、配置 |
| 复习系统 | 熟悉度更新 |
| 图谱 | 关系维护和可视化 |

这非常像一个优秀 Qt 工程，而不是“调 API 的壳”。

---

## 10. 需要避免的误区

### 误区一：让 VLM 直接生成最终卡片库

不建议。
应该让它生成候选卡片，用户确认后入库。

### 误区二：过度依赖联网搜索

你说成本无所谓，但稳定性还是问题。建议：

- VLM 解释可以作为模型笔记；
- 链接可以先生成搜索 URL；
- Wikipedia 链接不一定要实时验证；
- 真正网页抓取总结作为可选功能。

### 误区三：自定义识别器做得太复杂

第一版自定义识别器不用支持任意插件。支持这几种就够了：

1. API Endpoint；
2. API Key；
3. Model Name；
4. Prompt Template；
5. JSON Path / 返回格式说明。

也就是“自定义 HTTP VLM 后端”，不是完整插件系统。

---

## 11. 推荐的系统架构

可以这样画：

```text
                 ┌────────────────────┐
                 │    Image Import     │
                 └─────────┬──────────┘
                           ↓
                 ┌────────────────────┐
                 │   VLM Analyzer      │
                 │ OpenAI/Gemini/Mock  │
                 └─────────┬──────────┘
                           ↓
                 ┌────────────────────┐
                 │ Candidate Manager   │
                 │ 去重/熟悉度/合并     │
                 └─────────┬──────────┘
                           ↓
        ┌──────────────────┴──────────────────┐
        ↓                                     ↓
┌────────────────┐                   ┌────────────────┐
│   Card Library │                   │ Source Images   │
└───────┬────────┘                   └────────────────┘
        ↓
┌────────────────┐
│ Knowledge Graph │
└───────┬────────┘
        ↓
┌────────────────┐
│ Review / QA     │
└────────────────┘
```

这个结构清楚、好讲、好实现。

---

## 12. 可以把项目亮点改成这四个

### 亮点一：VLM 驱动的图片知识抽取

不是 OCR，而是让模型理解图片内容，直接生成结构化候选卡片。

### 亮点二：用户知识状态参与识别

已有卡片和熟悉度会影响模型推荐，避免重复和低价值词条。

### 亮点三：人机协同的卡片确认流程

模型生成候选，用户确认、合并、编辑后入库。

### 亮点四：可自定义识别器

用户可以配置模型、Prompt、场景模板，让系统适配菜单、教材、论文、数学题等不同场景。

---

## 13. 最终建议版本

我建议你的 idea 最终这样定义：

> 本项目是一个基于视觉语言模型的图片知识卡片管理系统。用户上传一张菜单、教材、论文截图或作业图片后，系统调用可配置的视觉语言模型，根据用户已有卡片库和熟悉度状态，识别出值得学习的术语、概念或实体，并生成结构化候选卡片。用户可以确认、忽略、合并或编辑这些候选卡片。每张卡片包含词条、熟悉度、用户笔记、模型笔记、互联网链接、来源图片和相关卡片。系统进一步提供卡片库搜索、图片标注视图、知识图谱和复习模式，使一次性的图片理解转化为长期可管理的个人知识库。

这个版本非常稳。

---

## 14. 一句话判断

你的修正很合理。
**完全用最新 VLM 替代 OCR + LM 是更好的 demo 策略**，只要你把 VLM 抽象成“可配置的图片理解模块”，并把系统重点放在**候选卡片确认、知识状态管理、来源图片追踪、关系维护和 GUI 交互**上，它就不是简单套壳，而是一个完整、有工程复杂度、有实用价值的 Qt 大作业。

-----

> 写一个更清楚的proposal,包含项目功能设计文档， 核心模块，数据结构

我会把它整理成一份可以直接放进课程立项/答辩材料里的 proposal，重点突出“不是单纯调用大模型”，而是完整的图片知识卡片管理系统。

# 项目 Proposal：基于视觉语言模型的图片知识卡片管理系统

## 1. 项目名称

**Image2Card：基于图片的个人知识卡片管理系统**

备选名称：

- 图识卡片
- 拍照知识库
- SnapKnow
- 视觉知识卡片库
- Image-based Knowledge Card Manager

---

## 2. 项目背景与痛点

在日常生活和学习中，用户经常会遇到一张信息密度很高的图片，例如：

- 出国旅游时看到一张外语菜单；
- 阅读教材、讲义、论文截图时遇到大量陌生术语；
- 学习哲学、历史、数学、计算机等课程时，一页纸上出现许多概念、人名、公式或专有名词；
- 参观博物馆、展览或阅读说明牌时，希望快速理解其中的关键信息。

目前大模型已经可以直接识别图片并解释内容，但这种方式通常是**一次性问答**，缺乏长期状态管理。用户仍然需要手动记录：

- 哪些词已经见过；
- 哪些词自己已经熟悉；
- 哪些词需要复习；
- 某个词最早来自哪张图片；
- 不同知识点之间有什么关系；
- 模型解释和自己的理解如何分开保存。

因此，本项目希望解决的问题是：

> 当用户面对一张充满陌生概念的图片时，只需要上传图片，系统就能自动识别值得学习的词条，并将其转化为可编辑、可管理、可复习、可关联的知识卡片。

---

## 3. 项目目标

本项目拟实现一个桌面端 Qt 应用，用户可以上传图片，系统调用可配置的视觉语言模型，对图片内容进行理解，识别出适合制作知识卡片的术语、概念、实体或公式，并生成结构化候选卡片。用户确认后，这些候选卡片会进入个人知识库。

系统不仅关注“识别图片”，更关注**图片识别后的知识状态管理**。

核心目标包括：

1. 将图片中的陌生知识点自动转化为候选卡片；
2. 支持用户确认、忽略、合并和编辑候选卡片；
3. 建立长期个人词条库，记录熟悉度、笔记、链接和来源图片；
4. 支持卡片之间的关系维护，形成轻量知识图谱；
5. 提供复习模式，帮助用户根据熟悉度巩固知识；
6. 支持用户自定义视觉语言模型识别器，包括模型接口、Prompt 模板和识别场景。

---

## 4. 项目核心特点

### 4.1 基于图片的知识库

传统笔记软件通常要求用户手动输入知识点。本项目以图片作为知识入口，用户上传一张图片后，系统自动分析其中的高价值知识点，并生成卡片。

图片可以是：

- 菜单照片；
- 教材截图；
- 数学作业；
- 论文页面；
- 博物馆展板；
- 课堂板书；
- 讲义或 PPT 页面。

每张卡片都会记录来源图片，因此用户既可以从图片回到卡片，也可以从卡片回到原始语境。

---

### 4.2 视觉语言模型驱动的知识抽取

本项目不采用传统的 “OCR + 分词 + 命名实体识别” 流程，而是直接使用视觉语言模型完成图片理解。

系统要求模型返回结构化结果，例如：

- 图片场景；
- 图片语言；
- 候选词条；
- 词条类型；
- 简短解释；
- 推荐理由；
- 互联网链接；
- 与其他词条的关系；
- 图片中的位置区域。

这样可以避免传统 OCR 在复杂排版、多语言、手写、公式、菜单等场景下不稳定的问题。

---

### 4.3 用户知识状态参与识别

系统不是每次都盲目生成卡片，而是会参考用户已有的卡片库。

例如：

- 如果某个词已经存在，则标记为“已有卡片”；
- 如果某个词用户熟悉度很高，则默认不推荐加入；
- 如果模型识别出的词和已有词相似，则提示用户是否合并；
- 如果某个词在多张图片中反复出现，则增强其重要性。

这使系统从“一次性看图解释工具”变成“长期个人知识管理系统”。

---

### 4.4 人机协同的卡片确认流程

模型生成的结果不会直接进入知识库，而是先进入候选区。用户可以对候选卡片执行：

- 确认加入；
- 忽略；
- 标记为熟悉；
- 合并到已有卡片；
- 编辑模型解释；
- 添加个人笔记；
- 修改熟悉度。

这样既保留了模型生成的效率，又避免了模型误识别、重复生成和解释不准确的问题。

---

### 4.5 模型笔记与用户笔记分离

每张卡片包含两类解释：

| 类型 | 来源 | 编辑权限 | 作用 |
|---|---|---|---|
| 用户笔记 | 用户手动输入 | 用户可编辑 | 保存个人理解、记忆方法、课堂补充 |
| 模型笔记 | 视觉语言模型生成 | 用户可编辑，模型不可覆盖用户笔记 | 提供初始解释、背景信息、总结 |

这个设计的核心思想是：

> 模型可以辅助生成知识，但用户始终拥有最终知识库的编辑权。

---

### 4.6 可自定义识别器

系统支持用户自定义视觉语言模型识别模块。用户可以配置：

- API 地址；
- API Key；
- 模型名称；
- Prompt 模板；
- 场景模式；
- 输出 JSON 格式要求。

系统也可以提供预置模板：

| 场景模板 | 识别重点 |
|---|---|
| 旅游菜单 | 菜名、食材、烹饪方式、过敏原、地方特色 |
| 教材讲义 | 概念、定义、人物、流派、术语 |
| 数学作业 | 定理、公式、符号、前置知识点 |
| 论文截图 | 方法名、模型名、指标、数据集、专业术语 |
| 博物馆展板 | 人物、地点、年代、事件、文化背景 |
| 通用模式 | 图片中值得学习或查询的知识点 |

---

## 5. 用户使用流程

### 5.1 基本流程

```text
上传图片
  ↓
选择识别模式
  ↓
调用视觉语言模型分析图片
  ↓
生成候选卡片
  ↓
系统与已有卡片库比对
  ↓
用户确认、忽略、合并或编辑
  ↓
正式加入知识库
  ↓
后续搜索、查看、复习、建立关系
```

---

### 5.2 示例场景：旅行菜单

用户在国外餐厅拍摄菜单图片。

系统识别出：

- Carbonara；
- Risotto；
- Tiramisu；
- Pecorino Romano；
- Guanciale。

系统发现：

- Tiramisu 用户熟悉度为 5，默认忽略；
- Carbonara 已有卡片，更新来源图片；
- Guanciale 是新词，推荐创建卡片；
- Pecorino Romano 和 Carbonara 有关系，推荐建立关联。

用户确认后，系统生成对应卡片，并在原图上高亮显示这些词条。

---

### 5.3 示例场景：数学作业

用户上传一张数学题图片。

系统识别出：

- Eigenvalue；
- Matrix diagonalization；
- Linear transformation；
- Characteristic polynomial；
- Determinant。

系统为每个概念生成解释，并记录它们来自同一张图片。系统自动建立“共现关系”，并推荐用户复习线性代数相关概念。

---

## 6. 功能设计

## 6.1 图片导入与管理模块

### 功能说明

该模块负责管理用户上传的图片，是整个系统的输入入口。

### 主要功能

1. 上传本地图片；
2. 支持常见格式：JPG、PNG、BMP；
3. 显示图片预览；
4. 为图片添加标题、标签和场景类型；
5. 保存图片分析结果；
6. 查看某张图片生成过哪些卡片；
7. 支持重新分析图片。

### GUI 设计

图片导入页可以分为左右两栏：

```text
+------------------------------------------------------+
| 上传图片 | 选择识别模式 | 开始分析                  |
+-----------------------------+------------------------+
|                             | 图片信息                |
|        图片预览区域          | 标题                    |
|                             | 场景                    |
|                             | 已生成卡片数量           |
+-----------------------------+------------------------+
```

---

## 6.2 视觉语言模型分析模块

### 功能说明

该模块负责调用用户配置的视觉语言模型，对图片进行理解，并返回结构化候选知识点。

### 输入

- 图片文件；
- 用户选择的场景模板；
- 用户已有卡片摘要；
- Prompt 模板；
- 模型配置。

### 输出

结构化分析结果，包括：

- 场景类型；
- 图片摘要；
- 候选卡片列表；
- 每个候选词的位置；
- 简短解释；
- 相关词推荐；
- 推荐互联网链接。

### 模型输出示例

```json
{
  "scene_type": "restaurant_menu",
  "language": "Italian",
  "summary": "This image is a restaurant menu containing Italian pasta dishes and desserts.",
  "items": [
    {
      "term": "Carbonara",
      "type": "dish",
      "original_text": "Spaghetti Carbonara",
      "short_explanation": "A Roman pasta dish made with eggs, cheese, cured pork, and black pepper.",
      "why_selected": "It is a common but potentially unfamiliar Italian dish name.",
      "familiarity_suggestion": 2,
      "links": [
        {
          "title": "Wikipedia",
          "url": "https://en.wikipedia.org/wiki/Carbonara"
        }
      ],
      "bbox": {
        "x": 120,
        "y": 240,
        "w": 180,
        "h": 32
      },
      "related_terms": [
        "Guanciale",
        "Pecorino Romano"
      ]
    }
  ]
}
```

### 设计重点

该模块需要处理模型输出不稳定的问题，因此需要：

- JSON 格式校验；
- 缺失字段补全；
- 异常结果提示；
- 模型调用失败时展示错误信息；
- 支持 mock 模式，方便离线演示。

---

## 6.3 候选卡片确认模块

### 功能说明

模型分析结果不会直接进入知识库，而是先进入候选卡片确认区。

### 候选状态

| 状态 | 含义 |
|---|---|
| New | 新词条，建议创建卡片 |
| Existing | 词库中已有卡片 |
| Familiar | 用户已经熟悉，默认不加入 |
| Similar | 与已有卡片相似，建议合并 |
| Ignored | 用户选择忽略 |
| Uncertain | 模型不确定，需要用户判断 |

### 用户操作

用户可以：

- 一键加入新卡片；
- 批量加入；
- 忽略某个候选词；
- 标记为熟悉；
- 合并到已有卡片；
- 修改词条名称；
- 修改模型解释；
- 添加用户笔记；
- 修改推荐链接；
- 设置初始熟悉度。

### GUI 设计

```text
+------------------------------------------------------+
| 图片分析结果                                          |
+-----------------------+------------------------------+
| 原图标注视图           | 候选卡片列表                  |
|                       | [New] Guanciale               |
|                       | [Existing] Carbonara           |
|                       | [Familiar] Tiramisu            |
|                       | [Similar] Pecorino             |
+-----------------------+------------------------------+
| 加入选中 | 忽略 | 合并 | 标记熟悉 | 编辑              |
+------------------------------------------------------+
```

---

## 6.4 卡片库模块

### 功能说明

卡片库是系统的核心数据管理模块，用于长期保存和管理用户的知识卡片。

### 卡片内容

每张卡片包含：

- 词条名称；
- 词条类型；
- 熟悉度；
- 用户笔记；
- 模型笔记；
- 简短摘要；
- 互联网链接；
- 来源图片；
- 相关卡片；
- 创建时间；
- 最近更新时间；
- 最近复习时间。

### 主要功能

1. 卡片创建；
2. 卡片编辑；
3. 卡片删除；
4. 卡片搜索；
5. 按熟悉度筛选；
6. 按类型筛选；
7. 按来源图片筛选；
8. 按标签筛选；
9. 查看卡片详情；
10. 查看相关卡片；
11. 查看来源图片。

### GUI 设计

卡片库页面可以采用三栏布局：

```text
+------------------------------------------------------+
| 搜索框：请输入词条                                   |
+------------+----------------------+------------------+
| 筛选栏      | 卡片列表 / 卡片网格    | 卡片详情          |
| 熟悉度      |                      | 词条              |
| 类型        |                      | 解释              |
| 标签        |                      | 笔记              |
| 来源图片    |                      | 链接              |
+------------+----------------------+------------------+
```

---

## 6.5 图片标注视图模块

### 功能说明

该模块将模型识别出的词条以可交互的方式显示在原图片上，使图片变成一个可点击的知识界面。

### 主要功能

1. 在图片上显示词条高亮框；
2. 鼠标悬停显示简短解释；
3. 点击词条打开卡片详情；
4. 右键菜单支持加入、忽略、标记熟悉；
5. 不同状态使用不同颜色或边框；
6. 支持缩放、拖动图片；
7. 支持隐藏或显示标注层。

### 状态展示

| 状态 | 显示方式 |
|---|---|
| 新词条 | 高亮边框 |
| 已有卡片 | 使用已有卡片颜色 |
| 熟悉词条 | 淡化显示 |
| 被忽略词条 | 灰色显示 |
| 选中词条 | 加粗边框 |

### GUI 示例

```text
+------------------------------------------------------+
|                  图片标注视图                         |
|                                                      |
|      [ Carbonara ]     [ Guanciale ]                 |
|           ↓                  ↓                       |
|       悬浮解释           加入卡片按钮                  |
|                                                      |
+------------------------------------------------------+
```

这是本项目最有展示效果的 GUI 之一。

---

## 6.6 知识图谱模块

### 功能说明

该模块维护卡片之间的关系，帮助用户理解不同知识点之间的联系。

### 关系来源

1. 同一张图片中共同出现；
2. 模型推荐；
3. 用户手动添加；
4. 用户在复习或编辑时建立关系。

### 关系类型

| 类型 | 含义 |
|---|---|
| related_to | 一般相关 |
| appears_with | 在同一张图片中共同出现 |
| is_a | A 是 B 的一种 |
| part_of | A 是 B 的组成部分 |
| contrast_with | A 与 B 对比 |
| prerequisite_of | A 是 B 的前置知识 |

### 主要功能

1. 查看当前卡片相关节点；
2. 添加关系；
3. 删除关系；
4. 修改关系类型；
5. 从图片自动生成共现关系；
6. 点击图谱节点跳转卡片详情。

### GUI 设计

可以实现轻量版关系图：

```text
              Pecorino Romano
                    |
                    |
Guanciale ---- Carbonara ---- Italian cuisine
                    |
                    |
                 Pasta
```

不需要实现复杂图数据库，用普通关系表即可。

---

## 6.7 复习模块

### 功能说明

复习模块帮助用户根据熟悉度和最近复习时间回顾卡片。

### 主要功能

1. 按熟悉度低的卡片优先复习；
2. 显示卡片正面：词条；
3. 点击显示背面：解释、用户笔记、来源图片；
4. 用户选择“认识 / 模糊 / 不认识”；
5. 系统更新熟悉度；
6. 支持按标签、类型、来源图片复习。

### GUI 设计

```text
+------------------------------------------------------+
|                    复习模式                           |
+------------------------------------------------------+
|                                                      |
|                    Carbonara                         |
|                                                      |
|              点击查看解释                            |
|                                                      |
+------------------------------------------------------+
| 认识 | 模糊 | 不认识 | 下一张                         |
+------------------------------------------------------+
```

---

## 6.8 模型配置与场景模板模块

### 功能说明

该模块允许用户自定义视觉语言模型识别方式。

### 配置项

| 配置项 | 说明 |
|---|---|
| Provider | OpenAI / Gemini / Claude / 自定义 HTTP / Mock |
| API Endpoint | API 地址 |
| API Key | 用户密钥 |
| Model Name | 模型名称 |
| Prompt Template | 提示词模板 |
| Scene Template | 场景模板 |
| Output Schema | 输出格式要求 |
| Timeout | 超时时间 |
| Mock Mode | 离线演示模式 |

### GUI 设计

```text
+------------------------------------------------------+
| 模型配置                                              |
+------------------------------------------------------+
| Provider:       [ OpenAI v ]                          |
| Model Name:     [ gpt-4o ]                            |
| API Endpoint:   [ https://... ]                       |
| API Key:        [ *************** ]                   |
| Scene Template: [ 旅游菜单 v ]                         |
| Prompt:                                              |
| [ 请识别这张图片中适合制作知识卡片的术语... ]          |
|                                                      |
| [测试模型] [保存配置]                                 |
+------------------------------------------------------+
```

---

## 6.9 本地存储与导入导出模块

### 功能说明

系统需要长期保存用户数据，包括卡片、图片、关系、配置和复习记录。

### 存储方式

推荐使用 SQLite，也可以在第一版使用 JSON 文件。

### 需要保存的数据

- 卡片数据；
- 图片数据；
- 候选卡片历史；
- 卡片关系；
- 用户配置；
- 场景模板；
- 复习记录；
- 模型返回缓存。

### 导入导出功能

1. 导出全部卡片为 JSON；
2. 导入备份文件；
3. 导出某张图片生成的卡片；
4. 导出复习数据；
5. 导出为 Markdown 笔记。

---

## 7. 核心模块划分

系统可以划分为以下核心模块：

```text
Image2Card
│
├── UI Layer
│   ├── MainWindow
│   ├── ImageImportPage
│   ├── AnalyzeResultPage
│   ├── CardLibraryPage
│   ├── CardDetailPage
│   ├── KnowledgeGraphPage
│   ├── ReviewPage
│   └── SettingsPage
│
├── Analyzer Layer
│   ├── IImageAnalyzer
│   ├── OpenAIImageAnalyzer
│   ├── CustomHttpAnalyzer
│   ├── MockImageAnalyzer
│   └── PromptManager
│
├── Core Logic Layer
│   ├── CandidateManager
│   ├── CardManager
│   ├── ImageManager
│   ├── RelationManager
│   ├── ReviewManager
│   └── SearchManager
│
├── Data Layer
│   ├── Card
│   ├── SourceImage
│   ├── CandidateCard
│   ├── Relation
│   ├── ReviewRecord
│   └── UserSettings
│
└── Storage Layer
    ├── DatabaseManager
    ├── JsonExporter
    ├── JsonImporter
    └── CacheManager
```

---

## 8. 核心数据结构设计

## 8.1 Card：知识卡片

```cpp
class Card {
public:
    QString id;

    QString term;
    QString normalizedTerm;
    QString type;
    QString language;
    QString category;

    int familiarity;              // 0-5
    QString summary;

    QString userNote;
    QString modelNote;

    QStringList tags;
    QStringList linkIds;
    QStringList sourceImageIds;
    QStringList relatedCardIds;

    QDateTime createdAt;
    QDateTime updatedAt;
    QDateTime lastReviewedAt;
};
```

### 字段说明

| 字段 | 含义 |
|---|---|
| id | 卡片唯一标识 |
| term | 卡片标题 |
| normalizedTerm | 标准化后的词条名，用于去重 |
| type | 词条类型，例如 dish、concept、person、formula |
| language | 词条语言 |
| category | 用户分类 |
| familiarity | 熟悉度，0 到 5 |
| summary | 简短摘要 |
| userNote | 用户笔记 |
| modelNote | 模型生成笔记 |
| tags | 标签 |
| linkIds | 互联网链接 |
| sourceImageIds | 来源图片 |
| relatedCardIds | 相关卡片 |
| createdAt | 创建时间 |
| updatedAt | 更新时间 |
| lastReviewedAt | 最近复习时间 |

---

## 8.2 CandidateCard：候选卡片

```cpp
enum class CandidateStatus {
    New,
    Existing,
    Familiar,
    Similar,
    Ignored,
    Confirmed,
    Uncertain
};

class CandidateCard {
public:
    QString id;
    QString sourceImageId;

    QString term;
    QString normalizedTerm;
    QString type;
    QString originalText;

    QString shortExplanation;
    QString whySelected;
    int familiaritySuggestion;

    QRect bbox;
    QStringList suggestedLinks;
    QStringList relatedTerms;

    CandidateStatus status;

    QString matchedCardId;
    double confidence;

    QDateTime createdAt;
};
```

### 字段说明

| 字段 | 含义 |
|---|---|
| sourceImageId | 来自哪张图片 |
| term | 候选词条 |
| originalText | 图片中的原始文本 |
| shortExplanation | 模型生成的简短解释 |
| whySelected | 模型推荐原因 |
| familiaritySuggestion | 模型建议熟悉度 |
| bbox | 图片中的位置框 |
| suggestedLinks | 推荐链接 |
| relatedTerms | 相关词 |
| status | 当前候选状态 |
| matchedCardId | 匹配到的已有卡片 |
| confidence | 模型置信度或系统匹配分数 |

---

## 8.3 SourceImage：来源图片

```cpp
class SourceImage {
public:
    QString id;

    QString filePath;
    QString thumbnailPath;
    QString title;
    QString sceneType;
    QString language;

    QString summary;
    QString rawModelOutput;

    QStringList candidateCardIds;
    QStringList confirmedCardIds;

    QDateTime importedAt;
    QDateTime analyzedAt;
};
```

### 字段说明

| 字段 | 含义 |
|---|---|
| filePath | 原始图片路径 |
| thumbnailPath | 缩略图路径 |
| title | 图片标题 |
| sceneType | 场景类型 |
| language | 图片主要语言 |
| summary | 图片摘要 |
| rawModelOutput | 模型原始输出，方便调试 |
| candidateCardIds | 该图片生成的候选卡片 |
| confirmedCardIds | 已确认入库的卡片 |
| importedAt | 导入时间 |
| analyzedAt | 分析时间 |

---

## 8.4 Link：互联网链接

```cpp
class Link {
public:
    QString id;
    QString title;
    QString url;
    QString source;
    QString description;

    QDateTime createdAt;
};
```

### 示例

```text
title: Wikipedia - Carbonara
url: https://en.wikipedia.org/wiki/Carbonara
source: Wikipedia
description: Background information about Carbonara.
```

---

## 8.5 Relation：卡片关系

```cpp
enum class RelationType {
    RelatedTo,
    AppearsWith,
    IsA,
    PartOf,
    ContrastWith,
    PrerequisiteOf,
    UserDefined
};

class Relation {
public:
    QString id;

    QString fromCardId;
    QString toCardId;

    RelationType type;
    double weight;

    QString source;       // user / model / co_occurrence
    QString note;

    QDateTime createdAt;
};
```

### 字段说明

| 字段 | 含义 |
|---|---|
| fromCardId | 起始卡片 |
| toCardId | 目标卡片 |
| type | 关系类型 |
| weight | 关系强度 |
| source | 关系来源 |
| note | 关系说明 |

---

## 8.6 ReviewRecord：复习记录

```cpp
enum class ReviewResult {
    Known,
    Vague,
    Unknown
};

class ReviewRecord {
public:
    QString id;
    QString cardId;

    ReviewResult result;
    int familiarityBefore;
    int familiarityAfter;

    QDateTime reviewedAt;
};
```

### 熟悉度更新规则示例

| 用户反馈 | 熟悉度变化 |
|---|---|
| 认识 | +1 |
| 模糊 | 不变或 -1 |
| 不认识 | -1 或设为 0 |

熟悉度范围限制在 0 到 5。

---

## 8.7 UserSettings：用户配置

```cpp
class UserSettings {
public:
    QString analyzerProvider;
    QString apiEndpoint;
    QString apiKey;
    QString modelName;

    QString defaultSceneTemplateId;
    int timeoutSeconds;

    bool enableMockMode;
    bool autoCreateRelations;
    bool skipFamiliarCards;

    int familiarThreshold;  // 例如 >=4 认为熟悉
};
```

---

## 8.8 SceneTemplate：场景模板

```cpp
class SceneTemplate {
public:
    QString id;
    QString name;
    QString description;

    QString promptTemplate;
    QString outputSchema;

    QStringList focusTypes;
};
```

### 示例模板：旅游菜单

```text
name: 旅游菜单模式

focusTypes:
- dish
- ingredient
- cooking_method
- allergen
- local_specialty

promptTemplate:
请分析这张菜单图片，识别其中对旅行者理解菜单有帮助的菜名、食材、烹饪方式和可能的过敏原。
请不要识别价格、编号、普通形容词。
请以 JSON 格式返回候选知识卡片。
```

---

## 9. 数据库表设计建议

如果使用 SQLite，可以设计如下表：

### cards

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| term | TEXT |
| normalized_term | TEXT |
| type | TEXT |
| language | TEXT |
| category | TEXT |
| familiarity | INTEGER |
| summary | TEXT |
| user_note | TEXT |
| model_note | TEXT |
| created_at | TEXT |
| updated_at | TEXT |
| last_reviewed_at | TEXT |

---

### source_images

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| file_path | TEXT |
| thumbnail_path | TEXT |
| title | TEXT |
| scene_type | TEXT |
| language | TEXT |
| summary | TEXT |
| raw_model_output | TEXT |
| imported_at | TEXT |
| analyzed_at | TEXT |

---

### candidate_cards

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| source_image_id | TEXT |
| term | TEXT |
| normalized_term | TEXT |
| type | TEXT |
| original_text | TEXT |
| short_explanation | TEXT |
| why_selected | TEXT |
| familiarity_suggestion | INTEGER |
| bbox_x | INTEGER |
| bbox_y | INTEGER |
| bbox_w | INTEGER |
| bbox_h | INTEGER |
| status | TEXT |
| matched_card_id | TEXT |
| confidence | REAL |
| created_at | TEXT |

---

### links

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| card_id | TEXT |
| title | TEXT |
| url | TEXT |
| source | TEXT |
| description | TEXT |

---

### relations

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| from_card_id | TEXT |
| to_card_id | TEXT |
| type | TEXT |
| weight | REAL |
| source | TEXT |
| note | TEXT |
| created_at | TEXT |

---

### image_card_map

| 字段 | 类型 |
|---|---|
| image_id | TEXT |
| card_id | TEXT |

用于记录某张图片和卡片之间的来源关系。

---

### review_records

| 字段 | 类型 |
|---|---|
| id | TEXT PRIMARY KEY |
| card_id | TEXT |
| result | TEXT |
| familiarity_before | INTEGER |
| familiarity_after | INTEGER |
| reviewed_at | TEXT |

---

## 10. 主要类设计

### 10.1 IImageAnalyzer

```cpp
class IImageAnalyzer {
public:
    virtual ~IImageAnalyzer() = default;

    virtual AnalyzeResult analyze(
        const QString& imagePath,
        const SceneTemplate& sceneTemplate,
        const QList<Card>& existingCards
    ) = 0;
};
```

作用：定义图片分析器接口。

---

### 10.2 OpenAIImageAnalyzer

```cpp
class OpenAIImageAnalyzer : public IImageAnalyzer {
public:
    AnalyzeResult analyze(
        const QString& imagePath,
        const SceneTemplate& sceneTemplate,
        const QList<Card>& existingCards
    ) override;

private:
    QString buildPrompt(
        const SceneTemplate& sceneTemplate,
        const QList<Card>& existingCards
    );

    QString sendRequest(const QString& imagePath, const QString& prompt);
    AnalyzeResult parseResponse(const QString& response);
};
```

作用：调用具体的视觉语言模型 API。

---

### 10.3 MockImageAnalyzer

```cpp
class MockImageAnalyzer : public IImageAnalyzer {
public:
    AnalyzeResult analyze(
        const QString& imagePath,
        const SceneTemplate& sceneTemplate,
        const QList<Card>& existingCards
    ) override;
};
```

作用：返回固定 demo 数据，方便离线展示和调试。

---

### 10.4 CandidateManager

```cpp
class CandidateManager {
public:
    QList<CandidateCard> generateCandidates(const AnalyzeResult& result);

    void compareWithExistingCards(
        QList<CandidateCard>& candidates,
        const QList<Card>& existingCards
    );

    Card confirmCandidate(const CandidateCard& candidate);
    void ignoreCandidate(const QString& candidateId);
    void mergeCandidate(const QString& candidateId, const QString& cardId);
};
```

作用：管理候选卡片状态，处理去重、合并、确认入库。

---

### 10.5 CardManager

```cpp
class CardManager {
public:
    Card createCard(const CandidateCard& candidate);
    void updateCard(const Card& card);
    void deleteCard(const QString& cardId);

    QList<Card> searchCards(const QString& keyword);
    QList<Card> filterByFamiliarity(int minValue, int maxValue);
    QList<Card> filterByType(const QString& type);

    Card getCardById(const QString& id);
};
```

作用：卡片的增删改查和搜索筛选。

---

### 10.6 RelationManager

```cpp
class RelationManager {
public:
    void addRelation(
        const QString& fromCardId,
        const QString& toCardId,
        RelationType type,
        const QString& source
    );

    void removeRelation(const QString& relationId);

    QList<Relation> getRelationsOfCard(const QString& cardId);

    void generateCoOccurrenceRelations(
        const QString& sourceImageId,
        const QList<QString>& cardIds
    );
};
```

作用：管理知识图谱关系。

---

### 10.7 ReviewManager

```cpp
class ReviewManager {
public:
    QList<Card> selectCardsForReview(int limit);

    void recordReviewResult(
        const QString& cardId,
        ReviewResult result
    );

private:
    int updateFamiliarity(int current, ReviewResult result);
};
```

作用：管理卡片复习和熟悉度更新。

---

### 10.8 DatabaseManager

```cpp
class DatabaseManager {
public:
    bool openDatabase(const QString& path);
    bool initializeTables();

    bool saveCard(const Card& card);
    bool saveSourceImage(const SourceImage& image);
    bool saveCandidateCard(const CandidateCard& candidate);
    bool saveRelation(const Relation& relation);
    bool saveReviewRecord(const ReviewRecord& record);

    QList<Card> loadAllCards();
    QList<SourceImage> loadAllImages();
    QList<Relation> loadRelations();
};
```

作用：统一封装数据库读写。

---

## 11. 关键算法与逻辑设计

### 11.1 词条去重逻辑

候选词进入系统后，需要与已有卡片比对。

基本规则：

1. 将词条转为小写；
2. 去掉首尾空格和标点；
3. 对比 normalizedTerm；
4. 如果完全相同，标记为 Existing；
5. 如果相似度较高，标记为 Similar；
6. 如果已有卡片熟悉度高于阈值，标记为 Familiar。

伪代码：

```cpp
for each candidate in candidates:
    normalized = normalize(candidate.term)

    if cardLibrary.contains(normalized):
        matched = cardLibrary.get(normalized)
        candidate.matchedCardId = matched.id

        if matched.familiarity >= familiarThreshold:
            candidate.status = Familiar
        else:
            candidate.status = Existing
    else if hasSimilarCard(normalized):
        candidate.status = Similar
    else:
        candidate.status = New
```

---

### 11.2 来源图片绑定逻辑

当用户确认候选卡片时：

- 如果是新卡片，则创建卡片并绑定当前图片；
- 如果是已有卡片，则不重复创建，只把当前图片加入该卡片的来源列表；
- 如果是合并卡片，则把候选信息合并到已有卡片。

```cpp
if candidate.status == New:
    card = createCard(candidate)
    card.sourceImageIds.append(sourceImageId)

if candidate.status == Existing:
    card = getCard(candidate.matchedCardId)
    card.sourceImageIds.append(sourceImageId)
    updateCard(card)
```

---

### 11.3 自动关系生成逻辑

当一张图片中有多个卡片被确认后，可以自动建立共现关系：

```cpp
for i in confirmedCards:
    for j in confirmedCards:
        if i != j:
            addRelation(i, j, AppearsWith, "co_occurrence")
```

为了避免关系过多，可以限制：

- 一张图片最多生成一定数量关系；
- 已存在关系只增加权重；
- 熟悉度很高的卡片不参与自动关系。

---

### 11.4 复习优先级逻辑

复习时优先选择：

1. 熟悉度低的卡片；
2. 最近没有复习的卡片；
3. 最近频繁出现的卡片；
4. 用户手动标记重要的卡片。

简单评分公式：

```text
review_score =
    (5 - familiarity) * 2
    + days_since_last_review
    + recent_appearance_count
```

分数越高，越优先复习。

---

## 12. GUI 总体设计

系统主界面可以采用侧边栏导航：

```text
+------------------------------------------------------+
| Image2Card                                           |
+------------+-----------------------------------------+
| 图片识别    |                                         |
| 卡片库      |              当前页面内容                 |
| 图片来源    |                                         |
| 知识图谱    |                                         |
| 复习模式    |                                         |
| 设置        |                                         |
+------------+-----------------------------------------+
```

### 页面列表

| 页面 | 功能 |
|---|---|
| 图片识别页 | 上传图片、调用模型、查看候选结果 |
| 分析结果页 | 标注图片、确认候选卡片 |
| 卡片库页 | 搜索、筛选、浏览所有卡片 |
| 卡片详情页 | 编辑笔记、链接、熟悉度、关系 |
| 图片来源页 | 查看所有上传图片及其生成卡片 |
| 知识图谱页 | 查看卡片之间关系 |
| 复习页 | 根据熟悉度进行卡片复习 |
| 设置页 | 配置模型、Prompt 和场景模板 |

---

## 13. 项目实现优先级

### P0：必须完成

| 功能 | 说明 |
|---|---|
| 图片上传 | 支持本地图片 |
| VLM 分析接口 | 可以调用模型或 mock 返回 |
| 候选卡片生成 | 从模型 JSON 转为候选卡片 |
| 候选确认 | 用户可加入、忽略、编辑 |
| 卡片库 | 支持增删改查 |
| 熟悉度 | 每张卡片有 0-5 熟悉度 |
| 来源图片绑定 | 卡片记录来自哪张图 |
| 本地保存 | JSON 或 SQLite 持久化 |
| 基本 GUI | 主窗口、图片页、卡片库、详情页 |

---

### P1：强烈建议完成

| 功能 | 说明 |
|---|---|
| 图片标注视图 | 在图片上显示候选词区域 |
| 卡片搜索筛选 | 按关键词、类型、熟悉度搜索 |
| 模型配置页 | 配置 API、Prompt、场景 |
| Mock 模式 | 离线演示 |
| 链接管理 | 卡片包含互联网链接 |
| 自动去重 | 已有卡片不重复创建 |

---

### P2：加分功能

| 功能 | 说明 |
|---|---|
| 知识图谱 | 卡片关系可视化 |
| 复习模式 | 类似 Anki 的卡片复习 |
| 自动共现关系 | 同图卡片自动建立关系 |
| Markdown 导出 | 导出为学习笔记 |
| 多场景模板 | 菜单、教材、数学、论文等 |

---

### P3：可选展示功能

| 功能 | 说明 |
|---|---|
| 基于知识图谱的 QA | 用卡片库回答问题 |
| 网页内容总结 | 抓取链接并总结 |
| 高级 spaced repetition | 更复杂的复习算法 |
| 多用户系统 | 支持多个知识库账户 |

---

## 14. 项目难点分析

### 14.1 模型输出稳定性

视觉语言模型可能返回格式不稳定，因此需要：

- 明确 JSON Schema；
- 对返回结果做解析和校验；
- 缺字段时使用默认值；
- 解析失败时展示原始结果并允许用户手动编辑；
- 提供 Mock 模式保证展示稳定。

---

### 14.2 候选卡片与已有卡片的状态管理

系统需要区分：

- 新词；
- 已有词；
- 熟悉词；
- 相似词；
- 被忽略词。

这部分是核心工程复杂度之一，需要设计清楚的状态流转。

---

### 14.3 GUI 复杂度

系统包含多个复杂页面：

- 图片预览；
- 图片标注；
- 候选卡片列表；
- 卡片详情编辑；
- 图谱显示；
- 复习界面；
- 模型配置页面。

这要求较好的 Qt 信号槽设计和页面状态同步。

---

### 14.4 数据持久化

卡片、图片、关系、复习记录、模型配置都需要长期保存。需要保证：

- 数据不会丢失；
- 图片路径有效；
- 卡片和图片的关联正确；
- 删除卡片时关系同步删除；
- 导入导出格式稳定。

---

## 15. 项目创新点

1. **图片作为知识库入口**
   用户不需要手动输入知识点，只需要上传图片。

2. **视觉语言模型直接生成结构化候选卡片**
   避免传统 OCR + 分词流程的复杂性和不稳定性。

3. **用户知识状态参与模型识别**
   系统会根据已有卡片和熟悉度过滤重复或低价值词条。

4. **人机协同的确认机制**
   模型负责推荐，用户负责确认和最终编辑。

5. **来源图片追踪**
   每个知识点都能回到原始图片语境。

6. **知识图谱和复习闭环**
   卡片不只是静态笔记，还可以关联和复习。

7. **可自定义识别器**
   用户可以配置模型、Prompt 和场景模板，扩展不同使用场景。

---

## 16. 与普通大模型看图问答的区别

| 普通大模型看图问答 | 本项目 |
|---|---|
| 一次性回答 | 长期知识库 |
| 没有熟悉度管理 | 每张卡片有熟悉度 |
| 不记录来源 | 卡片绑定来源图片 |
| 用户需要自己整理 | 系统自动生成候选卡片 |
| 不维护关系 | 支持卡片关系图谱 |
| 不支持复习 | 支持复习模式 |
| 模型输出不可控 | 用户确认后入库 |
| 只解决当前图片 | 积累个人知识状态 |

---

## 17. 预期代码规模

| 模块 | 预计代码量 |
|---|---:|
| 数据结构与模型类 | 500–1000 行 |
| 数据库存储 | 800–1500 行 |
| VLM 接口与 JSON 解析 | 800–1500 行 |
| 候选卡片管理 | 500–1000 行 |
| 卡片库管理 | 800–1500 行 |
| 图片标注 GUI | 1000–2000 行 |
| 卡片详情 GUI | 800–1500 行 |
| 设置页与 Prompt 模板 | 500–1000 行 |
| 复习模块 | 500–1000 行 |
| 知识图谱模块 | 800–1500 行 |
| 总计 | 6000–13000 行左右 |

实际代码量取决于 GUI 精细程度和是否实现 P2/P3 功能。

---

## 18. 最终交付目标

### 基础交付

1. 一个可运行的 Qt 桌面应用；
2. 支持上传图片；
3. 支持调用视觉语言模型或 Mock 模型；
4. 支持生成候选知识卡片；
5. 支持用户确认候选卡片；
6. 支持卡片库管理；
7. 支持熟悉度和用户笔记；
8. 支持来源图片追踪；
9. 支持本地保存和读取。

### 展示亮点

1. 上传一张菜单或教材图片；
2. 系统自动识别多个候选词；
3. 图片上显示词条标注；
4. 候选词与已有卡片库比对；
5. 用户确认后生成卡片；
6. 查看卡片详情、解释、链接、来源图片；
7. 在知识图谱中查看相关卡片；
8. 进入复习模式复习低熟悉度卡片。

---

## 19. 总结

本项目的核心不是简单调用视觉语言模型，而是围绕“图片中的陌生知识”建立一个完整的管理闭环：

```text
图片理解 → 候选卡片 → 用户确认 → 知识库 → 来源追踪 → 关系图谱 → 复习巩固
```

它的主要复杂度来自：

- 多页面 GUI 设计；
- 视觉语言模型接口抽象；
- 结构化 JSON 解析；
- 候选卡片状态管理；
- 卡片库增删改查；
- 来源图片和卡片的关联；
- 熟悉度与复习状态管理；
- 轻量知识图谱维护。

因此，它非常适合作为一个生活类、学习类、实用性强的程序设计实习项目。项目既有清晰的现实痛点，又有足够的工程复杂度和 GUI 展示空间，同时可以根据时间灵活裁剪功能范围。