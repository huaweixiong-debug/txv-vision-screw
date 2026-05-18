"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KL-NTCS-M7 拧紧枪测试面板</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#1a1d23;color:#e0e0e0;min-height:100vh;padding:1rem}
.container{max-width:1400px;margin:0 auto}
h1{font-size:1.4rem;color:#61dafb;margin-bottom:0.5rem}
h2{font-size:1rem;color:#a0c4ff;margin-bottom:0.6rem}
.card{background:#252830;border-radius:12px;padding:1rem;margin-bottom:0.8rem;border:1px solid #333}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0.8rem}
.row{display:flex;gap:0.6rem;align-items:end;flex-wrap:wrap}
.row>*{flex:1;min-width:120px}
label{display:block;font-size:0.75rem;color:#8899aa;margin-bottom:0.2rem}
input,select,button{padding:0.5rem 0.7rem;border-radius:6px;border:1px solid #444;background:#1e2127;color:#ddd;font-size:0.85rem;width:100%}
button{cursor:pointer;background:#2c5282;color:white;border:none;font-weight:600;transition:0.15s}
button:hover{opacity:0.85}
button.danger{background:#9b2c2c}
button.success{background:#276749}
button.warn{background:#975a16}
.status-led{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.led-green{background:#48bb78;box-shadow:0 0 6px #48bb78}
.led-red{background:#f56565;box-shadow:0 0 6px #f56565}
.info-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:0.4rem}
.info-item{background:#1e2127;padding:0.5rem 0.7rem;border-radius:6px;display:flex;justify-content:space-between;align-items:center}
.info-label{color:#8899aa;font-size:0.78rem}
.info-value{font-family:'JetBrains Mono','Consolas',monospace;font-weight:600;color:#e2e8f0}
.reg-table{font-family:'JetBrains Mono','Consolas',monospace;font-size:0.72rem}
.reg-table th{color:#61dafb;text-align:left;padding:0.2rem 0.4rem;position:sticky;top:0;background:#252830}
.reg-table td{padding:0.15rem 0.4rem;border-bottom:1px solid #1e2127}
.reg-table tr:hover{background:#2d3239}
.reg-table .non-zero{color:#f6e05e}.reg-table .zero{color:#4a5568}
.reg-wrap{max-height:400px;overflow:auto;border:1px solid #333;border-radius:8px}
.alert{background:#742a2a;color:#fed7d7;padding:0.5rem 0.8rem;border-radius:6px;margin-top:0.5rem}
.success-msg{background:#22543d;color:#c6f6d5;padding:0.5rem 0.8rem;border-radius:6px;margin-top:0.5rem}
.tabs{display:flex;gap:0.3rem;margin-bottom:1rem}
.tab-btn{padding:0.4rem 1rem;background:#2d3239;border:1px solid #444;color:#aaa;cursor:pointer;border-radius:8px 8px 0 0;width:auto}
.tab-btn.active{background:#252830;color:#61dafb;border-bottom-color:#252830}
.tab-content{display:none}
.tab-content.active{display:block}
.result-display{font-size:2.5rem;font-weight:700;font-family:'JetBrains Mono','Consolas',monospace}
.result-badge{display:inline-block;font-size:1.8rem;font-weight:700;padding:0.4rem 1.2rem;border-radius:10px;margin:0.3rem}
.badge-ok{background:#22543d;color:#48bb78}.badge-ng{background:#742a2a;color:#f56565}.badge-ns{background:#744210;color:#ecc94b}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
<h1>KL-NTCS-M7 拧紧枪 MODBUS 测试面板</h1>

<div class="tabs">
  <button class="tab-btn active" data-tab="status">设备状态</button>
  <button class="tab-btn" data-tab="result">拧紧结果</button>
  <button class="tab-btn" data-tab="control">远程控制</button>
  <button class="tab-btn" data-tab="registers">寄存器浏览器</button>
</div>

<!-- 连接栏 -->
<div class="card">
  <div class="row">
    <div style="flex:2"><label>拧紧枪 IP</label><input id="ip" value="192.168.0.105"></div>
    <div style="flex:1"><label>端口</label><input id="port" value="502"></div>
    <div style="flex:1"><label>Unit ID</label><input id="unitId" value="1"></div>
    <div style="flex:0 0 auto"><label>&nbsp;</label><button id="connectBtn">连接</button></div>
    <div style="flex:0 0 auto"><label>&nbsp;</label><button id="disconnectBtn" class="danger">断开</button></div>
  </div>
  <div id="connMsg" style="margin-top:0.5rem;font-size:0.85rem">未连接</div>
</div>

<!-- Tab 1: 设备状态 -->
<div id="tab-status" class="tab-content active">
  <div class="grid2">
    <div class="card">
      <h2>实时状态 (4305-4346)</h2>
      <div class="info-grid">
        <div class="info-item"><span class="info-label">连接</span><span class="info-value" id="s_conn">--</span></div>
        <div class="info-item"><span class="info-label">起子启用</span><span class="info-value" id="s_enable">--</span></div>
        <div class="info-item"><span class="info-label">运转状态</span><span class="info-value" id="s_run">--</span></div>
        <div class="info-item"><span class="info-label">当前 JOB</span><span class="info-value" id="s_job">--</span></div>
        <div class="info-item"><span class="info-label">当前工序</span><span class="info-value" id="s_seq">--</span></div>
        <div class="info-item"><span class="info-label">当前步骤</span><span class="info-value" id="s_step">--</span></div>
        <div class="info-item"><span class="info-label">当前颗数</span><span class="info-value" id="s_count">--</span></div>
        <div class="info-item"><span class="info-label">起子模式</span><span class="info-value" id="s_mode">--</span></div>
        <div class="info-item"><span class="info-label">流水号</span><span class="info-value" id="s_serial">--</span></div>
        <div class="info-item"><span class="info-label">更新时间</span><span class="info-value" id="s_time">--</span></div>
      </div>
      <div style="margin-top:0.6rem"><button id="refreshBtn">刷新</button></div>
    </div>
    <div class="card">
      <h2>最近拧紧结果</h2>
      <div class="info-grid">
        <div class="info-item"><span class="info-label">扭力 (4155-4156)</span><span class="info-value" id="s_torque">--</span></div>
        <div class="info-item"><span class="info-label">角度 (4159-4160)</span><span class="info-value" id="s_angle">--</span></div>
        <div class="info-item"><span class="info-label">结果码 (4164)</span><span class="info-value" id="s_result">--</span></div>
        <div class="info-item"><span class="info-label">锁附时间 (4158)</span><span class="info-value" id="s_time_ms">--</span></div>
        <div class="info-item" style="grid-column:1/-1"><span class="info-label">时间戳</span><span class="info-value" id="s_rtc">--</span></div>
        <div class="info-item" style="grid-column:1/-1"><span class="info-label">条码</span><span class="info-value" id="s_barcode" style="font-size:0.75rem;word-break:break-all">--</span></div>
      </div>
    </div>
  </div>
</div>

<!-- Tab 2: 拧紧结果 (大字体) -->
<div id="tab-result" class="tab-content">
  <div class="card" style="text-align:center">
    <div id="r_badge"></div>
    <div class="grid2" style="margin-top:1rem">
      <div>
        <div style="color:#8899aa;font-size:0.85rem">扭力 (x倍率)</div>
        <div class="result-display result-ok" id="r_torque">--</div>
        <div style="color:#4a5568;font-size:0.75rem">4155-4156 (32-bit)</div>
      </div>
      <div>
        <div style="color:#8899aa;font-size:0.85rem">角度</div>
        <div class="result-display" style="color:#61dafb" id="r_angle">--</div>
        <div style="color:#4a5568;font-size:0.75rem">4159-4160 (32-bit)</div>
      </div>
    </div>
    <div class="info-grid" style="margin-top:1rem">
      <div class="info-item"><span class="info-label">锁附时间</span><span class="info-value" id="r_time_ms">--</span></div>
      <div class="info-item"><span class="info-label">流水号</span><span class="info-value" id="r_serial">--</span></div>
      <div class="info-item"><span class="info-label">颗数</span><span class="info-value" id="r_count">--</span></div>
      <div class="info-item"><span class="info-label">JOB / 工序 / 步骤</span><span class="info-value" id="r_jobinfo">--</span></div>
      <div class="info-item" style="grid-column:1/-1"><span class="info-label">时间戳</span><span class="info-value" id="r_rtc">--</span></div>
      <div class="info-item" style="grid-column:1/-1"><span class="info-label">条码</span><span class="info-value" id="r_barcode" style="font-size:0.75rem;word-break:break-all">--</span></div>
    </div>
  </div>
</div>

<!-- Tab 3: 远程控制 -->
<div id="tab-control" class="tab-content">
  <div class="card">
    <div class="alert" style="margin-top:0;margin-bottom:0.8rem">
      <strong>重要:</strong> KL-NTCS-M7 不支持通过 Modbus 写入拧紧参数。只能切换已在控制器上建好的工作/工序。远程启动前请将控制器设为【远程启动】模式。
    </div>

    <h2>工作/工序切换</h2>
    <div class="row" style="align-items:end;margin-bottom:0.8rem">
      <div style="flex:0 0 auto;min-width:140px">
        <label>切换工作编号 (写 463, 范围 1-99/101-170)</label>
        <input id="c_job" type="number" value="1" min="1" max="170">
      </div>
      <div style="flex:0 0 auto;min-width:140px">
        <label>切换工序编号 (写 464, 范围 1-99)</label>
        <input id="c_seq" type="number" value="1" min="1" max="99">
      </div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="c_switchJobBtn" class="success">切换工作</button></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="c_switchSeqBtn" class="warn">切换工序</button></div>
      <span id="c_switchMsg" style="font-size:0.78rem;color:#8899aa;margin-left:0.5rem"></span>
    </div>

    <h2>起子控制</h2>
    <div style="display:flex;gap:0.4rem;flex-wrap:wrap">
      <button id="c_startBtn" class="success">启动 (456=1)</button>
      <button id="c_stopBtn" class="danger">停止 (456=0)</button>
      <button id="c_reverseBtn" class="warn">退螺丝 (457=1)</button>
      <button id="c_confirmBtn">确认解锁 (458=1)</button>
      <button id="c_clearCountBtn">清除颗数 (459=1)</button>
      <button id="c_clearSeqBtn">清除工序 (460=1)</button>
      <button id="c_disableBtn" class="warn">禁用起子 (461=0)</button>
      <button id="c_enableBtn" class="success">启用起子 (461=1)</button>
    </div>
    <div style="margin-top:0.4rem">
      <button id="c_rebootBtn" style="background:#742a2a;width:auto">重启控制器 (462=1)</button>
    </div>
    <div id="c_ctrlMsg" style="margin-top:0.4rem"></div>
  </div>
</div>

<!-- Tab 4: 寄存器浏览器 -->
<div id="tab-registers" class="tab-content">
  <div class="card">
    <h2>读取寄存器</h2>
    <div class="row" style="align-items:end">
      <div style="flex:1"><label>起始地址</label><input id="regStart" type="number" value="4096"></div>
      <div style="flex:1"><label>数量 (max 125)</label><input id="regCount" type="number" value="10" max="125"></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="readRegBtn" class="success">读取</button></div>
    </div>
    <div id="regResult" style="margin-top:0.5rem"></div>
  </div>
  <div class="card">
    <h2>写入单寄存器</h2>
    <div class="row" style="align-items:end">
      <div style="flex:1"><label>地址</label><input id="writeAddr" type="number" value="456"></div>
      <div style="flex:1"><label>值 (0-65535)</label><input id="writeVal" type="number" value="1"></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="writeBtn" class="warn">写入</button></div>
    </div>
    <div id="writeResult" style="margin-top:0.5rem"></div>
  </div>
  <div class="card">
    <h2>快速读取关键区域</h2>
    <div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.5rem">
      <button id="qrRTC" style="width:auto">RTC (4096,6)</button>
      <button id="qrTorque" style="width:auto">扭力 (4155,2)</button>
      <button id="qrResult" style="width:auto">结果区 (4155,10)</button>
      <button id="qrStatus" style="width:auto">状态 (4305,42)</button>
      <button id="qrBarcode" style="width:auto">条码 (4192,50)</button>
      <button id="qrSerial" style="width:auto">流水号 (4285,2)</button>
    </div>
    <div id="qrResultEl" style="margin-top:0.5rem;font-family:'JetBrains Mono',monospace;font-size:0.72rem"></div>
  </div>
</div>

</div>

<script>
const $ = id => document.getElementById(id);

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    $('tab-' + btn.dataset.tab).classList.add('active');
  });
});

async function api(path, body=null) {
  const opts = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {};
  const r = await fetch('/api' + path, opts);
  return r.json();
}

function msgEl(id, text, cls, isHtml) {
  const el = $(id);
  if (isHtml) el.innerHTML = text; else el.textContent = text;
  el.className = cls || '';
}

// ============ 连接 ============

$('connectBtn').addEventListener('click', async () => {
  msgEl('connMsg', '连接中...', '');
  const r = await api('/connect', {ip:$('ip').value, port:parseInt($('port').value), unit_id:parseInt($('unitId').value)});
  if(r.ok) {
    msgEl('connMsg', '已连接 ' + r.ip + ':' + r.port, 'success-msg');
    setTimeout(refreshAll, 300);
    startPolling();
  } else {
    msgEl('connMsg', '连接失败: ' + r.error, 'alert');
  }
});

$('disconnectBtn').addEventListener('click', async () => {
  stopPolling();
  await api('/disconnect', {});
  msgEl('connMsg', '已断开', '');
});

// ============ 状态刷新 ============

function decodeRTC(rtc) {
  const y=rtc.year||0, mo=rtc.month||0, d=rtc.day||0, h=rtc.hour||0, mi=rtc.min||0, s=rtc.sec||0;
  if(!y) return '--';
  return y+'-'+String(mo).padStart(2,'0')+'-'+String(d).padStart(2,'0')+' '+
         String(h).padStart(2,'0')+':'+String(mi).padStart(2,'0')+':'+String(s).padStart(2,'0');
}

const RESULT_MAP = {4:'OK',5:'OK-SEQ',6:'OK-JOB',7:'NG',8:'NS'};
const MODE_MAP = {0:'锁附',1:'退锁'};

async function refreshAll() {
  try {
    const s = await api('/status');

    $('s_conn').innerHTML = s.connected ? '<span class="status-led led-green"></span>已连接' : '<span class="status-led led-red"></span>离线';
    $('s_enable').textContent = s.enabled ? '已启用' : '已禁用';
    $('s_run').textContent = s.running ? '运转中' : '停止';
    $('s_job').textContent = s.currentJob || '--';
    $('s_seq').textContent = s.currentSeq || '--';
    $('s_step').textContent = s.currentStep || '--';
    $('s_count').textContent = s.currentCount || '--';
    $('s_mode').textContent = MODE_MAP[s.toolMode] || s.toolMode || '--';
    $('s_serial').textContent = s.serialNo || '--';
    $('s_time').textContent = s.lastUpdate || '--';

    $('s_torque').textContent = s.torqueRaw !== undefined ? s.torqueRaw : '--';
    $('s_angle').textContent = s.angleRaw !== undefined ? s.angleRaw : '--';
    const rCode = s.resultCode;
    $('s_result').textContent = RESULT_MAP[rCode] || rCode || '--';
    $('s_time_ms').textContent = s.tightenTimeMs ? s.tightenTimeMs + ' ms' : '--';
    $('s_rtc').textContent = decodeRTC(s.rtc);
    $('s_barcode').textContent = s.barcode || '--';

    // Tab 2: 大字体结果
    const badgeMap = {4:'badge-ok',5:'badge-ok',6:'badge-ok',7:'badge-ng',8:'badge-ns'};
    const badgeCls = badgeMap[rCode] || '';
    $('r_badge').innerHTML = rCode ? '<span class="result-badge '+badgeCls+'">'+(RESULT_MAP[rCode]||rCode)+'</span>' : '--';
    $('r_torque').textContent = s.torqueRaw || '--';
    $('r_angle').textContent = s.angleRaw || '--';
    $('r_time_ms').textContent = s.tightenTimeMs ? s.tightenTimeMs + ' ms' : '--';
    $('r_serial').textContent = s.serialNo || '--';
    $('r_count').textContent = s.currentCount || '--';
    $('r_jobinfo').textContent = 'JOB '+(s.currentJob||'?')+' / 工序 '+(s.currentSeq||'?')+' / 步骤 '+(s.currentStep||'?');
    $('r_rtc').textContent = decodeRTC(s.rtc);
    $('r_barcode').textContent = s.barcode || '--';
  } catch(e) { console.error(e); }
}

$('refreshBtn').addEventListener('click', refreshAll);

let pollTimer = null;
function startPolling() { if(pollTimer) clearInterval(pollTimer); pollTimer = setInterval(refreshAll, 1500); }
function stopPolling() { if(pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

// ============ 远程控制 ============

async function ctrlWrite(addr, val, label) {
  const r = await api('/write', {addr, value: val});
  msgEl('c_ctrlMsg', label + ' ('+addr+'='+val+'): ' + (r.ok ? 'OK' : 'FAIL: '+r.error), r.ok ? 'success-msg' : 'alert');
  return r.ok;
}

$('c_startBtn').addEventListener('click', () => ctrlWrite(456, 1, '启动'));
$('c_stopBtn').addEventListener('click', () => ctrlWrite(456, 0, '停止'));
$('c_reverseBtn').addEventListener('click', () => ctrlWrite(457, 1, '退螺丝'));
$('c_confirmBtn').addEventListener('click', () => ctrlWrite(458, 1, '确认解锁'));
$('c_clearCountBtn').addEventListener('click', () => ctrlWrite(459, 1, '清除颗数'));
$('c_clearSeqBtn').addEventListener('click', () => ctrlWrite(460, 1, '清除工序'));
$('c_disableBtn').addEventListener('click', () => ctrlWrite(461, 0, '禁用起子'));
$('c_enableBtn').addEventListener('click', () => ctrlWrite(461, 1, '启用起子'));
$('c_rebootBtn').addEventListener('click', async () => {
  if (!confirm('确定要重启控制器吗？')) return;
  await ctrlWrite(462, 1, '重启控制器');
});

$('c_switchJobBtn').addEventListener('click', async () => {
  const job = parseInt($('c_job').value);
  if (job < 1 || (job > 99 && job < 101) || job > 170) {
    msgEl('c_switchMsg', '工作编号范围: 1-99, 101-170', 'alert'); return;
  }
  msgEl('c_switchMsg', '切换中...', '');
  const r = await api('/write', {addr: 463, value: job});
  if (r.ok) { msgEl('c_switchMsg', '已切换到 JOB '+job, 'success-msg'); setTimeout(refreshAll, 500); }
  else msgEl('c_switchMsg', '切换失败: '+r.error, 'alert');
});

$('c_switchSeqBtn').addEventListener('click', async () => {
  const seq = parseInt($('c_seq').value);
  if (seq < 1 || seq > 99) { msgEl('c_switchMsg', '工序编号范围: 1-99', 'alert'); return; }
  msgEl('c_switchMsg', '切换中...', '');
  const r = await api('/write', {addr: 464, value: seq});
  if (r.ok) { msgEl('c_switchMsg', '已切换到工序 '+seq, 'success-msg'); setTimeout(refreshAll, 500); }
  else msgEl('c_switchMsg', '切换失败: '+r.error, 'alert');
});

// ============ 寄存器浏览器 ============

$('readRegBtn').addEventListener('click', async () => {
  const start = parseInt($('regStart').value);
  const count = parseInt($('regCount').value);
  const r = await api('/registers', {start, count});
  if(r.ok) {
    let html = '<div class="reg-wrap"><table class="reg-table"><thead><tr><th>地址</th><th>Dec</th><th>Hex</th><th>ASCII</th></tr></thead><tbody>';
    for(let i=0; i<r.values.length; i++) {
      let v = r.values[i], addr = start+i, cls = v !== 0 ? 'non-zero' : 'zero';
      let hi = String.fromCharCode((v>>8)&0xFF), lo = String.fromCharCode(v&0xFF);
      let ascii = (hi >= ' ' && hi <= '~' ? hi : '.') + (lo >= ' ' && lo <= '~' ? lo : '.');
      html += '<tr class="'+cls+'"><td>'+addr+'</td><td>'+v+'</td><td>0x'+v.toString(16).toUpperCase().padStart(4,'0')+'</td><td>'+ascii+'</td></tr>';
    }
    html += '</tbody></table></div>';
    $('regResult').innerHTML = html;
  } else {
    $('regResult').innerHTML = '<div class="alert">' + r.error + '</div>';
  }
});

$('writeBtn').addEventListener('click', async () => {
  const addr = parseInt($('writeAddr').value), val = parseInt($('writeVal').value);
  const r = await api('/write', {addr, value: val});
  msgEl('writeResult', r.ok ? '写入成功: ['+addr+'] = '+val : '写入失败: '+r.error, r.ok ? 'success-msg' : 'alert');
});

async function quickRead(start, count, label) {
  const r = await api('/registers', {start, count});
  const el = $('qrResultEl');
  if (!r.ok) { el.textContent = label + ' FAIL: ' + r.error; return; }
  let html = '<b>'+label+'</b> ('+start+', '+count+'):<br>';
  for (let i=0; i<r.values.length; i++) {
    const addr = start+i, v = r.values[i];
    html += '['+addr+']=<span style="color:'+(v?'#f6e05e':'#4a5568')+'">'+v+'</span> ';
  }
  el.innerHTML = html;
}
$('qrRTC').addEventListener('click', () => quickRead(4096, 6, 'RTC'));
$('qrTorque').addEventListener('click', () => quickRead(4155, 2, '扭力(32bit)'));
$('qrResult').addEventListener('click', () => quickRead(4155, 10, '结果区'));
$('qrStatus').addEventListener('click', () => quickRead(4305, 42, '状态区'));
$('qrBarcode').addEventListener('click', () => quickRead(4192, 50, '条码'));
$('qrSerial').addEventListener('click', () => quickRead(4285, 2, '流水号'));

refreshAll();
</script>
</body>
</html>"""
