import logging
import re
from io import StringIO

from dotenv import dotenv_values
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from app.heroku.client import HerokuAPIError, HerokuClient

log = logging.getLogger(__name__)
WAITING_TOKEN = 1
WAITING_ENV_VALUE = 2
WAITING_ENV_FILE = 3
LABEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    user, chat = update.effective_user, update.effective_chat
    return bool(user and chat and user.id == settings.owner_id and chat.type == ChatType.PRIVATE)


async def owner_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update, context):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ This bot is private and owner-only.")
        return False
    return True


def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Heroku Accounts", callback_data="accounts"),
         InlineKeyboardButton("📦 Apps", callback_data="apps")],
        [InlineKeyboardButton("🔐 ENV Manager", callback_data="envhelp"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    await update.effective_message.reply_text(
        "⚡ Manage — Heroku Control Panel\n\n"
        "Connect multiple Heroku accounts and manage each app independently.\n"
        "Choose an option below or use /help.",
        reply_markup=menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    text = (
        "Commands\n"
        "/addaccount <label> — connect a Heroku account\n"
        "/accounts — list connected accounts\n"
        "/removeaccount <label> — remove a saved account\n"
        "/apps <label> — list apps in an account\n"
        "/env <label> <app> — show ENV keys (values hidden)\n"
        "/setenv <label> <app> <KEY> — set a variable by private prompt\n"
        "/delenv <label> <app> <KEY> — delete a variable\n"
        "/restart <label> <app> — restart an app\n\n"
        "Use this bot in a private chat only. Never share credentials."
    )
    await update.effective_message.reply_text(text)


async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    if len(context.args) != 1 or not LABEL_RE.fullmatch(context.args[0]):
        await update.effective_message.reply_text("Usage: /addaccount <label>\nExample: /addaccount primary")
        return ConversationHandler.END
    label = context.args[0].lower()
    if await context.application.bot_data["db"].get_account(label):
        await update.effective_message.reply_text("That account label already exists.")
        return ConversationHandler.END
    context.user_data["new_account_label"] = label
    await update.effective_message.reply_text(
        "Send the Heroku API token in your next message. It will be encrypted before storage.\n"
        "I will try to delete your token message after receiving it. Send /cancel to stop."
    )
    return WAITING_TOKEN


async def receive_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    token = (update.effective_message.text or "").strip()
    if not token or token.startswith("/"):
        await update.effective_message.reply_text("Invalid token message. Try again or /cancel.")
        return WAITING_TOKEN
    # Delete the credential message before making network/database calls.
    try:
        await update.effective_message.delete()
    except Exception:
        log.warning("Could not delete submitted token message; deletion is best-effort.")
    try:
        client = HerokuClient(token)
        try:
            await client.validate_token()
        finally:
            await client.close()
        label = context.user_data.pop("new_account_label")
        encrypted = context.application.bot_data["secret_box"].encrypt(token)
        await context.application.bot_data["db"].add_account(label, encrypted)
        await update.effective_chat.send_message(f"✅ Heroku account {label} connected.")
    except HerokuAPIError as exc:
        await update.effective_message.reply_text(str(exc))
        return WAITING_TOKEN
    except Exception:
        log.exception("Account connection failed")
        await update.effective_message.reply_text("Could not save the account. Check database configuration.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("new_account_label", None)
    context.user_data.pop("pending_env", None)
    context.user_data.pop("pending_env_import_target", None)
    context.user_data.pop("pending_env_change", None)
    context.user_data.pop("pending_delete_env", None)
    await update.effective_message.reply_text("Cancelled.")
    return ConversationHandler.END


async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    rows = await context.application.bot_data["db"].get_accounts()
    if not rows:
        await update.effective_message.reply_text("No accounts connected yet. Use /addaccount <label>.")
        return
    await update.effective_message.reply_text("Connected Heroku accounts:\n" + "\n".join(f"• {row[1]}" for row in rows))


async def remove_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /removeaccount <label>")
        return
    removed = await context.application.bot_data["db"].remove_account(context.args[0])
    await update.effective_message.reply_text("Account removed." if removed else "Account not found.")


async def get_client(context, label: str):
    row = await context.application.bot_data["db"].get_account(label)
    if not row:
        raise ValueError("Account not found. Check /accounts.")
    token = context.application.bot_data["secret_box"].decrypt(row[2])
    return HerokuClient(token)


async def apps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /apps <account-label>")
        return
    client = None
    try:
        client = await get_client(context, context.args[0])
        items = await client.list_apps()
        if not items:
            await update.effective_message.reply_text("No apps found in this account.")
            return
        lines = [f"Apps in {context.args[0]}:"]
        lines.extend(f"• {item.get('name')} — {item.get('state', 'unknown')}" for item in items[:100])
        await update.effective_message.reply_text("\n".join(lines))
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if client:
            await client.close()


async def app_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /status <account-label> <app-name>")
        return
    label, app_name = context.args
    if not LABEL_RE.fullmatch(label) or not LABEL_RE.fullmatch(app_name):
        await update.effective_message.reply_text("Invalid account or app name.")
        return
    client = None
    try:
        client = await get_client(context, label)
        app = await client.get_app(app_name)
        dynos = await client.list_dynos(app_name)
        lines = [
            f"App: {app.get('name', app_name)}",
            f"State: {app.get('state', 'unknown')}",
            f"Region: {(app.get('region') or {}).get('name', 'unknown')}",
            f"Maintenance: {'ON' if app.get('maintenance') else 'OFF'}",
            f"Dynos: {len(dynos)}",
        ]
        for dyno in dynos[:15]:
            lines.append(
                f"• {dyno.get('type', 'process')} — {dyno.get('state', 'unknown')} "
                f"({dyno.get('size', 'unknown')})"
            )
        await update.effective_message.reply_text("\\n".join(lines))
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if client:
            await client.close()


async def env_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /env <account-label> <app-name>")
        return
    if not LABEL_RE.fullmatch(context.args[0]) or not LABEL_RE.fullmatch(context.args[1]):
        await update.effective_message.reply_text("Invalid account or app name.")
        return
    client = None
    try:
        client = await get_client(context, context.args[0])
        values = await client.get_config_vars(context.args[1])
        keys = sorted(values.keys())
        if not keys:
            await update.effective_message.reply_text("This app has no Config Vars.")
            return
        # Never send actual Config Var values to Telegram.
        await update.effective_message.reply_text(
            f"ENV keys for {context.args[1]}:\n" + "\n".join(f"• {key} = [hidden]" for key in keys)
        )
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if client:
            await client.close()


async def setenv_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    if len(context.args) != 3:
        await update.effective_message.reply_text("Usage: /setenv <account-label> <app-name> <KEY>")
        return ConversationHandler.END
    label, app_name, key = context.args
    if not LABEL_RE.fullmatch(label) or not LABEL_RE.fullmatch(app_name) or not KEY_RE.fullmatch(key):
        await update.effective_message.reply_text("Invalid account, app, or ENV key format.")
        return ConversationHandler.END
    context.user_data["pending_env"] = (label, app_name, key)
    await update.effective_message.reply_text(
        f"Send the value for {key} in your next message. It will not be echoed back. "
        "I will try to delete your message after applying it. Send /cancel to stop."
    )
    return WAITING_ENV_VALUE


async def receive_env_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    pending = context.user_data.pop("pending_env", None)
    if not pending:
        await update.effective_message.reply_text("No pending ENV update.")
        return ConversationHandler.END
    value = update.effective_message.text
    if value is None or value.startswith("/"):
        await update.effective_message.reply_text("Invalid value. Start again with /setenv.")
        return ConversationHandler.END
    # Delete the secret message before sending the value to Heroku.
    try:
        await update.effective_message.delete()
    except Exception:
        log.warning("Could not delete submitted ENV value message; deletion is best-effort.")
    label, app_name, key = pending
    client = None
    try:
        client = await get_client(context, label)
        await client.set_config_vars(app_name, {key: value})
        await update.effective_chat.send_message(f"✅ {key} updated for {app_name}. Value hidden.")
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if client:
            await client.close()
    return ConversationHandler.END


async def delete_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 3:
        await update.effective_message.reply_text("Usage: /delenv <account-label> <app-name> <KEY>")
        return
    label, app_name, key = context.args
    if not KEY_RE.fullmatch(key):
        await update.effective_message.reply_text("Invalid ENV key.")
        return
    if not LABEL_RE.fullmatch(label) or not LABEL_RE.fullmatch(app_name):
        await update.effective_message.reply_text("Invalid account or app name.")
        return
    context.user_data["pending_delete_env"] = (label, app_name, key)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm delete", callback_data="delenv_confirm"),
        InlineKeyboardButton("Cancel", callback_data="delenv_cancel"),
    ]])
    await update.effective_message.reply_text(
        f"⚠️ Delete ENV key {key} from {app_name}? This cannot be undone.",
        reply_markup=keyboard,
    )


async def importenv_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /importenv <account-label> <app-name>")
        return ConversationHandler.END
    label, app_name = context.args
    if not LABEL_RE.fullmatch(label) or not LABEL_RE.fullmatch(app_name):
        await update.effective_message.reply_text("Invalid account or app name.")
        return ConversationHandler.END
    context.user_data["pending_env_import_target"] = (label, app_name)
    await update.effective_message.reply_text(
        "Now upload a .env file (maximum 64 KB). Its values will not be shown. "
        "The bot will attempt to delete the uploaded message. Send /cancel to stop."
    )
    return WAITING_ENV_FILE


async def receive_env_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return ConversationHandler.END
    document = update.effective_message.document
    target = context.user_data.pop("pending_env_import_target", None)
    if not target:
        await update.effective_message.reply_text("No pending ENV import. Start with /importenv.")
        return ConversationHandler.END
    if not document or not (document.file_name or "").lower().endswith(".env"):
        await update.effective_message.reply_text("Please upload a file named .env.")
        return ConversationHandler.END
    if document.file_size and document.file_size > 65536:
        await update.effective_message.reply_text("The .env file must be 64 KB or smaller.")
        return ConversationHandler.END
    try:
        remote_file = await context.bot.get_file(document.file_id)
        raw = await remote_file.download_as_bytearray()
        try:
            await update.effective_message.delete()
        except Exception:
            log.warning("Could not delete uploaded ENV file message; deletion is best-effort.")
        parsed = dotenv_values(stream=StringIO(bytes(raw).decode("utf-8")), interpolate=False)
        values = {
            key: value for key, value in parsed.items()
            if value is not None and KEY_RE.fullmatch(key)
        }
        if not values:
            await update.effective_chat.send_message("No valid KEY=value entries were found in that file.")
            return ConversationHandler.END
        if len(values) > 100:
            await update.effective_chat.send_message("The import is limited to 100 variables per operation.")
            return ConversationHandler.END
        label, app_name = target
        context.user_data["pending_env_change"] = (label, app_name, values)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Confirm import", callback_data="envchange_confirm"),
            InlineKeyboardButton("Cancel", callback_data="envchange_cancel"),
        ]])
        await update.effective_chat.send_message(
            f"Import {len(values)} ENV variables into {app_name}? Existing keys with the same names will be overwritten. Values remain hidden.",
            reply_markup=keyboard,
        )
    except UnicodeDecodeError:
        await update.effective_chat.send_message("The .env file must use UTF-8 encoding.")
    except Exception:
        log.exception("ENV file import preparation failed")
        await update.effective_chat.send_message("Could not read that .env file.")
    return ConversationHandler.END


async def copy_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 4:
        await update.effective_message.reply_text(
            "Usage: /copyenv <source-account> <source-app> <target-account> <target-app>"
        )
        return
    source_label, source_app, target_label, target_app = context.args
    if not all(LABEL_RE.fullmatch(item) for item in (source_label, source_app, target_label, target_app)):
        await update.effective_message.reply_text("Invalid account or app name.")
        return
    source = target = None
    try:
        source = await get_client(context, source_label)
        values = await source.get_config_vars(source_app)
        if not values:
            await update.effective_message.reply_text("The source app has no Config Vars.")
            return
        if len(values) > 100:
            await update.effective_message.reply_text("Copy is limited to 100 variables per operation.")
            return
        context.user_data["pending_env_change"] = (target_label, target_app, values)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Confirm copy", callback_data="envchange_confirm"),
            InlineKeyboardButton("Cancel", callback_data="envchange_cancel"),
        ]])
        await update.effective_message.reply_text(
            f"Copy {len(values)} ENV variables from {source_app} to {target_app}? "
            "Existing target keys with the same names will be overwritten. Values remain hidden.",
            reply_markup=keyboard,
        )
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if source:
            await source.close()
        if target:
            await target.close()


async def restart_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update, context):
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /restart <account-label> <app-name>")
        return
    if not LABEL_RE.fullmatch(context.args[0]) or not LABEL_RE.fullmatch(context.args[1]):
        await update.effective_message.reply_text("Invalid account or app name.")
        return
    client = None
    try:
        client = await get_client(context, context.args[0])
        await client.restart_app(context.args[1])
        await update.effective_message.reply_text(f"♻️ Restart requested for {context.args[1]}.")
    except (ValueError, HerokuAPIError) as exc:
        await update.effective_message.reply_text(str(exc))
    finally:
        if client:
            await client.close()


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_owner(update, context):
        await query.answer("Owner-only", show_alert=True)
        return
    await query.answer()
    if query.data == "accounts":
        rows = await context.application.bot_data["db"].get_accounts()
        body = "No accounts connected. Use /addaccount <label>." if not rows else "\n".join(f"• {r[1]}" for r in rows)
        await query.edit_message_text("👤 Heroku Accounts\n" + body)
    elif query.data == "apps":
        await query.edit_message_text("📦 Use /apps <account-label> to list an account's apps.")
    elif query.data == "envhelp":
        await query.edit_message_text("🔐 ENV commands:\n/env <account> <app>\n/setenv <account> <app> <KEY>\n/delenv <account> <app> <KEY>\nValues are hidden and app-specific.")
    elif query.data == "delenv_cancel":
        context.user_data.pop("pending_delete_env", None)
        await query.edit_message_text("ENV deletion cancelled.")
    elif query.data == "delenv_confirm":
        pending = context.user_data.pop("pending_delete_env", None)
        if not pending:
            await query.edit_message_text("No pending ENV deletion.")
            return
        label, app_name, key = pending
        client = None
        try:
            client = await get_client(context, label)
            await client.delete_config_var(app_name, key)
            await query.edit_message_text(f"✅ {key} removed from {app_name}.")
        except (ValueError, HerokuAPIError) as exc:
            await query.edit_message_text(str(exc))
        finally:
            if client:
                await client.close()
    elif query.data == "envchange_cancel":
        context.user_data.pop("pending_env_change", None)
        await query.edit_message_text("ENV operation cancelled.")
    elif query.data == "envchange_confirm":
        pending = context.user_data.pop("pending_env_change", None)
        if not pending:
            await query.edit_message_text("No pending ENV operation.")
            return
        label, app_name, values = pending
        client = None
        try:
            client = await get_client(context, label)
            await client.set_config_vars(app_name, values)
            await query.edit_message_text(f"✅ Applied {len(values)} ENV variables to {app_name}. Values hidden.")
        except (ValueError, HerokuAPIError) as exc:
            await query.edit_message_text(str(exc))
        finally:
            if client:
                await client.close()
    else:
        await query.edit_message_text("Use /help to see all commands.", reply_markup=menu_keyboard())


def register_handlers(application: Application):
    account_conv = ConversationHandler(
        entry_points=[CommandHandler("addaccount", add_account)],
        states={WAITING_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    env_conv = ConversationHandler(
        entry_points=[CommandHandler("setenv", setenv_start)],
        states={WAITING_ENV_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_value)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    import_conv = ConversationHandler(
        entry_points=[CommandHandler("importenv", importenv_start)],
        states={WAITING_ENV_FILE: [MessageHandler(filters.Document.ALL, receive_env_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(account_conv)
    application.add_handler(env_conv)
    application.add_handler(import_conv)
    application.add_handler(CommandHandler("accounts", accounts))
    application.add_handler(CommandHandler("removeaccount", remove_account))
    application.add_handler(CommandHandler("apps", apps))
    application.add_handler(CommandHandler("status", app_status))
    application.add_handler(CommandHandler("env", env_command))
    application.add_handler(CommandHandler("delenv", delete_env))
    application.add_handler(CommandHandler("copyenv", copy_env))
    application.add_handler(CommandHandler("restart", restart_app))
    application.add_handler(CallbackQueryHandler(callbacks))
