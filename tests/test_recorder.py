# in remo-backend/test_recorder.py

import asyncio
from tools import start_recording_session

async def main():
    print("--- Testing the Recorder rrweb POC ---")
    # We call the tool directly, no agent needed for this POC
    await start_recording_session("https://google.github.io/adk-docs/")

if __name__ == "__main__":
    asyncio.run(main())