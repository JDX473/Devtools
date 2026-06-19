"""
Service Manager — 封装 systemctl，用于发现和管理 Linux 系统服务。

支持的操作：
  - 列出所有服务及其状态
  - 查看单个服务详情
  - 启动 / 停止 / 重启服务
  - 启用 / 禁用服务（开机自启）
"""

import subprocess
import platform
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ServiceStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    EXITED = "exited"       # oneshot 服务正常退出
    UNKNOWN = "unknown"

    @classmethod
    def from_systemctl(cls, raw: str) -> "ServiceStatus":
        raw = raw.strip().lower()
        mapping = {
            "active": cls.ACTIVE,
            "inactive": cls.INACTIVE,
            "failed": cls.FAILED,
            "exited": cls.EXITED,
        }
        return mapping.get(raw, cls.UNKNOWN)


class ServiceSubState(Enum):
    """systemd 子状态"""
    RUNNING = "running"
    DEAD = "dead"
    EXITED = "exited"
    FAILED = "failed"
    AUTO_RESTART = "auto-restart"
    UNKNOWN = "unknown"

    @classmethod
    def from_systemctl(cls, raw: str) -> "ServiceSubState":
        raw = raw.strip().lower()
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class ServiceInfo:
    """单个服务的信息"""
    name: str                     # 服务名（不含 .service 后缀）
    load_state: str = "unknown"   # loaded / not-found / masked
    active_state: ServiceStatus = ServiceStatus.UNKNOWN
    sub_state: ServiceSubState = ServiceSubState.UNKNOWN
    description: str = ""
    unit_file_state: str = ""     # enabled / disabled / static
    pid: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return self.sub_state == ServiceSubState.RUNNING

    @property
    def is_enabled(self) -> bool:
        return self.unit_file_state == "enabled"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "load_state": self.load_state,
            "active_state": self.active_state.value,
            "sub_state": self.sub_state.value,
            "description": self.description,
            "unit_file_state": self.unit_file_state,
            "is_running": self.is_running,
            "is_enabled": self.is_enabled,
            "pid": self.pid,
        }


def _is_linux() -> bool:
    return platform.system() == "Linux"


def _run_systemctl(*args: str, timeout: int = 15) -> str:
    """执行 systemctl 命令，返回 stdout 文本"""
    cmd = ["systemctl", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    # systemctl 对于某些查询即使成功也返回非 0，我们只关心 stdout
    return result.stdout


def _run_systemctl_quiet(*args: str, timeout: int = 30) -> bool:
    """执行 systemctl 命令，返回是否成功"""
    cmd = ["systemctl", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ---- 系统服务过滤 ----

# 匹配以下模式的服务视为系统内部服务，默认隐藏
SYSTEM_SERVICE_PATTERNS = [
    # systemd 自身组件
    "systemd-", "systemd_",
    # 用户会话
    "user@", "user-runtime-dir@", "session-",
    # 终端
    "getty@", "serial-getty@", "container-getty@", "console-getty@",
    # 包管理
    "apt-daily", "dpkg-db-backup", "packagekit", "unattended-upgrades",
    # snap
    "snap.", "snap-",
    # 固件
    "fwupd",
    # 硬件
    "alsa-", "bluetooth", "bolt-", "thermald", "irqbalance",
    # 启动画面
    "plymouth-", "kmod-static-nodes", "keyboard-setup", "console-setup",
    "setvtrgb", "systemd-modules-load",
    # D-Bus
    "dbus.", "dbus-",
    # 权限相关
    "polkit", "accounts-daemon", "rtkit-daemon",
    # 系统日志
    "rsyslog", "syslog", "systemd-journal",
    # 崩溃报告
    "apport", "whoopsie", "kerneloops",
    # 打印
    "cups", "cups-browsed",
    # 磁盘/LVM
    "e2scrub", "lvm2-", "multipathd", "dm-event",
    # 网络底层
    "NetworkManager-dispatcher", "NetworkManager-wait-online",
    "systemd-network", "systemd-resolved", "wpa_supplicant",
    # 时间同步
    "systemd-timesyncd", "systemd-time-wait-sync",
    # 杂项系统
    "pollinate", "motd-news", "ModemManager", "avahi-daemon",
    # 文件系统
    "fstrim", "fstrim-", "btrfs-",
    # 虚拟化工具
    "qemu-", "libvirt-guests", "vgauth", "vmtoolsd", "open-vm-tools",
    # 云相关
    "cloud-", "cloud-",
    # 电源/显示
    "upower", "colord", "gdm", "lightdm", "sddm",
    # 磁盘管理
    "udisks2", "uuidd",
    # GRUB
    "grub-",
    # iSCSI
    "open-iscsi", "iscsid",
    # 随机数种子
    "systemd-random-seed", "systemd-pstore",
    # 其他系统内部
    "dmesg", "emergency", "rescue", "rc-local",
    "pmlogger", "pmie", "pmcd", "pmproxy",
    "speech-dispatcher", "spice-vdagent",
    # 安全模块
    "apparmor", "auditd", "secureboot-db",
    # 定时任务
    "anacron", "atd",
    # ACPI/电源
    "acpid",
    # 磁盘/LVM/RAID 补充
    "blk-availability", "mdadm", "mdmonitor", "mdmon",
    "lvm2-monitor", "lvm2-lvmpolld", "dmraid-activation",
    # 网络补充
    "networking", "nftables", "ifupdown", "ifup", "ifdown",
    "networkd-dispatcher", "mptcpize",
    # SSH guard（不是 ssh 本身）
    "sshguard",
    # 硬件监控
    "hddtemp", "lm-sensors", "smartmontools", "smartd",
    "sysfsutils", "loadcpufreq", "ondemand",
    # 数据库/日志
    "man-db", "logrotate", "sysstat",
    # 加密/安全
    "cryptdisks", "cryptdisks-",
    # 虚拟化补充
    "libvirtd", "virtlockd", "virtlogd", "virtnetworkd",
    "virtnwfilterd", "virtsecretd", "virtstoraged",
    "virtinterfaced", "virtnodedevd", "virtproxyd",
    "virtqemud", "virtlxcd", "virtvboxd", "virtxend",
    # Ubuntu 特有
    "ubuntu-advantage", "ubuntu-fan", "casper-md5check",
    "ureadahead", "ureadahead-",
    # 打印机补充
    "cups-browsed", "avahi-daemon",
    # 其他系统
    "finalrd", "hwclock", "hwclock-",
    "kmod", "procps", "proc-sys-fs-binfmt_misc",
    "quotaon", "rpcbind", "rsync", "saned",
    "setvtrgb", "usbguard",
    "x11-common",
    # 网络文件系统/存储
    "rpc-statd", "nfs-", "rpc-gssd", "rpc-svcgssd",
    "nmbd", "smbd", "samba-ad-dc",
]

USER_SERVICE_WHITELIST = [
    # 显式保留的服务，即使匹配上面模式也不隐藏
    # （当前不需要额外配置，白名单备用）
]


def _is_system_service(name: str) -> bool:
    """判断是否为系统内部服务（应默认隐藏）"""
    # 检查白名单
    for pattern in USER_SERVICE_WHITELIST:
        if pattern in name:
            return False

    # 检查是否匹配系统服务模式
    for pattern in SYSTEM_SERVICE_PATTERNS:
        if pattern in name:
            return True

    return False


def _is_user_managed(name: str) -> bool:
    """检查服务是否由用户创建（在 /etc/systemd/system/ 下）"""
    if not _is_linux():
        return False
    try:
        output = _run_systemctl("show", f"{name}.service", "--property=FragmentPath")
        m = re.search(r"FragmentPath=(.+)", output)
        if m:
            path = m.group(1)
            return "/etc/systemd/system/" in path
    except Exception:
        pass
    return False


# ---- 服务发现与查询 ----

def list_services(
    filter_pattern: Optional[str] = None,
    user_only: bool = True,
) -> list[ServiceInfo]:
    """
    列出系统中的所有 systemd 服务。
    如果不运行在 Linux 上，返回空列表。
    """
    if not _is_linux():
        return []

    try:
        # --all 列出所有服务，不仅是 active 的
        # --plain 去掉颜色和状态点
        # --no-legend 去掉表头
        output = _run_systemctl(
            "list-units", "--type=service", "--all",
            "--plain", "--no-legend",
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    services = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue

        # systemctl list-units 输出格式（空格分隔，列宽不固定）：
        # UNIT  LOAD  ACTIVE  SUB  DESCRIPTION
        parts = line.split(None, 4)  # 最多拆成 5 部分
        if len(parts) < 4:
            continue

        name = parts[0].replace(".service", "")
        load = parts[1]
        active = ServiceStatus.from_systemctl(parts[2])
        sub = ServiceSubState.from_systemctl(parts[3])
        desc = parts[4] if len(parts) > 4 else ""

        if filter_pattern and filter_pattern.lower() not in name.lower():
            continue

        services.append(ServiceInfo(
            name=name,
            load_state=load,
            active_state=active,
            sub_state=sub,
            description=desc,
        ))

    # 过滤系统内部服务
    if user_only:
        services = [
            s for s in services
            if not _is_system_service(s.name) or _is_user_managed(s.name)
        ]

    # 补充查询 unit-file 状态（enabled/disabled）
    _fill_unit_file_states(services)
    # 补充 PID 信息
    _fill_pids(services)

    return services


def get_service(name: str) -> Optional[ServiceInfo]:
    """获取单个服务的详细信息"""
    if not _is_linux():
        return None

    try:
        # 查 active/sub 状态
        output = _run_systemctl(
            "show", f"{name}.service",
            "--property=Id,LoadState,ActiveState,SubState,Description",
        )
    except FileNotFoundError:
        return None

    props = _parse_show_output(output)

    if not props.get("Id"):
        return None

    info = ServiceInfo(
        name=props.get("Id", name).replace(".service", ""),
        load_state=props.get("LoadState", "unknown"),
        active_state=ServiceStatus.from_systemctl(props.get("ActiveState", "unknown")),
        sub_state=ServiceSubState.from_systemctl(props.get("SubState", "unknown")),
        description=props.get("Description", ""),
    )

    # unit-file 状态
    try:
        output = _run_systemctl("is-enabled", f"{name}.service")
        info.unit_file_state = output.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info.unit_file_state = "unknown"

    # PID
    try:
        output = _run_systemctl(
            "show", f"{name}.service", "--property=MainPID"
        )
        m = re.search(r"MainPID=(\d+)", output)
        if m:
            pid = int(m.group(1))
            info.pid = pid if pid > 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return info


def _fill_unit_file_states(services: list[ServiceInfo]) -> None:
    """批量查询 unit-file 状态"""
    names = [f"{s.name}.service" for s in services]
    if not names:
        return
    try:
        output = _run_systemctl("is-enabled", *names, timeout=30)
        lines = output.strip().split("\n")
        for line in lines:
            line = line.strip()
            for svc in services:
                if line.startswith(svc.name):
                    # "enabled" / "disabled" / "static" 等
                    svc.unit_file_state = line.replace(svc.name, "").strip()
                    break
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        # is-enabled 对所有非 enabled 服务会返回非 0，忽略
        pass


def _fill_pids(services: list[ServiceInfo]) -> None:
    """为 running 的服务填充 PID"""
    running = [s for s in services if s.sub_state == ServiceSubState.RUNNING]
    if not running:
        return

    props_to_get = ",".join(f"{s.name}.service:MainPID" for s in running)
    try:
        output = _run_systemctl("show", *[f"{s.name}.service" for s in running],
                                "--property=MainPID", timeout=30)
        # 输出类似：
        # MainPID=1234
        # MainPID=0
        # MainPID=5678
        pids = re.findall(r"MainPID=(\d+)", output)
        for svc, pid_str in zip(running, pids):
            pid = int(pid_str)
            if pid > 0:
                svc.pid = pid
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _parse_show_output(output: str) -> dict[str, str]:
    """解析 systemctl show 的 key=value 输出"""
    props = {}
    for line in output.strip().split("\n"):
        line = line.strip()
        if "=" in line:
            key, _, value = line.partition("=")
            props[key] = value
    return props


# ---- 服务操作 ----

class OperationResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message

    def to_dict(self) -> dict:
        return {"success": self.success, "message": self.message}


def start_service(name: str) -> OperationResult:
    if not _is_linux():
        return OperationResult(False, "非 Linux 环境，无法操作 systemd 服务")
    try:
        ok = _run_systemctl_quiet("start", f"{name}.service")
        if ok:
            return OperationResult(True, f"服务 {name} 已启动")
        else:
            return OperationResult(False, f"启动 {name} 失败，请检查权限或日志: journalctl -u {name}")
    except Exception as e:
        return OperationResult(False, str(e))


def stop_service(name: str) -> OperationResult:
    if not _is_linux():
        return OperationResult(False, "非 Linux 环境，无法操作 systemd 服务")
    try:
        ok = _run_systemctl_quiet("stop", f"{name}.service")
        if ok:
            return OperationResult(True, f"服务 {name} 已停止")
        else:
            return OperationResult(False, f"停止 {name} 失败，请检查权限或日志")
    except Exception as e:
        return OperationResult(False, str(e))


def restart_service(name: str) -> OperationResult:
    if not _is_linux():
        return OperationResult(False, "非 Linux 环境，无法操作 systemd 服务")
    try:
        ok = _run_systemctl_quiet("restart", f"{name}.service")
        if ok:
            return OperationResult(True, f"服务 {name} 已重启")
        else:
            return OperationResult(False, f"重启 {name} 失败，请检查权限或日志")
    except Exception as e:
        return OperationResult(False, str(e))


def enable_service(name: str) -> OperationResult:
    if not _is_linux():
        return OperationResult(False, "非 Linux 环境，无法操作 systemd 服务")
    try:
        ok = _run_systemctl_quiet("enable", f"{name}.service")
        if ok:
            return OperationResult(True, f"服务 {name} 已设为开机自启")
        else:
            return OperationResult(False, f"启用 {name} 失败，请检查权限")
    except Exception as e:
        return OperationResult(False, str(e))


def disable_service(name: str) -> OperationResult:
    if not _is_linux():
        return OperationResult(False, "非 Linux 环境，无法操作 systemd 服务")
    try:
        ok = _run_systemctl_quiet("disable", f"{name}.service")
        if ok:
            return OperationResult(True, f"服务 {name} 已取消开机自启")
        else:
            return OperationResult(False, f"禁用 {name} 失败，请检查权限")
    except Exception as e:
        return OperationResult(False, str(e))


def get_system_info() -> dict:
    """获取系统基本信息"""
    info = {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "hostname": platform.node(),
        "is_linux": _is_linux(),
        "service_count": 0,
    }

    if _is_linux():
        try:
            output = _run_systemctl("list-units", "--type=service", "--all",
                                    "--plain", "--no-legend")
            info["service_count"] = len(
                [l for l in output.strip().split("\n") if l.strip()]
            )
        except Exception:
            pass

    return info
