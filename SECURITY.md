# Security policy

This repository ships agent skills, command-line tools and a Claude Code
plugin that an estimator runs on their own machine against their own
BidSheet.ai and conformed.ai accounts. A flaw that lets a skill or tool act
outside what the user asked (write to a server the user did not name, read a
file outside the project, leak a token into an artifact or a log) is a
security issue, not just a bug. So is anything in the tree or the bundled
wheels that should not be public.

## Reporting

Report suspected vulnerabilities privately. Do not open a public issue: an
issue is visible to everyone the moment it is filed, before any fix exists.

1. **Preferred:** GitHub private vulnerability reporting —
   <https://github.com/BrandonLewis/estimating-tools/security/advisories/new>
   ("Report a vulnerability" on the repository's Security tab). Only you and
   the maintainer can see the advisory; the fix is coordinated there and the
   advisory is published when it ships.
2. **Fallback**, if you cannot use GitHub: email
   <security@anvilrockroad.com>.

Include a minimal reproduction (the skill or command and its input), the
version (`pip show estimating_tools`, or the plugin version from
`plugins/*/.claude-plugin/plugin.json`), and your platform.

You will get an acknowledgement within 5 business days. Fixes ship in the next
release with credit in the advisory and changelog unless you ask otherwise.

## Scope

- In scope: everything in this repository — `estimating_tools`, the plugins,
  the skills, the OpenWorker port, the manifest and IT templates, the
  bundled wheels.
- Out of scope: the BidSheet.ai and conformed.ai services the skills call
  (report through those products), the `bimforge` package
  (<https://github.com/BrandonLewis/BIMForge/security/policy>), and the
  libraries this repository depends on — report upstream, and tell us so we
  can raise the pinned minimum.

## Supported versions

Only the latest release receives fixes.
