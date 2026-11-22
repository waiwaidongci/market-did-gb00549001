"""配对市场日面板上的等权双重差分与精确置换计数。"""

from datetime import date
from fractions import Fraction
from re import split as re_split

from .permutation import count_sign_flips
from .spec import SPEC


def _options(key):
    return tuple(next(field["options"] for field in SPEC["fields"] if field["key"] == key))


_TREATED, _CONTROL = _GROUPS = _options("group")
_REQUIRED_FIELDS = {field["key"] for field in SPEC["fields"] if field.get("required", True)}
_DEFAULTS = {field["key"]: field["default"] for field in SPEC["params"]}
_PERIODS = ("试点前段", "试点前后段", "试点后")
_PAIR_SEPARATORS = r"[;；\n]+"
_PAIR_MEMBERS = r"[:：=]"


def _date(value, label):
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if value == parsed.isoformat():
                return parsed
        except ValueError:
            pass
    raise ValueError(f"{label}须使用有效的 YYYY-MM-DD 日期。")


def _number(value, minimum, maximum):
    return type(value) in (int, float) and minimum <= value <= maximum


def validate_rows(rows):
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("门岗明细至少需一条市场日记录。")
    result, groups, pairs, seen = [], {}, {}, set()
    for index, row in enumerate(rows, start=1):
        label = f"第 {index} 条记录"
        if not isinstance(row, dict) or not _REQUIRED_FIELDS <= row.keys():
            raise ValueError(f"{label}缺少市场日字段或格式有误。")
        market = row["market_id"]
        if not isinstance(market, str) or not market.strip() or len(market.strip()) > 300:
            raise ValueError(f"{label}的市场名称须为 1–300 个字符。")
        market = market.strip()
        pair = row.get("pair_id")
        if pair is not None and pair != "":
            if not isinstance(pair, str) or not pair.strip() or len(pair.strip()) > 120:
                raise ValueError(f"{label}的配对编号须为 1–120 个字符，或留空使用运行参数指定配对。")
            pair = pair.strip()
            if pairs.setdefault(market, pair) != pair:
                raise ValueError(f"市场「{market}」的配对编号不一致。")
        day = _date(row["date"], f"{label}的观测日期").isoformat()
        group = row["group"]
        if group not in _GROUPS:
            raise ValueError(f"{label}的分组须为试点组或对照组。")
        if groups.setdefault(market, group) != group:
            raise ValueError(f"市场「{market}」的试点分组不一致。")
        if (market, day) in seen:
            raise ValueError(f"市场「{market}」在 {day} 的记录重复。")
        wait = row["wait_minutes"]
        trucks = row["truck_count"]
        if not _number(wait, 0, 1440):
            raise ValueError(f"{label}的平均等候须为 0–1440 分钟。")
        if type(trucks) is not int or not 1 <= trucks <= 10000:
            raise ValueError(f"{label}的有效车辆数须为 1–10000 的整数。")
        seen.add((market, day))
        result.append({**row, "market_id": market, "pair_id": pair})
    return result


def _parameters(normalized_params):
    if not isinstance(normalized_params, dict) or normalized_params.keys() - _DEFAULTS.keys():
        raise ValueError("运行参数格式有误或包含未知参数。")
    options = {**_DEFAULTS, **normalized_params}
    pilot = _date(options["pilot_date"], "试点启动日").toordinal()
    days = options["window_days"]
    threshold = options["pretrend_threshold"]
    market_pairs = options.get("market_pairs") or ""
    if type(days) is not int or not 1 <= days <= 28:
        raise ValueError("每段自然日数须为 1–28 的整数。")
    if not _number(threshold, 0, 1440):
        raise ValueError("试点前偏离阈值须为 0–1440 分钟。")
    if not isinstance(market_pairs, str):
        raise ValueError("市场配对须为文本，格式为「试点市场:对照市场」，多对用分号分隔。")
    start, end = pilot - 2 * days, pilot + days
    if start < date.min.toordinal() or end - 1 > date.max.toordinal():
        raise ValueError("试点窗口超出有效日期范围，请调整启动日或每段天数。")
    return start, pilot, end, days, Fraction(str(threshold)), market_pairs.strip()


def _market_facts(readings):
    groups, assignments = {}, {}
    for row in readings:
        market = row["market_id"]
        groups[market] = row["group"]
        if row.get("pair_id"):
            assignments[market] = row["pair_id"]
    return groups, assignments


def _pairs_from_parameter(text, groups):
    pairs, used = {}, {}
    for chunk in re_split(_PAIR_SEPARATORS, text):
        chunk = chunk.strip()
        if not chunk:
            continue
        members = [item.strip() for item in re_split(_PAIR_MEMBERS, chunk) if item.strip()]
        if len(members) != 2 or members[0] == members[1]:
            raise ValueError(f"配对「{chunk}」须写成「市场:市场」两家不同的市场。")
        left, right = members
        for market in members:
            if market not in groups:
                raise ValueError(f"配对中的市场「{market}」不在门岗明细中。")
            if market in used:
                raise ValueError(f"市场「{market}」重复出现在多个配对中。")
        if {groups[left], groups[right]} != set(_GROUPS):
            raise ValueError(f"配对「{chunk}」须恰有一家试点组和一家对照组市场。")
        name = f"{left}·{right}"
        pairs[name] = {groups[left]: left, groups[right]: right}
        used[left] = used[right] = name
    return pairs


def _pairs_from_rows(assignments, groups):
    grouped = {}
    for market, pair in assignments.items():
        grouped.setdefault(pair, []).append(market)
    pairs = {}
    for pair, markets in grouped.items():
        if len(markets) > 2:
            raise ValueError(f"配对「{pair}」包含 {len(markets)} 家市场，每对最多两家。")
        members = {}
        for market in sorted(markets):
            group = groups[market]
            if group in members:
                raise ValueError(f"配对「{pair}」须恰有一家试点组和一家对照组市场。")
            members[group] = market
        pairs[pair] = members
    return pairs


def _pairs(readings, text):
    groups, assignments = _market_facts(readings)
    pairs = _pairs_from_parameter(text, groups) if text else _pairs_from_rows(assignments, groups)
    if not pairs:
        raise ValueError("尚未指定市场配对。请在门岗明细填写配对编号，或在运行参数中指定市场配对。")
    return pairs, groups


def _observed_windows(readings, start, end):
    by_market, outside = {}, 0
    for row in readings:
        day = date.fromisoformat(row["date"]).toordinal()
        if start <= day < end:
            by_market.setdefault(row["market_id"], {})[day] = row
        else:
            outside += 1
    return by_market, outside


def _mean(values):
    return sum(values, Fraction(0)) / len(values)


def _market_means(observed, start, days):
    early = [Fraction(str(observed[day]["wait_minutes"])) for day in range(start, start + days)]
    late = [Fraction(str(observed[day]["wait_minutes"])) for day in range(start + days, start + 2 * days)]
    post = [Fraction(str(observed[day]["wait_minutes"])) for day in range(start + 2 * days, start + 3 * days)]
    return _mean(early), _mean(late), _mean(post)


def _display(value):
    return float(round(value, 2))


def _table(title, columns, rows):
    return {"title": title, "columns": [{"key": key, "label": label} for key, label in columns], "rows": rows}


def _missing_text(missing):
    if not missing:
        return "无"
    return "、".join(date.fromordinal(day).isoformat() for day in missing)


def analyze(rows, normalized_params, checkpoint=None):
    readings = validate_rows(rows)
    start, pilot, end, days, threshold, pair_text = _parameters(normalized_params)
    pairs, groups = _pairs(readings, pair_text)
    by_market, outside = _observed_windows(readings, start, end)
    expected = end - start

    included, coverage = [], []
    for name in sorted(pairs):
        members = pairs[name]
        market_label = "、".join(f"{members[group]}（{group}）" for group in _GROUPS if group in members)
        missing = {}
        observed_days = 0
        for market in members.values():
            observed = by_market.get(market, {})
            observed_days += len(observed)
            gaps = [day for day in range(start, end) if day not in observed]
            if gaps:
                missing[market] = gaps
        reasons = []
        if len(members) < len(_GROUPS):
            reasons.append("配对缺少一家市场")
        if missing:
            reasons.append("三段窗口内有缺报")
        coverage.append({
            "pair": name, "markets": market_label,
            "observed_days": observed_days, "expected_days": len(_GROUPS) * expected,
            "status": "排除" if reasons else "纳入",
            "missing": "；".join(f"{market}：{_missing_text(gaps)}" for market, gaps in missing.items()) or "无",
            "reason": "；".join(reasons) + "，整对剔除。" if reasons else "—",
        })
        if reasons:
            continue
        treated, control = members[_TREATED], members[_CONTROL]
        t_early, t_late, t_post = _market_means(by_market[treated], start, days)
        c_early, c_late, c_post = _market_means(by_market[control], start, days)
        t_before, c_before = (t_early + t_late) / 2, (c_early + c_late) / 2
        t_change, c_change = t_post - t_before, c_post - c_before
        included.append({
            "pair": name, "treated": treated, "control": control,
            "treated_early": t_early, "treated_late": t_late, "treated_post": t_post,
            "control_early": c_early, "control_late": c_late, "control_post": c_post,
            "treated_before": t_before, "treated_after": t_post,
            "control_before": c_before, "control_after": c_post,
            "treated_change": t_change, "control_change": c_change,
            "effect": t_change - c_change,
            "placebo": (t_late - t_early) - (c_late - c_early),
            "market_days": observed_days,
        })

    if not included:
        raise ValueError("没有完整配对可用于置换。请补齐三段逐日记录或调整配对与窗口。")
    unpaired = sorted(set(groups) - {market for members in pairs.values() for market in members.values()})
    differences = [item["effect"] for item in included]
    observed = _mean(differences)
    counted = count_sign_flips(differences, progress=checkpoint)
    if not counted["complete"]:
        raise RuntimeError("置换计数未完成，无法生成完整结果。")
    count, total = counted["count"], counted["total"]
    placebo = _mean([item["placebo"] for item in included])
    review_pretrend = abs(placebo) > threshold
    ratio = round(count / total, 6)
    gaps = [
        _mean([item["treated_early"] - item["control_early"] for item in included]),
        _mean([item["treated_late"] - item["control_late"] for item in included]),
        _mean([item["treated_post"] - item["control_post"] for item in included]),
    ]

    excluded = len(coverage) - len(included)
    warnings = []
    if excluded:
        warnings.append(f"{excluded} 对配对因三段缺报或缺少另一家市场整对剔除。")
    if unpaired:
        warnings.append(f"{len(unpaired)} 家市场未指定配对，不参与置换。")
    if len(included) == 1:
        warnings.append("仅 1 对完整配对，置换分布只有 2 种分配，极端程度有限。")
    if review_pretrend:
        warnings.append("试点前组间差值变化超过阈值，复核同期变化假设。")
    pretrend_status = "超过复核阈值" if review_pretrend else "在复核阈值内"
    cutoff = date.fromordinal(pilot - days).isoformat()

    pair_rows = [{
        "pair": item["pair"], "treated": item["treated"], "control": item["control"],
        "treated_before": _display(item["treated_before"]),
        "treated_after": _display(item["treated_after"]),
        "treated_change": _display(item["treated_change"]),
        "control_before": _display(item["control_before"]),
        "control_after": _display(item["control_after"]),
        "control_change": _display(item["control_change"]),
        "effect": _display(item["effect"]), "market_days": item["market_days"],
    } for item in included]
    placebo_rows = [{
        "pair": item["pair"],
        "treated_change": _display(item["treated_late"] - item["treated_early"]),
        "control_change": _display(item["control_late"] - item["control_early"]),
        "placebo": _display(item["placebo"]),
    } for item in included]

    return {
        "state": "warning" if warnings else "ok",
        "headline": f"配对等权双重差分为 {_display(observed):+g} 分钟；"
                    f"{count} / {total} 种身份交换的绝对值不小于实测值。",
        "note": f"纳入 {len(included)} 对配对（{2 * len(included)} 家完整市场），剔除 {excluded} 对。"
                f"窗口外 {outside} 条。" + "".join(warnings),
        "metrics": [
            {"label": "等权双重差分（分钟）", "value": _display(observed),
             "detail": f"{len(included)} 对完整市场按对等权，负值表示相对缩短。"},
            {"label": "达到阈值的分配数", "value": count,
             "detail": "各对独立交换身份后，|等权双重差分| 不小于实测值的分配数，平局计入。"},
            {"label": "分配总数", "value": total,
             "detail": f"{len(included)} 对各自独立交换身份，共 2^{len(included)} 种分配。"},
            {"label": "置换比例", "value": ratio,
             "detail": "精确双侧置换比例（含平局），越小表示实测差分越极端。"},
            {"label": "试点前安慰剂差分（分钟）", "value": _display(placebo),
             "detail": f"配对等权，{pretrend_status}（{float(threshold):g} 分钟），假启动日 {cutoff}。"},
            {"label": "完整配对数", "value": len(included),
             "detail": f"共指定 {len(pairs)} 对，剔除 {excluded} 对，未配对市场 {len(unpaired)} 家。"},
        ],
        "tables": [
            _table("配对与实测差分", (
                ("pair", "配对"), ("treated", "试点市场"), ("control", "对照市场"),
                ("treated_before", "试点前均值（分钟）"), ("treated_after", "试点后均值（分钟）"),
                ("treated_change", "试点组变化"), ("control_before", "对照前均值（分钟）"),
                ("control_after", "对照后均值（分钟）"), ("control_change", "对照组变化"),
                ("effect", "配对双重差分（分钟）"), ("market_days", "市场日数"),
            ), pair_rows),
            _table("配对样本与剔除说明", (
                ("pair", "配对"), ("markets", "市场（分组）"), ("observed_days", "已报日数"),
                ("expected_days", "应报日数"), ("status", "样本状态"), ("missing", "缺报日期"),
                ("reason", "说明"),
            ), coverage),
            _table("试点前趋势与安慰剂", (
                ("pair", "配对"), ("treated_change", "试点组前段→后段（分钟）"),
                ("control_change", "对照组前段→后段（分钟）"), ("placebo", "配对安慰剂差分（分钟）"),
            ), placebo_rows),
        ],
        "charts": [
            {"title": "各配对双重差分（分钟）", "kind": "bar", "series": [
                {"label": item["pair"], "value": _display(item["effect"])} for item in included
            ]},
            {"title": "三段配对等权组间差值（试点组减对照组，分钟）", "kind": "line", "series": [
                {"label": period, "value": _display(gap)} for period, gap in zip(_PERIODS, gaps)
            ]},
        ],
        "sections": [
            {"title": "样本与计算口径", "text": "市场对互不重叠，每对恰有一家试点组和一家对照组市场。"
             "三个等长窗口逐日完整的配对才进入主估计；任一段缺报即整对剔除，并在覆盖表说明日期。"
             "市场日与配对等权，试点前合并两个等长窗口。"},
            {"title": "配对置换检验", "text": "固定各市场日的观测，配对内独立交换试点与对照身份，"
             "等权双重差分随该对差分符号改变。精确统计绝对值不小于实测值的分配数，平局计入，"
             "总数恒为 2 的配对数次方。计数采用折半枚举，不逐个生成全部分配；"
             "续跑从已保存的绝对计数继续，重试不会重复累计。计数未完成时不展示配对、实测差分和计数。"},
            {"title": "解释限制", "text": "因果解释依赖平行趋势、无提前响应和无跨市场分流。"
             "配对较少时置换分布较粗，单对缺报会降低代表性。需核对同期施工、节日备货、"
             "车型与到货时段变化；短窗口结果仅反映纳入配对和当前观测期。"},
        ],
        "permutation": {
            "complete": True, "observed": _display(observed), "count": count,
            "total": total, "ratio": ratio,
            "pairs": [{"pair": item["pair"], "treated": item["treated"], "control": item["control"],
                       "effect": _display(item["effect"])} for item in included],
            "excluded": [{"pair": row["pair"], "reason": row["reason"]}
                         for row in coverage if row["status"] == "排除"],
        },
    }
