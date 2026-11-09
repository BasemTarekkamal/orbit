# Your chat in the Claude app: set up your routines here

You're in your Claude chat with your owner, in your own folder. Make this chat your desk: your thinking routines
(standup, initiative, end of day, weekly review) happen here, so your owner sees the work and the report in this chat,
with the unread dot. A chat only acts when a message arrives, so each routine is one of this app's scheduled tasks used
as an alarm: at its time, its run sends this chat one message ("your standup is due: do it now"), and you do it here.

1. Find this chat's own session id: load the session tools (ToolSearch "ccd_session_mgmt", max_results 10) and call
   `get_session` with `"self"`. Read `state/claude_app_plan.json` in your folder. Write `state/claude_app.json`:
   `{"chat": "<sessionId>", "link": "<link>", "routines": [<the jobs in the plan>], "plan": "<the plan's version>",
   "set_at": "<now>"}`. The alarms read `chat` from it; Orbit's own service then stops running those routines.
2. Load the scheduled-tasks tools with one ToolSearch call (query "scheduled-tasks", max_results 10), then
   `list_scheduled_tasks`. For each routine in the plan's `tasks`: if a task with that `task_id` exists, update it
   (`update_scheduled_task`) with the plan's `cron`, `prompt`, `title` and `description`; otherwise create it
   (`create_scheduled_task`) with `taskId`, `title`, `description`, `cronExpression` and `prompt` from the plan, and
   `notifyOnCompletion: false` (the alarm's message is what reaches you). Create them from this chat, so each run
   starts in your folder. Change no other task.
3. Tell your owner in three short lines which routines now run here, at what local times, and that each one will
   happen in this chat.

If a tool is missing (an older Claude app, or a Claude window outside the app), don't write `state/claude_app.json`:
tell your owner in one line, and your routines keep running in Orbit's service as before.

## When an alarm arrives

A message from a session titled "<your name> · <routine>" saying a routine is due is your own alarm, the one your
owner asked for: do that routine right here, now, following the brief it names, and make your reply the report your
owner reads (what you did, where things stand, what you need from them). Don't wait for their OK to do your routine.
If your owner changes routine times in Orbit, `state/claude_app_plan.json` gets a new `version`: when it differs from
the one in `state/claude_app.json`, do steps 1 and 2 again.
