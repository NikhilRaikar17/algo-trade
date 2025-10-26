import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime


sender_email = os.getenv("GMAIL_USERNAME")
receiver_email = os.getenv("RECEIVER_EMAIL")
password = os.getenv("GMAIL_APP_PASSWORD")
subject = "Algo paper trading results"
body = "Hey Nikhil/Bharath, Please find attached the CSV file containing the latest paper trade results."

# File to attach
current_time = datetime.today().strftime("%Y-%m-%d")
filename = f"AlgoTrade.xlsx"

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
server = smtplib.SMTP("smtp.gmail.com", 587)
server.starttls()
server.login(sender_email, password)
server.sendmail(sender_email, receiver_email, message.as_string())
server.quit()
