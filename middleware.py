"""
Middleware Manager — 中间件自动发现与管理

支持四通道检测：
  1. systemd — 通过 systemctl 发现已注册的服务
  2. process  — 通过 ps + /proc 扫描运行中的进程
  3. port     — 通过 ss 扫描监听端口
  4. filesystem — 通过已知路径扫描已安装但未运行的中间件

对外接口：
  list_middleware(search, category)  — 列出所有检测到的中间件
  get_middleware(key)                — 获取单个中间件详情
  start_middleware(key) / stop / restart — 管理操作
  get_middleware_summary()           — 统计摘要
"""

import os
import re
import glob
import signal
import subprocess
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import service_manager as sm

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════════════

class MiddlewareStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class ManagementMethod(Enum):
    SYSTEMD = "systemd"
    SCRIPT = "script"
    PROCESS = "process"
    UNMANAGED = "unmanaged"


class MiddlewareCategory(Enum):
    DATABASE = "database"
    CACHE = "cache"
    WEB_SERVER = "web-server"
    MESSAGE_QUEUE = "message-queue"
    SEARCH = "search"
    CONTAINER = "container"
    AUTOMATION = "automation"
    MONITORING = "monitoring"
    STORAGE = "storage"
    REGISTRY = "registry"


@dataclass
class MiddlewareSignature:
    """中间件的已知特征目录条目"""
    key: str                          # 唯一标识, e.g. "postgresql"
    display_name: str                 # 显示名, e.g. "PostgreSQL"
    category: MiddlewareCategory
    process_names: list = field(default_factory=list)        # ps COMMAND 匹配
    java_cmdline_patterns: list = field(default_factory=list) # Java 进程 cmdline 匹配
    default_ports: list = field(default_factory=list)        # 默认监听端口
    known_paths: list = field(default_factory=list)          # 安装目录 glob
    binary_paths: list = field(default_factory=list)         # 二进制文件路径
    systemd_services: list = field(default_factory=list)     # systemd 服务名
    version_cmd: list = field(default_factory=list)          # 获取版本的命令
    version_regex: str = r"(\d+\.\d+(?:\.\d+)?)"            # 版本号正则
    version_from_path: bool = True                            # 是否从路径提取版本
    start_cmd: Optional[str] = None                           # 启动命令 (script 方法)
    stop_cmd: Optional[str] = None                            # 停止命令 (script 方法)
    status_cmd: Optional[str] = None                          # 状态检查命令
    work_dir: Optional[str] = None                            # 启动工作目录
    sub_components: list = field(default_factory=list)         # 子组件名称


@dataclass
class MiddlewareInfo:
    """单个中间件的运行时信息"""
    key: str
    display_name: str
    category: str = ""
    status: MiddlewareStatus = MiddlewareStatus.UNKNOWN
    version: Optional[str] = None
    pid: Optional[int] = None
    pids: list = field(default_factory=list)
    port: Optional[int] = None
    ports: list = field(default_factory=list)
    install_path: Optional[str] = None
    config_path: Optional[str] = None
    systemd_service: Optional[str] = None
    management: ManagementMethod = ManagementMethod.UNMANAGED
    start_command: Optional[str] = None
    stop_command: Optional[str] = None
    status_command: Optional[str] = None
    work_dir: Optional[str] = None
    detection_source: str = ""
    sub_components: list = field(default_factory=list)
    extra_info: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "category": self.category,
            "status": self.status.value,
            "version": self.version,
            "pid": self.pid,
            "pids": self.pids,
            "port": self.port,
            "ports": self.ports,
            "install_path": self.install_path,
            "config_path": self.config_path,
            "systemd_service": self.systemd_service,
            "management": self.management.value,
            "start_command": self.start_command,
            "stop_command": self.stop_command,
            "status_command": self.status_command,
            "work_dir": self.work_dir,
            "detection_source": self.detection_source,
            "sub_components": self.sub_components,
            "extra_info": self.extra_info,
        }


# ═══════════════════════════════════════════════════════════════════════
# 中间件目录
# ═══════════════════════════════════════════════════════════════════════

MIDDLEWARE_CATALOG: list[MiddlewareSignature] = [
    # ── 数据库 ──
    MiddlewareSignature(
        key="postgresql",
        display_name="PostgreSQL",
        category=MiddlewareCategory.DATABASE,
        process_names=["postgres"],
        default_ports=[5432],
        known_paths=["/etc/postgresql", "/var/lib/postgresql"],
        systemd_services=["postgresql"],
        version_cmd=["psql", "--version"],
        version_regex=r"(\d+\.\d+(?:\.\d+)?)",
    ),
    MiddlewareSignature(
        key="mongodb",
        display_name="MongoDB",
        category=MiddlewareCategory.DATABASE,
        process_names=["mongod"],
        default_ports=[27017],
        known_paths=["/etc/mongod.conf", "/var/lib/mongodb"],
        systemd_services=["mongod"],
        version_cmd=["mongod", "--version"],
        version_regex=r"db version v(\d+\.\d+\.\d+)",
    ),
    MiddlewareSignature(
        key="mysql",
        display_name="MySQL",
        category=MiddlewareCategory.DATABASE,
        process_names=["mysqld"],
        default_ports=[3306],
        known_paths=["/etc/mysql", "/var/lib/mysql"],
        systemd_services=["mysql"],
        version_cmd=["mysqld", "--version"],
        version_regex=r"(\d+\.\d+\.\d+)",
    ),

    # ── 缓存 ──
    MiddlewareSignature(
        key="redis",
        display_name="Redis",
        category=MiddlewareCategory.CACHE,
        process_names=["redis-server"],
        default_ports=[6379],
        known_paths=["/etc/redis", "/var/lib/redis"],
        systemd_services=["redis-server", "redis"],
        version_cmd=["redis-server", "--version"],
        version_regex=r"v=(\d+\.\d+\.\d+)",
    ),

    # ── Web 服务器 ──
    MiddlewareSignature(
        key="nginx",
        display_name="Nginx",
        category=MiddlewareCategory.WEB_SERVER,
        process_names=["nginx"],
        default_ports=[80, 443],
        known_paths=["/etc/nginx", "/var/log/nginx"],
        systemd_services=["nginx"],
        version_cmd=["nginx", "-v"],
        version_regex=r"nginx/(\d+\.\d+\.\d+)",
    ),

    # ── 消息队列 ──
    MiddlewareSignature(
        key="rocketmq",
        display_name="RocketMQ",
        category=MiddlewareCategory.MESSAGE_QUEUE,
        process_names=[],
        java_cmdline_patterns=["org.apache.rocketmq", "rocketmq"],
        default_ports=[9876, 10911, 10909],
        known_paths=["/opt/rocketmq-all-*", "/opt/rocketmq-*"],
        systemd_services=[],
        start_cmd="nohup sh bin/mqnamesrv > /dev/null 2>&1 & nohup sh bin/mqbroker -n 127.0.0.1:9876 > /dev/null 2>&1 &",
        stop_cmd="sh bin/mqshutdown broker && sh bin/mqshutdown namesrv",
        version_regex=r"rocketmq-all-(\d+\.\d+\.\d+)",
        version_from_path=True,
        sub_components=["namesrv", "broker"],
    ),

    # ── 搜索引擎 ──
    MiddlewareSignature(
        key="elasticsearch",
        display_name="Elasticsearch",
        category=MiddlewareCategory.SEARCH,
        process_names=[],
        java_cmdline_patterns=["org.elasticsearch.bootstrap.Elasticsearch", "elasticsearch"],
        default_ports=[9200, 9300],
        known_paths=["/opt/elasticsearch-*", "/usr/share/elasticsearch"],
        systemd_services=[],
        version_cmd=[],
        start_cmd=None,  # 无 systemd，需手动
        stop_cmd=None,
        version_regex=r"elasticsearch-(\d+\.\d+\.\d+)",
        version_from_path=True,
    ),

    # ── 注册中心 ──
    MiddlewareSignature(
        key="nacos",
        display_name="Nacos",
        category=MiddlewareCategory.REGISTRY,
        process_names=[],
        java_cmdline_patterns=["nacos-server.jar", "com.alibaba.nacos"],
        default_ports=[8848, 9848, 9849],
        known_paths=["/home/nacos", "/opt/nacos"],
        systemd_services=[],
        start_cmd="sh bin/startup.sh -m standalone",
        stop_cmd="sh bin/shutdown.sh",
        version_regex=r"nacos-server-(\d+\.\d+\.\d+)",
        version_from_path=True,
    ),

    # ── 容器 ──
    MiddlewareSignature(
        key="docker",
        display_name="Docker",
        category=MiddlewareCategory.CONTAINER,
        process_names=["dockerd", "docker"],
        default_ports=[],
        known_paths=["/var/lib/docker", "/etc/docker"],
        systemd_services=["docker"],
        version_cmd=["docker", "--version"],
        version_regex=r"Docker version (\d+\.\d+\.\d+)",
    ),
    MiddlewareSignature(
        key="containerd",
        display_name="containerd",
        category=MiddlewareCategory.CONTAINER,
        process_names=["containerd"],
        default_ports=[],
        known_paths=["/var/lib/containerd", "/etc/containerd"],
        systemd_services=["containerd"],
        version_cmd=["containerd", "--version"],
        version_regex=r"containerd.*?(\d+\.\d+\.\d+)",
    ),

    # ── 自动化 ──
    MiddlewareSignature(
        key="n8n",
        display_name="n8n",
        category=MiddlewareCategory.AUTOMATION,
        process_names=[],
        java_cmdline_patterns=[],
        default_ports=[5678, 5679],
        known_paths=["/usr/bin/n8n", "/usr/lib/node_modules/n8n"],
        systemd_services=["n8n"],
        version_cmd=["n8n", "--version"],
        version_regex=r"(\d+\.\d+\.\d+)",
    ),

    # ── 监控 ──
    MiddlewareSignature(
        key="prometheus",
        display_name="Prometheus",
        category=MiddlewareCategory.MONITORING,
        process_names=["prometheus"],
        default_ports=[9090],
        known_paths=["/usr/local/bin/prometheus", "/etc/prometheus"],
        systemd_services=["prometheus"],
        version_cmd=["prometheus", "--version"],
        version_regex=r"version (\d+\.\d+\.\d+)",
    ),
    MiddlewareSignature(
        key="grafana",
        display_name="Grafana",
        category=MiddlewareCategory.MONITORING,
        process_names=["grafana"],
        default_ports=[3000],
        known_paths=["/etc/grafana", "/usr/share/grafana"],
        systemd_services=["grafana-server"],
        version_cmd=["grafana-server", "--version"],
        version_regex=r"Version (\d+\.\d+\.\d+)",
    ),

    # ── 对象存储 ──
    MiddlewareSignature(
        key="minio",
        display_name="MinIO",
        category=MiddlewareCategory.STORAGE,
        process_names=["minio"],
        default_ports=[9000, 9001],
        known_paths=["/usr/local/bin/minio", "/etc/minio"],
        systemd_services=["minio"],
        version_cmd=["minio", "--version"],
        version_regex=r"(\d{4}-\d{2}-\d{2})",
        version_from_path=False,
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# 检测通道 1: systemd
# ═══════════════════════════════════════════════════════════════════════

def _detect_via_systemd() -> dict[str, MiddlewareInfo]:
    """通过 systemd 服务发现中间件"""
    results: dict[str, MiddlewareInfo] = {}

    try:
        all_services = sm.list_services(user_only=False)
    except Exception:
        return results

    # 构建 systemd 服务名 → 中间件 key 的映射
    svc_to_key: dict[str, str] = {}
    for sig in MIDDLEWARE_CATALOG:
        for svc in sig.systemd_services:
            svc_to_key[svc] = sig.key

    for svc in all_services:
        if svc.name not in svc_to_key:
            continue

        key = svc_to_key[svc.name]
        sig = _get_catalog(key)
        if sig is None:
            continue

        is_running = svc.sub_state.value == "running"
        info = MiddlewareInfo(
            key=sig.key,
            display_name=sig.display_name,
            category=sig.category.value,
            status=MiddlewareStatus.RUNNING if is_running else MiddlewareStatus.STOPPED,
            pid=svc.pid,
            systemd_service=svc.name,
            management=ManagementMethod.SYSTEMD,
            detection_source="systemd",
            sub_components=sig.sub_components.copy(),
        )
        if svc.pid:
            info.pids = [svc.pid]
        results[key] = info

    return results


# ═══════════════════════════════════════════════════════════════════════
# 检测通道 2: process
# ═══════════════════════════════════════════════════════════════════════

def _detect_via_processes() -> dict[str, MiddlewareInfo]:
    """通过扫描运行中的进程发现中间件"""
    results: dict[str, MiddlewareInfo] = {}

    # 收集所有进程
    processes: list[tuple[int, str, str]] = []  # (pid, comm, full_cmdline)
    try:
        # 先走 ps
        output = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10
        ).stdout
        for line in output.strip().split("\n")[1:]:
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            comm = parts[10] if len(parts) > 10 else ""
            processes.append((pid, comm, comm))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 补充 /proc 扫描（更全），也获取完整 cmdline
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                pid = int(entry)
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read()
                # cmdline 是 null 分隔的
                parts = raw.split(b"\x00")
                cmdline = " ".join(p.decode("utf-8", errors="replace") for p in parts if p)
                # stat 文件获取 comm
                with open(f"/proc/{pid}/stat", "r") as f:
                    stat = f.read()
                m = re.match(r"\d+\s+\((.+?)\)", stat)
                comm = m.group(1) if m else ""
                # 检查是否已存在
                existing = [i for i, (p, _, _) in enumerate(processes) if p == pid]
                if existing:
                    # 更新 cmdline
                    processes[existing[0]] = (pid, comm, cmdline)
                else:
                    processes.append((pid, comm, cmdline))
            except (OSError, IOError):
                continue
    except (FileNotFoundError, PermissionError):
        pass

    # 匹配目录
    for sig in MIDDLEWARE_CATALOG:
        match_pids: list[int] = []
        for pid, comm, cmdline in processes:
            matched = False
            # 直接进程名匹配
            if sig.process_names:
                if comm in sig.process_names:
                    matched = True
            # Java 进程 cmdline 匹配
            if not matched and sig.java_cmdline_patterns:
                for pattern in sig.java_cmdline_patterns:
                    if pattern in cmdline:
                        matched = True
                        break
            if matched:
                match_pids.append(pid)

        if not match_pids:
            continue

        # 已经通过 systemd 发现的，只补充 PID 信息
        if sig.key in results:
            existing_info = results[sig.key]
            for pid in match_pids:
                if pid not in existing_info.pids:
                    existing_info.pids.append(pid)
            if not existing_info.pid and existing_info.pids:
                existing_info.pid = existing_info.pids[0]
            existing_info.detection_source += "+process"
            continue

        info = MiddlewareInfo(
            key=sig.key,
            display_name=sig.display_name,
            category=sig.category.value,
            status=MiddlewareStatus.RUNNING,
            pid=match_pids[0],
            pids=match_pids,
            management=ManagementMethod.PROCESS,
            detection_source="process",
            sub_components=sig.sub_components.copy(),
        )
        results[sig.key] = info

    return results


# ═══════════════════════════════════════════════════════════════════════
# 检测通道 3: port
# ═══════════════════════════════════════════════════════════════════════

def _detect_via_ports() -> dict[str, MiddlewareInfo]:
    """通过监听端口发现中间件"""
    results: dict[str, MiddlewareInfo] = {}

    ports_map: dict[int, tuple[int, str]] = {}  # port -> (pid, process_name)

    # ss -tlnp
    try:
        output = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=10
        ).stdout
        for line in output.strip().split("\n")[1:]:
            # 格式: LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=858,fd=3))
            m = re.search(r":(\d+)\s+.*users:.*\(", line)
            if not m:
                continue
            port = int(m.group(1))
            pid_m = re.search(r"pid=(\d+)", line)
            pid = int(pid_m.group(1)) if pid_m else 0
            name_m = re.match(r".*users:\(\(" + '"(.*?)"' + r"", line)
            proc_name = name_m.group(1) if name_m else ""
            if port not in ports_map:
                ports_map[port] = (pid, proc_name)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not ports_map:
        return results

    # 匹配目录
    for sig in MIDDLEWARE_CATALOG:
        found_ports: list[int] = []
        found_pids: list[int] = []
        for port in sig.default_ports:
            if port in ports_map:
                found_ports.append(port)
                pid, _ = ports_map[port]
                if pid > 0:
                    found_pids.append(pid)

        if not found_ports:
            continue

        # 已通过其他通道发现的，只补充端口信息
        if sig.key in results:
            existing = results[sig.key]
            for p in found_ports:
                if p not in existing.ports:
                    existing.ports.append(p)
            if not existing.port and existing.ports:
                existing.port = existing.ports[0]
            for pid in found_pids:
                if pid not in existing.pids:
                    existing.pids.append(pid)
            if not existing.pid and existing.pids:
                existing.pid = existing.pids[0]
            existing.detection_source += "+port"
            continue

        info = MiddlewareInfo(
            key=sig.key,
            display_name=sig.display_name,
            category=sig.category.value,
            status=MiddlewareStatus.RUNNING,
            port=found_ports[0],
            ports=found_ports,
            pid=found_pids[0] if found_pids else None,
            pids=found_pids,
            management=ManagementMethod.PROCESS,
            detection_source="port",
            sub_components=sig.sub_components.copy(),
        )
        results[sig.key] = info

    return results


# ═══════════════════════════════════════════════════════════════════════
# 检测通道 4: filesystem
# ═══════════════════════════════════════════════════════════════════════

def _detect_via_filesystem() -> dict[str, MiddlewareInfo]:
    """通过文件系统扫描已知路径发现已安装的中间件"""
    results: dict[str, MiddlewareInfo] = {}

    for sig in MIDDLEWARE_CATALOG:
        # 如果已经通过进程/端口检测到运行中，只需要补充 install_path
        existing = results.get(sig.key)
        install_path = None
        config_path = None

        # 检查 known_paths
        for pattern in sig.known_paths:
            for path in glob.glob(pattern):
                if os.path.isdir(path) or os.path.isfile(path):
                    if not install_path and os.path.isdir(path):
                        install_path = path
                    elif not install_path:
                        install_path = os.path.dirname(path)
                    if "etc" in path or "conf" in path:
                        config_path = path
                    break
            if install_path:
                break

        # 检查 binary_paths
        if not install_path:
            for pattern in sig.binary_paths:
                for path in glob.glob(pattern):
                    if os.path.exists(path):
                        install_path = os.path.dirname(path)
                        break
                if install_path:
                    break

        if not install_path:
            continue

        if existing:
            existing.install_path = install_path or existing.install_path
            existing.config_path = config_path or existing.config_path
            existing.detection_source += "+filesystem"
            continue

        # 仅通过 filesystem 发现的（未运行）
        # 确定管理方法和命令
        management = ManagementMethod.UNMANAGED
        start_cmd = None
        stop_cmd = None
        work_dir = None

        if sig.systemd_services:
            management = ManagementMethod.SYSTEMD
        elif sig.start_cmd:
            management = ManagementMethod.SCRIPT
            start_cmd = sig.start_cmd
            stop_cmd = sig.stop_cmd
            work_dir = sig.work_dir or install_path
        elif sig.process_names or sig.java_cmdline_patterns:
            management = ManagementMethod.PROCESS

        # 快速版本检测（从路径）
        version = None
        if sig.version_from_path and install_path:
            m = re.search(sig.version_regex, install_path)
            if m:
                version = m.group(1)

        info = MiddlewareInfo(
            key=sig.key,
            display_name=sig.display_name,
            category=sig.category.value,
            status=MiddlewareStatus.STOPPED,
            version=version,
            install_path=install_path,
            config_path=config_path,
            systemd_service=sig.systemd_services[0] if sig.systemd_services else None,
            management=management,
            start_command=start_cmd,
            stop_command=stop_cmd,
            status_command=sig.status_cmd,
            work_dir=work_dir,
            detection_source="filesystem",
            sub_components=sig.sub_components.copy(),
        )
        results[sig.key] = info

    return results


# ═══════════════════════════════════════════════════════════════════════
# 合并与去重
# ═══════════════════════════════════════════════════════════════════════

def _merge_detections(
    systemd_detected: dict[str, MiddlewareInfo],
    process_detected: dict[str, MiddlewareInfo],
    port_detected: dict[str, MiddlewareInfo],
    filesystem_detected: dict[str, MiddlewareInfo],
) -> dict[str, MiddlewareInfo]:
    """合并四个通道的检测结果"""
    # 最终结果：从 filesystem 开始（提供 install_path），然后逐层覆盖
    merged = dict(filesystem_detected)

    # 逐层合并
    for source_name, source_dict in [
        ("systemd", systemd_detected),
        ("port", port_detected),
        ("process", process_detected),
    ]:
        for key, info in source_dict.items():
            if key not in merged:
                merged[key] = info
                continue

            existing = merged[key]

            # status: 任何通道检测到运行中即为运行中
            if info.status == MiddlewareStatus.RUNNING:
                existing.status = MiddlewareStatus.RUNNING

            # PID: process/port 通道优先
            if info.pid and not existing.pid:
                existing.pid = info.pid
            for pid in info.pids:
                if pid not in existing.pids:
                    existing.pids.append(pid)

            # Port: port 通道优先
            if info.port and not existing.port:
                existing.port = info.port
            for p in info.ports:
                if p not in existing.ports:
                    existing.ports.append(p)

            # install_path: filesystem 通道优先（在前面已设置）
            if info.install_path and not existing.install_path:
                existing.install_path = info.install_path

            # config_path
            if info.config_path and not existing.config_path:
                existing.config_path = info.config_path

            # systemd_service: systemd 通道优先
            if info.systemd_service and not existing.systemd_service:
                existing.systemd_service = info.systemd_service

            # management: systemd > script > process > unmanaged
            if _management_priority(info.management) > _management_priority(existing.management):
                existing.management = info.management
                existing.systemd_service = info.systemd_service
                existing.start_command = info.start_command
                existing.stop_command = info.stop_command
                existing.work_dir = info.work_dir

            # detection_source
            if source_name not in existing.detection_source:
                existing.detection_source += f"+{source_name}"

    return merged


def _management_priority(m: ManagementMethod) -> int:
    mapping = {
        ManagementMethod.SYSTEMD: 3,
        ManagementMethod.SCRIPT: 2,
        ManagementMethod.PROCESS: 1,
        ManagementMethod.UNMANAGED: 0,
    }
    return mapping.get(m, 0)


# ═══════════════════════════════════════════════════════════════════════
# 版本检测
# ═══════════════════════════════════════════════════════════════════════

def _detect_version_fast(sig: MiddlewareSignature, info: MiddlewareInfo) -> Optional[str]:
    """快速版本检测（从路径提取，不执行命令）"""
    if sig.version_from_path and info.install_path:
        m = re.search(sig.version_regex, info.install_path)
        if m:
            return m.group(1)
    return None


def _detect_version_command(sig: MiddlewareSignature) -> Optional[str]:
    """通过执行 version_cmd 获取版本"""
    if not sig.version_cmd:
        return None

    try:
        # 直接把输出送到 stderr 的（如 nginx -v），合并 stderr
        result = subprocess.run(
            sig.version_cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return None

    m = re.search(sig.version_regex, output)
    if m:
        return m.group(1)
    return None


# ═══════════════════════════════════════════════════════════════════════
# 目录查询
# ═══════════════════════════════════════════════════════════════════════

_CATALOG_MAP: dict[str, MiddlewareSignature] | None = None


def _get_catalog_map() -> dict[str, MiddlewareSignature]:
    global _CATALOG_MAP
    if _CATALOG_MAP is None:
        _CATALOG_MAP = {sig.key: sig for sig in MIDDLEWARE_CATALOG}
    return _CATALOG_MAP


def _get_catalog(key: str) -> Optional[MiddlewareSignature]:
    return _get_catalog_map().get(key)


# ═══════════════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════════════

def list_middleware(
    search: Optional[str] = None,
    category: Optional[str] = None,
) -> list[MiddlewareInfo]:
    """
    列出所有检测到的中间件。

    Args:
        search: 按名称或 key 搜索
        category: 按分类过滤 (database, cache, web-server, message-queue, ...)
    """
    # 四通道检测
    systemd_detected = _detect_via_systemd()
    process_detected = _detect_via_processes()
    port_detected = _detect_via_ports()
    filesystem_detected = _detect_via_filesystem()

    # 合并
    merged = _merge_detections(
        systemd_detected, process_detected, port_detected, filesystem_detected
    )

    # 快速版本检测 + 补充目录默认端口
    for key, info in merged.items():
        sig = _get_catalog(key)
        if sig:
            if not info.version:
                info.version = _detect_version_fast(sig, info)
            # 即使中间件未运行，也填充目录定义的默认端口作为预期端口
            if not info.ports and sig.default_ports:
                info.ports = list(sig.default_ports)
                info.port = sig.default_ports[0]

    result = list(merged.values())

    # 过滤
    if search:
        s = search.lower()
        result = [
            m for m in result
            if s in m.key.lower() or s in m.display_name.lower()
        ]
    if category:
        result = [m for m in result if m.category == category]

    # 排序：运行中优先，然后按名称
    result.sort(key=lambda m: (0 if m.status == MiddlewareStatus.RUNNING else 1, m.display_name))

    return result


def get_middleware(key: str) -> Optional[MiddlewareInfo]:
    """获取单个中间件的详细信息（含完整版本检测）"""
    all_mw = list_middleware()
    info = None
    for m in all_mw:
        if m.key == key:
            info = m
            break

    if info is None:
        return None

    # 完整版本检测（执行命令）
    sig = _get_catalog(key)
    if sig:
        cmd_version = _detect_version_command(sig)
        if cmd_version:
            info.version = cmd_version
        elif not info.version:
            info.version = _detect_version_fast(sig, info)

    return info


def start_middleware(key: str) -> sm.OperationResult:
    """启动中间件"""
    info = get_middleware(key)
    if info is None:
        return sm.OperationResult(False, f"中间件 {key} 未找到")

    method = info.management

    if method == ManagementMethod.SYSTEMD:
        if not info.systemd_service:
            return sm.OperationResult(False, f"{key} 缺少 systemd 服务名")
        return sm.start_service(info.systemd_service)

    elif method == ManagementMethod.SCRIPT:
        if not info.start_command:
            return sm.OperationResult(False, f"{key} 缺少启动命令")
        try:
            cwd = info.work_dir or info.install_path or "/"
            result = subprocess.run(
                info.start_command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return sm.OperationResult(True, f"{info.display_name} 启动命令已执行")
            else:
                err = result.stderr.strip() or result.stdout.strip()
                return sm.OperationResult(False, f"启动失败: {err}")
        except subprocess.TimeoutExpired:
            return sm.OperationResult(False, f"启动 {key} 超时")
        except Exception as e:
            return sm.OperationResult(False, str(e))

    elif method == ManagementMethod.PROCESS:
        # 进程管理：有 start_cmd 则执行，否则无法启动
        if info.start_command:
            try:
                cwd = info.work_dir or info.install_path or "/"
                subprocess.run(
                    info.start_command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return sm.OperationResult(True, f"{info.display_name} 启动命令已执行")
            except Exception as e:
                return sm.OperationResult(False, str(e))
        return sm.OperationResult(False, f"{key} 没有可用的启动方式，请手动启动")

    return sm.OperationResult(False, f"{key} 不支持管理操作 (management={method.value})")


def stop_middleware(key: str) -> sm.OperationResult:
    """停止中间件"""
    info = get_middleware(key)
    if info is None:
        return sm.OperationResult(False, f"中间件 {key} 未找到")

    method = info.management

    if method == ManagementMethod.SYSTEMD:
        if not info.systemd_service:
            return sm.OperationResult(False, f"{key} 缺少 systemd 服务名")
        return sm.stop_service(info.systemd_service)

    elif method == ManagementMethod.SCRIPT:
        if not info.stop_command:
            return sm.OperationResult(False, f"{key} 缺少停止命令")
        try:
            cwd = info.work_dir or info.install_path or "/"
            result = subprocess.run(
                info.stop_command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return sm.OperationResult(True, f"{info.display_name} 停止命令已执行")
            else:
                err = result.stderr.strip() or result.stdout.strip()
                return sm.OperationResult(False, f"停止失败: {err}")
        except subprocess.TimeoutExpired:
            return sm.OperationResult(False, f"停止 {key} 超时")
        except Exception as e:
            return sm.OperationResult(False, str(e))

    elif method == ManagementMethod.PROCESS:
        if not info.pids:
            return sm.OperationResult(False, f"{key} 未找到运行中的进程")
        errors = []
        for pid in info.pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception as e:
                errors.append(str(e))
        if errors and len(errors) == len(info.pids):
            return sm.OperationResult(False, f"停止进程失败: {'; '.join(errors)}")
        return sm.OperationResult(True, f"{info.display_name} (PID {info.pids}) 已发送停止信号")

    return sm.OperationResult(False, f"{key} 不支持管理操作")


def restart_middleware(key: str) -> sm.OperationResult:
    """重启中间件"""
    stop_result = stop_middleware(key)
    if not stop_result.success:
        return stop_result

    # 等待一下让进程完全退出
    import time
    time.sleep(1)

    return start_middleware(key)


def get_middleware_summary() -> dict:
    """获取中间件统计摘要"""
    all_mw = list_middleware()
    total = len(all_mw)
    running = sum(1 for m in all_mw if m.status == MiddlewareStatus.RUNNING)
    stopped = total - running

    categories: dict[str, int] = {}
    for m in all_mw:
        cat = m.category or "other"
        categories[cat] = categories.get(cat, 0) + 1

    management_methods: dict[str, int] = {}
    for m in all_mw:
        mm = m.management.value
        management_methods[mm] = management_methods.get(mm, 0) + 1

    return {
        "total": total,
        "running": running,
        "stopped": stopped,
        "categories": categories,
        "management_methods": management_methods,
    }
