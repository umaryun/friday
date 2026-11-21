"""The brain: takes what you said, lets Gemini call tools until the job is done, returns a spoken reply."""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

import cloud_tools
import config
import google_tools
from mac_bridge import mac
from mcp_hub import hub

# 20 s per AI call, so a stuck request moves to a backup model instead of hanging the Shortcut.
client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=20_000))
MODELS = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACK_MODELS if m != config.GEMINI_MODEL]


async def _generate(contents, gen_config):
    """Call Gemini, moving down the model list when one is busy, slow or rate-limited."""
    last_error = None
    for model in MODELS:
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=gen_config)
        except errors.APIError as e:
            if e.code not in (429, 500, 503, 504):
                raise
            last_error = e
        except Exception as e:  # timeouts, network drops
            last_error = e
        print(f"  {model} unavailable ({str(last_error)[:60]}), trying next model")
    raise last_error

MAX_STEPS = 12
MAX_SEARCHES = 1       # web searches allowed per request (each takes ~4s)
CONVERSATION_IDLE = config.CONVERSATION_IDLE_MINUTES * 60  # after this much silence, start a fresh conversation
ASK_TIMEOUT = 120      # a confirmation question left unanswered this long counts as "no"
MAX_CONTENTS = 60      # start a fresh conversation (keeping the history log) when one gets this long
HISTORY_FILE = config.DATA_DIR / "history.json"
GOODBYES = {"thanks", "thank you", "thanks friday", "that's all", "thats all", "that is all", "bye", "goodbye",
            "stop", "nothing", "no thanks", "never mind", "nevermind", "i'm good", "im good", "ok thanks",
            "okay thanks", "cool thanks"}

ASK_USER = {
    "name": "ask_user",
    "description": "Ask the user a short spoken question and wait for their answer. Use it to confirm before "
                   "sending a message or email, or when a request is unclear (e.g. two contacts match).",
    "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
}
WEB_SEARCH = {
    "name": "web_search",
    "description": "Search the web for current information (news, prices, exchange rates, weather, facts).",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}
END_CONVERSATION = {
    "name": "end_conversation",
    "description": "Call when the user is done talking (e.g. 'thanks', 'that's all', 'bye'), then say a very "
                   "short goodbye. Their watch stops listening.",
    "parameters": {"type": "object", "properties": {}},
}

SYSTEM = """You are {name}, a voice assistant. The user talks to you through a smartwatch and hears your \
reply read aloud by Siri. After each reply the watch keeps listening, so this is a flowing conversation:
- Reply in one or two short plain sentences. No markdown, lists, emojis or URLs.
- Act, don't describe. Use tools to get things done, then say what you did.
- For currencies use exchange_rate and for weather use weather; they are instant and exact.
- For anything else current, search the web once and answer from those results.
- Use the conversation so far: "send that to Ibrahim too" or "what about tomorrow?" refer to earlier turns.
- Don't end every reply with "anything else?"; the watch is already listening.
- Say exactly what you sent and to whom, e.g. "Sent to Ibrahim: on my way bro."
- If something fails, say so plainly. Never claim an action worked unless the tool said it did.
- Write messages the way the user would: casual, short, in their voice.
- Never make payments or delete anything.
{confirm}
Connected services: {services}. Tools named github_... act on the user's GitHub; use github_get_me \
to find their username. Before anything that creates or changes something (an issue, a comment, a \
calendar event), use ask_user to check first.
Some tools run on the user's Mac and only exist while the Mac is on. The Mac is {mac_state}.
If a request needs the Mac (WhatsApp, iMessage, files, Claude Code) and it's offline, say so.
For WhatsApp and iMessage, look the person up with contacts_search first.

Current time: {now}.
Things the user asked you to remember:
{memory}

Earlier conversations (oldest first), for context:
{history}"""


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    contents: list = field(default_factory=list)
    ask_call: types.FunctionCall | None = None
    held_responses: list = field(default_factory=list)
    started: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    ended: bool = False
    searches: int = 0  # web searches used for the current request


convo: Conversation | None = None


# ---------- history log (survives restarts and new conversations) ----------

def _load_history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _log_exchange(user: str, reply: str):
    items = _load_history()
    items.append({"t": time.time(), "when": config.now().strftime("%a %H:%M"), "user": user, "reply": reply})
    HISTORY_FILE.write_text(json.dumps(items[-50:], indent=1))


def _history_text(before: float) -> str:
    older = [h for h in _load_history() if h["t"] < before][-15:]
    return "\n".join(f"[{h['when']}] User: {h['user']} | You: {h['reply']}" for h in older) or "(none)"


# ---------- prompt and tools, rebuilt every turn so time and Mac state are current ----------

def _tools() -> list[dict]:
    return ([ASK_USER, WEB_SEARCH, END_CONVERSATION] + cloud_tools.TOOLS + hub.tools()
            + (mac.tools if mac.online else []))


def _system(c: Conversation) -> str:
    memory = "\n".join(f"- [{n['id']}] {n['note']}" for n in cloud_tools.memory_notes()) or "(nothing yet)"
    confirm = ("- Before sending any message or email, use ask_user to read it back and get a yes."
               if config.CONFIRM_BEFORE_SEND else "")
    return SYSTEM.format(
        name=config.ASSISTANT_NAME,
        confirm=confirm,
        services=", ".join(hub.connected() + (["Gmail", "Google Calendar"] if google_tools.available() else [])) or "none",
        mac_state="ONLINE" if mac.online else "OFFLINE",
        now=config.now().strftime("%A %d %B %Y, %H:%M (%Z)"),
        memory=memory,
        history=_history_text(before=c.started),
    )


def _declaration(t: dict) -> types.FunctionDeclaration:
    params = t["parameters"] if t["parameters"].get("properties") else None
    return types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=params)


def _response_part(call: types.FunctionCall, result: str) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response={"result": result}))


def _web_search_sync(query: str) -> str:
    # Gemini's built-in Google Search has no free quota, so use the free ddgs library instead.
    from ddgs import DDGS

    results = DDGS().text(query, max_results=8, backend="google,bing")
    return "\n".join(f"- {r['title']}: {r['body']} ({r['href']})" for r in results) or "No results."


async def _run_tool(call: types.FunctionCall, c: Conversation) -> str:
    args = dict(call.args or {})
    print(f"  tool {call.name} {args}")
    try:
        if call.name == "end_conversation":
            c.ended = True
            return "OK. Say a very short goodbye."
        if call.name == "web_search":
            c.searches += 1
            if c.searches > MAX_SEARCHES:
                return "Search limit reached for this question. Answer now from the results you already have."
            return await asyncio.to_thread(_web_search_sync, args.get("query", ""))
        if call.name in cloud_tools.TOOLS_BY_NAME:
            return str(await asyncio.to_thread(cloud_tools.TOOLS_BY_NAME[call.name]["fn"], **args))
        if hub.has(call.name):
            return await hub.call(call.name, args)
        if mac.has(call.name):
            return await mac.call(call.name, args)
        return f"The tool {call.name} is not available right now (the Mac may be offline)."
    except Exception as e:
        return f"Error: {e}"


# ---------- main entry ----------

def _current_conversation() -> Conversation:
    """One running conversation. It carries on across Shortcut runs until you go quiet for a while."""
    global convo
    idle = convo is None or time.time() - convo.updated > CONVERSATION_IDLE
    too_long = convo is not None and not convo.ask_call and len(convo.contents) > MAX_CONTENTS
    if idle or too_long:
        convo = Conversation()
    return convo


async def handle(text: str, session_id: str = "") -> dict:
    """One spoken request in, one spoken reply out."""
    if not text:
        return _finish(None, "", "Okay, talk later.", listen=False)

    c = _current_conversation()
    c.ended, c.searches = False, 0
    if text.lower().strip(" .!?,") in GOODBYES and not c.ask_call:
        c.updated = time.time()
        return _finish(c, text, "Anytime.", listen=False)

    if c.ask_call:
        if time.time() - c.updated > ASK_TIMEOUT:  # they never answered; treat as no, then handle the new request
            parts = c.held_responses + [_response_part(c.ask_call, "No answer, so not done. Don't do it."),
                                        types.Part(text=text)]
        else:  # this text answers the question we just asked
            parts = c.held_responses + [_response_part(c.ask_call, text)]
        c.ask_call, c.held_responses = None, []
    else:
        parts = [types.Part(text=text)]
    c.contents.append(types.Content(role="user", parts=parts))
    c.updated = time.time()

    gen_config = types.GenerateContentConfig(
        system_instruction=_system(c),
        tools=[types.Tool(function_declarations=[_declaration(t) for t in _tools()])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for _ in range(MAX_STEPS):
        try:
            resp = await _generate(c.contents, gen_config)
        except errors.APIError as e:
            c.contents.pop()  # drop the unanswered turn so the conversation stays valid
            if e.code in (429, 503, 504):
                return _finish(c, text, "Gemini is busy or I've hit the free limit. Give me a minute.", listen=False)
            return _finish(c, text, f"The AI service failed: {e.message}", listen=False)
        except Exception as e:  # timeouts, network drops
            print("  AI call error:", repr(e))
            c.contents.pop()
            return _finish(c, text, "The AI service didn't answer in time. Try again.", listen=False)

        if not resp.candidates or not resp.candidates[0].content:
            return _finish(c, text, "Sorry, I couldn't come up with an answer.")
        c.contents.append(resp.candidates[0].content)

        calls = resp.function_calls or []
        if not calls:
            return _finish(c, text, (resp.text or "Done.").strip(), listen=not c.ended)

        ask = next((x for x in calls if x.name == "ask_user"), None)
        others = [x for x in calls if x.name != "ask_user"]
        results = await asyncio.gather(*(_run_tool(x, c) for x in others))
        parts = [_response_part(x, r) for x, r in zip(others, results)]

        if ask:  # pause here; the user's next utterance is the answer
            c.ask_call, c.held_responses = ask, parts
            return _finish(c, text, (ask.args or {}).get("question", "Should I go ahead?"), listen=True)

        c.contents.append(types.Content(role="user", parts=parts))

    return _finish(c, text, "That took too many steps, so I stopped. Try asking in a simpler way.")


def _finish(c: Conversation | None, user_text: str, reply: str, listen: bool = True) -> dict:
    print(f"  -> {reply}")
    if user_text:
        _log_exchange(user_text, reply)
    if c:
        c.updated = time.time()
    listen = listen and (config.FOLLOW_UPS or bool(c and c.ask_call))
    # "listen" is plain text because Shortcuts compares text more reliably than booleans.
    return {"reply": reply, "listen": "yes" if listen else "no", "expects_reply": listen,
            "session": c.id if c else ""}
