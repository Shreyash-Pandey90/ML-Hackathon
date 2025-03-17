import os
from authlib.integrations.flask_client import OAuth
from flask import Flask, render_template, request, redirect, url_for, session
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from pymongo import MongoClient
import spacy
from dotenv import load_dotenv
from pytz import timezone
import dateparser
import re
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import autogen

# Load environment variables from .env file
load_dotenv()

# Flask app setup
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
app.config['SESSION_COOKIE_NAME'] = 'google_auth_session'

# Google OAuth setup
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email'
]

oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.getenv('CLIENT_ID'),
    client_secret=os.getenv('CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    access_token_url='https://accounts.google.com/o/oauth2/token',
    client_kwargs={
        'scope': SCOPES,
        'access_type': 'offline',
        'prompt': 'consent',
    },
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
)

# SpaCy NLP Setup
nlp = spacy.load("en_core_web_sm")

# MongoDB Setup
client = MongoClient('mongodb://localhost:27017/')
db = client['scheduling_bot']
candidate_responses_collection = db['candidate_responses']

# Define recruiter email addresses
RECRUITER_EMAILS = ['ishfaqkodinhi@gmail.com', 'recruiter2@gmail.com', 'recruiter3@gmail.com']

# Email Configuration
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")


# Email Sending Function
def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()

        return f"Email successfully sent to {to_email}"

    except Exception as e:
        return f"Failed to send email: {str(e)}"


# AutoGen AI Email Agent Setup
class EmailAgent(autogen.Agent):
    def __init__(self, name="EmailAgent"):
        super().__init__(name)

    def send_candidate_email(self, candidate_email, availability):
        subject = "Interview Confirmation"
        body = f"Dear Candidate, your interview is scheduled on {availability.get('date', 'N/A')} at {availability.get('start_time', 'N/A')}."
        return send_email(candidate_email, subject, body)

    def send_recruiter_email(self, recruiter_email, candidate_email, availability):
        subject = "New Interview Scheduled"
        body = f"Dear Recruiter, you have an interview scheduled with candidate {candidate_email} on {availability.get('date', 'N/A')} at {availability.get('start_time', 'N/A')}."
        return send_email(recruiter_email, subject, body)

    def send_no_availability_email(self, candidate_email):
        subject = "No Availability for Your Chosen Slot"
        body = "Dear Candidate, unfortunately, no recruiters are available for the given slot. Please select another one."
        return send_email(candidate_email, subject, body)


# Instantiate the Email Agent
email_agent = EmailAgent()


# Routes for Flask app
@app.route('/')
def index():
    if 'recruiter_credentials' not in session:
        return redirect(url_for('recruiter_login'))
    return render_template('index.html')


@app.route('/recruiter_login')
def recruiter_login():
    redirect_uri = 'http://127.0.0.1:5000/recruiter_authorize'
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/recruiter_authorize')
def recruiter_authorize():
    try:
        token = oauth.google.authorize_access_token()
        if not token:
            return "Authentication failed: No token received", 401

        user_info = oauth.google.userinfo()
        if not user_info:
            return "Authentication failed: User info not available", 401

        session['recruiter_credentials'] = {
            'access_token': token['access_token'],
            'refresh_token': token.get('refresh_token'),
            'expires_at': token['expires_at']
        }

        session['recruiter_email'] = user_info.get('email')

        return redirect('/')

    except Exception as e:
        print(f"Authentication error: {str(e)}")
        return f"Authentication failed: {str(e)}", 401


# Extract Date and Time
def extract_availability(text):
    doc = nlp(text)
    parsed_date = None

    for ent in doc.ents:
        if ent.label_ == "DATE":
            parsed = dateparser.parse(ent.text, settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.now()})
            if parsed:
                parsed_date = parsed
                break

    time_pattern = r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\b)'
    times = re.findall(time_pattern, text, re.IGNORECASE)

    if parsed_date and len(times) >= 2:
        start_time = dateparser.parse(times[0]).time()
        return {
            'date': parsed_date.strftime("%d-%m-%Y"),
            'start_time': start_time.strftime("%H:%M")
        }

    return None


# Handle Scheduling Logic
@app.route('/submit', methods=['POST'])
def submit():
    candidate_email = request.form['candidate_email']
    availability = extract_availability(request.form['candidate_response'])

    if availability:
        available_recruiter = RECRUITER_EMAILS[0]  # Assuming first recruiter for simplicity
        email_agent.send_candidate_email(candidate_email, availability)
        email_agent.send_recruiter_email(available_recruiter, candidate_email, availability)
        return render_template('thank_you.html', message="Interview Scheduled!")
    else:
        email_agent.send_no_availability_email(candidate_email)
        return render_template('thank_you.html', message="Unable to extract availability from response.")


if __name__ == '__main__':
    app.run(debug=True)
