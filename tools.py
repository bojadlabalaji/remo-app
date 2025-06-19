# in remo-backend/tools.py

from playwright.async_api import async_playwright
# Import ToolContext to access agent actions
from google.adk.tools import ToolContext
import json
from fastapi import WebSocket

# This tool will let our agent exit the loop.
def finish_task(reason: str, tool_context: ToolContext):
    """
    Call this function ONLY when the user's goal has been fully achieved.
    This signals that the autonomous process should end.
    
    Args:
        reason: A brief explanation of why the task is considered complete.
    """
    print(f"--- Tool: finish_task called. Reason: {reason} ---")
    # This is the special action that tells a LoopAgent to stop iterating.
    tool_context.actions.escalate = True
    return {"status": "finished", "reason": reason}


async def use_browser_and_get_content(url: str) -> dict:
    """
    Navigates to a URL and returns a simplified version of the page's HTML content
    for an LLM to analyze.
    """
    print(f"--- Browser Tool Activated (Async): Navigating to {url} ---")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='domcontentloaded')
            
            print(f"--- Browser Tool: Successfully navigated to {url} ---")
            
            # Get the full HTML content of the page
            page_content = await page.content()
            
            await browser.close()
            
            # We will simplify this later. For now, just return it.
            return {"status": "success", "html_content": page_content}
    except Exception as e:
        print(f"--- Browser Tool: A critical error occurred: {e} ---")
        return {"status": "error", "message": str(e)}



async def start_interactive_session(url: str, websocket: WebSocket):
    """
    Launches a browser, injects rrweb, and streams DOM events
    back over the provided WebSocket connection.
    """
    print(f"--- Recorder Tool: Starting interactive session for URL: {url} ---")
    try:
        with open("rrweb.js", "r") as f:
            rrweb_script_content = f.read()
    except FileNotFoundError:
        await websocket.send_text(json.dumps({"error": "rrweb.js not found on server"}))
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # This function will now send data over the websocket
        async def send_event_to_frontend(event):
            await websocket.send_text(json.dumps(event))

        # Expose the function to the browser page
        await page.expose_function("send_event_to_backend", send_event_to_frontend)

        await page.goto(url)
        await page.evaluate(rrweb_script_content)
        await page.evaluate("""
            rrweb.record({
                emit(event) { window.send_event_to_backend(event); },
            });
        """)
        
        print(f"--- Recorder Tool: rrweb injected. Streaming events to WebSocket. ---")
        
        # Keep the session alive until the browser page is closed.
        page.on("close", lambda: print(f"Browser closed for session on {url}."))
        await page.wait_for_event("close")


