from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import time
from scraper import get_leaderboard_mapping_cached, force_refresh_leaderboard, CACHE_DURATION

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///competitors.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Expose timedelta to Jinja templates for adjusting time to UTC+1
app.jinja_env.globals['timedelta'] = timedelta

# ----------------------
# Database Models
# ----------------------
class Competitor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    golfer1 = db.Column(db.String(100), nullable=False)
    golfer2 = db.Column(db.String(100), nullable=False)
    golfer3 = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Competitor {self.name}>"

class MasterScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    golfer = db.Column(db.String(100), nullable=False, unique=True)
    current_score = db.Column(db.String(20), nullable=False)
    today = db.Column(db.String(20), nullable=True)
    thru = db.Column(db.String(20), nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class MasterScoreHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    master_score_id = db.Column(db.Integer, db.ForeignKey('master_score.id'), nullable=False)
    score = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# ----------------------
# Helper Functions
# ----------------------
def update_master_scores(scraped, now=None):
    """Update MasterScore records and log changes in history."""
    if now is None:
        now = datetime.utcnow()
    for entry in scraped:
        golfer = entry["player"]
        new_score = entry["score"]
        new_today = entry.get("today", "N/A")
        new_thru = entry.get("thru", "N/A")
        record = MasterScore.query.filter_by(golfer=golfer).first()
        if record:
            # Log change if any field differs
            if record.current_score != new_score or record.today != new_today or record.thru != new_thru:
                history = MasterScoreHistory(
                    master_score_id=record.id,
                    score=record.current_score,
                    timestamp=record.last_updated
                )
                db.session.add(history)
            record.current_score = new_score
            record.today = new_today
            record.thru = new_thru
            record.last_updated = now
        else:
            new_record = MasterScore(
                golfer=golfer,
                current_score=new_score,
                today=new_today,
                thru=new_thru,
                last_updated=now
            )
            db.session.add(new_record)
    db.session.commit()

def generate_scoreboard():
    """
    Generate a competition scoreboard by looking up each competitor's selected golfers'
    overall scores from the cached leaderboard data. Returns a sorted list of dictionaries.
    """
    leaderboard_mapping = get_leaderboard_mapping_cached()  # {golfer: {"score":..., "today":..., "thru":...}, ...}
    scoreboard = []
    competitors = Competitor.query.all()
    for comp in competitors:
        golfers = [comp.golfer1, comp.golfer2, comp.golfer3]
        scores = {}
        total_score_num = 0
        for golfer in golfers:
            # Use overall score only for competition scoreboard
            score_str = leaderboard_mapping.get(golfer, {}).get("score", "N/A")
            try:
                score_val = int(score_str)
            except ValueError:
                score_val = 0
            scores[golfer] = score_str
            total_score_num += score_val

        if total_score_num == 0:
            total_score_display = "E"
        elif total_score_num > 0:
            total_score_display = f"+{total_score_num}"
        else:
            total_score_display = str(total_score_num)

        scoreboard.append({
            "id": comp.id,
            "competitor": comp.name,
            "golfers": golfers,
            "scores": scores,
            "total": total_score_display,
            "total_numeric": total_score_num
        })
    scoreboard.sort(key=lambda x: x["total_numeric"])
    return scoreboard

def get_full_masters_scoreboard():
    """Return all MasterScore records sorted by numeric value (treating 'E' as 0)."""
    all_scores = MasterScore.query.all()
    def convert_score(score_str):
        s = score_str.strip()
        if s.upper() == "E":
            return 0
        try:
            return int(s)
        except ValueError:
            return 9999
    return sorted(all_scores, key=lambda rec: convert_score(rec.current_score))

# ----------------------
# Routes
# ----------------------
@app.route("/")
def index():
    competition_scoreboard = generate_scoreboard()
    full_masters = get_full_masters_scoreboard()
    leaderboard_mapping = get_leaderboard_mapping_cached()
    available_golfers = sorted(leaderboard_mapping.keys())
    return render_template("index.html", 
                           competition_scoreboard=competition_scoreboard,
                           full_masters=full_masters,
                           available_golfers=available_golfers)

@app.route("/add-competitor", methods=["POST"])
def add_competitor():
    name = request.form.get("name")
    golfer1 = request.form.get("golfer1")
    golfer2 = request.form.get("golfer2")
    golfer3 = request.form.get("golfer3")
    if name and golfer1 and golfer2 and golfer3:
        new_competitor = Competitor(name=name, golfer1=golfer1, golfer2=golfer2, golfer3=golfer3)
        db.session.add(new_competitor)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/delete-competitor/<int:competitor_id>", methods=["POST"])
def delete_competitor(competitor_id):
    competitor = Competitor.query.get(competitor_id)
    if competitor:
        db.session.delete(competitor)
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/edit-competitor/<int:competitor_id>", methods=["GET", "POST"])
def edit_competitor(competitor_id):
    competitor = Competitor.query.get(competitor_id)
    if not competitor:
        return redirect(url_for("index"))
    leaderboard_mapping = get_leaderboard_mapping_cached()
    available_golfers = sorted(leaderboard_mapping.keys())
    if request.method == "POST":
        competitor.name = request.form.get("name")
        competitor.golfer1 = request.form.get("golfer1")
        competitor.golfer2 = request.form.get("golfer2")
        competitor.golfer3 = request.form.get("golfer3")
        db.session.commit()
        return redirect(url_for("index"))
    return render_template("edit_competitor.html", competitor=competitor, available_golfers=available_golfers)

@app.route("/refresh")
def refresh():
    scraped = force_refresh_leaderboard()  # Force a fresh scrape and update cache
    update_master_scores(scraped)
    return redirect(url_for("index"))

@app.route("/api/scoreboard")
def api_scoreboard():
    return jsonify(generate_scoreboard())

@app.route("/api/competition")
def api_competition():
    return jsonify(generate_scoreboard())

@app.route("/api/full")
def api_full():
    # Optionally force a refresh if the cache is expired.
    if time.time() - get_leaderboard_mapping_cached().get('_last_scrape', 0) > CACHE_DURATION:
        scraped = force_refresh_leaderboard()
        update_master_scores(scraped)
    full = get_full_masters_scoreboard()
    result = []
    for entry in full:
        # Adjust last_updated to UTC+1 and format to show only the time.
        adjusted_time = entry.last_updated + timedelta(hours=1)
        result.append({
            "golfer": entry.golfer,
            "current_score": entry.current_score,
            "today": entry.today,
            "thru": entry.thru,
            "last_updated": adjusted_time.strftime("%H:%M:%S")
        })
    return jsonify(result)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
