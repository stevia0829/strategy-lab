# -*- coding: utf-8 -*-
"""聚宽 B 版信号的 Strategy Lab 日线适配，用于口径对比。

源策略由用户提供；信号尽量保持一致。这里的成交统一发生在次日开盘，
无法复刻聚宽 09:35 卖出、09:36 买入和基金固定 0.001 元滑点。
"""
import math

ENABLE_ROTATION_GUARD = True


REGIME_AWARE_ROTATION = True


MIN_HISTORY_DAYS = 60  # A/B 同为 60；另测 0 时必须同时修改两组


FAST_WINDOW = 5


MONITOR_WINDOW = 10


MONITOR_TOP_K = 3


ENTER_CHURN = 0.40


EXIT_CHURN = 0.20


ENTER_CONFIRM = 3


EXIT_CONFIRM = 5


ETF_POOL = [
    '518880.XSHG', '161226.XSHE', '501018.XSHG', '159985.XSHE',
    '513520.XSHG', '513100.XSHG', '513300.XSHG', '513400.XSHG',
    '159529.XSHE', '513030.XSHG', '159329.XSHE', '513130.XSHG',
    '513090.XSHG', '513120.XSHG', '159206.XSHE', '159218.XSHE',
    '159227.XSHE', '159565.XSHE', '562500.XSHG', '159819.XSHE',
    '159363.XSHE', '512480.XSHG', '512760.XSHG', '515880.XSHG',
    '515230.XSHG', '515050.XSHG', '159786.XSHE', '159890.XSHE',
    '516160.XSHG', '515790.XSHG', '159755.XSHE', '512660.XSHG',
    '159732.XSHE', '159992.XSHE', '159852.XSHE', '159851.XSHE',
    '159869.XSHE', '516780.XSHG', '159928.XSHE', '512690.XSHG',
    '515170.XSHG', '512010.XSHG', '512980.XSHG', '159378.XSHE',
    '159611.XSHE', '159766.XSHE', '515220.XSHG', '159865.XSHE',
    '562800.XSHG', '560860.XSHG', '510050.XSHG', '510300.XSHG',
    '159922.XSHE', '159531.XSHE', '159915.XSHE', '588080.XSHG',
    '588380.XSHG', '160211.XSHE', '512000.XSHG', '512800.XSHG',
    '510880.XSHG', '511090.XSHG',
]


MONITOR_GROUPS = {
    '513100.XSHG': 'nasdaq', '513300.XSHG': 'nasdaq',
    '159206.XSHE': 'satellite', '159218.XSHE': 'satellite',
    '512480.XSHG': 'chip', '512760.XSHG': 'chip',
    '515880.XSHG': 'communication', '515050.XSHG': 'communication',
    '515230.XSHG': 'software', '159852.XSHE': 'software',
}


def positive(value):
    return value is not None and math.isfinite(value) and value > 0


def momentum_score(prices, window=21):
    """与 Go 相同：回归使用 w²，R² 使用 w，保留原策略的混合权重口径。"""
    if window < 2 or len(prices) < window or not all(positive(v) for v in prices[-window:]):
        return None
    y = [math.log(v) for v in prices[-window:]]
    weights = [1.0 + i / float(window - 1) for i in range(window)]
    fw = [v * v for v in weights]
    sw = sum(fw)
    sx = sum(fw[i] * i for i in range(window))
    sy = sum(fw[i] * y[i] for i in range(window))
    sxx = sum(fw[i] * i * i for i in range(window))
    sxy = sum(fw[i] * i * y[i] for i in range(window))
    slope = (sw * sxy - sx * sy) / (sw * sxx - sx * sx)
    intercept = (sy - slope * sx) / sw
    mean = sum(y) / window
    total = sum(weights[i] * (y[i] - mean) ** 2 for i in range(window))
    residual = sum(weights[i] * (y[i] - slope * i - intercept) ** 2 for i in range(window))
    r2 = 1 - residual / total if total > 1e-15 else 0.0
    try:
        score = math.expm1(slope * 250) * r2
    except OverflowError:
        return None
    return score if math.isfinite(score) else None


def eligible(history, code, end, min_history):
    """日历对齐，不跨缺失日拼接价格；上市不足不参与，昨日停牌不参与排名。"""
    row = history[code]
    need = max(21, min_history)
    if end + 1 < need or not row['tradable'][end]:
        return False
    return all(positive(v) for v in row['close'][end + 1 - need:end + 1])


def rank_at(history, end, min_history=MIN_HISTORY_DAYS):
    """只看 end 及之前：保留原 0~6 分过滤，以及过热加速赢家独占排名。"""
    normal, hot = [], []
    for code in ETF_POOL:
        if code not in history or not eligible(history, code, end, min_history):
            continue
        prices = history[code]['close'][:end + 1]
        score = momentum_score(prices)
        if score is None:
            continue
        if 0 <= score <= 6:
            normal.append((code, score))
        elif score > 6:
            previous = momentum_score(prices[:-1])
            if previous is None or score >= previous * 1.1:
                hot.append((code, score))
    # 同分沿用固定池顺序，避免排序噪声制造换手。
    return sorted(hot if hot else normal, key=lambda row: -row[1])


def rotation_metrics(history, end):
    """经验监测量；适用于缺乏延续的震荡，稳定下跌可能漏报，急反弹可能误报。

    速度：近 10 日前 3 组的平均日更换率，按 5 日收益排名。
    失效：当时原动量前 3 个不同组的赢家，下一日收盘到收盘收益，滚动复合。
    后者是零成本诊断，不是开盘可成交收益，不作为策略绩效汇报。
    """
    start = end - MONITOR_WINDOW
    if start < max(21, MIN_HISTORY_DAYS, FAST_WINDOW + 1) - 1:
        return None
    # 速度监测组在窗口起点固定：不让窗口中新增上市/成熟标的制造热点切换。
    groups = {}
    for code in ETF_POOL:
        if code not in history or not eligible(history, code, start, MIN_HISTORY_DAYS):
            continue
        group = MONITOR_GROUPS.get(code, code)
        groups.setdefault(group, []).append(code)
    if len(groups) < max(8, MONITOR_TOP_K):
        return None
    # 起点已入组的任何标的停牌/缺失，标记监测不可用，不能解释成正常或高切换。
    for members in groups.values():
        for code in members:
            row = history[code]
            if not all(row['tradable'][start:end + 1]):
                return None
            if not all(positive(v) for v in row['close'][start - FAST_WINDOW:end + 1]):
                return None
    previous_top = None
    replacements = []
    continuation = 1.0
    for day in range(start, end + 1):
        group_returns = []
        for group, members in groups.items():
            returns = [history[c]['close'][day] / history[c]['close'][day - FAST_WINDOW] - 1
                       for c in members]
            group_returns.append((group, sum(returns) / len(returns)))
        group_returns.sort(key=lambda row: (-row[1], row[0]))
        top = set(row[0] for row in group_returns[:MONITOR_TOP_K])
        if previous_top is not None:
            replacements.append(1 - len(top & previous_top) / float(MONITOR_TOP_K))
        previous_top = top
        if day == end:
            break
        # 按 day 的实际原策略排名去重；不拿 day+1 的赢家回填 day。
        leaders, seen = [], set()
        for code, score in rank_at(history, day):
            group = MONITOR_GROUPS.get(code, code)
            if group not in seen:
                seen.add(group)
                leaders.append(code)
            if len(leaders) == MONITOR_TOP_K:
                break
        returns = []
        for code in leaders:
            prices = history[code]['close']
            if not positive(prices[day + 1]) or not history[code]['tradable'][day + 1]:
                return None
            returns.append(prices[day + 1] / prices[day] - 1)
        # 没有合格赢家时诊断组合视为空仓，计 0，不虚构亏损。
        continuation *= 1 + (sum(returns) / len(returns) if returns else 0)
    return {'churn': sum(replacements) / len(replacements),
            'continuation': continuation - 1, 'groups': len(groups)}


def classify_regime(prices):
    """沿用 Go 的 MA20/60/120 与近 60 日最大回撤；历史不足返回未知。"""
    if len(prices) < 120 or not all(positive(v) for v in prices[-120:]):
        return ''
    price = prices[-1]
    ma20, ma60, ma120 = [sum(prices[-n:]) / n for n in (20, 60, 120)]
    peak, dd = prices[-60], 0.0
    for value in prices[-60:]:
        peak = max(peak, value)
        dd = max(dd, 1 - value / peak)
    if price < ma120 and dd >= 0.08:
        return 'risk_off'
    if price < ma60 and ma60 < ma120:
        return 'bear'
    if price > ma20 > ma60 > ma120:
        return 'bull'
    if price > ma60:
        return 'neutral_up'
    return 'neutral'


def next_guard(state, metrics, trend, enabled, regime_aware):
    """纯状态转移；确认只计交易日，数据缺失打断连续性但不解除已有防守。

    经验机制：进出使用不同阈值与确认长度，减轻反复切换。默认只在弱市/未知
    生效；强市旁路并复位。代价是指数状态来回切换时仍可能提前恢复风险。
    """
    new = dict(state)
    if not enabled or (regime_aware and trend not in ('bear', 'risk_off', '')):
        return {'mode': 'normal', 'bad_days': 0, 'good_days': 0}
    if metrics is None:
        new['bad_days'], new['good_days'] = 0, 0
        if new['mode'] != 'defensive':
            new['mode'] = 'normal'
        return new
    bad = metrics['churn'] >= ENTER_CHURN and metrics['continuation'] < 0
    good = metrics['churn'] <= EXIT_CHURN and metrics['continuation'] > 0
    if new['mode'] == 'defensive':
        new['good_days'] = new['good_days'] + 1 if good else 0
        if new['good_days'] >= EXIT_CONFIRM:
            return {'mode': 'normal', 'bad_days': 0, 'good_days': 0}
    else:
        new['bad_days'] = new['bad_days'] + 1 if bad else 0
        new['good_days'] = 0
        new['mode'] = ('defensive' if new['bad_days'] >= ENTER_CONFIRM
                       else 'observe' if bad else 'normal')
    return new


# 状态只在同一次回测进程里延续，不会写入磁盘。
_guard = {'mode': 'normal', 'bad_days': 0, 'good_days': 0}
_last_signal = None


def _aligned_history(ctx):
    """以沪深300日历对齐最近 120 根日线，上市前保留空值。"""
    master = ctx['history'].get('000300', [])
    days = [bar['date'] for bar in master if bar['date'] <= ctx['date']][-120:]
    if len(days) < 120:
        return None, None
    history = {}
    for code in ETF_POOL:
        short = code[:6]
        bars = ctx['history'].get(short, [])
        mapped = {bar['date']: bar for bar in bars if bar['date'] <= ctx['date']}
        if not mapped:
            continue
        first = min(mapped)
        closes = []
        tradable = []
        last_close = None
        for day in days:
            if day < first:
                closes.append(None)
                tradable.append(False)
            elif day in mapped:
                bar = mapped[day]
                last_close = float(bar['close'])
                closes.append(last_close)
                tradable.append(bar['volume'] > 0)
            else:
                # 新浪原始日线省略停牌/跨市场休市日；聚宽 skip_paused=False
                # 通常保留该日并标记 paused。信号沿用上次收盘，禁止当日交易。
                # 引擎输入仍保留缺日，由引擎记录拒单，不伪造成交。
                if last_close is None:
                    raise ValueError('{} 在 {} 缺少首个有效收盘'.format(short, day))
                closes.append(last_close)
                tradable.append(False)
        history[code] = {'close': closes, 'tradable': tradable}
    if '510300.XSHG' not in history:
        raise ValueError('510300 行情缺失')
    return history, len(days) - 1


def decide(ctx):
    """按昨日收盘形成目标；异常时维持真实持仓，不把缺数据当清仓。"""
    global _guard, _last_signal
    if _last_signal == ctx['date']:
        return [code for code, qty in ctx['positions'].items() if qty > 0]
    _last_signal = ctx['date']
    held = [code for code, qty in ctx['positions'].items() if qty > 0]
    try:
        history, end = _aligned_history(ctx)
        if history is None:
            return held
        ranked = rank_at(history, end)
        trend = classify_regime(history['510300.XSHG']['close'])
        metrics = rotation_metrics(history, end)
        _guard = next_guard(_guard, metrics, trend,
                            ENABLE_ROTATION_GUARD, REGIME_AWARE_ROTATION)
        gate = ENABLE_ROTATION_GUARD and (
            not REGIME_AWARE_ROTATION or trend in ('bear', 'risk_off', ''))
        if gate and metrics is None:
            return [] if _guard['mode'] == 'defensive' else held
        target = ranked[0][0][:6] if ranked else None
        if _guard['mode'] == 'defensive':
            target = None
        elif _guard['mode'] == 'observe' and target not in held:
            target = None
        return [target] if target is not None else []
    except (ValueError, KeyError, TypeError, OverflowError):
        _guard['bad_days'] = 0
        _guard['good_days'] = 0
        return held
