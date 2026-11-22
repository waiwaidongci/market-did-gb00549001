"""配对符号翻转的精确置换计数。

每一对市场在固定市场日上独立交换试点／对照身份，因此一次身份交换对应一组
符号 ``s_i ∈ {-1, +1}``。等权配对双重差分正比于 ``Σ s_i d_i``。这里用整数
缩放和折半枚举精确统计满足 ``|Σ s_i d_i| >= |Σ d_i|`` 的分配数，不逐条生成
全部 ``2**n`` 个分配。

计数进度可写入调用方提供的 checkpoint（需实现 ``load()`` 和 ``save()``）。
checkpoint 保存的是绝对进度（已处理的第二半下标与对应累计数），续跑从该处
继续，不会把同一段分配重复累计。
"""

from bisect import bisect_left, bisect_right
from fractions import Fraction
from hashlib import sha256
from json import dumps
from math import gcd, lcm

MAX_PAIRS = 40
CHECKPOINT_INTERVAL = 8192


def _fraction(value):
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _scaled_integers(differences):
    """把有理差分缩成互质整数，返回 (weights, threshold)。"""

    fractions = [_fraction(value) for value in differences]
    scale = 1
    for item in fractions:
        scale = lcm(scale, item.denominator)
    weights = [int(item * scale) for item in fractions]
    threshold = abs(sum(weights))
    divisor = 0
    for weight in weights:
        divisor = gcd(divisor, abs(weight))
    divisor = gcd(divisor, threshold)
    if divisor > 1:
        weights = [weight // divisor for weight in weights]
        threshold //= divisor
    return weights, threshold


def _iter_sums(weights):
    """按固定顺序枚举一半配对的正负和（列表倍增，供排序后的第一半使用）。"""

    totals = [0]
    for weight in weights:
        totals = [partial + weight for partial in totals] + [partial - weight for partial in totals]
    return iter(totals)


def _second_chunk(weights, start, stop):
    """生成第二半下标 ``[start, stop)`` 的正负和，顺序与 ``_iter_sums`` 一致。

    先把 ``start`` 的和算出来，之后按二进制计数的进位增量更新，避免为每个下标
    重算全部权重，也避免从头枚举已计入 checkpoint 的部分。
    """

    width = len(weights)
    if start >= stop:
        return

    def sign(position, index):
        # 与列表倍增顺序一致：第一位权重是最低位，位为 1 时取负号。
        return -1 if (index >> position) & 1 else 1

    total = sum(weight * sign(position, start) for position, weight in enumerate(weights))
    yield total
    for index in range(start + 1, stop):
        previous = index - 1
        bit = 0
        while (previous >> bit) & 1:
            total += 2 * weights[bit]
            bit += 1
        total -= 2 * weights[bit]
        yield total


def _signature(weights, threshold, split):
    payload = dumps({"version": 1, "weights": weights, "threshold": threshold, "split": split},
                    separators=(",", ":"), sort_keys=True)
    return sha256(payload.encode()).hexdigest()


def _state(state, signature):
    if not isinstance(state, dict) or state.get("signature") != signature:
        return None
    try:
        index = int(state.get("index", 0))
        count = int(state.get("count", 0))
    except (TypeError, ValueError):
        return None
    if index < 0 or count < 0:
        return None
    return {"index": index, "count": count, "phase": state.get("phase", "count"),
            "signature": signature}


def _save(progress, signature, index, count, phase="count"):
    if progress is not None:
        progress.save({"signature": signature, "index": index, "count": count, "phase": phase})


def _qualifying(first, second, threshold):
    """第一半和有序时，统计与 second 相加后绝对值达到阈值的分配数。"""

    lower = bisect_left(first, threshold - second)
    upper = bisect_right(first, -threshold - second)
    return (len(first) - lower) + upper


def count_sign_flips(differences, progress=None, max_items=None):
    """精确统计配对身份交换中绝对值不小于实测值的分配数。

    ``differences`` 是各配对的双重差分（``Fraction`` 或可转成有理数的值）。
    ``progress`` 可选，提供 ``load()`` 与 ``save(state)``；``max_items`` 可选，
    限制本次处理的第二半分配数，用于分批计算或演练中断续跑。

    返回值包含 ``total``、``observed``、``checked``；只有 ``complete`` 为真时
    才包含 ``count``。
    """

    fractions = [_fraction(value) for value in differences]
    if not fractions:
        raise ValueError("至少需要一对市场才能进行置换计数。")
    if len(fractions) > MAX_PAIRS:
        raise ValueError(f"市场配对最多 {MAX_PAIRS} 对。")

    total = 1 << len(fractions)
    observed = sum(fractions, Fraction(0)) / len(fractions)
    if max_items is not None and (type(max_items) is not int or max_items < 1):
        raise ValueError("每批分配数须为正整数。")

    weights, threshold = _scaled_integers(fractions)
    split = len(weights) // 2
    signature = _signature(weights, threshold, split)
    second_count = 1 << (len(weights) - split)

    # 实测差分为零（Σ weights = 0）时所有分配都达到阈值，无需枚举。
    if threshold == 0:
        _save(progress, signature, second_count, total, "complete")
        return {"complete": True, "count": total, "total": total,
                "observed": observed, "checked": second_count}

    state = _state(progress.load() if progress is not None else None, signature)
    if state and state["phase"] == "complete":
        return {"complete": True, "count": state["count"], "total": total,
                "observed": observed, "checked": second_count}

    index = min(state["index"], second_count) if state else 0
    count = min(state["count"], total) if state else 0
    if index == second_count:
        _save(progress, signature, index, count, "complete")
        return {"complete": True, "count": count, "total": total,
                "observed": observed, "checked": index}

    first = sorted(_iter_sums(weights[:split]))
    stop = second_count if max_items is None else min(second_count, index + max_items)
    for processed, second in enumerate(_second_chunk(weights[split:], index, stop), start=index):
        count += _qualifying(first, second, threshold)
        if (processed + 1) % CHECKPOINT_INTERVAL == 0:
            _save(progress, signature, processed + 1, count)
    processed = stop

    complete = processed == second_count
    _save(progress, signature, processed, count, "complete" if complete else "count")
    result = {"complete": complete, "total": total, "observed": observed, "checked": processed}
    if complete:
        result["count"] = count
    return result
