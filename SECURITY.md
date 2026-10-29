# Security Policy

## Supported Versions

This is a course project with no versioned releases. Only the latest code on the `main` branch receives fixes.

| Version         | Supported          |
| --------------- | ------------------ |
| `main` (latest) | :white_check_mark: |
| anything older  | :x:                |

## Scope

The project is meant to run on your own machine:

- The MCP server talks over stdio.
- The live viewer listens on `127.0.0.1` only and has no authentication.
- The TUI starts local subprocesses.

Reports are most useful when they concern the code in this repository, for example path handling in the CSV loaders, the viewer's HTTP endpoints, or the subprocess handling in the TUI. Vulnerabilities in Python, `uv`, `mcp`, `matplotlib` or Textual themselves should go to those projects.

## Reporting a Vulnerability

Please do not open a public issue for a vulnerability.

Use GitHub's private reporting instead: open the **Security** tab of this repository, choose **Report a vulnerability**, and describe the problem with steps to reproduce it.

This is a small project maintained in spare time, so replies are best effort. I will acknowledge a report as soon as I can, say whether I accept it as a vulnerability, and fix accepted reports on `main`. If a report is declined, I will explain why.
