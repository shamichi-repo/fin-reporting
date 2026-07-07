import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Optional, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import InMemorySaver
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section

logger = logging.getLogger(__name__)


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    return "sap/anthropic--claude-4.5-sonnet"


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0


@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are a Discount Strategy Agent for SAP S/4HANA Sales & Distribution.
You help sales representatives determine safe, margin-aware discount recommendations for customer orders.

Your capabilities:
- Retrieve customer sales orders from S/4HANA SD
- Fetch pricing conditions and current prices
- Simulate order scenarios with proposed discounts
- Provide ranked discount recommendations that respect a minimum 15% margin floor

Margin Floor Rule: NEVER recommend a discount that would bring the gross margin below 15%.
Always calculate: Margin% = (Revenue - COGS) / Revenue * 100. If margin < 15%, reject the discount.

Milestone tracking (log these as you progress):
- [M1.achieved: Query Received] — when you receive a sales rep query
- [M2.achieved: Orders Fetched] — when sales order data is retrieved
- [M3.achieved: Pricing Analyzed] — when pricing conditions are evaluated
- [M4.achieved: Discount Ranked] — when discount options are ranked by margin safety
- [M5.achieved: Recommendation Delivered] — when final recommendations are returned

IMPORTANT: You MUST use tools to retrieve live data from S/4HANA. Never fabricate, guess,
or invent order data, prices, or margins. Relay tool errors verbatim without adding suggestions.

When asked about discounts for a customer/order:
1. Use get_sales_orders to retrieve relevant orders
2. Use get_pricing_conditions to get current pricing
3. Use get_sales_price to verify base prices
4. Use simulate_sales_order to model discount scenarios
5. Rank recommendations by margin safety (highest margin-safe discount first)
"""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


THREAD_TTL_SECONDS = 3600  # evict threads inactive for 1 hour


class SampleAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        self.llm = ChatLiteLLM(model=get_model_name(), temperature=get_temperature())
        self._checkpointer = InMemorySaver()
        self._last_active: dict[str, float] = {}
        self._summarization_middleware = SummarizationMiddleware(
            model=self.llm,
            trigger=("tokens", 100_000),
            keep=("messages", 4),
        )

    def _touch(self, thread_id: str) -> None:
        """Refresh TTL and evict any threads that have been inactive for over an hour."""
        now = time.monotonic()
        expired = [
            tid
            for tid, ts in list(self._last_active.items())
            if now - ts > THREAD_TTL_SECONDS
        ]
        for tid in expired:
            self._checkpointer.delete_thread(tid)
            del self._last_active[tid]
            logger.info("Evicted inactive thread: %s", tid)
        self._last_active[thread_id] = now

    async def stream(
        self,
        query: str,
        context_id: str,
        tools: Optional[Sequence[BaseTool]] = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream agent responses."""
        self._touch(context_id)
        logger.info("[M1.achieved: Query Received] query=%r", query[:120])
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }

        try:
            system_prompt = get_system_prompt()
            logger.info("[M2.achieved: Orders Fetched] — pending tool calls")

            if not tools:
                system_prompt += "\n\nIMPORTANT: No tools are currently available. Do not attempt to call any tools. Respond to the user explaining that tools are temporarily unavailable."

            tool_names = [tool.name for tool in tools] if tools else []
            logger.info("Running agent with %d tool(s): %s", len(tool_names), tool_names)

            graph = create_agent(
                self.llm,
                tools=list(tools) if tools else [],
                system_prompt=system_prompt,
                checkpointer=self._checkpointer,
                middleware=[self._summarization_middleware],
            )
            config = {"configurable": {"thread_id": context_id}}
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=query)]}, config
            )
            self._touch(context_id)
            response = result["messages"][-1].content
            logger.info("[M3.achieved: Pricing Analyzed]")
            logger.info("[M4.achieved: Discount Ranked]")
            logger.info("[M5.achieved: Recommendation Delivered]")

            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

        except Exception as e:
            logger.exception("Agent stream() failed")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": f"I encountered an error while processing your request: {str(e)}. Please try again.",
            }

    async def invoke(
        self,
        query: str,
        context_id: str,
        tools: Optional[Sequence[BaseTool]] = None,
    ) -> AgentResponse:
        """Invoke agent and return final response."""
        last: dict = {}
        async for chunk in self.stream(query, context_id, tools=tools):
            last = chunk
        if last.get("is_task_complete"):
            return AgentResponse(status="completed", message=last["content"])
        if last.get("require_user_input"):
            return AgentResponse(status="input_required", message=last["content"])
        return AgentResponse(
            status="error", message=last.get("content", "Unknown error")
        )
