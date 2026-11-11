import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from .db import now
from .queries import record_where


NEGATIVE = {"negative", "mixed"}
SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def percent(numerator, denominator):
    return round(numerator * 100 / denominator, 1) if denominator else None


def delta(current, previous):
    return round(current - previous, 1) if current is not None and previous is not None else None


def measure(rows):
    feedback = [r for r in rows if r["is_feedback"]]
    negative = [r for r in feedback if r["sentiment"] in NEGATIVE]
    return {"records": len(rows), "feedback": len(feedback), "negative": len(negative), "positive": sum(r["sentiment"] == "positive" for r in feedback), "negative_rate": percent(len(negative), len(feedback))}


def executive_dashboard(db, scope, window_days=20):
    base_scope = scope.model_copy(update={"start": None, "end": None})
    where, args = record_where(base_scope)
    with db.connect() as con:
        con.execute("BEGIN")
        records = [dict(r) for r in con.execute("SELECT r.*,s.name AS store_name FROM records r LEFT JOIN stores s ON s.id=r.store_id WHERE " + where, args)]
        events = [dict(e) for e in con.execute("SELECT e.* FROM events e JOIN records r ON r.id=e.record_id WHERE " + where + " AND r.status='completed' AND e.review_status!='dismissed'", args)]
        stores = [dict(s) for s in con.execute("SELECT id,name FROM stores WHERE workspace_id=? ORDER BY name", (scope.workspace_id,))]
        actions = [dict(a) for a in con.execute("SELECT a.*,s.name AS store_name FROM experience_actions a LEFT JOIN stores s ON s.id=a.store_id WHERE a.workspace_id=? ORDER BY a.due_at,a.id", (scope.workspace_id,))]
        anchor = con.execute("SELECT MAX(substr(created_at,1,10)) FROM records WHERE workspace_id=?", (scope.workspace_id,)).fetchone()[0]
    end = scope.end or date.fromisoformat(anchor or date.today().isoformat())
    if scope.start and end < scope.start:
        end = max(scope.start, date.today())
    start = scope.start or end - timedelta(days=window_days - 1)
    days = (end - start).days + 1
    prior_end, prior_start = start - timedelta(days=1), start - timedelta(days=days)
    by_record = defaultdict(list)
    for event in events:
        by_record[event["record_id"]].append(event)
    for r in records:
        r["day"] = date.fromisoformat(r["created_at"][:10])
        r["metadata"] = json.loads(r["metadata_json"])
        r["events"] = by_record[r["id"]]
        tags = r["metadata"].get("executive", {})
        r["topics"] = [tags["topic"]] if tags.get("topic") and r["events"] else sorted({e["theme"] for e in r["events"]})
        r["negative_topics"] = r["topics"] if tags.get("topic") and any(e["sentiment"] in NEGATIVE for e in r["events"]) else sorted({e["theme"] for e in r["events"] if e["sentiment"] in NEGATIVE})
        r["segment"] = r["metadata"].get("guest_segment") or "未标注客群"
    completed = [r for r in records if r["status"] == "completed"]
    current = [r for r in completed if start <= r["day"] <= end]
    previous = [r for r in completed if prior_start <= r["day"] <= prior_end]
    current_metrics, previous_metrics = measure(current), measure(previous)
    current_events = [e for r in current for e in r["events"]]
    high_events = [e for e in current_events if e["severity"] in {"high", "critical"} and e["workflow_status"] != "resolved"]
    names = sorted({topic for r in current + previous for topic in r["topics"]})
    topic_rows = []
    for topic in names:
        affected = [r for r in current if topic in r["negative_topics"]]
        before = [r for r in previous if topic in r["negative_topics"]]
        topic_high = [e for r in affected for e in r["events"] if e in high_events]
        topic_rows.append({"name": topic, "count": len(affected), "previous_count": len(before), "rate": percent(len(affected), current_metrics["feedback"]), "previous_rate": percent(len(before), previous_metrics["feedback"]), "stores": len({r["store_id"] for r in affected}), "high_open": len(topic_high), "record_ids": [r["id"] for r in affected]})
    topic_rows.sort(key=lambda t: (-bool(t["high_open"]), -t["count"], -(t["count"] - t["previous_count"]), t["name"]))
    topic_rows = [t for t in topic_rows if t["count"]]
    top_ids = set(i for t in topic_rows[:3] for i in t["record_ids"])
    negative_ids = {r["id"] for r in current if r["is_feedback"] and r["sentiment"] in NEGATIVE}
    store_rows = []
    for store in stores:
        if scope.store_id and store["id"] != scope.store_id:
            continue
        a = [r for r in current if r["store_id"] == store["id"]]
        b = [r for r in previous if r["store_id"] == store["id"]]
        ma, mb = measure(a), measure(b)
        cells = {topic: sum(topic in r["negative_topics"] for r in a) for topic in names}
        lead = max(cells, key=cells.get) if cells and max(cells.values()) else None
        store_rows.append({**store, **ma, "previous": mb, "delta_pp": delta(ma["negative_rate"], mb["negative_rate"]), "topics": cells, "lead_topic": lead, "small_sample": min(ma["feedback"], mb["feedback"]) < 10})
    store_rows.sort(key=lambda s: (-(s["negative_rate"] if s["negative_rate"] is not None else -1), -s["feedback"]))
    segments = []
    for segment in sorted({r["segment"] for r in current}):
        rows = [r for r in current if r["segment"] == segment]
        m = measure(rows)
        dominant = Counter(t for r in rows for t in r["negative_topics"]).most_common(1)
        segments.append({"name": segment, **m, "lead_topic": dominant[0][0] if dominant else None})
    segments.sort(key=lambda s: (-s["negative"], s["name"]))
    trend = []
    bin_days = max(1, (days * 2 + 7) // 8)
    for offset in range(0, days * 2, bin_days):
        left = prior_start + timedelta(days=offset)
        right = min(end, left + timedelta(days=bin_days - 1))
        rows = [r for r in completed if left <= r["day"] <= right]
        trend.append({"start": left.isoformat(), "end": right.isoformat(), **measure(rows)})
    action_rows = []
    for action in actions:
        if scope.store_id and action["store_id"] not in (None, scope.store_id):
            continue
        matching = [r for r in current if not action["store_id"] or r["store_id"] == action["store_id"]]
        if scope.search and not matching:
            continue
        item = {k: v for k, v in action.items() if k != "metadata_json"}
        item["metadata"] = json.loads(action["metadata_json"])
        item["affected"] = sum(action["topic"] in r["negative_topics"] for r in matching)
        item["comparison"] = None
        if action["started_at"]:
            boundary = date.fromisoformat(action["started_at"])
            sample = [r for r in current + previous if not action["store_id"] or r["store_id"] == action["store_id"]]
            available = min((boundary - prior_start).days, (end - boundary).days + 1, days)
            if available > 0:
                before = [r for r in sample if boundary - timedelta(days=available) <= r["day"] < boundary]
                after = [r for r in sample if boundary <= r["day"] < boundary + timedelta(days=available)]
                before_n = sum(action["topic"] in r["negative_topics"] for r in before)
                after_n = sum(action["topic"] in r["negative_topics"] for r in after)
                bm, am = measure(before), measure(after)
                br, ar = percent(before_n, bm["feedback"]), percent(after_n, am["feedback"])
                item["comparison"] = {"days": available, "before_start": (boundary - timedelta(days=available)).isoformat(), "after_end": (boundary + timedelta(days=available - 1)).isoformat(), "before": before_n, "after": after_n, "before_base": bm["feedback"], "after_base": am["feedback"], "before_rate": br, "after_rate": ar, "delta_pp": delta(ar, br), "small_sample": min(bm["feedback"], am["feedback"]) < 10, "record_ids": [r["id"] for r in before + after if action["topic"] in r["negative_topics"]]}
        action_rows.append(item)
    strengths = []
    for store in stores:
        rows = [r for r in current if r["store_id"] == store["id"] and r["is_feedback"] and r["sentiment"] == "positive"]
        if rows:
            counts = Counter(t for r in rows for t in r["topics"])
            strengths.append({"store_id": store["id"], "store_name": store["name"], "count": len(rows), "topics": [k for k, _ in counts.most_common(2)], "record_ids": [r["id"] for r in rows]})
    strengths.sort(key=lambda s: (-s["count"], s["store_name"]))
    evidence = []
    for r in current + previous:
        selected = sorted(r["events"], key=lambda e: (e["sentiment"] not in NEGATIVE, SEVERITY.get(e["severity"], 4)))
        event = selected[0] if selected else {}
        evidence.append({"id": r["id"], "title": r["title"], "date": r["created_at"][:10], "store_id": r["store_id"], "store_name": r["store_name"] or "未分配", "sentiment": r["sentiment"], "is_feedback": bool(r["is_feedback"]), "topics": r["topics"], "negative_topics": r["negative_topics"], "segment": r["segment"], "summary": r["summary"], "quote": event.get("quote", ""), "severity": event.get("severity"), "has_audio": bool(r["audio_path"]), "period": "current" if r in current else "previous", "high_open": any(e in high_events for e in r["events"]), "event_ids": [e["id"] for e in r["events"]]})
    evidence.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    rate_delta = delta(current_metrics["negative_rate"], previous_metrics["negative_rate"])
    if rate_delta is None:
        headline = "先建立可对照的体验基线"
    elif rate_delta < 0:
        headline = "整体负向占比下降，仍需聚焦局部问题"
    elif rate_delta > 0:
        headline = "负向反馈占比上升，优先处理集中问题"
    else:
        headline = "整体负向占比持平，关注门店间差异"
    worsening = [s for s in store_rows if s["delta_pp"] is not None and s["delta_pp"] > 0]
    worst = max(worsening, key=lambda s: s["delta_pp"]) if worsening else None
    summary = f"本期{current_metrics['feedback']}条有效体验反馈，{current_metrics['negative']}条负向或褒贬并存。"
    if worst:
        if not worst["small_sample"]:
            headline = f"{worst['name']}负向占比上升{worst['delta_pp']}个百分点"
        else:
            headline = f"{worst['name']}出现上升信号，需补充样本核实"
        if rate_delta is not None:
            summary += f"集团较前期{'下降' if rate_delta < 0 else '上升' if rate_delta > 0 else '持平'}{abs(rate_delta)}个百分点，"
        summary += f"该店问题主要集中于{worst['lead_topic'] or '多个体验环节'}。"
    return {
        "generated_at": now(), "scope": scope.model_dump(mode="json"),
        "period": {"start": start.isoformat(), "end": end.isoformat(), "previous_start": prior_start.isoformat(), "previous_end": prior_end.isoformat(), "days": days, "anchor": anchor},
        "headline": headline, "summary": summary, "metrics": {**current_metrics, "previous": previous_metrics, "delta_pp": rate_delta, "events": len(current_events), "pending_review": sum(e["review_status"] == "pending" for e in current_events), "high_open": len(high_events), "high_records": len({e["record_id"] for e in high_events}), "priority_coverage": percent(len(top_ids & negative_ids), len(negative_ids)), "priority_records": len(top_ids & negative_ids), "pending_records": sum(r["status"] != "completed" and start <= r["day"] <= end for r in records)},
        "trend": trend, "topics": topic_rows, "stores": store_rows, "segments": segments, "actions": action_rows, "strengths": strengths[:3], "evidence": evidence,
        "definitions": [
            "统计按反馈提交去重，不等于住客人数；分析仅覆盖已完成记录。负向占比含负向和褒贬并存，分母为有效体验反馈。",
            "日期以UTC反馈日期统计，默认锚定工作空间最新反馈日；本期与紧邻前期天数相同。百分比变化用百分点，不用增长率。",
            "经营议题来自演示场景人工归类；无人工标签时使用模型主题。议题问题数需有未排除的负向或褒贬并存事件，同条在同议题只计一次。",
            "优先顺序为高严重度未解决信号优先，其次问题覆盖条数，再其次新增条数。前三项覆盖仅计算负向记录的去重并集。",
            "事件复核与反馈情绪是独立口径：排除事件会移出议题和风险统计，但不自动重写原反馈情绪。高严重度信号仍需复核。",
            "行动前后按同一门店、同一议题与等长窗口比较，显示分子与分母；少于10条标记小样本，前后差异不构成因果证明。",
            "CXO演示空间的门店、日期、客群、议题与管理行动为编排数据；原文、语音、图片和Qwen结果可溯源。未接入入住量或收入，不推算NPS、经营损失或ROI。",
        ],
    }


def executive_markdown(data, session_id):
    p, m = data["period"], data["metrics"]
    def value(number, suffix=""):
        return f"{number}{suffix}" if number is not None else "暂无可比数据"

    lines = ["# VOC 集团经营简报", f"Session ID：`{session_id}`", f"生成时间：{data['generated_at']}", f"本期：{p['start']} 至 {p['end']}；前期：{p['previous_start']} 至 {p['previous_end']}（UTC）", f"筛选：{json.dumps(data['scope'], ensure_ascii=False)}", "## 管理摘要", data["headline"], data["summary"], f"负向占比：{value(m['negative_rate'], '%')}；前期：{value(m['previous']['negative_rate'], '%')}；变化：{value(m['delta_pp'], '个百分点')}。前三项覆盖{m['priority_records']}条负向反馈；高严重度未解决{m['high_open']}个事件，涉及{m['high_records']}条反馈。", "## 门店对比"]
    for s in data["stores"]:
        lines.append(f"- {s['name']}：本期{s['negative']}/{s['feedback']}，负向占比{value(s['negative_rate'], '%')}；前期{s['previous']['negative']}/{s['previous']['feedback']}；变化{value(s['delta_pp'], '个百分点')}；首要议题{s['lead_topic'] or '暂无'}。")
    lines.append("## 议题优先级")
    for t in data["topics"]:
        lines.append(f"- {t['name']}：{t['count']}条问题反馈，覆盖{t['stores']}家门店；前期{t['previous_count']}条；高严重度未解决{t['high_open']}个。")
    lines.append("## 客群与正向体验")
    for s in data["segments"]:
        lines.append(f"- {s['name']}：{s['negative']}/{s['feedback']}条负向反馈，占比{value(s['negative_rate'], '%')}；首要议题{s['lead_topic'] or '暂无'}。")
    for s in data["strengths"]:
        lines.append(f"- {s['store_name']}：{s['count']}条正向反馈，集中于{'、'.join(s['topics'])}，建议核实可复制的服务做法。")
    lines.append("## 管理行动与成效观察")
    for a in data["actions"]:
        lines += [f"### {a['title']}", f"负责人：{a['owner']}；状态：{a['status']}；期限：{a['due_at']}。", a["decision"], f"验收标准：{a['success_criterion']}"]
        c = a["comparison"]
        if c:
            lines.append(f"等长{c['days']}天观察：前{c['before']}/{c['before_base']}（{value(c['before_rate'], '%')}），后{c['after']}/{c['after_base']}（{value(c['after_rate'], '%')}），变化{value(c['delta_pp'], '个百分点')}。{'样本较少，继续观察。' if c['small_sample'] else ''}前后变化不构成因果证明。")
    lines += ["## 统计口径", *data["definitions"], "## 全量反馈证据索引", f"本期与前期共{len(data['evidence'])}条已分析记录，无前200条截断。"]
    for r in data["evidence"]:
        lines += [f"### {r['title']}", f"反馈ID：`{r['id']}`；{r['date']}；{r['store_name']}；{'本期' if r['period']=='current' else '前期'}", r["summary"], "> " + r["quote"].replace("\n", "\n> ")]
    return "\n\n".join(lines)
