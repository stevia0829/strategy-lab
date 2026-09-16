"""Example: hold 510300 only while its 14-day RSI exceeds 50."""
from strategylab.engine import indicator


def decide(ctx):
    bars = ctx['history']['510300']
    values = indicator(bars, {'kind': 'rsi', 'period': 14})
    return ['510300'] if values and values[-1] is not None and values[-1] > 50 else []
