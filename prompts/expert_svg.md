# 高质量专家 SVG 生成

你要根据原图和 `element_analysis.json` 输出 `output.svg`。

硬规则：
- SVG 根节点必须使用原图尺寸的 `viewBox`、`width`、`height`。
- 主要文字必须尽量保持为可编辑 `<text>` / `<tspan>`。
- 模块框、箭头、面板、标签和简单符号必须尽量使用 SVG primitive。
- 只允许使用证据包明确允许的本地 assets 路径。
- 禁止外部 URL、绝对路径、`file://`、base64、`<style>`、filter、mask、clipPath、foreignObject、textPath、symbol、use。

目标是生成可继续导出 PPTX 的 SVG，而不是生成只在浏览器里好看的 SVG。
