# Cowork Connector Setup

Cowork connects from Anthropic's cloud and supports **remote + OAuth only**
(no custom headers). Register each server below as an org-level Custom Connector
(Team/Enterprise Owners), then members click Connect and sign in via SSO.

## bidmanager

- **URL:** https://www.bidsheet.ai/mcp/
- **Auth:** OAuth 2.1 (per-user SSO)
- **Description:** BidSheet.ai estimating data (projects, bid items, estimates, assemblies, quotes, work packages).

## conformed

- **URL:** https://conformed-production.up.railway.app/mcp/
- **Auth:** OAuth 2.1 (per-user SSO)
- **Description:** conformed.ai document-conformance (plans/specs, conformance checks).
