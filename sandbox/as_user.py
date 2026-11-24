"""Run a command as the unprivileged test user (uid/gid 10001, no supplementary groups).

usage: python as_user.py <cmd> [args...]
Used where a tool, not runner.py, starts the test process (mutmut's --runner), so that test
code never runs as the root runner (B3). A no-op when not root.
"""
import os
import sys

if os.geteuid() == 0:
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
os.execvp(sys.argv[1], sys.argv[1:])
