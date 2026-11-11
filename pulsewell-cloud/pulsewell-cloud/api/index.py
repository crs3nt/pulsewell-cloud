import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime  # type: ignore[reportMissingImports]
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY", "pulsewell-super-secret-key-2026")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///pulsewell.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite fallback handles single-thread checks gracefully
engine_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=engine_args)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# Database Tables
class HRUser(Base):
    __tablename__ = "hr_users"
    id = Column(Integer, primary_key=True)
    org_name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    surveys = relationship("Survey", backref="owner", cascade="all, delete-orphan")

class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True)
    hr_id = Column(Integer, ForeignKey("hr_users.id"), nullable=False) # Data privacy per HR
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    responses = relationship("Response", backref="survey", cascade="all, delete-orphan")

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True)
    survey_id = Column(Integer, ForeignKey("surveys.id"), nullable=False)
    engagement_score = Column(Integer, nullable=False)
    workload_score = Column(Integer, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def get_db():
    return SessionLocal()

@app.route("/")
def index():
    return redirect(url_for("dashboard")) if "hr_id" in session else redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        org = request.form.get("org_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        db = get_db()
        if db.query(HRUser).filter_by(email=email).first():
            db.close()
            flash("Account with this email already exists.")
            return redirect(url_for("register"))

        user = HRUser(org_name=org, email=email, password_hash=generate_password_hash(password))
        db.add(user)
        db.commit()
        session["hr_id"] = user.id
        session["hr_org"] = user.org_name
        db.close()
        return redirect(url_for("dashboard"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        db = get_db()
        user = db.query(HRUser).filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session["hr_id"] = user.id
            session["hr_org"] = user.org_name
            db.close()
            return redirect(url_for("dashboard"))
        db.close()
        flash("Invalid email or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "hr_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    # Tenant privacy: ONLY select surveys created by this specific HR user
    surveys = db.query(Survey).filter_by(hr_id=session["hr_id"]).all()
    
    total_responses = sum(len(s.responses) for s in surveys)
    total_eng = sum(r.engagement_score for s in surveys for r in s.responses)
    total_work = sum(r.workload_score for s in surveys for r in s.responses)

    avg_engagement = round(total_eng / total_responses, 2) if total_responses else 0
    avg_workload = round(total_work / total_responses, 2) if total_responses else 0
    db.close()

    return render_template(
        "dashboard.html",
        surveys=surveys,
        total_responses=total_responses,
        avg_engagement=avg_engagement,
        avg_workload=avg_workload
    )

@app.route("/survey/create", methods=["GET", "POST"])
def create_survey():
    if "hr_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        
        db = get_db()
        survey = Survey(hr_id=session["hr_id"], title=title, description=description)
        db.add(survey)
        db.commit()
        db.close()
        return redirect(url_for("dashboard"))
    return render_template("new_survey.html")

@app.route("/s/<int:survey_id>", methods=["GET", "POST"])
def submit_response(survey_id):
    db = get_db()
    survey = db.query(Survey).filter_by(id=survey_id).first()
    if not survey:
        db.close()
        return "Survey Not Found", 404

    if request.method == "POST":
        eng = int(request.form.get("engagement", 3))
        work = int(request.form.get("workload", 3))
        resp = Response(survey_id=survey.id, engagement_score=eng, workload_score=work)
        db.add(resp)
        db.commit()
        db.close()
        return render_template("submitted.html")

    db.close()
    return render_template("public_survey.html", survey=survey)

if __name__ == "__main__":
    app.run(debug=True, port=5000)