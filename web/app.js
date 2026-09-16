'use strict';
const $ = id => document.getElementById(id);
const clone = v => JSON.parse(JSON.stringify(v));
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {open:'开盘价',high:'最高价',low:'最低价',close:'收盘价',volume:'成交量'};
const kinds = {sma:'SMA 均线',ema:'EMA 指数均线',rsi:'RSI 相对强弱',macd:'MACD',roc:'ROC 涨跌幅 %',momentum_score:'加权动量评分',atr:'ATR 真实波幅',highest:'窗口最高值',lowest:'窗口最低值'};
const operators = {gt:'大于 >',gte:'大于等于 ≥',lt:'小于 <',lte:'小于等于 ≤',eq:'等于 =',cross_above:'向上穿越 ↑',cross_below:'向下穿越 ↓'};
const state = {config:null,presets:{},csv:null,dataMode:'market',modeDrafts:{},jsonMode:false,complex:false,report:null,result:null,busy:false};
const opts = (values, selected, labels={}) => values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(labels[v]||v)}</option>`).join('');
const refs = () => [...Object.keys(names),...Object.keys(state.config.indicators)];
const setStatus = (text,type='') => { $('status').textContent=text; $('status').className=type; };
const dateInChina = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
function marketDates(){const d=new Date(dateInChina()+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-1);const end=d.toISOString().slice(0,10);d.setUTCFullYear(d.getUTCFullYear()-2);return [d.toISOString().slice(0,10),end];}
function marketDefaults(c){const next=clone(c),[start,end]=marketDates();next.universe=['510300','518880','511010'];next.benchmark='510300';next.start=start;next.end=end;next.selection.max_positions=Math.min(next.selection.max_positions,3);return next;}
function updateSourceLabel(){const mode=state.dataMode,c=state.config;const badge=$('source-badge');$('data-source').value=mode;
 if(mode==='market'){badge.innerHTML='真实行情 · 公开接口<span>前复权 · PostgreSQL 缓存</span>';$('data-name').textContent=c.universe.join(' · ');}
 else if(mode==='uploaded'){badge.textContent='本地导入行情 · 请确认数据口径';}
 else{badge.innerHTML='合成演示数据<span>不代表真实市场表现</span>';$('data-name').textContent='800 个模拟交易日 · 3 个资产';}
 badge.classList.toggle('uploaded',mode!=='synthetic_demo');$('reset-data').classList.toggle('hidden',mode==='synthetic_demo');}
function switchSource(mode){if(mode==='uploaded'&&!state.csv)throw new Error('请先导入行情 CSV');
 const before=collect();state.modeDrafts[state.dataMode]=before;
 let next=state.modeDrafts[mode]||clone(before);
 if(mode==='market'&&!state.modeDrafts.market&&next.universe.every(c=>c.startsWith('DEMO_')))next=marketDefaults(next);
 if(mode==='synthetic_demo'&&!state.modeDrafts.synthetic_demo)next=clone(state.presets[$('preset').value]);
 state.dataMode=mode;state.config=next;render();updateSourceLabel();dirty();}

const editableCondition = n => n && typeof n.left==='string' && refs().includes(n.left) && n.op in operators && (typeof n.right==='number'||refs().includes(n.right));
const simple = r => r && (editableCondition(r) || ((r.all||r.any) && (r.all||r.any).every(editableCondition)));

function renderRules(which){
 const node=state.config[which];
 if(!simple(node))return;
 const group=node.any?'any':'all'; $(which+'-mode').value=group;
 const conditions=node.left!==undefined?[node]:node[group];
 $(which+'-rows').innerHTML=conditions.map(c=>`<div class="rule-row">
 <select class="left" aria-label="${which==='entry'?'入场':'退出'}指标">${opts(refs(),c.left,names)}</select>
 <select class="operator" aria-label="比较方式">${opts(Object.keys(operators),c.op,operators)}</select>
 <button class="remove" aria-label="删除条件">×</button>
 <div class="operand"><select class="right-kind" aria-label="比较对象">${opts(['constant',...refs()],typeof c.right==='number'?'constant':c.right,{constant:'数值',...names})}</select><input class="right-value ${typeof c.right==='number'?'':'hidden'}" type="number" step="any" aria-label="比较数值" value="${typeof c.right==='number'?c.right:0}"></div></div>`).join('');
 $(which+'-rows').querySelectorAll('.right-kind').forEach(el=>el.addEventListener('change',()=>el.nextElementSibling.classList.toggle('hidden',el.value!=='constant')));
 $(which+'-rows').querySelectorAll('.remove').forEach(el=>el.addEventListener('click',()=>{
  if($(which+'-rows').children.length<=1){setStatus('至少保留一个条件；常量规则可在 JSON 中设置。','error');return;}el.parentElement.remove();dirty();
 }));
}
function readRule(which){return {[$(which+'-mode').value]:[...$(which+'-rows').children].map(row=>({left:row.querySelector('.left').value,op:row.querySelector('.operator').value,right:row.querySelector('.right-kind').value==='constant'?Number(row.querySelector('.right-value').value):row.querySelector('.right-kind').value}))};}
function renderIndicators(){
 $('indicator-count').textContent=`· ${Object.keys(state.config.indicators).length} 项`;
 $('indicators').innerHTML=Object.entries(state.config.indicators).map(([id,s])=>`<div class="indicator-row" data-id="${esc(id)}"><div class="indicator-id"><strong>${esc(id)}</strong><button class="remove" aria-label="删除指标 ${esc(id)}">×</button></div><label>指标类型<select data-param="kind">${opts(Object.keys(kinds),s.kind,kinds)}</select></label><label>价格字段<select data-param="field">${opts(Object.keys(names),s.field||'close',names)}</select></label>${s.kind==='macd'?['fast','slow','signal'].map((p,i)=>`<label>${['快周期','慢周期','信号周期'][i]}<input type="number" min="2" max="500" data-param="${p}" value="${s[p]||[12,26,9][i]}"></label>`).join('')+`<label>输出<select data-param="output">${opts(['hist','line','signal'],s.output||'hist',{hist:'柱值（不乘2）',line:'DIF',signal:'DEA'})}</select></label>`:`<label>周期<input data-param="period" type="number" min="2" max="500" value="${s.period||20}"></label>`}</div>`).join('');
 $('indicators').querySelectorAll('[data-param=kind]').forEach(el=>el.addEventListener('change',()=>{
  const id=el.closest('.indicator-row').dataset.id;const c=collect();
  c.indicators[id]=el.value==='macd'?{kind:'macd',fast:12,slow:26,signal:9,output:'hist'}:{kind:el.value,period:el.value==='rsi'?14:20};state.config=c;renderIndicators();dirty();
 }));
 $('indicators').querySelectorAll('.remove').forEach(el=>el.addEventListener('click',()=>{
  const id=el.closest('.indicator-row').dataset.id;const c=collect();
  if(JSON.stringify([c.entry,c.exit,c.selection.rank_by]).includes(JSON.stringify(id))){setStatus('这个指标仍被条件或候选排名引用，请先移除引用。','error');return;}
  delete c.indicators[id];state.config=c;render();dirty();
 }));
}
function collect(){
 if(state.jsonMode)return JSON.parse($('strategy-json').value);
 const c=clone(state.config);c.name=$('strategy-name').value;c.universe=$('universe').value.split(',').map(s=>s.trim()).filter(Boolean);c.benchmark=$('benchmark').value.trim();
 c.start=$('start').value;c.end=$('end').value;
 c.selection={max_positions:Number($('max-positions').value),rank_by:$('rank-by').value,descending:$('rank-order').value==='desc',mode:$('selection-mode').value};
 c.execution={initial_cash:Number($('capital').value),commission_rate:Number($('commission').value)/100,min_commission:Number($('min-fee').value),slippage:Number($('slippage').value)/100,lot_size:Number($('lot').value),max_exposure:Number($('exposure').value)/100};
 if(!state.complex){c.entry=readRule('entry');c.exit=readRule('exit');}
 c.indicators={};$('indicators').querySelectorAll('.indicator-row').forEach(row=>{const spec={};row.querySelectorAll('[data-param]').forEach(el=>spec[el.dataset.param]=el.tagName==='INPUT'?Number(el.value):el.value);c.indicators[row.dataset.id]=spec;});
 return c;
}
function render(){
 const c=state.config;
 if(!c||!c.execution||!c.selection||!c.indicators||!Array.isArray(c.universe))throw new Error('策略 JSON 缺少 execution / selection / indicators / universe');
 $('strategy-name').value=c.name;$('universe').value=c.universe.join(',');$('benchmark').value=c.benchmark;
 $('start').value=c.start||'';$('end').value=c.end||'';$('capital').value=c.execution.initial_cash;
 $('max-positions').value=c.selection.max_positions;$('exposure').value=c.execution.max_exposure*100;
 $('rank-by').innerHTML=opts(refs(),c.selection.rank_by,names);$('rank-order').value=c.selection.descending?'desc':'asc';$('selection-mode').value=c.selection.mode;
 $('commission').value=+(c.execution.commission_rate*100).toFixed(8);$('min-fee').value=c.execution.min_commission;$('slippage').value=+(c.execution.slippage*100).toFixed(8);$('lot').value=c.execution.lot_size;
 state.complex=!simple(c.entry)||!simple(c.exit);$('complex-notice').classList.toggle('hidden',!state.complex);$('rule-editors').classList.toggle('hidden',state.complex);
 renderIndicators();if(!state.complex){renderRules('entry');renderRules('exit');}
 $('strategy-json').value=JSON.stringify(c,null,2);
}
function tab(json){
 const previous=state.config,previousMode=state.jsonMode;
 try {state.config=collect();state.jsonMode=json;render();$('visual-editor').classList.toggle('hidden',json);$('json-editor').classList.toggle('hidden',!json);
 $('visual-tab').classList.toggle('active',!json);$('json-tab').classList.toggle('active',json);$('visual-tab').setAttribute('aria-selected',String(!json));$('json-tab').setAttribute('aria-selected',String(json));
 document.querySelectorAll('.builder > details').forEach(d=>d.classList.toggle('hidden',json));
 document.querySelector('.run-inputs').classList.toggle('hidden',json);dirty();
 }catch(e){state.config=previous;state.jsonMode=previousMode;setStatus('配置未应用：'+e.message,'error');}
}
function dirty(){if(state.report&&!state.busy)setStatus('参数已修改。当前结果仍属于上一次运行，请重新回测。');}
function download(name,text,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function num(v,n=2){return v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:n,minimumFractionDigits:n});}
function pct(v){return v==null?'—':num(v*100)+'%';}
function showReport(bundle){
 state.report=bundle;state.result=bundle.result;const r=state.result,m=r.metrics;
 $('empty').classList.add('hidden');$('report').classList.remove('hidden');
 $('run-summary').textContent=`回测完成 · ${r.engine==='go'?'Go':'Python'} · ${r.metrics.sessions} 个交易日`;
 $('metric-cards').innerHTML=[['累计收益',pct(m.total_return),'日净值，已扣交易成本',m.total_return>=0?'positive':'negative'],['最大回撤',pct(m.max_drawdown),'包含未平仓期间的回撤',''],['Sharpe',num(m.sharpe),'日收益 · 无风险利率 0',''],['Calmar',num(m.calmar),'年化收益 ÷ 最大回撤','']].map(([label,value,note,cls])=>`<div class="metric-card"><span>${label}</span><strong class="${cls}">${value}</strong><small>${note}</small></div>`).join('');
 const risk=[['年化收益',pct(m.annual_return)],['基准收益',pct(m.benchmark_return)],['建仓 / 已平仓',`${m.entries} / ${m.closed_trades}`],['平仓胜率',pct(m.win_rate)],['佣金 + 滑点成本',num(m.total_costs)],['平均风险仓位',pct(m.average_exposure)],['最大回撤恢复',m.max_drawdown_recovery_days==null?'截至末日未恢复':m.max_drawdown_recovery_days+' 个交易日'],['最长水下时间',m.longest_underwater_days+' 个交易日'],['未执行订单',r.rejected.length+' 笔']];
 $('risk-metrics').innerHTML=risk.map(([label,value])=>`<div class="risk-item">${label}<strong>${esc(value)}</strong></div>`).join('');
 const stale=r.equity.filter(p=>p.stale_symbols.length).length;
 const providerNames={eastmoney:'东方财富',tencent:'腾讯'};
 const providers=bundle.source==='market'?Object.entries(bundle.source_meta.symbol_providers).map(([symbol,source])=>`${symbol} ${providerNames[source]||source}`).join('、'):'';
 $('data-note').textContent=(bundle.source==='synthetic_demo'?'本结果使用合成演示行情，只用于检查规则和引擎。':bundle.source==='market'?`本结果使用前复权日线（${providers}）；${bundle.source_meta.fetched_symbols.length} 只资产从公开接口更新，${bundle.source_meta.cached_symbols.length} 只直接命中 PostgreSQL 缓存。行情不包含涨跌停价，分红及复权修订仍需核对。`:'本结果使用你导入的行情；请确认复权、上市时间和数据来源。')+(stale?` 有 ${stale} 天持仓缺失行情，暂沿用上次收盘估值，请检查完整报告。`:'');
 $('range-label').textContent=`${r.equity[0].date} — ${r.equity.at(-1).date} · ${m.sessions} 个交易日`;$('result-name').textContent=r.strategy_name;
 $('fill-count').textContent=`· ${r.fills.length} 笔`;
 $('fills').innerHTML=r.fills.length?r.fills.slice(-100).reverse().map(f=>`<tr><td>${esc(f.date)}<small>信号 ${esc(f.signal_date)}</small></td><td>${esc(f.symbol)}</td><td class="${f.side==='buy'?'positive':'negative'}">${f.side==='buy'?'买入':'卖出'}</td><td>${num(f.quantity,0)}</td><td>${num(f.price,4)}</td><td>${num(f.fee)}</td></tr>`).join(''):'<tr><td colspan="6">没有成交。请检查规则、指标预热和可用资金；完整报告中可查看目标与拒单原因。</td></tr>';
 drawChart(r,bundle.strategy.execution.initial_cash);
}
function drawChart(r,initial){
 const a=r.equity,W=900,H=280,L=55,R=18,T=15,B=30,values=a.flatMap(p=>[p.equity/initial,p.benchmark/initial]);let lo=Infinity,hi=-Infinity;for(const value of values){lo=Math.min(lo,value);hi=Math.max(hi,value);}const pad=Math.max((hi-lo)*.12,.02);lo-=pad;hi+=pad;
 const x=i=>L+i/Math.max(1,a.length-1)*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
 let svg='';for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4,Y=y(value);svg+=`<line x1="${L}" y1="${Y}" x2="${W-R}" y2="${Y}" stroke="#e9eef1"/><text x="${L-10}" y="${Y+4}" text-anchor="end" fill="#8c9aa5" font-size="10">${value.toFixed(2)}</text>`;}
 for(const i of [0,Math.floor((a.length-1)/2),a.length-1])svg+=`<text x="${x(i)}" y="${H-5}" text-anchor="${i===0?'start':i===a.length-1?'end':'middle'}" fill="#8c9aa5" font-size="10">${esc(a[i].date)}</text>`;
 const path=key=>a.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+','+y(p[key]/initial).toFixed(2)).join(' ');
 svg+=`<path d="${path('equity')} L${x(a.length-1)},${H-B} L${L},${H-B} Z" fill="#e9f5f1"/><path d="${path('benchmark')}" fill="none" stroke="#b1bcc7" stroke-width="1.7"/><path d="${path('equity')}" fill="none" stroke="#098a79" stroke-width="2.2"/>`;
 $('chart').innerHTML=svg;
 $('chart').onpointermove=e=>{const rect=$('chart').getBoundingClientRect();const unit=(e.clientX-rect.left)/rect.width*W;const i=Math.max(0,Math.min(a.length-1,Math.round((unit-L)/(W-L-R)*(a.length-1))));const p=a[i];$('chart-tooltip').textContent=`${p.date} ｜净值 ${num(p.equity/initial,4)} ｜仓位 ${pct(p.exposure)}`;$('chart-tooltip').classList.remove('hidden');};$('chart').onpointerleave=()=>$('chart-tooltip').classList.add('hidden');
}
async function run(){
 if(state.busy)return;
 try{const config=collect();state.busy=true;$('run').disabled=true;$('run').textContent='计算中…';setStatus(state.dataMode==='market'?'正在查库；缺失或过期的行情会从公开接口拉取并入库。':'正在使用本地数据回放订单并计算日净值。');
 const response=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:$('engine').value,strategy:config,source:state.dataMode,csv:state.dataMode==='uploaded'?state.csv:null})});const bundle=await response.json();if(!response.ok)throw new Error(bundle.error||'回测失败');showReport(bundle);setStatus('回测完成。结果保留了策略配置、数据指纹、每日目标与全部成交。','success');
 }catch(e){setStatus('无法完成回测：'+e.message,'error');}finally{state.busy=false;$('run').disabled=false;$('run').innerHTML='运行回测 <span>→</span>';}
}
function csvRows(text){const rows=[];let row=[],cell='',quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(cell);cell='';}else if(c==='\n'&&!quoted){row.push(cell.replace(/\r$/,''));if(row.some(Boolean))rows.push(row);row=[];cell='';}else cell+=c;}if(quoted)throw new Error('CSV 引号未闭合');if(cell||row.length){row.push(cell.replace(/\r$/,''));rows.push(row);}return rows;}
$('visual-tab').onclick=()=>tab(false);$('json-tab').onclick=()=>tab(true);$('apply-json').onclick=()=>tab(false);
$('run').onclick=run;
$('preset').onchange=()=>{try{let old=state.config?collect():null;state.config=clone(state.presets[$('preset').value]);if(state.dataMode!=='synthetic_demo'&&old){state.config.universe=old.universe;state.config.benchmark=old.benchmark;state.config.start=old.start;state.config.end=old.end;state.config.selection.max_positions=Math.min(state.config.selection.max_positions,old.universe.length);}render();updateSourceLabel();dirty();}catch(e){setStatus(e.message,'error');}};
document.querySelectorAll('[data-add]').forEach(el=>el.onclick=()=>{try{state.config=collect();const which=el.dataset.add;state.config[which][$(which+'-mode').value].push({left:'rsi14' in state.config.indicators?'rsi14':'close',op:'gt',right:0});renderRules(which);dirty();}catch(e){setStatus(e.message,'error');}});
$('add-indicator').onclick=()=>{try{state.config=collect();let n=1;while(state.config.indicators['indicator'+n])n++;state.config.indicators['indicator'+n]={kind:'ema',period:20};render();dirty();}catch(e){setStatus(e.message,'error');}};
$('export-config').onclick=()=>{try{download('strategy.json',JSON.stringify(collect(),null,2),'application/json');}catch(e){setStatus(e.message,'error');}};
$('export-result').onclick=()=>{if(state.report)download('experiment.json',JSON.stringify(state.report,null,2),'application/json');};
$('export-trades').onclick=()=>{if(!state.result)return;const columns=['date','signal_date','symbol','side','quantity','price','fee'];const cell=v=>'"'+String(v).replaceAll('"','""')+'"';download('trades.csv',columns.join(',')+'\n'+state.result.fills.map(f=>columns.map(c=>cell(f[c])).join(',')).join('\n'),'text/csv');};
$('download-demo').onclick=async()=>{try{const response=await fetch('/api/demo');download('demo-synthetic.csv',await response.text(),'text/csv');}catch(e){setStatus(e.message,'error');}};
$('json-file').onchange=async e=>{const previous=state.config;try{const f=e.target.files[0];if(!f)return;if(f.size>100000)throw new Error('策略文件过大');const config=JSON.parse(await f.text());state.config=config;render();dirty();}catch(err){state.config=previous;setStatus('导入失败：'+err.message,'error');}e.target.value='';};
$('data-source').onchange=e=>{try{switchSource(e.target.value);if(e.target.value==='market')setStatus('真实行情已选择；请核对六位代码与日期，运行时自动查库和补齐。');}catch(err){$('data-source').value=state.dataMode;setStatus(err.message,'error');}};
$('csv-file').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;if(f.size>8*1024*1024)throw new Error('CSV 文件请小于 8 MB');const text=await f.text();const rows=csvRows(text.replace(/^\uFEFF/,''));const header=rows.shift()||[];const col=header.indexOf('symbol'),dateCol=header.indexOf('date');if(col<0||dateCol<0||!rows.length)throw new Error('需要 date、symbol 和 OHLCV 列');const symbols=[...new Set(rows.map(r=>r[col]))].sort(),days=[...new Set(rows.map(r=>r[dateCol]))].sort();state.modeDrafts[state.dataMode]=collect();state.config=clone(state.modeDrafts[state.dataMode]);state.csv=text;state.dataMode='uploaded';$('uploaded-option').disabled=false;state.config.universe=symbols.slice(0,3);state.config.benchmark=symbols[0];state.config.start=days[0];state.config.end=days.at(-1);state.config.selection.max_positions=Math.min(state.config.selection.max_positions,state.config.universe.length);render();updateSourceLabel();$('data-name').textContent=`${f.name} · ${days.length} 天 · ${symbols.length} 个资产`;setStatus('行情已导入。默认选取前 3 个资产，可在资产代码中调整。');dirty();}catch(err){setStatus('导入失败：'+err.message,'error');}e.target.value='';};
$('reset-data').onclick=()=>{try{switchSource('synthetic_demo');setStatus('已切换到合成演示数据；此数据不能用于判断策略收益。');}catch(e){setStatus(e.message,'error');}};
document.querySelector('.workspace').addEventListener('input',dirty);
(async()=>{try{$('run').disabled=true;const response=await fetch('/api/presets');state.presets=await response.json();state.config=marketDefaults(state.presets.trend);render();updateSourceLabel();$('run').disabled=false;try{const ready=await (await fetch('/api/market/status')).json();setStatus(ready.ready?'PostgreSQL 已就绪。真实行情回测会先查库，再按需更新。':ready.message,'ready' in ready&&!ready.ready?'error':'');}catch(e){setStatus('无法检查数据库状态：'+e.message,'error');}}catch(e){setStatus('初始化失败：'+e.message,'error');}})();
