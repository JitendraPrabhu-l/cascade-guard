# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please email **jitendraprabhul@gmail.com** with the details (or use GitHub's
private vulnerability reporting on the repository). Do **not** open a public
issue for security reports. You can expect an acknowledgement within 72 hours
and a fix or mitigation plan within 30 days for confirmed issues.

## Threat model notes for users

- **Traces are untrusted input.** Cascade Guard parses arbitrary JSON and
  renders excerpts into HTML; all rendered content is escaped, and the report
  is fully self-contained (no external scripts, styles, or images). Report any
  escaping gap as a vulnerability.
- **No network by default.** The core performs no network I/O and emits no
  telemetry. Only the optional `--judge anthropic` mode calls an external API —
  it sends transcript excerpts to Anthropic, so do not enable it on traces
  containing data you may not share.
- **Secrets in traces.** Agent logs frequently capture prompts, tool outputs,
  and sometimes credentials. Cascade Guard copies excerpts into its reports —
  treat generated reports with the same sensitivity as the traces themselves.
