# Chat channels

Your employees answer on Telegram, Slack or Discord, through bots you create yourself. Each install talks
only to the bots whose tokens you saved; nobody else can reach your bots, and your bots reach nobody else.
Only approved owners can direct the team. A stranger who messages one of your bots gets no answer and is
listed in the control panel under Settings → Access, where you decide.

## Telegram

1. In Telegram, open **@BotFather**, send `/newbot`, follow the two questions and copy the token it gives you.
2. On the Mac: `staff secret telegram` (paste the token; it is typed hidden and stored only on this Mac).
3. Message your bot once (anything), then approve yourself in the control panel: `staff panel` →
   Settings → Access.

**Team group.** Add the bot to a Telegram group as an admin (so it can read the messages), send any
message there, then read the chat id from `staff logs` (a line like "unregistered telegram chat
-100…") and run `staff group -100…`. Mention employees in the group as `/sara` or by name.

## Slack

1. Go to **api.slack.com/apps** → Create New App → **From a manifest** → pick your workspace → paste the
   manifest below (YAML) → Create.
2. **Install to Workspace** (under Install App), then copy the **Bot User OAuth Token** (`xoxb-…`).
3. Under **Basic Information → App-Level Tokens**, generate a token with the scope `connections:write`
   and copy it (`xapp-…`). This is what lets the bot receive messages without a public address
   (Socket Mode).
4. On the Mac: `staff secret slack` (it asks for both tokens).
5. If `staff doctor` asks for it: `pip3 install --user websocket-client` (the only package the
   Slack and Discord listeners need).
6. In Slack, open the app's Messages tab and DM the bot once, then approve yourself in the control
   panel (Settings → Access).

The manifest:

```yaml
display_information:
  name: Staffroom
  description: My AI team
features:
  app_home:
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: Staffroom
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - files:read
      - files:write
      - groups:history
      - im:history
      - im:read
      - im:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
  interactivity:
    is_enabled: false
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

Rename the app and the bot as you like; the scopes and events are what the kit needs (reading DMs and
the channels it is invited to, posting, sending and receiving files, looking up who wrote).

**Team channel.** Invite the bot to the channel (`/invite @Staffroom`), then `staff group C0… --channel
slack`. The channel id is in the channel's details (open the channel name → the id is at the bottom).
Mention employees as `@sara` (Slack keeps `/` for its own slash commands). Slack shows the bot's
replies at the top level of the channel, not in threads.

## Discord

1. Go to **discord.com/developers** → New Application → name it → open **Bot** in the left menu.
2. **Reset Token**, copy the token. On the same page, under **Privileged Gateway Intents**, enable
   **Message Content Intent** (without it the bot receives empty messages).
3. Under **OAuth2 → URL Generator**: scope `bot`; bot permissions **View Channels**, **Send Messages**,
   **Read Message History**, **Attach Files**. Open the generated URL and pick your server to invite
   the bot.
4. On the Mac: `staff secret discord`. If `staff doctor` asks for it: `pip3 install --user websocket-client`.
5. DM the bot (open its profile from the server's member list → Message; a bot can only be messaged by
   people who share a server with it), then approve yourself in the control panel (Settings → Access).

**Team channel.** `staff group <channel id> --channel discord`. To see channel ids, turn on Developer
Mode (User Settings → Advanced), then right-click the channel → Copy Channel ID. Mention employees
as `@sara`. Messages up to 2,000 characters; longer answers arrive in parts.

## What the kit never does

- No user tokens: every channel runs as a bot you created, with a bot token. The kit never signs in as
  you.
- It never reads a channel it wasn't invited to. On Slack and Discord it only receives what the bot's
  own membership and scopes allow; private messages reach it only from people who message the bot.
- It never messages anyone but approved owners and the team chat you registered. A stranger's message
  is logged for you, never answered.
- Tokens stay in `~/Staff/.secrets`, readable by you and the service, never by employees: that folder
  is on the sandbox's deny list, and the guard blocks reading it.
- Employees can't use the raw chat APIs: the guard blocks `api.telegram.org`, `slack.com/api`,
  `discord.com/api` and the like, and the sandbox can't reach them. Everything an employee says goes
  through the service, which delivers only to the addresses above.
