### Overview

core/vlm.py核心接口
dataclass/models.py数据结构定义
storage/repository.py: database存储


### Setup

#### 读取 .env 并设置环境变量

```PowerShell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}
```

```linux/mac
set -a && source .env && set +a
```

#### Install
python 3.12可运行
```bash
conda env create -f environment.yml
conda activate image2card

```

或使用已有 Python 3.12 环境：

```bash
python -m pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
pip install -r requirements.txt
```

#### Run

真实调用 VLM API 前需要配置 `OPENAI_API_KEY`。推荐把中转站配置写到本项目的 `.env.local`，它已被 `.gitignore` 忽略，不会污染全局 shell：

```bash
OPENAI_API_KEY="your_api_key"
OPENAI_BASE_URL="http://106.14.248.123:8080"
OPENAI_MODEL="gpt-5.4"
OPENAI_WIRE_API="responses"
OPENAI_TIMEOUT_SECONDS="60"
OPENAI_TRUST_ENV="false"
```

如果中转站兼容 Chat Completions，也可以把 `OPENAI_WIRE_API` 改成 `chat`。

然后直接运行：

```bash
python demo.py demo_samples/menus/toms_restaurant_menu.jpg
```
