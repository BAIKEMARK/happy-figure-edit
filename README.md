# Happy Figure Edit

把位图里的流程图、科研图、截图式图表重建成可编辑的 `SVG` 和 `PPTX`。

这个仓库是一个 Codex Skill。它的核心思路不是直接把整张图截图塞进 PPT，而是让 agent 先读图、拆元素，再把文字、框线、箭头、面板、表格等可编辑部分重绘成 SVG；照片、热图、复杂图标、logo 等不适合矢量重绘的区域会按规则裁切成局部图片资产。

## 适合做什么

- 把论文图、流程图、系统架构图、AI 生成的信息图转成可继续编辑的 SVG/PPTX。
- 保留原图布局、文字、箭头、区域框和视觉层级。
- 对复杂小图标、logo、头像等使用 `crop_nobg` 抠背景，避免错误地简化成线条图。
- 对照片、截图、热图、纹理、3D 渲染、统计图等密集位图使用 `crop`，保留原始视觉细节。

不适合直接当作通用 OCR、自动排版软件或纯命令行“一键完美重绘”工具。高质量结果依赖 Codex agent 对原图的视觉判断和迭代修正。

## 安装

先选择一种安装位置。

作为 Codex Skill 使用时，建议直接放到 skills 目录:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/BAIKEMARK/happy-figure-edit.git ~/.agents/skills/happy-figure-edit
cd ~/.agents/skills/happy-figure-edit
```

如果只是普通开发或调试，也可以放在项目目录:

```bash
git clone https://github.com/BAIKEMARK/happy-figure-edit.git
cd happy-figure-edit
```

第一次使用需要创建虚拟环境并安装依赖:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
brew install resvg
```

`resvg` 用于生成 SVG 渲染图和视觉差异报告。如果没有安装 `resvg`，仍然可以生成 `output.svg` 和 `output.pptx`，只是 `quality_report.json` 里的像素差异会标记为不可用。

## 在 Codex 里怎么用

给 Codex 一张图，并明确调用这个 skill:

```text
使用 happy-figure-edit skill，把 /path/to/input.png 重建成可编辑 SVG 和 PPTX。
```

Codex 会按 `SKILL.md` 的流程执行:

1. 读取原图和画布尺寸。
2. 运行脚本生成运行目录、基础证据和保守兜底产物。
3. 由 agent 目视拆解图中元素，写入 `expert_response.json`。
4. 用脚本校验 JSON、生成 `output.svg`、裁剪资产和视觉差异报告。
5. 查看 `rendered.png`、`diff.png`、`quality_report.json`，反复修正坐标、字号、颜色和元素拆分。
6. SVG 确认可接受后，再用 `package-run` 生成最终 `output.pptx` 和交付目录。

## 手动运行流程

下面所有命令都在 skill 根目录执行，也就是包含 `SKILL.md` 的目录。不要 `cd`
到 `outputs/*_work` 后再用相对路径试命令；正常使用时也不需要阅读 `scripts/`
或 `_vendor/` 源码，除非是在调试 skill 本身。

准备一张图的运行目录:

```bash
.venv/bin/python scripts/run_expert_mvp.py \
  --image /path/to/input.png \
  --out-dir outputs/example_work
```

默认把所有运行产物放在 skill 目录内的 `outputs/` 下：`outputs/<image-stem>_work`
作为工作目录，`outputs/<image-stem>` 作为交付目录。除非用户明确指定，不要写到
`/tmp`、`~/Documents` 或调用方当前目录。

这一步会生成:

- `outputs/example_work/evidence.json`: 原图尺寸和基础证据。
- `outputs/example_work/element_overlay.png`: 初始占位叠加图，通常只有整图 fallback 框；不要用它做元素拆解。
- `outputs/example_work/element_analysis.json`: 保守的元素分析。
- `outputs/example_work/output.svg`: 保守兜底 SVG。

然后由 agent 根据原图和 prompts 手写:

```text
outputs/example_work/expert_response.json
```

如果用临时 Python 脚本辅助生成 `expert_response.json`，把脚本放在
`outputs/example_work/` 下，但仍然从 skill 根目录执行:

```bash
.venv/bin/python outputs/example_work/build_expert_response.py
```

应用 expert response:

```bash
.venv/bin/python scripts/run_expert_mvp.py apply-response \
  --run-dir outputs/example_work \
  --response outputs/example_work/expert_response.json
```

成功后重点看这些文件:

- `outputs/example_work/output.svg`: 可编辑 SVG。
- `outputs/example_work/element_overlay.png`: 元素框叠加图。
- `outputs/example_work/report.html`: 便于浏览的结果报告。
- `outputs/example_work/rendered.png`: SVG 渲染结果。
- `outputs/example_work/diff.png`: 原图与渲染图的差异。
- `outputs/example_work/quality_summary.txt`: 优先阅读的短质量摘要。
- `outputs/example_work/quality_report.json`: 差异指标和质量检查结果。
- `outputs/example_work/review_tiles/*.png`: 局部原图 / 渲染 / diff 三联图，用于检查大 zone 内部问题。
- `outputs/example_work/assets/*.png`: `crop` / `crop_nobg` 生成的局部图片资产。

`report.html` 使用相对路径引用 `output.svg`、`element_overlay.png`、`rendered.png`、`diff.png`、`review_tiles/` 和 `assets/`。交付目录默认只保留这些 canonical 文件，避免为同一份 `SVG` / `PPTX` 额外生成重复副本。

推荐使用内置打包命令生成交付目录:

```bash
.venv/bin/python scripts/run_expert_mvp.py package-run \
  --run-dir outputs/example_work \
  --out-dir outputs/example
```

这会复制 `report.html` 依赖的 canonical 文件，例如 `output.svg` / `output.pptx`，不会额外生成内容相同的改名副本。

## 元素策略

每个元素只能选择一种策略:

| 策略 | 用途 |
| --- | --- |
| `svg_self_draw` | 文字、标题、框、面板、表格、坐标轴、箭头、简单几何；用 SVG 重绘，保持可编辑 |
| `crop_nobg` | 图标、logo、徽标、按钮、头像、app/document glyph、复杂小符号等可分离前景；抠背景，bbox 只包对象本身 |
| `crop` | 照片、截图、热图、纹理、3D 渲染、统计图等密集位图；整块裁切保背景 |

判定顺序:

1. 能用 SVG 忠实重绘的，优先 `svg_self_draw`。
2. 重绘会失真但前景可分离的用 `crop_nobg`，bbox 只包对象本身。
3. 保真优先且背景需要保留的，使用 `crop`。
4. 不要把这些前景对象简化成可编辑线条，也不要把它们藏在大面板的 `svg_self_draw` 元素里。
5. 超过画布 75% 面积的区域不要直接当成一个大 `crop`，应该继续拆成更小的元素。

## 目录结构

```text
.
├── SKILL.md                 # Codex Skill 主说明
├── requirements.txt         # Python 依赖
├── assets/
│   └── report_template.html # 报告模板
├── scripts/
│   └── run_expert_mvp.py    # 主入口: 准备运行目录 / 应用 expert response / 打包交付
├── prompts/                 # expert_response 和 SVG 规则提示
└── _vendor/                 # 内置 SVG 到 PPTX 转换器
```

## 校验

校验 skill 基本格式:

```bash
.venv/bin/python /path/to/skill-creator/scripts/quick_validate.py .
```

## 当前限制

- 没有绑定外部视觉模型 API；高质量重建由 Codex agent 读图后生成 `expert_response.json`。
- OCR 和坐标判断需要人工式迭代，复杂图可能需要多轮修正。
