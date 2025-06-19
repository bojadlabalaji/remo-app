# in remo-backend/test_thinker.py

import asyncio
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from agents import thinker_agent # Import our new LoopAgent

async def main():
    print("--- Testing the Thinker Agent ---")
    load_dotenv()
    
    session_service = InMemorySessionService()
    runner = Runner(agent=thinker_agent, app_name="remo_app", session_service=session_service)
    
    session = await session_service.create_session(
        app_name="remo_app",
        user_id="test_thinker_user",
        # Set the initial state for the agent to use
        state={
            "user_goal": "Find the main headline on the Hacker News homepage.",
            "page_observation": "" # Start with no observation
        }
    )
    
    # The initial message just triggers the agent to start. The logic is driven by the state.
    agent_input = Content(role="user", parts=[Part(text="Start task: Navigate to Hacker News and find the headline.")])
    
    async for event in runner.run_async(user_id="test_thinker_user", session_id=session.id, new_message=agent_input):
        if event.is_final_response():
            print(f"Thinker Agent Final Response: {event.content.parts[0].text}")

if __name__ == "__main__":
    asyncio.run(main())