# Migration SQL

这个目录只放数据库 schema migration 所需的 SQL。

当前约定：

- 按文件名字典序执行
- 一个文件只允许一条 SQL 语句
- 每个文件是一个独立 migration 单元
- 业务侧的 `SELECT` / `INSERT` / `UPDATE` / `DELETE` 按职责分散在 `knowledge_base/stores/` 下的各个 store 中

这样做的目标是：

- 让 schema 变更更容易阅读和 review
- 让 schema migration 与业务 store 职责分离
- 保持当前项目的轻量级 migration 方式，不强行引入完整 migration 框架
