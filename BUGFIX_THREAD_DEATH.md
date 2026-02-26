# 运行超过一天后无法收到推送问题修复报告

## 问题描述
运行时间超过一天后，应用无法收到推送通知，且控制台无任何输出。

## 根本原因分析

### 1. 线程静默死亡 🔴 严重
**问题：** 文件跟踪线程在遇到异常时会静默退出，没有任何日志记录

**位置：** `journal_watcher.py:219-305`

**原因：**
- 内层循环（275-295行）中的 `_publish_line()` 如果抛出异常，会导致整个线程退出
- 没有 try-catch 包裹整个线程逻辑
- 线程退出时没有日志记录

**影响：**
- 线程死亡后不再处理日志
- 用户看不到任何错误信息
- 心跳监控无法及时发现（只在心跳超时时检查）

### 2. 文件句柄泄漏 🔴 严重
**问题：** 打开的文件句柄可能不会被正确关闭

**位置：** `journal_watcher.py:244-295`

**原因：**
- `with open()` 在外层循环
- 内层循环中的异常可能导致文件未正确关闭
- 长时间运行后文件句柄耗尽

**影响：**
- 系统文件句柄耗尽
- 无法打开新文件
- 线程卡死或退出

### 3. 心跳监控失效 🟡 中等
**问题：** 文件模式下心跳监控不够主动

**位置：** `journal_watcher.py:1579-1719`

**原因：**
- 文件模式下只检查线程是否存活
- 不检查线程是否卡住
- 不检查队列状态

**影响：**
- 线程卡住时无法及时发现
- 队列满时无告警
- 问题发现延迟

### 4. 缺少健康检查 🟡 中等
**问题：** 没有定期健康检查机制

**原因：**
- 只依赖心跳监控（被动）
- 没有主动检查线程状态
- 没有定期输出统计信息

**影响：**
- 问题发现延迟
- 难以排查故障
- 缺少可观测性

---

## 修复方案

### 修复 1: 线程异常保护 ✅

**修改：** 添加多层异常捕获

```python
def _follow_file(self, path: str):
    """持续读取文件新增内容"""
    self.logger.info(f"文件跟踪线程启动: {path}")

    try:
        while self.running and not self.file_stop_event.is_set():
            try:
                # 外层异常捕获：文件操作异常
                with open(path, 'r', encoding='utf-8', errors='replace') as logfile:
                    while self.running and not self.file_stop_event.is_set():
                        try:
                            # 内层异常捕获：单行处理异常
                            line = logfile.readline()
                            # ... 处理逻辑
                            self._publish_line(line)
                        except Exception as exc:
                            # 单行处理失败，记录错误但继续处理下一行
                            self.logger.error(f"处理日志行时出错 {path}: {exc}", exc_info=True)
                            self.stats['errors'] += 1
                            # 继续处理下一行，不退出线程
            except FileNotFoundError:
                # 文件不存在，等待重试
                pass
            except Exception as exc:
                # 其他异常，记录并重试
                self.logger.error(f"读取日志文件 {path} 时出错: {exc}", exc_info=True)
    except Exception as exc:
        # 最外层异常捕获：线程级别异常
        self.logger.error(f"文件跟踪线程异常退出 {path}: {exc}", exc_info=True)
    finally:
        # 线程退出时记录日志
        self.logger.warning(f"文件跟踪线程已退出: {path}")
```

**效果：**
- ✅ 单行处理失败不会导致线程退出
- ✅ 所有异常都有日志记录
- ✅ 线程退出时有明确日志

---

### 修复 2: 增强心跳监控 ✅

**修改：** 文件模式下更主动的监控

```python
def _heartbeat_monitor(self):
    while self.running:
        time.sleep(self.heartbeat_interval)

        idle_duration = time.time() - self.last_heartbeat
        threshold = self.heartbeat_interval * (3 if self.log_mode == "file" else 2)

        if idle_duration > threshold:
            if self.log_mode == "file":
                self.logger.warning(f"文件模式心跳超时（{idle_duration:.0f}秒无活动），检查线程状态")

                # 检查死亡线程
                dead_threads = []
                for path, thread in list(self.file_followers.items()):
                    if not thread.is_alive():
                        dead_threads.append(path)

                if dead_threads:
                    self.logger.error(f"发现 {len(dead_threads)} 个死亡线程: {dead_threads}")
                    # 重启死亡线程
                    for path in dead_threads:
                        self.logger.warning(f"重启死亡线程: {path}")
                        del self.file_followers[path]
                        self._start_file_follower(path)
                else:
                    # 所有线程存活但无输出
                    self.logger.info(f"所有跟踪线程存活，但 {idle_duration:.0f}秒无日志输出")

                    # 检查队列状态
                    queue_size = self.line_queue.qsize()
                    if queue_size > 0:
                        self.logger.warning(f"队列中有 {queue_size} 条待处理日志，可能处理线程卡住")

                    # 探测是否有新日志
                    if self._probe_log_source_for_new_content():
                        self.logger.info("探测到新日志内容，更新心跳")
                    else:
                        self.logger.debug("未探测到新日志内容，可能日志文件确实无更新")

                # 更新心跳，避免频繁告警
                self.last_heartbeat = time.time()
                continue
```

**效果：**
- ✅ 主动检测死亡线程并重启
- ✅ 检查队列状态
- ✅ 更详细的日志输出
- ✅ 避免频繁告警

---

### 修复 3: 添加健康检查线程 ✅

**修改：** 新增独立的健康检查线程

```python
def _health_check_monitor(self):
    """健康检查监控线程（每分钟检查一次）"""
    self.logger.info("健康检查线程启动（间隔: 60秒）")

    while self.running:
        time.sleep(60)  # 每分钟检查一次

        if not self.running:
            break

        try:
            # 检查文件跟踪线程状态
            self._ensure_file_followers_alive()

            # 检查队列状态
            queue_size = self.line_queue.qsize()
            if queue_size > 8000:  # 80% 阈值
                self.logger.warning(f"队列接近满载: {queue_size}/10000")

            # 输出统计信息
            stats = self.get_stats()
            self.logger.debug(
                f"健康检查 - 队列: {stats['queue_size']}, "
                f"活跃线程: {stats['active_file_followers']}, "
                f"已处理: {stats['entries_read']}, "
                f"错误: {stats['errors']}, "
                f"丢弃: {stats['dropped_lines']}"
            )
        except Exception as e:
            self.logger.error(f"健康检查失败: {e}", exc_info=True)
```

**启动：**
```python
# 在 start() 方法中
if self.log_mode == "file":
    self.health_check_thread = threading.Thread(
        target=self._health_check_monitor,
        name="HealthCheckMonitor",
        daemon=True
    )
    self.health_check_thread.start()
```

**效果：**
- ✅ 每分钟主动检查线程状态
- ✅ 监控队列深度
- ✅ 定期输出统计信息
- ✅ 提高可观测性

---

### 修复 4: 增强线程重启逻辑 ✅

**修改：** 更健壮的线程重启

```python
def _ensure_file_followers_alive(self):
    """确保文件跟踪线程保持运行"""
    if not self.file_followers:
        return

    dead_count = 0
    for path, thread in list(self.file_followers.items()):
        if thread.is_alive():
            continue

        dead_count += 1
        self.logger.error(f"文件跟踪线程已死亡: {path}，准备重启")
        del self.file_followers[path]

        try:
            self._start_file_follower(path)
            self.logger.info(f"文件跟踪线程重启成功: {path}")
        except Exception as e:
            self.logger.error(f"重启文件跟踪线程失败 {path}: {e}", exc_info=True)

    if dead_count > 0:
        self.logger.warning(f"共重启了 {dead_count} 个死亡线程")
```

**效果：**
- ✅ 重启失败有日志记录
- ✅ 统计重启数量
- ✅ 更详细的错误信息

---

## 修复效果

### 可靠性提升
- ✅ 线程异常不会导致静默死亡
- ✅ 死亡线程会被自动重启
- ✅ 所有异常都有日志记录

### 可观测性提升
- ✅ 线程启动/退出有日志
- ✅ 每分钟输出健康检查信息
- ✅ 队列状态监控
- ✅ 详细的错误日志

### 自愈能力
- ✅ 心跳监控主动检测并重启死亡线程
- ✅ 健康检查线程定期检查
- ✅ 双重保障机制

---

## 测试建议

### 1. 长时间运行测试
```bash
# 运行 48 小时
docker-compose up -d
sleep 172800
docker-compose logs --tail=100
```

**验证：**
- 应用持续运行
- 能收到推送通知
- 日志中有健康检查信息

### 2. 异常注入测试
```bash
# 模拟文件删除
rm /var/log/syslog

# 模拟文件权限问题
chmod 000 /var/log/syslog

# 模拟文件轮转
logrotate -f /etc/logrotate.conf
```

**验证：**
- 线程不会死亡
- 有错误日志
- 自动恢复

### 3. 监控日志
```bash
# 查看健康检查日志
docker-compose logs | grep "健康检查"

# 查看线程状态
docker-compose logs | grep "线程"

# 查看错误日志
docker-compose logs | grep "ERROR"
```

---

## 监控指标

### 关键日志
```
# 正常运行
健康检查 - 队列: 0, 活跃线程: 8, 已处理: 12345, 错误: 0, 丢弃: 0

# 线程死亡
文件跟踪线程已死亡: /var/log/syslog，准备重启
文件跟踪线程重启成功: /var/log/syslog

# 队列告警
队列接近满载: 8500/10000

# 心跳超时
文件模式心跳超时（540秒无活动），检查线程状态
```

### 告警规则
```python
# 建议的告警阈值
if stats['errors'] > 100:  # 错误过多
    alert("错误数量异常")

if stats['dropped_lines'] > 0:  # 有日志丢弃
    alert("日志队列满，有丢弃")

if stats['active_file_followers'] < expected:  # 线程数不足
    alert("文件跟踪线程数量异常")

if queue_size > 8000:  # 队列接近满
    alert("日志处理队列接近满载")
```

---

## 总结

### 修复的问题
1. ✅ 线程静默死亡 → 多层异常捕获 + 退出日志
2. ✅ 文件句柄泄漏 → 异常保护确保文件正确关闭
3. ✅ 心跳监控失效 → 增强监控逻辑
4. ✅ 缺少健康检查 → 新增健康检查线程

### 新增功能
1. ✅ 健康检查线程（每分钟）
2. ✅ 增强的心跳监控
3. ✅ 自动重启死亡线程
4. ✅ 队列状态监控

### 预期效果
- **可靠性**：线程不会静默死亡，死亡后自动重启
- **可观测性**：详细的日志输出，便于排查问题
- **自愈能力**：自动检测并修复问题

---

**修复日期：** 2026-02-09
**修复状态：** ✅ 完成
**测试状态：** 待测试
