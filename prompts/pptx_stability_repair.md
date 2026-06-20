# PPTX 稳定性修复

你会收到 SVG/PPTX 导出问题。

修复原则：
- 保持可编辑优先。
- 避免 PPTX 不稳定或不支持的 SVG 特性。
- 使用 rect、circle、ellipse、line、polyline、polygon、简单 path、text、tspan、g。
- 不使用 unsupported feature。

输出新的 `expert_response.json`。
