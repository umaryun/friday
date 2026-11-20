# Friday

Press the watch button → Siri → "Friday" → say what you want → hear the result on your wrist.

```
Watch (mic + speaker) → iPhone Shortcut → Jarvis server (Gemini + tools) ⇄ Mac agent (when the Mac is on)
```

| Part | File | Runs where |
|---|---|---|
| Server: the brain, plus memory, reminders, web, Gmail, Calendar, MCP servers (GitHub…) | `server.py`, `agent.py`, `cloud_tools.py`, `google_tools.py`, `mcp_hub.py` | Your Mac for testing, a cloud server later |
| Mac agent: WhatsApp, iMessage, Contacts, files, Claude Code | `mac_agent.py` | Your Mac |

The Mac agent connects *out* to the server, so the server works on its own when the Mac is closed. It just
tells you Mac-only tasks have to wait.

## 1. First test (iPhone and Mac on the same Wi-Fi)

1. Get a free Gemini key at https://aistudio.google.com/apikey and paste it into `.env` as `GEMINI_API_KEY`.
   `.env` already has a generated `JARVIS_TOKEN` and `NTFY_TOPIC`. Also set `DEFAULT_COUNTRY_CODE` (e.g. `234`).
2. Start the server in one terminal:
   ```bash
   .venv/bin/python server.py
   ```
3. Start the Mac agent in a second terminal:
   ```bash
   .venv/bin/python mac_agent.py
   ```
4. Try it from the Mac before involving the phone:
   ```bash
   curl -s localhost:8787/ask -H "Authorization: Bearer $(grep ^JARVIS_TOKEN .env | cut -d= -f2)" -H 'Content-Type: application/json' -d '{"text":"what projects do I have?"}'
   ```

The first time Jarvis uses Contacts, Messages or WhatsApp, macOS asks for permission for Terminal. Allow it.
WhatsApp also needs **System Settings → Privacy & Security → Accessibility → Terminal** (so it can press Enter).

## 2. The iPhone Shortcut

Create a shortcut named **Friday** (a plain English word Siri never mishears). It runs as a loop: listen,
ask the server, speak, and listen again until you say "thanks"/"that's all" or stay quiet.

1. **Text**: leave it empty. Then **Set Variable**: name `session`, input *Text*.
2. **Repeat** 10 times. Put everything below inside the Repeat:
   1. **Dictate Text** (Stop Listening: *After Pause*)
   2. **Get Contents of URL**
      - URL: `http://<your Mac's Wi-Fi IP>:8787/ask` (later, your cloud URL)
      - Method **POST**, Header `Authorization` = `Bearer <JARVIS_TOKEN from .env>`
      - Request Body **JSON**: `text` = *Dictated Text*, `session` = the *session* variable
   3. **Get Dictionary Value**: key `reply` from *Contents of URL* → **Speak Text** (*Dictionary Value*)
   4. **Get Dictionary Value**: key `session` from *Contents of URL* → **Set Variable** `session`
   5. **Get Dictionary Value**: key `listen` from *Contents of URL* → **Text** (*Dictionary Value*)
   6. **If** *Text* **is** `no` → **Stop This Shortcut** → **End If**
3. **End Repeat**

Press the watch button, say **"Friday"**, wait for the chime, then talk. After each answer you get another
chime and can carry on. Calling Friday again within 15 minutes continues the same conversation, and it
keeps a log of recent conversations, so "what did I ask you earlier?" works.

## 3. Connections

Friday connects to services in two ways:

- **MCP servers** listed in `mcp_servers.json` (handled by `mcp_hub.py`). Add any MCP server there, hosted
  (`url` + `headers`) or local (`command` + `args`), and its tools show up automatically. Use `${VAR}` for
  secrets; they come from `.env`, and a server whose token is empty is skipped.
- **Custom tools** for things without a suitable MCP server: Gmail/Calendar (`google_tools.py`),
  WhatsApp, iMessage, files and Claude Code (`mac_agent.py`).

`curl localhost:8787/health` shows which MCP servers are connected.

### GitHub (MCP)

1. Open https://github.com/settings/personal-access-tokens/new (fine-grained token).
2. Name it `Friday`, pick an expiry, **Repository access → All repositories**.
3. Permissions (Repository): **Contents, Issues, Pull requests, Actions, Metadata: Read-only**, and
   **Issues: Read and write** if you want "open an issue…". Account permissions: **Notifications** isn't
   available on fine-grained tokens; skip it.
4. Put it in `.env` as `GITHUB_TOKEN=...` and restart the server.

Friday only gets GitHub's read tools plus creating issues and comments (`read_only` and `allow_writes`
in `mcp_servers.json`), and asks before writing.

### Gmail and Calendar (custom tools)

Google's own Gmail/Calendar MCP servers are invite-only previews and the Gmail one can't send email, so
these stay as six small custom tools.

1. https://console.cloud.google.com → new project → enable **Gmail API** and **Google Calendar API**.
2. **APIs & Services → OAuth consent screen**: External, add yourself as a test user.
3. **Credentials → Create credentials → OAuth client ID → Desktop app** → download the JSON to `data/google_client.json`.
4. Run `.venv/bin/python setup_google.py` and sign in. Restart the server.

## 4. Claude Code sign-in (one time)

Jarvis runs the Claude Code that comes with the Claude desktop app. To give it a long-lived login, run
this in Terminal, sign in through the browser, and copy the token it prints:

```bash
"$(ls -t ~/Library/Application\ Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude | head -1)" setup-token
```

Add it to `.env` as `CLAUDE_CODE_OAUTH_TOKEN=...`, then restart `mac_agent.py`.

## 5. Things to say

- "Tell Ibrahim on WhatsApp I'm on my way" *(Mac on)*
- "Ask Claude Code in bizbot why the login test is failing" *(Mac on; long jobs send a notification when done)*
- "Follow up with Claude Code in bizbot: go ahead and fix it" *(continues the same Claude Code conversation)*
- "Remind me to call mum at 7"
- "Remember Ibrahim is my brother"
- "Is https://my-site.com up?"
- "What's the dollar to naira rate?"
- "Any open pull requests on bizbot?" / "Did my last GitHub Action pass?" *(after GitHub)*
- "Any important emails today?" / "What's on my calendar tomorrow?" *(after step 3)*

## Settings

- `CONFIRM_BEFORE_SEND=false` sends messages without reading them back first.
- `FOLLOW_UPS=false` makes Friday answer once and stop listening.
- `CONVERSATION_IDLE_MINUTES` (default 15) sets how long a conversation stays open between calls.
- `ASSISTANT_NAME` sets what the assistant calls itself.
- `CLAUDE_CODE_ARGS` sets the flags passed to Claude Code. The default (`--permission-mode acceptEdits`)
  lets it edit files but not run shell commands, so it won't run, commit or push anything from a voice request.
- `GEMINI_MODEL`: change it if Google retires the default.

## Next: always-on cloud

Deploy `server.py` to a small cloud host (Railway, Fly.io, Hetzner…), set the same `.env` values there
(plus `TIMEZONE`), then point the Shortcut URL and the Mac's `JARVIS_SERVER_URL` at it.
# friday
