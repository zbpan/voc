from collections import defaultdict
from dataclasses import dataclass


NEGATIVE = {"negative", "mixed"}
SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
UNLABELED = "未标注客群"
MIN_PER_STORE = 2
MIN_SEGMENT_BASE = 10
MIN_SEGMENT_HITS = 3
MIN_GAP_PP = 10


def event_topic(row, event):
    return row["metadata"].get("executive", {}).get("topic") or event["theme"]


@dataclass
class Hit:
    row: dict
    event: dict

    def order(self):
        return (self.event["review_status"] != "confirmed", SEVERITY.get(self.event["severity"], 4),
                -self.row["day"].toordinal(), self.row["id"], self.event["id"])

    def citation(self):
        return {"record_id": self.row["id"], "event_id": self.event["id"], "title": self.event["title"], "quote": self.event["quote"],
                "store_name": self.row["store_name"] or "未分配门店", "review_status": self.event["review_status"]}


def keep(mapping, hit):
    rid = hit.row["id"]
    if rid not in mapping or hit.order() < mapping[rid].order():
        mapping[rid] = hit


class PeriodIndex:
    def __init__(self, rows):
        self.problems = defaultdict(dict)
        self.praise = defaultdict(dict)
        self.urgent = {}
        self.unassigned = set()
        self.store_bases = defaultdict(list)
        self.segment_bases = defaultdict(list)
        for row in rows:
            if not row["is_feedback"]:
                continue
            self.store_bases[row["store_id"]].append(row["id"])
            if row["segment"] != UNLABELED:
                self.segment_bases[row["segment"]].append(row["id"])
            for event in row["events"]:
                topic = event_topic(row, event)
                hit = Hit(row, event)
                if event["sentiment"] in NEGATIVE:
                    keep(self.problems[topic], hit)
                    if event["severity"] in {"high", "critical"} and event["workflow_status"] != "resolved":
                        keep(self.urgent, hit)
                        if not event["owner"].strip():
                            self.unassigned.add(row["id"])
                elif row["sentiment"] == event["sentiment"] == "positive":
                    keep(self.praise[topic], hit)


def group(label, hits):
    entries = [hit.citation() for hit in sorted(hits, key=Hit.order)]
    return {"label": label, "count": len(entries), "entries": entries}


def ratio(n, total):
    return f"{n}/{total}（{n / total:.1%}）" if total else "没有有效反馈"


def base_group(label, ids):
    return {"label": label, "record_ids": ids, "count": len(ids)}


def service_recovery(index):
    if not index.urgent:
        return None
    confirmed, pending = [], []
    for hit in index.urgent.values():
        (confirmed if hit.event["review_status"] == "confirmed" else pending).append(hit)
    missing = len(index.unassigned)
    state = f"{len(confirmed)}条已有人工确认，{len(pending)}条仍待核实" if confirmed and pending else ("均已有人工确认" if confirmed else "均待人工核实")
    return {
        "kind": "recovery", "label": "服务补救", "title": f"先跟进{len(index.urgent)}条高严重度反馈",
        "finding": f"{len(index.urgent)}条反馈涉及尚未关闭的高严重度线索，{state}。"
                   + (f"其中{missing}条至少有一项未填跟进人。" if missing else "每项线索都已登记跟进人。"),
        "manager_step": ("先为未分派的信号指定复核人，再把核实结果和下次回复时间记到对应事件。"
                         if missing else "和已登记的跟进人核对处理进展，为待核实的事件约定回复时间。"),
        "customer_step": "有回访渠道时，先确认困扰是否仍在，再与客户约定下一次答复；在跟进记录里区分已联系和已解决。",
        "check": "下次交班逐条核对：谁接手、是否回复、客户是否确认问题消除。",
        "groups": [group(label, hits) for label, hits in (("待核实", pending), ("已有确认", confirmed)) if hits],
    }


def by_store(hits):
    result = defaultdict(list)
    for hit in hits:
        if hit.row["store_id"]:
            result[hit.row["store_id"]].append(hit)
    return result


def recurring(now, before):
    best = None
    for topic, hits in now.problems.items():
        current = {s: rows for s, rows in by_store(hits.values()).items() if len(rows) >= MIN_PER_STORE}
        if not current:
            continue
        prior = by_store(before.problems.get(topic, {}).values())
        if len(current) == 1 and len(prior.get(next(iter(current)), [])) < MIN_PER_STORE:
            continue
        size = sum(map(len, current.values()))
        rank = (-len(current), -size, topic)
        if best is None or rank < best[0]:
            best = rank, topic, current, prior
    if best is None:
        return None
    _, topic, current, prior = best
    hits = [hit for rows in current.values() for hit in rows]
    old = [hit for sid in current for hit in prior.get(sid, [])]
    current_base = [rid for sid in current for rid in now.store_bases[sid]]
    prior_base = [rid for sid in current for rid in before.store_bases[sid]]
    names = sorted(((rows[0].row["store_name"], len(rows)) for rows in current.values()), key=lambda p: (-p[1], p[0]))
    stores = "、".join(f"{name}{n}条" for name, n in names[:3])
    if len(names) > 3:
        stores += f"等{len(names)}家门店"
    multiple = len(current) > 1
    return {
        "kind": "recurrence", "label": "重复问题", "title": f"「{topic}」在{len(current)}家门店反复出现" if multiple else f"{names[0][0]}连续两期收到「{topic}」问题",
        "finding": f"{stores}。在这些门店的有效反馈中，本期涉及该议题的有{ratio(len(hits), len(current_base))}；"
                   f"前期同口径：{ratio(len(old), len(prior_base))}。",
        "manager_step": ("请涉及门店各选一条原声，比较出错的具体步骤。只有步骤相同，才值得共同改一项标准。"
                         if multiple else "请门店负责人从前后两期各取一例，核对同一流程是否仍让客户遇到困难。"),
        "customer_step": sample_step(hits),
        "check": "下个等长周期用相同门店复算：该议题问题反馈数 / 有效反馈数，同时核对采集量。",
        "groups": [group("本期问题", hits), group("前期问题", old)],
        "bases": [base_group("本期有效反馈", current_base), base_group("前期有效反馈", prior_base)],
    }


def sample_step(hits):
    hit = min(hits, key=Hit.order)
    suggestion = hit.event["recommendation"].strip()
    return f"针对所引个案：{suggestion.removeprefix('建议')}" if suggestion else f"和一线人员复现「{hit.event['title']}」，试一项客户当场能感受到的调整。"


def segment_gap(index):
    total = sum(map(len, index.segment_bases.values()))
    best = None
    for topic, hits in index.problems.items():
        segments = defaultdict(list)
        for hit in hits.values():
            if hit.row["segment"] != UNLABELED:
                segments[hit.row["segment"]].append(hit)
        known_hits = sum(map(len, segments.values()))
        for name, rows in segments.items():
            n, base = len(rows), len(index.segment_bases[name])
            other_n, other_base = known_hits - n, total - base
            if n < MIN_SEGMENT_HITS or min(base, other_base) < MIN_SEGMENT_BASE:
                continue
            gap = 100 * (n * other_base - other_n * base) / (base * other_base)
            if gap < MIN_GAP_PP:
                continue
            rank = (-gap, -n, topic, name)
            if best is None or rank < best[0]:
                best = rank, topic, name, rows, base, segments, other_n, other_base, gap
    if best is None:
        return None
    _, topic, name, rows, base, segments, other_n, other_base, gap = best
    return {
        "kind": "segment", "label": "客群差异", "title": f"{name}更常提到「{topic}」问题",
        "finding": f"本期{name}：{ratio(len(rows), base)}；其他已标注客群：{ratio(other_n, other_base)}。两组相差{gap:.1f}个百分点。",
        "manager_step": f"先核对{name}是否集中在某家店或某个渠道，再决定是改通用流程，还是只在该场景试点。",
        "customer_step": sample_step(rows),
        "check": "在同店、同渠道继续收集两组反馈，再按各自有效反馈数复算；缺少可比样本时保留为线索。",
        "groups": [group(name, rows), group("其他已标注客群", [h for key, entries in segments.items() if key != name for h in entries])],
        "bases": [base_group(name, index.segment_bases[name]), base_group("其他已标注客群", [rid for key, ids in index.segment_bases.items() if key != name for rid in ids])],
    }


def practice_pair(index):
    best = None
    for topic in index.praise.keys() & index.problems.keys():
        good = by_store(index.praise[topic].values())
        bad = by_store(index.problems[topic].values())
        eligible = sorted(((sid, rows) for sid, rows in bad.items() if len(rows) >= MIN_PER_STORE),
                          key=lambda pair: (-len(pair[1]), pair[0]))
        for sid, praise in good.items():
            if len(praise) < MIN_PER_STORE:
                continue
            target = next(((key, rows) for key, rows in eligible[:2] if key != sid), None)
            if not target:
                continue
            other, problems = target
            rank = (-min(len(praise), len(problems)), -len(problems), -len(praise), topic, sid, other)
            if best is None or rank < best[0]:
                best = rank, topic, praise, problems
    if best is None:
        return None
    _, topic, praise, problems = best
    source, target = praise[0].row["store_name"], problems[0].row["store_name"]
    a, b = (min(hits, key=Hit.order).row["metadata"].get("executive", {}).get("scenario") for hits in (praise, problems))
    different_steps = bool(a and b and a != b)
    return {
        "kind": "transfer", "label": "门店互学",
        "title": f"{topic}：表扬样例谈{a}，问题样例谈{b}" if different_steps else f"「{topic}」有哪些做法值得跨店验证？",
        "finding": f"同一议题下，{source}有{len(praise)}条反馈明确表扬，{target}有{len(problems)}条反馈提到问题。",
        "manager_step": (f"两条样例说的是不同环节。请两店再找与「{b}」直接相关的表扬，确认有可借用的做法后再试点。"
                         if different_steps else f"请{source}和{target}各带一条原声，先确认说的是同一服务环节，再决定哪项做法值得借用。"),
        "customer_step": (f"请{target}先核实客户提到的{b}并回复处理进展；{source}的{a}做法单独保留。"
                          if different_steps else "若是同一环节，请获表扬的班组演示做法，再选一个班次试做并问客户是否有改善。若是不同环节，分开跟进。"),
        "check": "记录试做的动作、适用条件及客户回应；下一周期同时查看表扬和问题原声，再决定是否推广。",
        "groups": [group("表扬实例", praise), group("问题实例", problems)],
    }


def improvement_agenda(current, previous):
    now, before = PeriodIndex(current), PeriodIndex(previous)
    return [item for item in (service_recovery(now), recurring(now, before), segment_gap(now), practice_pair(now)) if item]


def snapshot_agenda(items):
    result = []
    for item in items:
        groups = []
        for g in item["groups"]:
            groups.append({"label": g["label"], "count": g["count"], "example": next(iter(g["entries"]), None)})
        result.append({**item, "groups": groups, "bases": [{"label": b["label"], "count": b["count"]} for b in item.get("bases", [])]})
    return result


def agenda_markdown(items):
    lines = ["## 管理与体验提示"]
    for item in items:
        lines.extend([f"### {item['label']}｜{item['title']}", item["finding"], f"管理动作：{item['manager_step']}",
                      f"一线试法：{item['customer_step']}", f"复查方法：{item['check']}"])
        for g in item["groups"]:
            example = g.get("example") or next(iter(g.get("entries", [])), None)
            if example:
                lines.append(f"{g['label']}（{g['count']}条） · {example['store_name']} · "
                             f"反馈 `{example['record_id']}` / 事件 `{example['event_id']}`\n\n> " + example["quote"].replace("\n", "\n> "))
    return lines if items else lines + ["当前范围的证据尚未达到提示条件。"]
