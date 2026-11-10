# Security policy

Please report a vulnerability privately through GitHub's **Report a vulnerability** button on the
Security tab of this repository, or by email to support@tanrenway.com. Do not open a public
issue, and do not include real account numbers, passwords, tokens or trading data.

We aim to acknowledge a report within three working days.

## Scope

- This repository: the Windows app, its installer and its release workflow.
- How the app authenticates to Tanren and what it sends.

The Tanren website and server are operated separately; report issues with them to the same
address. Security of the service never depends on this source code being secret: the server
treats every client as untrusted, scopes every request to the paired device and owner, and a
revoked device cannot send data.
