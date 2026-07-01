# 高质量专家结构分析

你要先理解原图结构，再输出 `element_analysis.json`。

原则：
- 原图结构优先，不从候选框出发机械修补。
- 可读文字、模块框、箭头、区域标签、底部说明卡片优先保持可编辑。
- `svg_self_draw` 用于文字、箭头、面板、表格、简单几何和技术图结构。
- `crop` 只用于照片、截图、纹理、复杂热图等不适合矢量重绘的区域。
- `crop_nobg` 用于可分离前景对象，尤其是图标、logo、徽标、按钮、头像、app/document glyph 和复杂小符号。

输出必须符合 `happyfigure.edit.element_analysis.v1`。

## 截图 / 抠图判定表

每个元素三选一：

| 元素 | asset_strategy | 说明 |
| --- | --- | --- |
| 文字、标题、框、面板、表格、坐标轴、箭头、简单几何 | svg_self_draw | 用 SVG 重绘，保持可编辑 |
| 图标、logo、徽标、按钮、头像、app/document glyph、复杂小符号等可分离前景 | crop_nobg | 抠背景，bbox 只包对象本身 |
| 照片、截图、热图、显微图、纹理、复杂 3D 渲染、统计图/函数图等密集位图 | crop | 整块裁切保背景 |

判定顺序：
- 能矢量忠实重绘的优先 `svg_self_draw`。
- 重绘会失真但前景可分离的用 `crop_nobg`，bbox 只包对象本身，不要把外层卡片背景框进来。
- 保真优先且背景要保留的用 `crop`。
- 不要把应当 `crop_nobg` 的图标、logo、徽标、头像、复杂小符号“简化成可编辑线条”；不要把它们藏在大面板的 `svg_self_draw` 元素里。
- `crop`/`crop_nobg` 元素在 SVG 里引用 `assets/<box_id>.png`，运行器会在校验前按 bbox 自动裁切；`crop_nobg` 会输出透明 PNG。
- 超过画布 75% 面积的整图不要当作单个 `crop`，应继续拆解结构。
