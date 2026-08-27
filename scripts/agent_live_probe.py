# Live agent probe (local-only, not committed test): real DeepSeek structured parsing.
import os

for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

from enterprise_energy_research.settings import Settings
from enterprise_energy_research.gateway import LiteLLMModelGateway
from enterprise_energy_research.agent.mission_parser import MissionParser
from enterprise_energy_research.agent.goal_planner import GoalPlanner
from enterprise_energy_research.agent.router import ResearchSkillRouter
from enterprise_energy_research.agent.models import ResearchMission, ResearchMode
from enterprise_energy_research.domain.ids import new_sortable_id

gateway = LiteLLMModelGateway(Settings())
parser = MissionParser(gateway)
planner = GoalPlanner()
router = ResearchSkillRouter(gateway)

cases = [
    "调研宁波鄞开集团，重点分析主营业务、生产基地、产品线和竞争情况。",
    "调研阳光电源在西班牙户储市场的发展机会。",
    "调查企业A有没有针对矿山场景开发储能产品",
]
for text in cases:
    result = parser.parse(text)
    print("=" * 60)
    print("request:", text)
    print("mode:", result.mode.value, "| parse_mode:", result.parse_mode)
    print("subject:", result.primary_subject, "| geo:", result.geographies)
    print("custom_goals:", [(g.name, g.goal_class_hint) for g in result.custom_goals])
    print("market_goals:", [(g.name, g.geography) for g in result.market_goals])
    mission = ResearchMission(mission_id=new_sortable_id("MISSION"), raw_request=text)
    mission.mode = result.mode
    mission.primary_subject = result.primary_subject
    mission.geographies = result.geographies
    goals = planner.plan(mission, result)
    routing = router.route(mission, goals)
    ent = sum(1 for d in routing if d.assigned_skill.value == "ENTERPRISE_RESEARCH")
    mkt = sum(1 for d in routing if d.assigned_skill.value == "OVERSEAS_MARKET_RESEARCH")
    print(f"goals: {len(goals)} (enterprise={ent}, market={mkt})")
    print("sample routing_reason:", routing[0].routing_reason[:80] if routing else "-")
