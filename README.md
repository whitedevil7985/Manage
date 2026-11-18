# Manage — Heroku Management Bot

A private, owner-controlled Telegram bot for managing multiple Heroku accounts and multiple Heroku apps from one interface.

## Planned features

- Connect and manage multiple Heroku accounts.
- List apps separately under each connected account.
- App-specific Config Vars (ENV): view names, add, update, delete, and bulk upload from a `.env` file.
- Explicit, user-triggered ENV copy between apps; no automatic sharing.
- Deploy apps from GitHub repositories or ZIP uploads.
- Restart apps and inspect app status, dynos, builds, and logs.
- Telegram control panel with owner-only access.

## Security principles

- Never commit Heroku API keys, Telegram bot tokens, database credentials, or real `.env` files.
- Store credentials encrypted at rest.
- Redact secret values from logs and Telegram responses.
- Require confirmation for destructive actions such as deleting an app or removing config vars.
- Use least-privilege access wherever the Heroku platform permits it.

## Initial architecture

```text
Manage/
├── app/
│   ├── bot/          # Telegram handlers and control panel
│   ├── heroku/       # Heroku API client and account/app operations
│   ├── services/     # ENV, deployment, monitoring workflows
│   ├── storage/      # Persistent account and app metadata
│   └── security/     # Authorization, encryption, secret redaction
├── tests/
├── .env.example      # Names/placeholders only; never real secrets
├── .gitignore
├── Procfile
├── requirements.txt
└── README.md
```

## Configuration

Runtime configuration will be documented in `.env.example` when the implementation is added. Put actual secrets only in the hosting platform's Config Vars, never in Git.

## Status

Repository initialized with the project scope and security requirements. Implementation and automated tests are the next steps.
