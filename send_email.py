import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime
from dotenv import load_dotenv

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_FILE, override=True)


def send_algo_report(filename="AlgoTrade.xlsx"):
    sender_email = os.getenv("GMAIL_USERNAME")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    receiver_emails = receiver_email.split(",")  # split into list
    receiver_emails = [email.strip() for email in receiver_emails]  # clean spaces
    password = os.getenv("GMAIL_APP_PASSWORD")
    subject = "Algo paper trading results"
    body = "Hey Nikhil/Bharath, Please find attached the CSV file containing the latest paper trade results."

    # File to attach
    current_time = datetime.today().strftime("%Y-%m-%d")

    # Create a multipart message and set headers
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject

    # Attach the body with the msg instance
    message.attach(MIMEText(body, "plain"))

    # Open the file as binary mode
    with open(filename, "rb") as attachment:
        # MIMEBase is used to attach the file
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment.read())

    # Encode file in ASCII characters to send by email
    encoders.encode_base64(part)

    # Add header as key/value pair to attachment part
    part.add_header(
        "Content-Disposition",
        f"attachment; filename= {filename}",
    )

    # Attach the file to the message
    message.attach(part)

    # Log in to the server and send the email
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())
    print("Email sent successfully!")


if __name__ == "__main__":
    send_algo_report()
