"""把已完成任务的交付物文件补传到飞书（一次性探针）。"""

from pathlib import Path

from enterprise_energy_research.automation.feishu.lark import LarkFeishuAdapter

FILES = [
    "/data/automation_work/AGENTENT-01M0W5TYTVETEYWXZXA81YGT9W/outputs/artifacts/enterprise_research.docx",
    "/data/automation_work/AGENTENT-01M0W5TYTVETEYWXZXA81YGT9W/outputs/artifacts/enterprise_research.xlsx",
    "/data/automation_work/AGENTENT-01M0W5TYTVETEYWXZXA81YGT9W/outputs/artifacts/enterprise_research_dashboard.html",
]

adapter = LarkFeishuAdapter()
print("available =", adapter.available())
for ref in FILES:
    path = Path(ref)
    if not path.is_file():
        print("MISSING", ref)
        continue
    delivery = adapter.send_file("", str(path), file_name=path.name)
    print(path.name, "delivered =", delivery.delivered, delivery.diagnostics)
