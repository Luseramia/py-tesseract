"""
Krungsri savings-account PDF statement parser.

Format detected from extract_text():
  TRANSACTION LINE:
    DD/MM/YYYY HH:MM:SS  <type>  <amount>  <balance>  MOBILE|ATM|OTHERS  [details]
  CONTINUATION LINE (optional, 1-2 per transaction):
    บัญชีปลายทาง : XXXXX
    รหัสพร้อมเพย์ : XXXXX
    บัญชีต้นทาง : XXXXX

Deposit vs Withdrawal is determined by transaction type:
  - type contains "รับ"  →  deposit (ฝาก)
  - otherwise            →  withdrawal (ถอน)
"""

import re
import pdfplumber
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    datetime: str           # "14/03/2026 08:46:11"
    transaction_type: str   # "จ่ายคิวอาร์พร้อมเพย์", "โอนเงิน", ...
    withdrawal: Optional[float]  # None for deposits
    deposit: Optional[float]     # None for withdrawals
    balance: float
    channel: str            # "MOBILE" | "ATM" | "OTHERS"
    details: str            # รายละเอียด + continuation lines joined by \n


@dataclass
class StatementSummary:
    withdrawal_count: int
    withdrawal_total: float
    deposit_count: int
    deposit_total: float


@dataclass
class BankStatement:
    account_name: str
    account_number: str
    branch: str
    period_start: str        # "14/03/2026"
    period_end: str          # "13/04/2026"
    transactions: list[Transaction] = field(default_factory=list)
    summary: Optional[StatementSummary] = None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches a transaction line: datetime + type + amount + balance + channel [+ details]
_TX_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})"   # group 1: datetime
    r"\s+(.+?)"                                     # group 2: type (lazy → stops before 1st number)
    r"\s+([\d,]+\.\d{2})"                          # group 3: amount
    r"\s+([\d,]+\.\d{2})"                          # group 4: balance
    r"\s+(MOBILE|ATM|OTHERS|COUNTER|BRANCH)"       # group 5: channel
    r"(?:\s+(.+))?$"                               # group 6: details (optional)
)

# Continuation lines (account / promptpay reference)
_CONTINUATION_RE = re.compile(
    r"^(บัญชีปลายทาง|บัญชีต้นทาง|รหัสพร้อมเพย์)\s*:\s*(.+)$"
)

# Header field patterns
_ACCT_NO_RE   = re.compile(r"เลขบัญชีเงินฝาก\s+([\d\-]+)")
_BRANCH_RE    = re.compile(r"สาขาเจ้าของบัญชี\s+(.+)")
_PERIOD_RE    = re.compile(r"รอบบัญชีระหว่างวันที่\s+(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")
_NAME_RE      = re.compile(r"ชื่อบัญชี\s+(.+)")

# Summary (last page)
_SUM_W_RE = re.compile(r"รายการถอนเงิน\s+([\d,]+)\s+รายการ\s+([\d,]+\.\d{2})")
_SUM_D_RE = re.compile(r"รายการฝากเงิน\s+([\d,]+)\s+รายการ\s+([\d,]+\.\d{2})")

# Column header line to skip
_HEADER_ROW_RE = re.compile(r"เวลาทำรายการ\s+รายการ")


# ---------------------------------------------------------------------------
# Krungthai (KTB) statement patterns
#   TRANSACTION LINE:
#     DD/MM/YY <type> [(CODE)] <details>  <amount>  <balance>  <branch_code>
#   TIME LINE (next line):
#     HH:MM  [extra notes]
#   Year is 2-digit Buddhist era (68 → 2025, 69 → 2026).
# ---------------------------------------------------------------------------

# Transaction line: trailing amount + balance + branch are anchored at the end,
# everything between the date and the amount is "rest" (type + code + details).
_KTB_TX_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{2})"          # group 1: date (DD/MM/YY, Buddhist)
    r"\s+(.*?)"                       # group 2: rest (type + code + details)
    r"\s+([\d,]+\.\d{2})"            # group 3: amount (withdrawal OR deposit column)
    r"\s+([\d,]+\.\d{2})"            # group 4: running balance
    r"\s+(\d+)$"                     # group 5: branch code
)

# Time-only continuation line (may carry trailing notes after the time)
_KTB_TIME_RE = re.compile(r"^(\d{2}:\d{2})(?:\s+(.+))?$")

# Transaction code inside parentheses, e.g. (MORISW)
_KTB_CODE_RE = re.compile(r"\(([A-Z]+)\)")

# Header fields
_KTB_NAME_RE   = re.compile(r"ชื่อบัญชี\s+(.+?)\s+ประเภทบัญชี")
_KTB_ACCT_RE   = re.compile(r"เลขที่บัญชี\s+(\d+)")
_KTB_BRANCH_RE = re.compile(r"(?:^|\n)สาขา\s+(\S.*?)\s*$", re.MULTILINE)
_KTB_PERIOD_RE = re.compile(
    r"รายการบัญชีระหว่างวันที่\s+(\d{2}/\d{2}/\d{2})\s*ถึง\s*(\d{2}/\d{2}/\d{2})"
)

# Summary (last page): "รายการถอนทั้งหมด <count> <total>"
_KTB_SUM_W_RE = re.compile(r"รายการถอนทั้งหมด\s+([\d,]+)\s+([\d,]+\.\d{2})")
_KTB_SUM_D_RE = re.compile(r"รายการฝากทั้งหมด\s+([\d,]+)\s+([\d,]+\.\d{2})")

# Inflow keywords for KTB transaction types
_KTB_DEPOSIT_KEYWORDS = ("เข้า", "รับ", "ฝาก", "ดอกเบี้ย")


def _be2_to_ce(date_str: str) -> str:
    """Convert 'DD/MM/YY' (2-digit Buddhist year) to 'DD/MM/YYYY' (Gregorian)."""
    try:
        dd, mm, yy = date_str.split("/")
        ce_year = 1957 + int(yy)  # 2500+yy-543 == 1957+yy ; 68→2025, 69→2026
        return f"{dd}/{mm}/{ce_year}"
    except (ValueError, AttributeError):
        return date_str

# Lines to skip (bank footer, page number, address)
_SKIP_RE = re.compile(
    r"^(Page \d+|ธนาคารกรุงศรีอยุธยา|สำนักงานใหญ่|รายการถอนเงิน|รายการฝากเงิน"
    r"|บริการรับรายการ|รายการเดินบัญชี|เลขบัญชีเงินฝาก|สาขาเจ้าของบัญชี"
    r"|รอบบัญชีระหว่างวันที่|ชื่อบัญชี|เวลาทำรายการ|ถนาคาร|\d{3}/.+)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(text: str) -> float:
    return float(text.replace(",", ""))


def _is_deposit(tx_type: str) -> bool:
    """Rows that contain รับ are inflows (ฝาก)."""
    return "รับ" in tx_type


def _parse_header(text: str) -> dict:
    info = {}
    m = _ACCT_NO_RE.search(text)
    info["account_number"] = m.group(1).strip() if m else ""

    m = _BRANCH_RE.search(text)
    info["branch"] = m.group(1).strip() if m else ""

    m = _PERIOD_RE.search(text)
    if m:
        info["period_start"] = m.group(1)
        info["period_end"]   = m.group(2)
    else:
        info["period_start"] = info["period_end"] = ""

    m = _NAME_RE.search(text)
    info["account_name"] = m.group(1).strip() if m else ""

    return info


def _parse_summary(text: str) -> Optional[StatementSummary]:
    mw = _SUM_W_RE.search(text)
    md = _SUM_D_RE.search(text)
    if mw and md:
        return StatementSummary(
            withdrawal_count = int(mw.group(1).replace(",", "")),
            withdrawal_total = _to_float(mw.group(2)),
            deposit_count    = int(md.group(1).replace(",", "")),
            deposit_total    = _to_float(md.group(2)),
        )
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_krungsri_statement(pdf_path: str) -> BankStatement:
    """
    Parse a Krungsri savings-account PDF statement.

    Parameters
    ----------
    pdf_path : str
        Absolute or relative path to the unlocked PDF file.

    Returns
    -------
    BankStatement
        Populated with account metadata, all transactions, and summary totals.
    """
    stmt = BankStatement(
        account_name="", account_number="", branch="",
        period_start="", period_end="",
    )

    all_text: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            all_text.append(text)

            # Extract header info from page 1
            if page_idx == 0:
                h = _parse_header(text)
                stmt.account_name   = h["account_name"]
                stmt.account_number = h["account_number"]
                stmt.branch         = h["branch"]
                stmt.period_start   = h["period_start"]
                stmt.period_end     = h["period_end"]

            # Parse transactions line-by-line
            _parse_lines(text.splitlines(), stmt.transactions)

    # Summary from the combined text
    stmt.summary = _parse_summary("\n".join(all_text))
    return stmt


def parse_krungthai_statement(pdf_path: str) -> BankStatement:
    """Parse a Krungthai (KTB) savings-account PDF statement."""
    stmt = BankStatement(
        account_name="", account_number="", branch="",
        period_start="", period_end="",
    )

    all_text: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            all_text.append(text)

            if page_idx == 0:
                m = _KTB_NAME_RE.search(text)
                stmt.account_name = m.group(1).strip() if m else ""
                m = _KTB_ACCT_RE.search(text)
                stmt.account_number = m.group(1).strip() if m else ""
                m = _KTB_BRANCH_RE.search(text)
                stmt.branch = m.group(1).strip() if m else ""
                m = _KTB_PERIOD_RE.search(text)
                if m:
                    stmt.period_start = _be2_to_ce(m.group(1))
                    stmt.period_end   = _be2_to_ce(m.group(2))

            _parse_ktb_lines(text.splitlines(), stmt.transactions)

    # Summary totals
    combined = "\n".join(all_text)
    mw = _KTB_SUM_W_RE.search(combined)
    md = _KTB_SUM_D_RE.search(combined)
    if mw and md:
        stmt.summary = StatementSummary(
            withdrawal_count=int(mw.group(1).replace(",", "")),
            withdrawal_total=_to_float(mw.group(2)),
            deposit_count=int(md.group(1).replace(",", "")),
            deposit_total=_to_float(md.group(2)),
        )
    return stmt


def _parse_ktb_lines(lines: list[str], transactions: list[Transaction]) -> None:
    current: Optional[Transaction] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # --- Transaction line -----------------------------------------------
        m = _KTB_TX_RE.match(line)
        if m:
            date    = _be2_to_ce(m.group(1))
            rest    = m.group(2).strip()
            amount  = _to_float(m.group(3))
            balance = _to_float(m.group(4))
            branch  = m.group(5)

            code_m = _KTB_CODE_RE.search(rest)
            if code_m:
                tx_type = rest[:code_m.start()].strip()
                details = rest[code_m.end():].strip()
            else:
                tx_type = rest
                details = ""

            is_deposit = any(k in tx_type for k in _KTB_DEPOSIT_KEYWORDS)
            if is_deposit:
                withdrawal, deposit = None, amount
            else:
                withdrawal, deposit = amount, None

            channel = "ATM" if ("ATM" in tx_type or (code_m and code_m.group(1).startswith("AT"))) else "MOBILE"

            current = Transaction(
                datetime         = date,   # time appended from the following line
                transaction_type = tx_type,
                withdrawal       = withdrawal,
                deposit          = deposit,
                balance          = balance,
                channel          = channel,
                details          = details,
            )
            transactions.append(current)
            continue

        # --- Time line (carries the HH:MM for the preceding transaction) ----
        mt = _KTB_TIME_RE.match(line)
        if mt and current is not None:
            current.datetime = f"{current.datetime} {mt.group(1)}"
            extra = (mt.group(2) or "").strip()
            if extra:
                current.details = (current.details + "\n" + extra).strip() if current.details else extra
            current = None
            continue

        # --- Anything else resets context -----------------------------------
        current = None


def parse_statement(pdf_path: str) -> BankStatement:
    """
    Auto-detect the issuing bank and parse the statement accordingly.

    Supports Krungsri (กรุงศรี) and Krungthai (กรุงไทย / KTB) savings statements.
    Falls back to the Krungsri parser if the format cannot be identified.
    """
    with pdfplumber.open(pdf_path) as pdf:
        first = pdf.pages[0].extract_text(x_tolerance=3, y_tolerance=3) or ""

    is_ktb = (
        "กรุงไทย" in first
        or "รายการบัญชีระหว่างวันที่" in first
        or "เลขที่บัญชี" in first
    )
    if is_ktb:
        return parse_krungthai_statement(pdf_path)
    return parse_krungsri_statement(pdf_path)


def _parse_lines(lines: list[str], transactions: list[Transaction]) -> None:
    current: Optional[Transaction] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # --- Transaction line -----------------------------------------------
        m = _TX_RE.match(line)
        if m:
            dt        = m.group(1)
            tx_type   = m.group(2).strip()
            amount    = _to_float(m.group(3))
            balance   = _to_float(m.group(4))
            channel   = m.group(5)
            details   = (m.group(6) or "").strip()

            if _is_deposit(tx_type):
                withdrawal, deposit = None, amount
            else:
                withdrawal, deposit = amount, None

            current = Transaction(
                datetime         = dt,
                transaction_type = tx_type,
                withdrawal       = withdrawal,
                deposit          = deposit,
                balance          = balance,
                channel          = channel,
                details          = details,
            )
            transactions.append(current)
            continue

        # --- Continuation line (account / promptpay reference) --------------
        mc = _CONTINUATION_RE.match(line)
        if mc and current is not None:
            label = mc.group(1)
            value = mc.group(2).strip()
            extra = f"{label} : {value}"
            current.details = (current.details + "\n" + extra).strip() if current.details else extra
            continue

        # --- Anything else resets continuation context ----------------------
        # (header, footer, address lines — skip)
        current = None


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def statement_to_dicts(statement: BankStatement) -> list[dict]:
    """Return transactions as plain dicts (JSON-serialisable)."""
    return [
        {
            "datetime":         tx.datetime,
            "transaction_type": tx.transaction_type,
            "withdrawal":       tx.withdrawal,
            "deposit":          tx.deposit,
            "balance":          tx.balance,
            "channel":          tx.channel,
            "details":          tx.details,
        }
        for tx in statement.transactions
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    sys.stdout.reconfigure(encoding="utf-8")

    path = sys.argv[1] if len(sys.argv) > 1 else "statement.pdf"
    stmt = parse_krungsri_statement(path)

    print(f"Account : {stmt.account_name}  ({stmt.account_number})")
    print(f"Branch  : {stmt.branch}")
    print(f"Period  : {stmt.period_start} - {stmt.period_end}")
    print(f"Txns    : {len(stmt.transactions)}")
    if stmt.summary:
        print(f"ถอน     : {stmt.summary.withdrawal_count} รายการ = {stmt.summary.withdrawal_total:,.2f}")
        print(f"ฝาก     : {stmt.summary.deposit_count}  รายการ = {stmt.summary.deposit_total:,.2f}")
    print()
    print(json.dumps(statement_to_dicts(stmt), ensure_ascii=False, indent=2))
