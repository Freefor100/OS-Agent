# 08_network — Baseline vs Agent

- 题库题数: 7
- baseline `report_quality_score`: 0.91
- agent `report_quality_score`: 0.88

| question_id | type | agreement | better_side(初值) | baseline_se | baseline_sc | agent_se | agent_sc | baseline_value | agent_value |
|---|---|:---|:---|---:|---:|---:|---:|---|---|
| Q08_001 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.95 | 0.95 | not_found | not_found |
| Q08_002 | single_choice | 一致 | tie | 0.90 | 0.85 | 0.95 | 0.85 | 未发现 | 未发现 |
| Q08_003 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.95 | 0.95 | not_found | not_found |
| Q08_004 | short_answer | 表述差异 | 待酌 | 0.90 | 0.90 | 0.50 | 0.70 | not_found: 该 OS 未实现网络子系统，无 sendto 系统调用，无协议栈，无网卡驱动。无法追踪发送路径。 | 未发现 sys_sendto 实现。该内核未实现网络发送路径。poll/select 机制已就绪可用于未来 socket 集成：sys_pselect(kernel/syscall/sysfile.c:761) → pselect(kernel/fs/poll.c:127) → file_poll(kernel/fs/poll.c:58) → fp->poll 回调(如 pipepoll kernel/fs/pipe.c:378) |
| Q08_005 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.95 | 0.95 | not_found | not_found |
| Q08_006 | multi_choice | 一致 | tie | 0.90 | 0.75 | 0.95 | 0.75 | [] | [] |
| Q08_007 | tri_state_impl | 一致 | tie | 0.90 | 1.00 | 0.95 | 0.95 | not_found | not_found |

统计: 一致=6, 表述差异=1, 结论冲突=0
