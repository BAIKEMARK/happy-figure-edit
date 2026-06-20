# 高质量专家结构分析

你要先理解原图结构，再输出 `element_analysis.json`。

原则：
- 原图结构优先，不从候选框出发机械修补。
- 可读文字、模块框、箭头、区域标签、底部说明卡片优先保持可编辑。
- `svg_self_draw` 用于文字、箭头、面板、表格、简单几何和技术图结构。
- `crop` 只用于照片、截图、纹理、复杂热图等不适合矢量重绘的区域。
- `crop_nobg` 只用于可分离前景对象。

输出必须符合 `happyfigure.edit.element_analysis.v1`。

## 截图 / 抠图判定表

逐个元素按下表选 `asset_strategy`，先判前景可分离性，再判矢量可重绘性：

| 元素 | asset_strategy | 说明 |
| --- | --- | --- |
| 文字、标题、标签 | svg_self_draw | 保持可编辑 `<text>`/`<tspan>` |
| 矩形框、面板、容器、表格、坐标轴 | svg_self_draw | SVG primitive 重绘 |
| 箭头、连接线、简单几何 | svg_self_draw | 用 path/line 重绘，不截图 |
| 图标、logo、徽标、按钮、头像、表情、复杂小符号 | crop_nobg | 可分离前景，抠掉背景后叠在重绘背景上 |
| 照片、截图、热图、显微图、密集纹理、复杂 3D 渲染、统计图/函数图 | crop | 保留背景的整块位图，矢量重绘会明显失真 |

判定要点：
- 能用 SVG primitive 忠实重绘的，一律 `svg_self_draw`，不要截图。
- 重绘会明显变丑或不准、但前景能从背景分离的小对象 → `crop_nobg`，bbox 只包住对象本身，不要把外层卡片背景框进来。
- 不要把复杂图标、logo、徽标、头像、复杂小符号“简化成可编辑线条”来替代原图保真；这类对象应优先 `crop_nobg`。
- 保真比可编辑更重要、且背景应随对象一起保留的密集位图 → `crop`。
- `crop`/`crop_nobg` 元素在 SVG 里引用 `assets/<box_id>.png`，运行器会在校验前按 bbox 自动裁切；`crop_nobg` 会输出透明 PNG。
- 超过画布 75% 面积的整图不要当作单个 `crop`，应继续拆解结构。
