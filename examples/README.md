# 原创虚构文字演示

完整多模态体验请先停止VOC，再执行`python examples/import_full_demo.py`，下载并导入两个完整200条视图。需要已安装`app/requirements.txt`中的依赖。详情见`../public-docs/full-demo-package.md`及`full-demo-licenses.md`。以下是无需下载大文件的轻量选项。

执行`python examples/seed_demo.py`后，在工作台选择“开源酒店演示 · 虚构数据”。

- 3家虚构门店、36条原创文字反馈、36个预置事件、3项虚构管理行动。
- 文本与预置分析仅用于交互演示，不是模型生成效果或真实经营结论。
- 不包含真实姓名、联系方式、第三方图片、音频或模型权重。
- 不发送模型请求，不需要API密钥；新增反馈仍需要配置模型才能处理。
- 重复执行只复用现有空间，不覆盖内容。可以用独立`VOC_DATA_DIR`隔离实验。

本目录原创文本和脚本采用仓库的Apache-2.0许可证。
