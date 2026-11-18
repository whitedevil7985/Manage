# Manage — Heroku Management Bot

Manage is an owner-only Telegram bot for controlling multiple Heroku accounts and the apps inside each account.

## Implemented in the current MVP

- Connect multiple Heroku accounts using their API tokens.
- Validate each token against the Heroku API before saving it.
- Store API tokens encrypted with Fernet in PostgreSQL.
- List and remove connected accounts.
- List apps separately for each connected account.
- View app state, region, maintenance mode, and dyno state/size.
- View app Config Var names without revealing their values.
- Add/update Config Vars through a private prompt; the submitted value is not echoed and the bot attempts to delete the incoming message.
- Bulk import up to 100 Config Vars from a UTF-8 .env file (64 KB maximum), after explicit confirmation.
- Bulk paste up to 100 `KEY=VALUE` Config Vars in one Telegram message (3,500 characters maximum), after explicit confirmation.
- Copy Config Vars between apps/accounts, after explicit confirmation.
- Delete a Config Var only after an inline confirmation.
- Request an app restart.
- Owner-only commands and private-chat restriction.

## Commands

| Command | Purpose |
|---|---|
| `/start` | Open the control panel |
| `/help` | Show commands |
| `/addaccount <label>` | Connect a Heroku account |
| `/accounts` | List connected accounts |
| `/removeaccount <label>` | Remove a saved account token |
| `/apps <label>` | List apps in an account |
| `/status <label> <app>` | Show app and dyno status |
| `/env <label> <app>` | List Config Var names; values stay hidden |
| `/setenv <label> <app> <KEY>` | Add/update a Config Var via a follow-up private message |
| `/importenv <label> <app>` | Upload a .env file and import its keys after confirmation |
| `/bulksetenv <label> <app>` | Paste multiple `KEY=VALUE` lines in one message and apply after confirmation |
| `/copyenv <source-account> <source-app> <target-account> <target-app>` | Copy ENV after confirmation |
| `/delenv <label> <app> <KEY>` | Delete a Config Var after confirmation |
| `/restart <label> <app>` | Restart app dynos |
| `/cancel` | Cancel an active prompt |

Account labels should contain letters, digits, dots, underscores, or hyphens. Example: `/addaccount primary`.

## Deploy on Heroku

1. Create a Telegram bot with BotFather and copy its token.
2. Create a Heroku app for this manager.
3. Attach a Heroku Postgres database to the manager app (or provide a reachable PostgreSQL URL).
4. Set these Config Vars on the manager app:
   - `BOT_TOKEN`: Telegram bot token.
   - `OWNER_ID`: your numeric Telegram user ID.
   - `DATABASE_URL`: PostgreSQL connection URL.
   - `ENCRYPTION_KEY`: Fernet key generated with:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

5. Deploy this repository and scale the worker to one instance:

   ```bash
   heroku ps:scale worker=1 -a YOUR_MANAGER_APP
   ```

6. Open the bot in Telegram and send `/start`.

Keep `ENCRYPTION_KEY` backed up and stable. If it is lost or changed, saved Heroku account tokens cannot be decrypted. Never commit real tokens, database URLs, or `.env` files.

## Connect Heroku accounts

In the bot's private chat:

1. Send `/addaccount primary`.
2. Send the API token for that Heroku account when prompted.
3. The bot validates the token and encrypts it before storing it.
4. Repeat with another unique label for each Heroku account.

The bot attempts to delete the message containing the API token or a new Config Var value. Telegram deletion is best-effort; if deletion fails, the secret may remain visible in chat history. Use a private chat and rotate any credential that may have been exposed.

## Security notes

- Only the configured `OWNER_ID` can operate the bot, and only in a private chat.
- Heroku API tokens are encrypted at rest. The encryption key is supplied separately through manager app Config Vars.
- Config Var values are never returned by the ENV listing command.
- Do not enable debug logging around secrets or paste credentials into support chats.
- Removing a connected account only removes its encrypted token from this manager; it does not delete the Heroku account or its apps.

## Planned next phases

- GitHub and ZIP deployment workflows.
- Build, release, dyno, and live log views.
- App create/delete controls with confirmation.
- Account/app browser buttons and richer status dashboard.

These planned features are not implemented yet.
