# 身份与命名

用户人工维护 `config/works.yaml` 和 canonical clone 目录。

Agent 在正文中只能使用 `display_name`。`T2026...-282` 这类机器 repo id、裸数字 fork 后缀、旧 clone 目录名禁止进入公开正文。

如果缺少 `work_name` 或 `canonical_dir`，停在身份校验阶段，不进入后续评审。
