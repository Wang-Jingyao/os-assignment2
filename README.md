# Assignment 2：Spawn

在 `ans.rs` 中实现 `spawn` 系统调用和 `do_spawn`。题目见 [作业要求](docs/assignment.md)。

## 开始做题

本作业使用 Linux。请先按 [环境与自测说明](docs/testing.md) 检查工具版本，然后在项目目录运行：

```bash
./scripts/prepare.sh
# 编辑 ans.rs
./scripts/selftest.sh
```

起始答案尚未完成，自测得到 0 分是正常的。自测结束后会列出各项得分，总分为 100 分；详细结果和日志保存在 `target/`。

## 提交

只提交 `ans.rs`。需要压缩包时，在项目目录运行：

```bash
zip submission.zip ans.rs
```

自测会将 `ans.rs` 复制到 `src/syscall/spawn.rs`。请直接编辑根目录的 `ans.rs`，以免修改被覆盖。

## 文件位置

| 位置 | 内容 |
|---|---|
| `ans.rs` | 需要完成的答案 |
| `docs/` | 作业要求、环境与自测说明 |
| `scripts/` | 准备和自测入口 |
| `src/` | 内核代码及 Rust 测试 |
| `user/` | 用户程序及测试程序 |
| `grader/` | 公开评分代码、资源限制和文件校验清单 |

后端在 Linux 容器中运行，使用包内同一套测试。
