@echo off
rem work-plan CLI launcher (Windows). Resolves work_plan.py relative to this
rem shim's parent (the wrapper lives at <root>\bin\work-plan.cmd).
set "WP=%~dp0..\skills\work-plan\work_plan.py"
if exist "%WP%" ( python "%WP%" %* & goto :eof )
if defined CLAUDE_PLUGIN_ROOT if exist "%CLAUDE_PLUGIN_ROOT%\skills\work-plan\work_plan.py" ( python "%CLAUDE_PLUGIN_ROOT%\skills\work-plan\work_plan.py" %* & goto :eof )
if exist "%USERPROFILE%\.claude\skills\work-plan\work_plan.py" ( python "%USERPROFILE%\.claude\skills\work-plan\work_plan.py" %* & goto :eof )
echo work-plan: CLI not found. 1>&2
exit /b 1
