/**
 * DevTools 服务管理面板 — 前端逻辑
 */

// ---- 状态 ----
let allServices = [];
let currentSearch = "";

// ---- DOM 元素 ----
const $tbody = document.getElementById("service-tbody");
const $searchInput = document.getElementById("search-input");
const $refreshBtn = document.getElementById("refresh-btn");
const $loading = document.getElementById("loading-indicator");
const $hostname = document.getElementById("hostname");
const $platformBadge = document.getElementById("platform-badge");
const $serviceCount = document.getElementById("service-count");
const $platformWarning = document.getElementById("platform-warning");
const $toast = document.getElementById("toast");

// ---- 初始化 ----
document.addEventListener("DOMContentLoaded", () => {
    loadSystemInfo();
    loadServices();

    $refreshBtn.addEventListener("click", loadServices);

    let debounceTimer;
    $searchInput.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            currentSearch = $searchInput.value.trim();
            render();
        }, 300);
    });
});

// ---- API 调用 ----

async function loadSystemInfo() {
    try {
        const resp = await fetch("/api/system");
        const info = await resp.json();
        $hostname.textContent = info.hostname || "--";
        $platformBadge.textContent = info.platform + " " + (info.platform_release || "");
        $platformBadge.className = info.is_linux ? "badge badge-green" : "badge badge-yellow";

        if (!info.is_linux) {
            $platformWarning.classList.remove("hidden");
        }
    } catch (err) {
        console.error("加载系统信息失败:", err);
    }
}

async function loadServices() {
    $loading.classList.remove("hidden");
    $refreshBtn.disabled = true;

    try {
        const resp = await fetch("/api/services");
        const data = await resp.json();
        allServices = data.services || [];

        if (!data.platform) {
            $platformWarning.classList.remove("hidden");
        }

        $serviceCount.textContent = `${data.total} 个服务`;
        render();
    } catch (err) {
        console.error("加载服务列表失败:", err);
        showToast("加载服务列表失败: " + err.message, "error");
        $tbody.innerHTML =
            '<tr><td colspan="7" class="empty-state">加载失败，请检查后端是否运行</td></tr>';
    } finally {
        $loading.classList.add("hidden");
        $refreshBtn.disabled = false;
    }
}

async function doAction(name, action) {
    const displayNames = {
        start: "启动",
        stop: "停止",
        restart: "重启",
        enable: "启用自启",
        disable: "禁用自启",
    };
    const displayName = displayNames[action] || action;

    try {
        const resp = await fetch(`/api/services/${encodeURIComponent(name)}/${action}`, {
            method: "POST",
        });
        const result = await resp.json();

        if (result.success) {
            showToast(`${name}: ${result.message}`, "success");
            // 操作后刷新列表
            setTimeout(loadServices, 800);
        } else {
            showToast(`${name}: ${result.message}`, "error");
        }
    } catch (err) {
        showToast(`${displayName} ${name} 失败: ${err.message}`, "error");
    }
}

// ---- 渲染 ----

function render() {
    const search = currentSearch.toLowerCase();
    const filtered = search
        ? allServices.filter((s) => s.name.toLowerCase().includes(search))
        : allServices;

    if (filtered.length === 0) {
        $tbody.innerHTML =
            '<tr><td colspan="7" class="empty-state">' +
            (search ? "没有匹配的服务" : "未发现任何服务") +
            "</td></tr>";
        return;
    }

    $tbody.innerHTML = filtered.map(renderRow).join("");
}

function renderRow(svc) {
    const statusClass = svc.sub_state; // running / dead / failed / exited / auto-restart
    const statusLabel = statusLabelMap[svc.sub_state] || svc.sub_state;

    const activeBadge = statusBadge(svc.active_state, svc.sub_state);

    const bootBadge = svc.is_enabled
        ? '<span class="badge badge-green">enabled</span>'
        : svc.unit_file_state
            ? `<span class="badge">${svc.unit_file_state}</span>`
            : '<span class="badge">--</span>';

    const pidText = svc.pid ? svc.pid : "--";

    return `
        <tr>
            <td>${activeBadge}</td>
            <td><span class="service-name">${escapeHtml(svc.name)}</span></td>
            <td><span class="service-desc" title="${escapeHtml(svc.description)}">${escapeHtml(svc.description || "--")}</span></td>
            <td>
                <span class="status-dot ${statusClass}"></span>
                ${statusLabel}
            </td>
            <td>${bootBadge}</td>
            <td><code>${pidText}</code></td>
            <td>
                <div class="actions-group">
                    ${actionButtons(svc)}
                </div>
            </td>
        </tr>`;
}

function actionButtons(svc) {
    const name = escapeAttr(svc.name);

    if (svc.sub_state === "running") {
        return `
            <button class="btn btn-sm btn-danger" onclick="doAction('${name}','stop')" title="停止">&#x23F9; 停止</button>
            <button class="btn btn-sm btn-warning" onclick="doAction('${name}','restart')" title="重启">&#x21BB; 重启</button>
            ${svc.is_enabled
                ? `<button class="btn btn-sm btn-outline" onclick="doAction('${name}','disable')" title="取消自启">&#x1F513; 禁自启</button>`
                : `<button class="btn btn-sm btn-outline" onclick="doAction('${name}','enable')" title="开机自启">&#x1F512; 开自启</button>`}
        `;
    } else {
        return `
            <button class="btn btn-sm btn-success" onclick="doAction('${name}','start')" title="启动">&#x25B6; 启动</button>
            ${svc.is_enabled
                ? `<button class="btn btn-sm btn-outline" onclick="doAction('${name}','disable')" title="取消自启">&#x1F513; 禁自启</button>`
                : `<button class="btn btn-sm btn-outline" onclick="doAction('${name}','enable')" title="开机自启">&#x1F512; 开自启</button>`}
        `;
    }
}

function statusBadge(activeState, subState) {
    if (subState === "running") {
        return '<span class="badge badge-green">&#x25CF; 运行中</span>';
    }
    if (subState === "failed" || activeState === "failed") {
        return '<span class="badge badge-red">&#x2716; 失败</span>';
    }
    if (subState === "exited") {
        return '<span class="badge badge-yellow">&#x2714; 已退出</span>';
    }
    if (subState === "auto-restart") {
        return '<span class="badge badge-yellow">&#x21BB; 重启中</span>';
    }
    if (activeState === "inactive" || subState === "dead") {
        return '<span class="badge">&#x25CB; 已停止</span>';
    }
    return `<span class="badge">${activeState}</span>`;
}

const statusLabelMap = {
    running: "运行中",
    dead: "已停止",
    exited: "已退出",
    failed: "失败",
    "auto-restart": "自动重启中",
};

// ---- Toast ----

function showToast(message, type) {
    $toast.textContent = message;
    $toast.className = `toast ${type}`;
    $toast.classList.remove("hidden");

    clearTimeout($toast._timeout);
    $toast._timeout = setTimeout(() => {
        $toast.classList.add("hidden");
    }, 3000);
}

// ---- 工具函数 ----

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
