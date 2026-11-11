import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from voc.config import load_settings
from voc.db import Database, dumps, now


WORKSPACE = "open-source-demo"
SCENARIOS = [
    ("入住办理", "等待效率", "到店后等了很久才拿到房卡，希望高峰时段能有明确的排队说明。", "negative", "核实排队与客房就绪时间，优化高峰说明。"),
    ("客房清洁", "卫生安全", "床品和浴室都很干净，住起来比较放心。", "positive", "保留清洁检查流程并收集后续反馈。"),
    ("网络体验", "设施环境", "房间网络断了几次，开线上会议时受到了影响。", "negative", "按房间和时段排查无线覆盖及网络稳定性。"),
    ("早餐服务", "服务体验", "早餐选择丰富，工作人员也会主动说明过敏原信息。", "positive", "核实并推广清晰的菜品与过敏原提示。"),
    ("费用说明", "价格费用", "退房时才知道停车需要另外付费，希望预订时就能说明。", "negative", "核查预订页及到店费用告知是否一致。"),
    ("前台服务", "员工态度", "前台帮忙调整了房间，也耐心解释了交通路线，谢谢。", "positive", "记录并保留主动解释和补救做法。"),
]


def main():
    settings = load_settings()
    db = Database(settings.db_path)
    db.initialize()
    if db.one("SELECT id FROM workspaces WHERE id=?", (WORKSPACE,)):
        print("Demo workspace already exists; no data was overwritten.")
        return
    end = date.today()
    with db.connect() as con:
        con.execute("INSERT INTO workspaces VALUES (?,?,?)", (WORKSPACE, "开源酒店演示 · 虚构数据", now()))
        for index, name in enumerate(["虚构海湾店", "虚构商务店", "虚构庭院店"]):
            store = f"oss-demo-store-{index}"
            con.execute("INSERT INTO stores VALUES (?,?,?,?,?,?)", (store, WORKSPACE, name, "虚构演示区域", secrets.token_urlsafe(24), now()))
            for period in range(2):
                for scenario, (topic, theme, text, sentiment, recommendation) in enumerate(SCENARIOS):
                    identifier = f"oss-demo-{index}-{period}-{scenario}"
                    day = (end - timedelta(days=30 if period == 0 else 8) + timedelta(days=scenario)).isoformat() + "T10:00:00+00:00"
                    title = f"虚构样例 · {topic} · {scenario + 1}"
                    summary = f"演示预置：{text}"
                    if index == 1 and period == 1 and scenario == 0:
                        text = "这次到店很快拿到了房卡，前台也提前说明了早餐安排。"
                        sentiment = "positive"
                        summary = "演示预置：入住办理顺畅，说明清楚。"
                    metadata = {"synthetic": True, "analysis_source": "precomputed-demo-not-model-output", "guest_segment": ["休闲客群", "商务客群", "家庭客群"][index], "executive": {"topic": topic}, "modalities": ["text"]}
                    con.execute("INSERT INTO records(id,workspace_id,store_id,title,source_type,text_input,media_type,status,stage,progress,created_at,completed_at,language,summary,transcript,sentiment,is_feedback,model,prompt_version,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier, WORKSPACE, store, title, "text", text, "text", "completed", "虚构预置演示", 100, day, day, "zh", summary, text, sentiment, 1, "synthetic-demo-no-model-call", "demo-v1", dumps(metadata)))
                    evidence = [{"start": 0, "end": 0, "quote": text, "precision": "text"}]
                    con.execute("INSERT INTO events(id,workspace_id,record_id,title,theme,summary,quote,recommendation,severity,sentiment,role,evidence_json,review_status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier + "-event", WORKSPACE, identifier, title, theme, summary, text, recommendation, "medium" if sentiment == "negative" else "low", sentiment, "customer", dumps(evidence), "pending", day))
            con.execute("INSERT INTO experience_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (f"oss-demo-action-{index}", WORKSPACE, store, "入住办理", "虚构计划：核查高峰入住流程", "演示角色 · 运营负责人", "待决策" if index == 2 else "进行中", None if index == 2 else (end - timedelta(days=15)).isoformat(), (end + timedelta(days=7)).isoformat(), "演示设定：记录排队和房间就绪时间，先核查再决定资源投入。", "演示标准：核对实际时间和原声，前后差异不证明因果。", dumps({"synthetic": True})))
        total = con.execute("SELECT COUNT(*) FROM records WHERE workspace_id=?", (WORKSPACE,)).fetchone()[0]
        events = con.execute("SELECT COUNT(*) FROM events WHERE workspace_id=?", (WORKSPACE,)).fetchone()[0]
        stores = con.execute("SELECT COUNT(*) FROM stores WHERE workspace_id=?", (WORKSPACE,)).fetchone()[0]
        assert (total, events, stores) == (36, 36, 3)
    print("DONE: 36 original synthetic text samples, 36 precomputed demo events, 3 fictional locations. No model calls or third-party media.")
    print("Open http://127.0.0.1:8765/?workspace=open-source-demo")


if __name__ == "__main__":
    main()
