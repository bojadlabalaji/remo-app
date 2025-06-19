

from google.adk.agents import LlmAgent, LoopAgent
# Import our new tools
from tools import use_browser_and_get_content, finish_task

# Create an instance of an LlmAgent. This is the standard way to create
# an agent that can reason and use tools.
browser_agent = LlmAgent(
    name="BrowserAgent",
    model="gemini-2.0-flash", # A fast and capable model for tool use
    
    # The instruction is the most critical part for a tool-using agent.
    # It tells the LLM how to behave and when to use its tools.
    instruction="""You are a simple web browsing assistant.
    Your sole purpose is to take a URL provided by the user and call the `use_browser` tool with that exact URL.
    Do not modify the URL. Do not ask questions. Just call the tool.
    After the tool is called, confirm the success message from the tool's output.
    """,

    # We provide the agent with a list of tools it is allowed to use.
    tools=[use_browser_and_get_content],
    description="A simple agent that takes a URL and uses a tool to browse it."
)



# The Planner is the "brain" of the loop.
planner_agent = LlmAgent(
    name="PlannerAgent",
    model="gemini-2.0-flash",
    instruction="""You are a web agent planner. Your goal is to help a user achieve a task on a webpage.
    Based on the user's goal and the current HTML content of the page, decide the single next action to take.
    
    Your available actions are:
    1. `use_browser_and_get_content(url)`: To navigate to a new page.
    2. `finish_task(reason)`: If the goal is fully accomplished.
    
    Analyze the {page_observation} and the {user_goal}. If the goal is met, call `finish_task`.
    Otherwise, choose the next logical tool to call.
    """,
    tools=[use_browser_and_get_content, finish_task],
)

# The ThinkerAgent is a LoopAgent that orchestrates the planning.
# For now, it just has one step. We will add an Executor later.
thinker_agent = LoopAgent(
    name="ThinkerAgent",
    sub_agents=[
        planner_agent,
    ],
    max_iterations=5 # Set a limit to prevent infinite loops
)