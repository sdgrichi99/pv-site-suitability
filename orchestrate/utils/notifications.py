import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pendulum
from prefect.logging import get_run_logger

LOCAL_TZ = pendulum.timezone("Europe/Rome")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def send_email_notification(subject: str, body: str):
    """Invia una mail tramite i server SMTP di Gmail."""
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_USER
        msg["To"] = GMAIL_USER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD.replace(" ", ""))
            server.send_message(msg)
    except Exception as e:
        print(f"Errore durante l'invio della mail: {e}")


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