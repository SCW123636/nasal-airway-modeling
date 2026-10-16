# -*- coding: utf-8 -*-
"""stdmodel —— nasal-cfd 标准模型（v0.1）可复现架构。

设计依据：plan/有依据的标准模型_设计_v1.md
- 四层证据 E0 队列事实 / E1 文献锚点 / E2 文献关联 / E3 操作化假设
- 三类声明 C-a 队列事实 / C-b 锚点偏离 / C-c 文献迁移假说（句子模板化）
- 七条依据判据 B1-B7（数字三件套 / 已知答案 CI / 分层显式 / 预注册 /
  可失败性 / 反例纳入 / 诚实性口径）

本包只做「装配与判据」，不重算生产链产物：几何特征读 T-059 批跑的
surface/opening 产物 + measure_mca 输出；CFD 特征读 T-058 已验证
metrics/wss JSON。每个特征行带口径六元组 + 输入指纹，行级可追。
"""

SCHEMA_VERSION = "stdmodel_feature_schema/v1"
MODEL_VERSION = "stdmodel/v0.1"
CLINICAL_STATUS = "generalisation_test_only_no_human_review"
