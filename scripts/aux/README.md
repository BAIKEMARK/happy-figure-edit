# 支线脚本（aux）

这里存放非主线脚本，便于保持主线清晰。主线只有一个入口：
`scripts/run_expert_mvp.py`（生成证据包 → agent 看图写 `expert_response.json` → `apply-response`）。

本目录脚本仅用于测试基准、批量冒烟和路线对比，不参与每张图的正式重建流程：

- `make_transformer_fixture.py`：当年针对 attention 图写死坐标的回归基准夹具，只对那张
  2752x1536 的图有效，无法泛化。保留它仅作为质量上限的回归对照。
- `smoke_media_dir.py`：对一个目录里的多张图批量跑主线，验证产物链路是否正常。
- `compare_quality_expert_routes.py`：把 fixture / 专家路线 /（可选）DrawAI 参考的 run 目录
  汇总成对比报告。

这些脚本通过相对路径调用主线脚本（`../run_expert_mvp.py`）。移动它们时请同步更新引用。
