import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
import pendulum
from prefect.logging import get_run_logger

LOCAL_TZ = pendulum.timezone("Europe/Rome")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def send_email_notification(subject: str, body: str, html: str | None = None):
    """Invia una mail tramite i server SMTP di Gmail.
    Se html e' indicato, la mail ha sia la versione di solo testo (body) sia quella HTML."""
    try:
        msg = MIMEMultipart("alternative" if html else "mixed")
        msg["From"] = GMAIL_USER
        msg["To"] = GMAIL_USER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD.replace(" ", ""))
            server.send_message(msg)
    except Exception as e:
        print(f"Errore durante l'invio della mail: {e}")


# colonne del registro audit.model_load_log riportate nella mail, nell'ordine della tabella
LOAD_LOG_COLUMNS = ["model_name", "schema_name", "load_date", "month_key", "rows_inserted", "logged_at"]


def _text_table(rows: list) -> str:
    """Tabella a larghezza fissa per la versione di solo testo della mail."""
    cells = [[str(row.get(column, "")) for column in LOAD_LOG_COLUMNS] for row in rows]
    widths = [max(len(column), *(len(line[i]) for line in cells)) for i, column in enumerate(LOAD_LOG_COLUMNS)]
    lines = [" | ".join(column.ljust(widths[i]) for i, column in enumerate(LOAD_LOG_COLUMNS))]
    lines.append("-+-".join("-" * width for width in widths))
    lines += [" | ".join(value.ljust(widths[i]) for i, value in enumerate(line)) for line in cells]
    return "\n".join(lines)


def _html_table(rows: list) -> str:
    cell = "border:1px solid #999;padding:4px 10px;"
    head = "".join(f'<th style="{cell}background:#eee;text-align:left;">{escape(column)}</th>' for column in LOAD_LOG_COLUMNS)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="{cell}{"text-align:right;" if column == "rows_inserted" else ""}">{escape(str(row.get(column, "")))}</td>'
            for column in LOAD_LOG_COLUMNS
        )
        + "</tr>"
        for row in rows
    )
    return f'<table style="border-collapse:collapse;font-family:Consolas,monospace;font-size:13px;"><tr>{head}</tr>{body}</table>'


def notify_on_success(flow_name: str, target: str, load_log, months_run=None):
    """Mail di fine caricamento, con la tabella del registro dei caricamenti del bronze.

    load_log: righe di audit.model_load_log da riportare, con le colonne LOAD_LOG_COLUMNS
        (ultimo caricamento degli ultimi mesi di ogni tabella di bronze); None se il registro
        non e' stato letto.
    months_run: mesi caricati da questa esecuzione."""
    info = [
        ("Data flow name", flow_name),
        ("Target", target),
        ("Time", pendulum.now(LOCAL_TZ).to_cookie_string()),
        ("Mesi caricati in questa esecuzione", ", ".join(months_run) if months_run else "nessuno"),
    ]
    table_name = f"lakehouse_{target}.audit.model_load_log"

    if load_log is None:
        caption = f"La tabella {table_name} non e' leggibile: conteggi non disponibili (vedi il log del flow)."
        text_table = html_table = ""
    elif not load_log:
        caption = f"La tabella {table_name} non contiene righe per il bronze."
        text_table = html_table = ""
    else:
        months = len({row.get("month_key") for row in load_log})
        caption = f"{table_name}, tabelle di bronze, ultimo caricamento degli ultimi {months} mesi:"
        text_table = _text_table(load_log)
        html_table = _html_table(load_log)

    subject = f"Success: '{flow_name}' ({target})"
    body = "\n".join(
        ["La pipeline e' terminata correttamente.", ""]
        + [f"- {label}: {value}" for label, value in info]
        + ["", caption, "", text_table]
    )
    html = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;">'
        "<p>La pipeline e' terminata correttamente.</p><ul>"
        + "".join(f"<li>{escape(label)}: {escape(str(value))}</li>" for label, value in info)
        + f"</ul><p>{escape(caption)}</p>{html_table}</div>"
    )
    send_email_notification(subject, body, html)


def notify_on_failure(flow, flow_run, state):
    """Hook di callback per Prefect invocato quando il flusso fallisce."""
    logger = get_run_logger()
    logger.error("Flusso fallito! Invio email di errore...")

    subject = f"Failure: data freshness is failed '{flow.name}'"
    body = f"""
    Attention!
    
    La pipeline di produzione è fallita.
    
    - Data flow name: {flow.name}
    - Run ID: {flow_run.id}
    - Time: {pendulum.now(LOCAL_TZ).to_cookie_string()}
    - Error details: {state.message}
    """
    send_email_notification(subject, body)