from __future__ import annotations

import unittest

from app.agents.di import make_agent_manager, make_agent_registry
from app.agents.interfaces import (
    AGENT_FOLLOW_UP,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AgentContext,
)
from app.agents.manager import DefaultAgentManager
from app.agents.property_search import PropertySearchAgent
from app.agents.selector import RuleAgentSelector
from app.agents.service import prepare_agent, set_agent_obs, get_agent_obs
from app.agents.skeletons import make_skeleton_agents
from app.supervisor.interfaces import SupervisorRequest
from app.supervisor.manager import DefaultSupervisor, DefaultSupervisorManager
from app.supervisor.policy import RuleExecutionPolicy
from app.supervisor.router import RuleRouter
from app.supervisor.service import set_supervisor_context


class MultiAgentLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = make_agent_registry()
        self.manager = make_agent_manager(self.registry)
        self.sup = DefaultSupervisorManager(
            DefaultSupervisor(router=RuleRouter(), policy=RuleExecutionPolicy())
        )

    def test_registry_has_active_and_skeletons(self) -> None:
        ids = self.registry.list_ids()
        self.assertIn(AGENT_PROPERTY_SEARCH, ids)
        self.assertIn(AGENT_PROPERTY_ANALYSIS, ids)
        self.assertIn(AGENT_FOLLOW_UP, ids)
        self.assertTrue(self.registry.get(AGENT_PROPERTY_SEARCH).active)
        for sk in make_skeleton_agents():
            self.assertFalse(sk.active)

    def test_property_search_route_selects_active_agent(self) -> None:
        out = self.sup.orchestrate(
            SupervisorRequest(message="ویلا تا ۱۵ میلیارد در دماوند پیدا کن")
        )
        set_supervisor_context(out)
        agent_out = self.manager.prepare(
            AgentContext(message="ویلا", route=out.workflow.route)
        )
        self.assertEqual(agent_out.selection.selected_agent, AGENT_PROPERTY_SEARCH)
        self.assertIsNotNone(agent_out.result)
        self.assertEqual(agent_out.result.status, "ready")
        self.assertEqual(agent_out.result.agent_tokens, 0)
        self.assertIn("rag", agent_out.result.used_components)
        self.assertIn(AGENT_PROPERTY_ANALYSIS, agent_out.selection.skipped_agents)
        set_supervisor_context(None)

    def test_greeting_skips_all_agents(self) -> None:
        out = self.sup.orchestrate(SupervisorRequest(message="سلام"))
        agent_out = self.manager.prepare(
            AgentContext(message="سلام", route=out.workflow.route)
        )
        self.assertEqual(agent_out.selection.selected_agent, "")
        self.assertTrue(agent_out.result.skipped)
        self.assertIn(AGENT_PROPERTY_SEARCH, agent_out.selection.skipped_agents)

    def test_selector_only_maps_search_routes(self) -> None:
        sel = RuleAgentSelector(self.registry)
        s1 = sel.select(route="property_search", ctx=AgentContext(message="x"))
        s2 = sel.select(route="faq", ctx=AgentContext(message="x"))
        self.assertEqual(s1.selected_agent, AGENT_PROPERTY_SEARCH)
        self.assertEqual(s2.selected_agent, "")

    def test_skeleton_not_executed_as_active(self) -> None:
        agent = self.registry.get(AGENT_PROPERTY_ANALYSIS)
        result = agent.run(AgentContext(message="test"))
        self.assertEqual(result.status, "skeleton")
        self.assertTrue(result.skipped)

    def test_service_obs(self) -> None:
        set_agent_obs(None)
        out = prepare_agent(
            message="زمین در لواسان",
            route="property_search",
        )
        set_agent_obs(out)
        obs = get_agent_obs()
        self.assertEqual(obs["selected_agent"], AGENT_PROPERTY_SEARCH)
        self.assertEqual(obs["agent_tokens"], 0)
        set_agent_obs(None)

    def test_property_search_agent_zero_tokens(self) -> None:
        agent = PropertySearchAgent()
        result = agent.run(AgentContext(message="ویلا", route="property_search"))
        self.assertEqual(result.agent_tokens, 0)
        self.assertEqual(result.metadata.get("pipeline"), "existing")


if __name__ == "__main__":
    unittest.main()
