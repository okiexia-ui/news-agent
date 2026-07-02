# 生成后校验清单

## 黄金原则：别凭感觉说"看起来没问题"

哪怕 `render_and_send.py` 跑完没报错，PDF 也可能有网格错位、文字溢出、占位符漏替换、颜色不对——**每次生成后至少过一遍下面的检查**，不要跳过。

## 1. 生成截图

PDF 转图看：
```bash
pdftoppm -png -r 100 -f 1 -l 1 /tmp/frontier_brief_morning_*.pdf preview
```

或者渲染阶段的 HTML 直接截图（改版面调试时更快，不用等 PDF 导出）：
```bash
npx playwright screenshot file:///tmp/frontier_brief_debug.html preview.png --viewport-size=1200,1600
```

## 2. 肉眼检查

- 占位符是否有遗漏：搜 `__` 开头的字符串，PDF/截图里不该出现任何 `__XXX__` 字面量（出现说明 `render_and_send.py` 里的 `html.replace` 和模板占位符名字没对上）
- 卡片文字是否溢出容器
- 网格是否对齐（Big Picture 应该是 2×2，地缘板块每条应该是 2×2 四象限）
- 概率条 / 情景规划两栏宽度是否一致
- 配色是否符合 `references/design-system.md` 的色板，没有跑出赤陶/森林绿/暗底体系之外的颜色

## 3. 结构性检查（没有视觉能力时的兜底）

如果只能读 DOM/文本，不能看图，用 Playwright 跑一段结构检查脚本：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("file:///tmp/frontier_brief_debug.html")

    checks = page.evaluate("""
    () => {
      const out = [];
      const bp = document.querySelectorAll('.bp-card').length;
      out.push(`Big Picture cards: ${bp}/4`);

      const ci = document.querySelectorAll('.cross-item').length;
      out.push(`Cross-signal items: ${ci}`);

      const g4 = document.querySelectorAll('.geo-4-item').length;
      out.push(`Geo 4-column items: ${g4} (expect multiple of 4)`);

      const overflow = [...document.querySelectorAll('.nc, .geo, .cross, .bp-card, .mkt-item')]
        .filter(el => el.getBoundingClientRect().right > window.innerWidth + 5).length;
      out.push(`Overflow count: ${overflow} (expect 0)`);

      const remaining = document.body.innerText.match(/__[A-Z_]+__/g);
      out.push(`Unreplaced placeholders: ${remaining ? remaining.join(', ') : 'none'}`);

      return out.join('\\n');
    }
    """)
    print(checks)
    browser.close()
```

`Unreplaced placeholders` 那一行是最值得盯的——非 `none` 就说明 schema 字段名或模板占位符对不上，回去比对 `references/design-system.md` 的占位符列表。

## 4. 常见问题修法

- **卡片文字溢出**：调小字号，或加 `overflow:hidden;text-overflow:ellipsis`
- **网格错位**：检查 `grid-template-columns`，确认没有子元素自带冲突宽度
- **分页从卡片中间断开**：给对应 block 加 `page-break-inside:avoid;break-inside:avoid`
- **颜色不一致**：搜有没有游离于 CSS 变量之外的硬编码色值（`#fff`、`#1a1a1a` 这类），改用 `var(--xxx)`
