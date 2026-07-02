# JSON 解析常见坑（LLM 生成结构化内容时）

如果你在 Step 2 生成 JSON 后，打算再用代码去解析它（而不是直接写文件让 `render_and_send.py` 读），留意下面这些常见故障模式。

## 1. 中文语境里的 ASCII 双引号

描述中文内容时，容易在字符串值内部混入 ASCII 双引号 `"`，提前把 JSON 字符串截断：

```json
{"desc": "市场解读为AI投资需求仍处于"超级周期"，投资者..."}
```

**预防（最有效）**：生成 JSON 时的指令里明确写「JSON 字符串值内部禁止使用 ASCII 双引号，引用用中文引号「」『』，或不加引号」。这是 Step 2 里已经强调的规则，照做基本能避免这一类问题。

**事后修复**（如果还是漏了）：
```python
import re
# 左引号：CJK 字符之间的 ASCII "
text = re.sub(r'(?<=[一-鿿])"(?=[一-鿿])', '“', text)
# 右引号：CJK 字符后接标点的 ASCII "
text = re.sub(r'(?<=[一-鿿])"(?=[　-〿一-鿿，。！？、；：])', '”', text)
```

已知盲区：`CJK""`（CJK 字符 + 中文右引号 + JSON 分隔符引号连在一起）这种三字符相邻的情况，正则匹配不到——如果 `json.loads` 报 `Expecting ',' delimiter` 且报错位置在 CJK 文本附近，装 `json_repair`（`pip install json-repair`）做兜底：

```python
from json_repair import repair_json
data = json.loads(repair_json(candidate))
```

## 2. Markdown 代码块包裹

```python
candidate = re.sub(r'^```json\s*', '', candidate)
candidate = re.sub(r'^```\s*', '', candidate)
candidate = re.sub(r'\s*```\s*$', '', candidate)
```

## 3. JSON 前有说明性文字

找第一个 `{` 开始解析：
```python
json_start = output.find("{")
candidate = output[json_start:] if json_start >= 0 else output
```

## 4. JSON 后有多余文字

用 `raw_decode`，它只消费合法 JSON，忽略后面的内容：
```python
decoder = json.JSONDecoder()
data, _ = decoder.raw_decode(candidate)
```

## 5. 组合处理流程

```python
import json, re

def extract_json(output: str) -> dict:
    text = re.sub(r'(?<=[一-鿿])"(?=[一-鿿])', '“', output)
    text = re.sub(r'(?<=[一-鿿])"(?=[　-〿一-鿿，。！？、；：])', '”', text)
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)

    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON found")

    decoder = json.JSONDecoder()
    try:
        return decoder.raw_decode(text[start:])[0]
    except json.JSONDecodeError:
        from json_repair import repair_json
        return json.loads(repair_json(text[start:]))
```

## 最省事的做法

如果你（agent）本来就在生成这份 JSON，最省事的做法是**自己校验后再落盘**——生成完直接读一遍确认能 `json.loads` 成功，不合法就自己改，不要指望下游脚本帮你兜底。上面的清洗流程是给"生成和解析分离"场景（比如脚本调外部 LLM API）用的。
