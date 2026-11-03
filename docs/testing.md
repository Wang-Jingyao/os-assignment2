# 环境与自测

## 环境

后端使用 Ubuntu 24.04 ARM64 容器，在 QEMU 中运行 RISC-V64 内核。学生自测也应使用 Linux；本包不提供原生 macOS 支持。

| 工具 | 后端版本或要求 |
|---|---|
| Python | 3.10 及以上 |
| Rust | `nightly-2025-02-01` |
| Rust 组件 | `rust-src`、`rustc-dev`、`llvm-tools-preview` |
| cargo-osdk | 0.16.1 |
| addr2line | 0.24.1，启用 `bin` feature |
| RISC-V Linux GCC | 13.3.0，含 `riscv64-linux-gnu-gcc` 和 `riscv64-linux-gnu-nm` |
| QEMU | 8.2.2，含 `qemu-system-riscv64` |
| 其他 | GNU make、Linux `/proc`、Unix domain socket |

如尚未安装 OSDK 和 addr2line，在项目目录运行：

```bash
cargo install cargo-osdk --version 0.16.1 --locked
cargo install addr2line --version 0.24.1 --locked --features bin
```

`rust-toolchain.toml` 指定 Rust 版本及组件，`Cargo.lock` 固定库依赖。`scripts/prepare.sh` 下载项目依赖并编译用户程序，不负责安装系统工具。准备阶段需要联网；后端评分时关闭网络。

## 自测命令

在项目目录运行：

```bash
./scripts/prepare.sh
./scripts/selftest.sh
```

只测一项时可加 `--question`，例如：

```bash
./scripts/selftest.sh --question correctness
```

可选项为 `correctness`、`performance`、`analysis_fork`、`analysis_spawn`、`analysis_discard`。

终端显示分项成绩；`target/grades.json` 保存各项 `score`、`max_score`、失败原因 `reason` 及总分。单项运行时，总分只包含该项。满分退出码为 0，有分项未通过为 1，参数错误为 2。编译和运行日志也在 `target/`，排错时先查看对应日志。

正确性、性能各自全过才得分；分析三项按 5、5、10 分独立判断。编译失败、崩溃、超时或测试未完成时，对应项为 0。

## 测试文件

| 文件 | 检查内容 |
|---|---|
| `user/spawn_template.c`、`user/spawn_test.c` | 创建子进程、PID、wait 和退出值 |
| `src/process/audit.rs` | 子进程真实运行、初始上下文及地址空间、退出和回收 |
| `src/lib.rs` | 性能测试及比例断言 |
| `src/spawn_analysis.rs` | 三组内存复制实验与 `analyze_spawn` |
| `grader/grade.py` | 输出解析、得分条件及分值 |
| `grader/qemu_evidence.py` | 从 QEMU 读取执行检查点和测量值 |

后端只替换 `ans.rs`，其余计分代码与本包一致，没有另加隐藏计分测试。

正确性测试要求创建和回收的 PID 均为 2 至 11；10 个子进程的初始上下文与完整地址空间须匹配 `spawn_test`，并实际从用户态以 100 退出。最后只剩父进程，由它以 0 退出。QEMU 检查点读取的创建、启动、退出、回收数量均须为 10。

内存实验在 `0x20_0000_0000` 增加 `[1,5,13]` 页。只统计 `MemorySpace::duplicate` 中复制父映射的字节，不统计加载 ELF、初始化新栈等操作。每次操作重置计数；每组结束后回收实验进程，并核对进程表恢复。丢弃量根据复制时记录的地址空间来源与 `exec` 清理记录核对。

性能和分析实验也必须到达实际执行检查点。评分脚本通过 QEMU 调试接口读取数据，再与日志核对；不需要安装 GDB。单独打印通过信息或提前退出 QEMU不能代替测试完成。

## 分析输出

框架输出一行 `A2_ANALYSIS {JSON}`，只含三个字段：

| 字段 | 类型及含义 |
|---|---|
| `fork_copy_bytes_per_added_page` | u64，fork 每增加一页的复制字节数 |
| `spawn_copy_bytes_per_added_page` | u64，spawn 每增加一页的复制字节数 |
| `discarded_parent_copy_bytes` | 三个 u64，依次对应 1、5、13 页样本的丢弃字节数 |

`A2_EVIDENCE` 记录原始样本，`A2_ANALYSIS_COMPLETE` 表示实验结束。数值以字节为单位，不接受负数、浮点数或布尔值。字段、样本数或输出次数不符，带颜色转义码，页数不递增，差值不整除，或者与 QEMU 读取值不一致，都判失败。解析规则见 `grader/grade.py`。

## 资源限制

每个计分项限时 300 秒，包含准备和编译；输出上限为 2 MiB。后端每项单独运行，分析三项分别执行完整实验。本地全测只执行一次分析实验并给出三项成绩。

容器限 2 CPU、6 GiB 内存、无额外 swap、128 个进程、1024 个文件描述符；单文件限 256 MiB，工作目录限 4 GiB，临时目录限 128 MiB。具体参数见 `grader/limits.json`。容器使用非 root 用户、只读根文件系统和关闭的网络。超时或超限时该项为 0；容器无法启动属于评分环境异常，应重试。

性能成绩受硬件和负载影响。在不同机器上通过一次性能测试，不能保证后端取得同样结果。

## 核对测试文件

如需确认框架文件未被修改：

```bash
python3 grader/verify_manifest.py
```

`grader/manifest.json` 保存文件校验值，排除答案、生成文件及清单本身。`src/progs/progs.rs` 由 Makefile 按文件名顺序生成；`user/spawn.c` 由模板填入当次 token。token 用于核对运行日志，不是秘密凭据。

评分脚本的解析器测试可单独运行，不计入作业成绩：

```bash
python3 -m unittest discover -s grader -p 'test_*.py'
```
