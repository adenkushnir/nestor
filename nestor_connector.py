# Nestor's connector for Claude Code and Claude Desktop: a small MCP server that the Claude app starts on this PC. It
# offers Nestor's tools (Datebook, the speaker, reminders, timers, trains, lights, Spotify) and passes each call on to
# Nestor's web API, wherever Nestor runs. To use a Nestor on another computer, set nestor_url in config.yaml and pair:
#     python nestor_connector.py --pair 123456
import json
import os
import sys
import urllib.error
import urllib.request
import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from nestor.config import DATA_DIR
from nestor.config import load_config
from nestor.storage import read_json
from nestor.storage import write_json
TOKEN_PATH = os.path.join(DATA_DIR, "connector_token.json")
TOOLS_PATH = os.path.join(DATA_DIR, "connector_tools.json")  # The last tool list, for when Nestor isn't running
TIMEOUT_SECONDS = 60  # Some tools speak or wait on Spotify, so they get a while
INSTRUCTIONS = ("Nestor runs the user's home: a Google speaker, Datebook (their calendar app, on their phone), "
                "reminders, timers and alarms, NJ Transit trains, Govee lights and Spotify. Adding to Datebook "
                "(datebook_action new_plan) shows a prompt on their phone to confirm. For lighting, have a real "
                "back-and-forth: ask what it's for, show one look at a time with preview_mood and a fun name, and "
                "tweak it with adjust_mood; lights_status says what's showing.")

# Where Nestor's web API is: the NESTOR_URL environment variable, nestor_url in config.yaml, or this PC
def nestor_url():
    settings = load_config()
    url = os.environ.get("NESTOR_URL") or settings.get("nestor_url")
    return (url or f"http://127.0.0.1:{int(settings.get('port', 8765))}").rstrip("/")

# Call Nestor's web API with the pairing token (if any); returns (reply JSON, None) or (None, why it failed)
def call_nestor(method, path, payload=None):
    headers = {"Content-Type": "application/json"}
    token = read_json(TOKEN_PATH, {}).get("token")

    # A paired connector shows its token
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(nestor_url() + path, data=body, method=method, headers=headers)

    # Nestor's own refusals carry a reason; no answer means it isn't running
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            return json.loads(reply.read()), None
    except urllib.error.HTTPError as error:
        # Nestor explains in JSON; anything else is shown as it came
        try:
            return None, json.loads(error.read()).get("error") or f"Nestor answered {error.code}"
        except ValueError:
            return None, f"Nestor answered {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, f"Nestor isn't answering at {nestor_url()} (is it running?): {error}"

# Nestor's tool list, kept for when Nestor isn't running (its tools then explain that it's off)
def fetch_tools():
    reply, problem = call_nestor("GET", "/tools")

    # A fresh list is kept; without Nestor, the last one known is used
    if reply:
        write_json(TOOLS_PATH, reply["tools"])
        return reply["tools"]
    print(f"Nestor's tools: {problem}", file=sys.stderr)
    return read_json(TOOLS_PATH, [])

# Run one tool on Nestor; returns (text for Claude, whether it failed)
def run_tool(name, arguments):
    reply, problem = call_nestor("POST", f"/tools/{name}", arguments)
    return (problem, True) if problem else (reply["result"], False)

# List the tools for the Claude app
async def list_tools(context, params):
    definitions = await anyio.to_thread.run_sync(fetch_tools)
    return types.ListToolsResult(tools=[types.Tool(name=tool["name"], description=tool["description"],
                                                   input_schema=tool["input_schema"]) for tool in definitions])

# Run a tool the Claude app asked for
async def call_tool(context, params):
    text, failed = await anyio.to_thread.run_sync(run_tool, params.name, params.arguments or {})
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=failed)

# Pair with a Nestor on another computer, using the code from python -m nestor --pair there
def pair(code):
    reply, problem = call_nestor("POST", "/pair", {"code": code, "device": "Claude connector", "kind": "computer"})

    # The token is kept in data/ (never committed)
    if problem:
        print(f"Pairing didn't work: {problem}")
        return 1
    write_json(TOKEN_PATH, {"token": reply["token"]})
    print(f"Paired with Nestor at {nestor_url()}")
    return 0

# Serve the Claude app over stdin and stdout until it closes the connection
async def serve():
    server = Server("nestor", version="1.0", instructions=INSTRUCTIONS, on_list_tools=list_tools,
                    on_call_tool=call_tool)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

# Pair when asked to, otherwise serve
if __name__ == "__main__":
    # --pair CODE pairs; anything else is the Claude app starting the connector
    if len(sys.argv) == 3 and sys.argv[1] == "--pair":
        sys.exit(pair(sys.argv[2]))
    anyio.run(serve)
