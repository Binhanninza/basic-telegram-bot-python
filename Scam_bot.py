from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ChatMemberHandler, JobQueue
import logging
import sqlite3
import os
import datetime
import math # Thêm thư viện math để dùng cho việc chia nhỏ tin nhắn

# --- CẤU HÌNH CỦA BẠN ---
# NHỚ THAY THẾ "YOUR_BOT_TOKEN_HERE" BẰNG TOKEN BOT CỦA BẠN!
TOKEN = "7725842212:AAHgtkLAQOztjhdvnmQWvHe4Pcsq-z5CovA" 
# NHỚ THAY THẾ "123456789" BẰNG ID TELEGRAM CỦA ADMIN!
ADMIN_USER_ID = 5835093566 
# --- KẾT THÚC CẤU HÌNH ---

# Cấu hình logging để xem các thông báo lỗi và hoạt động của bot
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tên file cơ sở dữ liệu SQLite
DB_FILE = 'scam_accounts.db'
# Tên file JSON cũ (chỉ cần nếu bạn có file JSON cũ và muốn import, nếu không có thì không sao)
OLD_SCAM_JSON_FILE = 'scam_accounts_old.json' 

# --- Hàm hỗ trợ kết nối và thao tác với SQLite ---

def init_db():
    """Khởi tạo database và các bảng nếu chưa tồn tại.
    Thêm cột 'added_at' vào bảng scam_accounts nếu chưa có.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Bảng scam_accounts để lưu các số tài khoản lừa đảo đã được duyệt
        # Thêm cột added_at TEXT
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scam_accounts (
                account_number TEXT PRIMARY KEY,
                reason TEXT,
                added_at TEXT
            )
        ''')
        conn.commit()

        # Kiểm tra và thêm cột 'added_at' nếu nó chưa tồn tại (cho các database cũ)
        cursor.execute("PRAGMA table_info(scam_accounts)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'added_at' not in columns:
            cursor.execute("ALTER TABLE scam_accounts ADD COLUMN added_at TEXT")
            conn.commit()
            logger.info("Đã thêm cột 'added_at' vào bảng 'scam_accounts'.")


        # Bảng pending_reports để lưu các báo cáo đang chờ admin duyệt
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                account_number TEXT NOT NULL,
                reason TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        ''')
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi khởi tạo database: {e}")
    finally:
        if conn:
            conn.close()

def add_scam_account_to_db(account_number: str, reason: str | None) -> bool:
    """Thêm một số tài khoản vào database. Trả về True nếu thêm thành công, False nếu đã tồn tại."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        added_at = datetime.datetime.now().isoformat() # Lấy thời gian hiện tại theo chuẩn ISO 8601
        cursor.execute("INSERT INTO scam_accounts (account_number, reason, added_at) VALUES (?, ?, ?)",
                       (account_number, reason, added_at))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi thêm số tài khoản '{account_number}' vào DB: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_scam_account_from_db(account_number: str) -> bool:
    """Xóa một số tài khoản khỏi database. Trả về True nếu xóa thành công, False nếu không tìm thấy."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scam_accounts WHERE account_number = ?", (account_number,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi xóa số tài khoản '{account_number}' khỏi DB: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_scam_account_from_db(account_number: str) -> tuple[str | None, str | None] | None:
    """Lấy lý do và thời gian thêm của số tài khoản scam từ database. Trả về tuple (reason, added_at) hoặc None nếu không tìm thấy."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT reason, added_at FROM scam_accounts WHERE account_number = ?", (account_number,))
        result = cursor.fetchone()
        return result # result sẽ là (reason, added_at) hoặc None
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi kiểm tra số tài khoản '{account_number}' trong DB: {e}")
        return None
    finally:
        if conn:
            conn.close()

# Hàm MỚI: Lấy tất cả số tài khoản lừa đảo
def get_all_scam_accounts_from_db() -> list[tuple[str, str | None, str | None]]:
    """Lấy tất cả số tài khoản lừa đảo cùng lý do và thời gian thêm từ database."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT account_number, reason, added_at FROM scam_accounts ORDER BY account_number")
        return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi lấy tất cả số tài khoản lừa đảo từ DB: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_pending_report_to_db(user_id: int, username: str, account_number: str, reason: str) -> int | None:
    """Thêm một báo cáo chờ duyệt vào database. Trả về report_id nếu thành công."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        timestamp = datetime.datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO pending_reports (user_id, username, account_number, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, account_number, reason, timestamp)
        )
        conn.commit()
        return cursor.lastrowid # Trả về ID của báo cáo vừa thêm
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi thêm báo cáo chờ duyệt: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_pending_report_from_db(report_id: int) -> tuple | None:
    """Lấy thông tin báo cáo chờ duyệt từ database bằng report_id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, username, account_number, reason, timestamp FROM pending_reports WHERE report_id = ?",
            (report_id,)
        )
        result = cursor.fetchone()
        return result
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi lấy báo cáo chờ duyệt ID {report_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def delete_pending_report_from_db(report_id: int) -> bool:
    """Xóa một báo cáo chờ duyệt khỏi database."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_reports WHERE report_id = ?", (report_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Lỗi khi xóa báo cáo chờ duyệt ID {report_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def import_json_to_db():
    """Import ID từ file JSON cũ vào database SQLite (chỉ chạy một lần)."""
    if os.path.exists(OLD_SCAM_JSON_FILE):
        import json
        with open(OLD_SCAM_JSON_FILE, 'r', encoding='utf-8') as f:
            try:
                old_data = json.load(f)
                count = 0
                for account_num, reason_json in old_data.items():
                    # Đảm bảo lý do là chuỗi hoặc None
                    reason_to_add = str(reason_json) if reason_json else None
                    if add_scam_account_to_db(account_num, reason_to_add):
                        count += 1
                logger.info(f"Imported {count} accounts from {OLD_SCAM_JSON_FILE} to database.")
                # Sau khi import, bạn có thể xóa file JSON cũ nếu muốn
                # os.remove(OLD_SCAM_JSON_FILE)
            except json.JSONDecodeError:
                logger.warning(f"Lỗi đọc file JSON cũ '{OLD_SCAM_JSON_FILE}'. Bỏ qua import.")
            except Exception as e:
                logger.error(f"Lỗi không xác định khi import JSON: {e}")
    else:
        logger.info(f"Không tìm thấy file JSON cũ '{OLD_SCAM_JSON_FILE}' để import.")

# --- Khởi tạo database và import dữ liệu cũ khi bot khởi động ---
init_db()
import_json_to_db()

# Hàm kiểm tra quyền admin
def is_admin(user_id):
    return user_id == ADMIN_USER_ID

# --- Các lệnh của Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gửi tin nhắn chào mừng khi nhận lệnh /start."""
    await update.message.reply_text(
        "Chào bạn! Tôi là bot kiểm tra số tài khoản lừa đảo.\n"
        "Hãy gửi số tài khoản bạn muốn kiểm tra hoặc gõ /help để xem hướng dẫn."
    )

async def add_scam_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Thêm một hoặc nhiều số tài khoản scam (chỉ Admin).
    Có thể kèm lý do chung hoặc không có lý do.
    VD: /add 6182873398 7977503288 Lý do chung cho tất cả
    VD: /add 7005554366 6737267452
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text(
            "Vui lòng cung cấp ít nhất một số tài khoản cần thêm. "
            "Ví dụ: `/add 0123456789` hoặc `/add 6182873398 7977503288 Lý do chung`"
        )
        return

    # Tách các số tài khoản và lý do (nếu có)
    account_numbers_to_add = []
    reason_for_all = None

    # Tìm vị trí của đối số không phải là số đầu tiên, đó có thể là bắt đầu của lý do
    first_non_digit_arg_index = -1
    for i, arg in enumerate(context.args):
        if not arg.isdigit():
            first_non_digit_arg_index = i
            break
    
    if first_non_digit_arg_index == -1: # Tất cả đều là số
        account_numbers_to_add = [arg.strip() for arg in context.args]
    else: # Có lý do
        account_numbers_to_add = [arg.strip() for arg in context.args[:first_non_digit_arg_index]]
        reason_for_all = " ".join(context.args[first_non_digit_arg_index:]).strip()

    if not account_numbers_to_add:
        await update.message.reply_text("Vui lòng cung cấp ít nhất một số tài khoản hợp lệ để thêm.")
        return

    added_count = 0
    skipped_count = 0
    invalid_count = 0
    results_message = [] # Để lưu kết quả của từng số tài khoản

    for account_number in account_numbers_to_add:
        # Nếu không có lý do chung được cung cấp, lý do cho từng số sẽ là None
        current_reason = reason_for_all if reason_for_all else None

        if account_number.isdigit() and 5 <= len(account_number) <= 15:
            if add_scam_account_to_db(account_number, current_reason):
                results_message.append(f"✅ Đã thêm `{account_number}`")
                added_count += 1
                logger.info(f"Admin {user_id} added scam account: {account_number}, reason: {current_reason}")
            else:
                results_message.append(f"⚠️ `{account_number}` đã có sẵn")
                skipped_count += 1
        else:
            results_message.append(f"❌ `{account_number}` không hợp lệ")
            invalid_count += 1
    
    final_message = "Kết quả thêm số tài khoản:\n" + "\n".join(results_message)
    final_message += f"\n\nTổng cộng: Đã thêm {added_count}, Bỏ qua {skipped_count}, Không hợp lệ {invalid_count}."
    
    await update.message.reply_text(final_message, parse_mode='Markdown')


async def delete_scam_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa số tài khoản scam (chỉ Admin)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return

    if not context.args:
        await update.message.reply_text("Vui lòng cung cấp số tài khoản cần xóa. Ví dụ: `/delete 012345`")
        return

    account_number = context.args[0].strip()

    if delete_scam_account_from_db(account_number):
        await update.message.reply_text(f"Đã xóa số tài khoản `{account_number}` khỏi danh sách lừa đảo.")
        logger.info(f"Admin {user_id} deleted scam account: {account_number}")
    else:
        await update.message.reply_text(f"Số tài khoản `{account_number}` không có trong danh sách lừa đảo hoặc có lỗi khi xóa.")

async def report_scam_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Người dùng báo cáo số tài khoản lừa đảo."""
    user_id = update.effective_user.id
    username = update.effective_user.username or f"ID:{user_id}"

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Vui lòng cung cấp số tài khoản và lý do bắt buộc. Ví dụ:\n"
            "`/baocao 0123456789 Kẻ lừa đảo bán tiền khi mua bán online.`",
            parse_mode='Markdown'
        )
        return

    account_number = context.args[0].strip()
    reason = " ".join(context.args[1:]).strip()

    if not account_number.isdigit() or not (5 <= len(account_number) <= 15):
        await update.message.reply_text("Số tài khoản không hợp lệ. Vui lòng nhập đúng định dạng số (5-15 chữ số).")
        return
    if not reason: # Đảm bảo lý do không rỗng
        await update.message.reply_text("Lý do báo cáo không được để trống.")
        return

    # Lưu báo cáo vào database
    report_id = add_pending_report_to_db(user_id, username, account_number, reason)

    if report_id:
        await update.message.reply_text(
            "Cảm ơn bạn đã báo cáo! Báo cáo của bạn đã được gửi đến Admin để xem xét."
        )
        logger.info(f"User {username} ({user_id}) reported: {account_number} - {reason}. Report ID: {report_id}")

        # Gửi thông báo đến Admin
        admin_message_text = (
            f"⚠️ **BÁO CÁO MỚI TỪ NGƯỜI DÙNG** ⚠️\n\n"
            f"**Người báo cáo:** `{username}` (ID: `{user_id}`)\n"
            f"**Số tài khoản:** `{account_number}`\n"
            f"**Lý do:** `{reason}`\n"
            f"**Report ID:** `{report_id}`"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Phê duyệt", callback_data=f"approve_{report_id}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"reject_{report_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=admin_message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"Sent report {report_id} to admin {ADMIN_USER_ID}")
        except Exception as e:
            logger.error(f"Không thể gửi báo cáo đến admin {ADMIN_USER_ID}: {e}")
            await update.message.reply_text("Có lỗi khi gửi báo cáo đến admin. Vui lòng thử lại sau.")
    else:
        await update.message.reply_text("Có lỗi khi lưu báo cáo. Vui lòng thử lại sau.")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý khi Admin nhấn nút inline (approve/reject)."""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.answer("Bạn không có quyền thực hiện thao tác này.")
        return

    await query.answer() # Báo cho Telegram biết đã nhận được callback

    action, report_id_str = query.data.split('_')
    report_id = int(report_id_str)

    report_info = get_pending_report_from_db(report_id)

    if not report_info:
        await query.edit_message_text(f"Báo cáo ID `{report_id}` không tồn tại hoặc đã được xử lý.")
        logger.warning(f"Admin tried to process non-existent/processed report {report_id}")
        return

    # Lấy thông tin từ report_info tuple: (user_id_reporter, username_reporter, account_number, reason, timestamp)
    reporter_user_id, reporter_username, account_number, reason, _ = report_info

    if action == "approve":
        # Khi approve từ báo cáo, lý do luôn có sẵn
        if add_scam_account_to_db(account_number, reason):
            delete_pending_report_from_db(report_id)
            await query.edit_message_text(
                f"✅ Đã phê duyệt báo cáo ID `{report_id}`:\n"
                f"**STK:** `{account_number}`\n"
                f"**Lý do:** `{reason}`\n"
                f"Báo cáo từ: `{reporter_username}`",
                parse_mode='Markdown'
            )
            logger.info(f"Admin {user_id} APPROVED report {report_id}: {account_number}")
            # Thông báo cho người dùng đã báo cáo
            try:
                await context.bot.send_message(
                    chat_id=reporter_user_id,
                    text=f"Báo cáo số tài khoản `{account_number}` của bạn đã được Admin phê duyệt và thêm vào danh sách scam. Cảm ơn sự đóng góp của bạn!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Không thể gửi thông báo phê duyệt tới user {reporter_user_id}: {e}")
        else:
            # Trường hợp đã có sẵn trong danh sách scam_accounts
            delete_pending_report_from_db(report_id) # Vẫn xóa khỏi pending
            await query.edit_message_text(
                f"⚠️ Báo cáo ID `{report_id}` (STK: `{account_number}`) đã có trong danh sách scam từ trước. Đã xóa báo cáo chờ duyệt.",
                parse_mode='Markdown'
            )
            logger.info(f"Admin {user_id} approved report {report_id} but it was already in scam list: {account_number}")

    elif action == "reject":
        delete_pending_report_from_db(report_id)
        await query.edit_message_text(
            f"❌ Đã từ chối báo cáo ID `{report_id}`:\n"
            f"**STK:** `{account_number}`\n"
            f"**Lý do:** `{reason}`\n"
            f"Báo cáo từ: `{reporter_username}`",
            parse_mode='Markdown'
        )
        logger.info(f"Admin {user_id} REJECTED report {report_id}: {account_number}")
        # Thông báo cho người dùng đã báo cáo
        try:
            await context.bot.send_message(
                chat_id=reporter_user_id,
                text=f"Báo cáo số tài khoản `{account_number}` của bạn đã bị Admin từ chối. Nếu bạn có thêm thông tin, vui lòng gửi báo cáo mới.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Không thể gửi thông báo từ chối tới user {reporter_user_id}: {e}")

async def check_scam_account_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý tin nhắn của người dùng để kiểm tra số tài khoản."""
    # Quan trọng: Kiểm tra update.message có tồn tại không trước khi truy cập
    if not update.message:
        return # Bỏ qua nếu không phải tin nhắn từ người dùng

    message_text = update.message.text.strip()

    # Kiểm tra xem tin nhắn có phải là một số (hoặc chuỗi số) có độ dài hợp lệ
    if message_text.isdigit() and len(message_text) >= 5 and len(message_text) <= 15:
        result = get_scam_account_from_db(message_text) # result sẽ là (reason, added_at) hoặc None
        
        if result:
            reason, added_at_str = result
            reply_text = f"⚠️ **CẢNH BÁO:** Số tài khoản `{message_text}` có trong dữ liệu lừa đảo!"
            if reason: # Chỉ hiển thị lý do nếu nó không rỗng hoặc None
                reply_text += f"\nLý do: {reason}"
            
            # Chuyển đổi chuỗi thời gian sang định dạng dễ đọc hơn
            try:
                added_datetime = datetime.datetime.fromisoformat(added_at_str)
                # Format thời gian theo múi giờ Việt Nam (GMT+7)
                # Lưu ý: datetime.fromisoformat không tự động chuyển múi giờ.
                # Đây là cách hiển thị đẹp, không thực sự chuyển đổi múi giờ nếu database không lưu UTC.
                formatted_added_at = added_datetime.strftime("%H:%M:%S %d-%m-%Y")
                reply_text += f"\nĐược thêm vào: {formatted_added_at} (GMT+7)"
            except (ValueError, TypeError):
                logger.warning(f"Không thể định dạng thời gian '{added_at_str}' cho STK {message_text}")
                reply_text += f"\nĐược thêm vào: {added_at_str}" # Vẫn hiển thị chuỗi gốc nếu lỗi

            await update.message.reply_text(
                reply_text,
                parse_mode='Markdown'
            )
            logger.info(f"User {update.effective_user.id} checked scam account: {message_text}")
        else:
            await update.message.reply_text(
                f"Số tài khoản `{message_text}` hiện không có trong dữ liệu lừa đảo của tôi."
            )
    # Nếu không phải là số tài khoản hợp lệ, bot sẽ không trả lời gì.

async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý sự kiện thành viên mới vào nhóm và gửi lời chào mừng."""
    # Kiểm tra nếu update.chat_member không tồn tại (chẳng hạn nếu đây không phải sự kiện thành viên nhóm)
    if not update.chat_member:
        return

    # Lấy đối tượng ChatMemberUpdated
    new_chat_member_info: ChatMemberUpdated = update.chat_member
    
    # Lấy thông tin về thành viên vừa tham gia (từ trạng thái mới của chat member)
    new_member: ChatMember = new_chat_member_info.new_chat_member

    # Kiểm tra xem có phải là thành viên mới tham gia (tức là trạng thái từ bất kỳ thành 'member')
    # và user đó không phải là chính bot để tránh loop
    if new_member.status == ChatMember.MEMBER and new_member.user.id != context.bot.id:
        # Lấy tên của thành viên mới
        # Ưu tiên username nếu có, nếu không thì full_name
        member_name = new_member.user.username
        if not member_name:
            member_name = new_member.user.full_name # full_name là kết hợp first_name và last_name
        
        # Lấy số lượng thành viên hiện tại của nhóm
        # Đây là một tác vụ bất đồng bộ, cần await
        try:
            chat_member_count = await context.bot.get_chat_member_count(update.effective_chat.id)
        except Exception as e:
            logger.warning(f"Could not get chat member count: {e}")
            chat_member_count = "nhiều" # Fallback nếu không lấy được

        # Lấy thời gian tham gia nhóm (thời gian hiện tại bot nhận được event)
        join_time = datetime.datetime.now()
        formatted_join_time = join_time.strftime("%H:%M:%S %d-%m-%Y") # Ví dụ: 14:30:00 28-05-2025

        # Tạo tin nhắn chào mừng
        welcome_message = (
            f"𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝗰𝗼𝗻 𝘃𝗸 {member_name} đ𝗮̃ đ𝗲̂́𝗻 👉🏻 𝘃𝗼̛́𝗶 𝗻𝗵𝗼́𝗺 𝗖𝗦𝗖𝗦𝟭\n"
            f"𝑭𝒓𝒊𝒆𝒏𝒅 𝒍𝗮̀ 𝒕𝒉𝒂̀𝒏𝒉 𝒗𝒊𝒆̂𝒏 𝒔𝒐̂́ {chat_member_count} của cộng đồng này. \n"
            f"𝚃ê𝚗: {member_name}\n"
            f"𝚃𝚑ờ𝚒 𝚐𝚒𝚊𝚗 𝚝𝚑𝗮𝗺 𝚐𝗶𝗮: {formatted_join_time}\n"
            f"𝘾h𝒖́𝙘 𝙘𝙤𝙣 𝙫𝙠 𝙣h𝒂̆́𝙣 𝙩𝙞𝙣 𝙫𝙪𝙞 𝙫𝒆̉, 𝙣h𝒐̛́ 𝙩𝙪𝐚̂𝙣 /𝙧𝙪𝒍𝒆𝒔 𝙘𝒖̉𝗮 𝙣h𝒐́𝙢 𝙣h𝒆́!!!"
        )

        # Gửi tin nhắn chào mừng vào nhóm
        try:
            await update.effective_chat.send_message(welcome_message)
            logger.info(f"Sent welcome message for new member: {member_name} (ID: {new_member.user.id})")
        except Exception as e:
            logger.error(f"Không thể gửi tin nhắn chào mừng trong nhóm {update.effective_chat.id}: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hiển thị hướng dẫn sử dụng bot."""
    await update.message.reply_text(
        "Chào bạn! Tôi là bot kiểm tra số tài khoản lừa đảo.\n\n"
        "**Lệnh của Admin:**\n"
        "• `/add {STK1} [STK2...] [Lý do]`: Thêm một hoặc nhiều số tài khoản lừa đảo vào dữ liệu. Lý do là tùy chọn và áp dụng cho tất cả STK trong lệnh.\n"
        "  Ví dụ: `/add 012345 Scam bán acc` hoặc `/add 987654 11223344`\n"
        "• `/delete {STK}`: Xóa số tài khoản lừa đảo ra khỏi dữ liệu.\n"
        "  Ví dụ: `/delete 012345`\n"
        "• `/backup`: Gửi toàn bộ danh sách tài khoản lừa đảo.\n\n" # Thêm mô tả lệnh backup
        "**Lệnh của Người dùng:**\n"
        "• Gửi trực tiếp **số tài khoản** bạn muốn kiểm tra.\n"
        "• `/baocao {STK} {Lý do}`: Báo cáo một số tài khoản lừa đảo. **Lý do là bắt buộc.**\n"
        "  Ví dụ: `/baocao 1234567890 Kẻ lừa đảo bán hàng giả`\n"
        "• `/help`: Hiển thị hướng dẫn sử dụng này."
        , parse_mode='Markdown' # Đảm bảo parse_mode là Markdown
    )

# Hàm MỚI: Chia nhỏ tin nhắn nếu quá dài
def chunk_message(text: str, max_length: int = 4096) -> list[str]:
    """Chia một chuỗi văn bản thành các đoạn nhỏ hơn không vượt quá max_length."""
    chunks = []
    current_chunk = ""
    # Tách theo dòng để tránh cắt ngang thông tin quan trọng
    lines = text.split('\n') 
    
    for line in lines:
        # Nếu thêm dòng này vào mà vượt quá max_length
        if len(current_chunk) + len(line) + 1 > max_length and current_chunk: # +1 cho ký tự xuống dòng
            chunks.append(current_chunk.strip())
            current_chunk = line + '\n'
        else:
            current_chunk += line + '\n'
            
    if current_chunk: # Thêm phần còn lại nếu có
        chunks.append(current_chunk.strip())
    
    return chunks

# Hàm MỚI: Gửi backup dữ liệu scam
async def send_scam_data_backup(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lấy dữ liệu scam và gửi tới chat_id được chỉ định, chia nhỏ nếu cần."""
    scam_accounts = get_all_scam_accounts_from_db()

    if not scam_accounts:
        await context.bot.send_message(chat_id=chat_id, text="Không có tài khoản lừa đảo nào trong dữ liệu.")
        logger.info(f"Sent empty scam data backup to {chat_id}")
        return

    # Sắp xếp theo thứ tự thêm vào (mới nhất trước) để dễ xem
    # scam_accounts_sorted = sorted(scam_accounts, key=lambda x: x[2] if x[2] else '', reverse=True)
    # Vì đã ORDER BY account_number trong get_all_scam_accounts_from_db nên không cần sắp xếp lại

    header = "📊 **DANH SÁCH TÀI KHOẢN LỪA ĐẢO** 📊\n\n"
    footer = f"\n\nTổng cộng: {len(scam_accounts)} tài khoản."
    
    all_data_lines = []
    for account, reason, added_at_iso in scam_accounts:
        added_info = ""
        if added_at_iso:
            try:
                added_datetime = datetime.datetime.fromisoformat(added_at_iso)
                added_info = f" (thêm: {added_datetime.strftime('%d-%m-%Y')})"
            except (ValueError, TypeError):
                added_info = f" (thêm: {added_at_iso})" # Fallback nếu lỗi format

        if reason:
            all_data_lines.append(f"• `{account}`: {reason}{added_info}")
        else:
            all_data_lines.append(f"• `{account}`{added_info}")

    full_message_content = header + "\n".join(all_data_lines) + footer

    # Chia nhỏ tin nhắn nếu vượt quá giới hạn Telegram (4096 ký tự)
    message_chunks = chunk_message(full_message_content)

    for i, chunk in enumerate(message_chunks):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode='Markdown'
            )
            # Thêm độ trễ nhỏ giữa các tin nhắn nếu có nhiều chunk để tránh giới hạn rate
            if len(message_chunks) > 1 and i < len(message_chunks) - 1:
                await asyncio.sleep(0.5) # Để tránh FloodWait
        except Exception as e:
            logger.error(f"Không thể gửi chunk {i+1} của backup đến {chat_id}: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"Lỗi khi gửi một phần backup: {e}")
            break # Dừng nếu có lỗi

    logger.info(f"Sent scam data backup ({len(scam_accounts)} accounts) to {chat_id}.")


# Hàm MỚI: Lệnh /backup (chỉ admin)
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lệnh Admin để gửi backup dữ liệu lừa đảo thủ công."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    
    await update.message.reply_text("Đang tạo và gửi backup dữ liệu...")
    await send_scam_data_backup(user_id, context) # Gửi backup đến Admin


# Hàm MỚI: Job để gửi backup tự động
async def scheduled_backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job được lên lịch để gửi backup dữ liệu tự động đến Admin."""
    logger.info(f"Running scheduled backup job for ADMIN_USER_ID: {ADMIN_USER_ID}")
    await send_scam_data_backup(ADMIN_USER_ID, context)

# Hàm chính để chạy bot
def main() -> None:
    """Chạy bot."""
    application = Application.builder().token(TOKEN).build()

    # --- Đăng ký các handler ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_scam_account))
    application.add_handler(CommandHandler("delete", delete_scam_account))
    application.add_handler(CommandHandler("baocao", report_scam_account))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("backup", backup_command)) # Đăng ký lệnh backup mới
    
    # Handler cho các nút inline (CallbackQuery)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Đăng ký handler cho sự kiện thành viên nhóm (thêm hoặc xóa thành viên)
    application.add_handler(ChatMemberHandler(greet_new_member, ChatMemberHandler.CHAT_MEMBER))

    # Handler cho tin nhắn TEXT không phải lệnh
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_scam_account_message))

    # --- Lên lịch gửi backup tự động ---
    job_queue = application.job_queue

    # Lên lịch gửi backup lúc 12h trưa (12:00) và 1h sáng (01:00) hàng ngày
    # Đặt múi giờ cho phù hợp với Việt Nam (GMT+7)
    # job_queue.run_daily sẽ chạy job vào một thời điểm cụ thể mỗi ngày.
    # time=datetime.time(hour=12, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
    # Sử dụng datetime.time.fromisoformat('12:00:00+07:00') nếu cần

    # Để đơn giản, chúng ta sẽ không đặt tzinfo trực tiếp vào datetime.time() ở đây
    # và giả định môi trường chạy bot có múi giờ được cấu hình tương ứng
    # hoặc bạn có thể điều chỉnh giờ nếu bot chạy ở múi giờ khác.
    # Tuy nhiên, cách an toàn nhất là sử dụng thư viện pytz để định nghĩa múi giờ rõ ràng
    # Nhưng để giữ code đơn giản và tránh thêm dependency, ta sẽ đặt giờ trực tiếp
    
    # Backup lúc 12:00 trưa
    job_queue.run_daily(
        scheduled_backup_job,
        time=datetime.time(hour=12, minute=0, second=0),
        name="Daily Backup 12 PM"
    )
    # Backup lúc 1:00 sáng
    job_queue.run_daily(
        scheduled_backup_job,
        time=datetime.time(hour=1, minute=0, second=0),
        name="Daily Backup 1 AM"
    )

    logger.info("Bot đang chạy...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Thêm import asyncio nếu bạn dùng asyncio.sleep trong chunk_message
    try:
        import asyncio
    except ImportError:
        pass # asyncio đã là built-in từ Python 3.4
    main()

