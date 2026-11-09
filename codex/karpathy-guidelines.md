# Coding discipline

Follow these rules on every coding task. For a trivial task, use judgment and keep it short.

## Understand first
- Read the code that your change touches before you edit it.
- State your assumptions in the answer. Do not hide them.
- If a request has more than one meaning, list the meanings. Do not pick one in silence.
- If a simpler way exists, say so before you start.
- If a part of the task is unclear and a wrong guess is costly, stop and name what is unclear.

## Keep it small
- Write the least code that solves the task.
- Add no feature that the user did not request.
- Add no abstraction for code that has one use.
- Add no option or setting that nobody asked for.
- Add no error handling for a case that cannot occur.
- If your draft is much longer than the task needs, rewrite it shorter.

## Change only what you must
- Edit only the lines that the task needs. Each changed line must trace to the request.
- Do not reformat, rename, or refactor code that works.
- Match the style of the file, even if you prefer another style.
- If you see unrelated dead code or a bug, report it. Do not fix it.
- Remove the imports, variables, and functions that your own change made unused.
- Keep dead code that was there before your change.

## Define done, then prove it
- Turn the task into a check that you can run.
- For a bug: write a test that fails, then make it pass.
- For new input rules: write tests for bad input, then make them pass.
- For a refactor: run the tests before and after. Both runs must pass.
- For a task with many steps, write a short plan. Give each step a check:
  1. Step -> check
  2. Step -> check
- Run the checks. Do not say "done" until they pass.
- Report the real command and its real output.
