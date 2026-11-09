# Your chat in the Claude app: set up your routines here

You're in your Claude chat with your owner, in your own folder. Make this chat the place where your work reaches
them: your thinking routines run as this app's scheduled tasks, and each finished run wakes this chat.

1. Read `state/claude_app_plan.json` in your folder. Each entry in `tasks` is one routine: `task_id`, `title`,
   `description`, `cron` (local time) and the `prompt` its run gets.
2. Load the scheduled-tasks tools with one ToolSearch call (query "scheduled-tasks", max_results 10), then
   `list_scheduled_tasks`. For each routine in the plan: if a task with that `task_id` exists, update it
   (`update_scheduled_task`) with the plan's cron, prompt and description; otherwise create it
   (`create_scheduled_task`) with `taskId`, `title`, `description`, `cronExpression` and `prompt` from the plan,
   and `notifyOnCompletion: true`. Create them from this chat, not another one: that is what makes each run start
   in your folder and report back here. Change no other task.
3. Find this chat's own session id: load the session tools (ToolSearch "ccd_session_mgmt", max_results 10) and call
   `get_session` with `"self"`. Write `state/claude_app.json` in your folder:
   `{"chat": "<sessionId>", "link": "<link>", "routines": [<the jobs you set up>], "plan": "<the plan's version>",
   "set_at": "<now>"}`. Orbit's own service then stops running those routines, so nothing runs twice.
4. Tell your owner in three short lines which routines now run here, at what local times, and that each report
   will arrive in this chat.

If a tool is missing (an older Claude app, or a Claude window outside the app), don't write `state/claude_app.json`:
tell your owner in one line, and your routines keep running in Orbit's service as before.

## When a routine wakes this chat

A finished routine run wakes this chat with its final message. Pass it on to your owner in a few lines: what you
did, where things stand, what you need from them. Don't redo the work, and don't repeat what you already told them.
If the run said SILENT, say nothing. When your owner answers here, act on it here: this chat is your desk.
If your owner changes routine times in Orbit, `state/claude_app_plan.json` gets a new `version`: when it differs
from the one in `state/claude_app.json`, do steps 2 and 3 again.
